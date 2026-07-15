"""Per-carrier energy balance (M1 — sector coupling analytics).

A single-carrier (electricity-only) model has one trivial balance — supply meets
demand — so the carrier-mix donut already tells the story. A sector-coupled model
has several energy vectors (electricity, gas, H₂, heat) linked by conversion
``Link`` s, and the interesting question becomes: for each vector, where did the
energy come from and where did it go?

This builder answers that per bus-carrier, reading the solved flows:

  • Generators on a carrier's buses           → a **source** (by fuel carrier)
  • Loads on a carrier's buses                 → a **sink**  ("Demand")
  • Link withdrawing from a carrier (``p0``)   → a **sink**  (conversion out)
  • Link injecting into a carrier (``-p1``)    → a **source** (conversion in)
  • Storage / Store discharge / charge         → source / sink

So a gas→power CCGT shows as a *sink* on the gas balance (fuel consumed) and a
*source* on the electricity balance (power produced) — the two sides of the
conversion. Multi-port Links count every output port the same way: a CHP's
heat co-product (``bus2`` / ``p2``) shows as a source on the heat balance.
Only built when the model has more than one bus carrier; returns ``None`` for
electricity-only runs. Energy is snapshot-weighted MWh over the modelled
window.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd
import pypsa

from ..utils.series import weighted_sum

_EPS = 1e-9


def _bus_carriers(network: pypsa.Network) -> pd.Series:
    """Bus → carrier, with blank/missing normalised to ``AC`` (PyPSA's default)."""
    if "carrier" in network.buses.columns:
        s = network.buses["carrier"].astype(str)
    else:
        s = pd.Series("AC", index=network.buses.index)
    return s.replace("", "AC").fillna("AC")


def build_energy_balance(network: pypsa.Network) -> dict[str, Any] | None:
    """Per-carrier source/sink energy balance, or ``None`` if single-carrier.

    Returns:
        ``{"carriers": [{carrier, supplyMWh, demandMWh, sources[], sinks[]}]}``
        where each source/sink is ``{label, energyMWh, kind}`` and ``kind`` is one
        of ``generation`` | ``load`` | ``conversion`` | ``storage``.
    """
    if network.buses.empty:
        return None
    bus_carrier = _bus_carriers(network)
    if bus_carrier.nunique() < 2:
        return None  # electricity-only: the carrier-mix donut already covers it

    weights = network.snapshot_weightings["generators"].reindex(network.snapshots).fillna(1.0)

    sources: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    sinks: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    src_kind: dict[tuple[str, str], str] = {}
    snk_kind: dict[tuple[str, str], str] = {}

    def add_source(carrier: str, label: str, energy: float, kind: str) -> None:
        if energy <= _EPS:
            return
        sources[carrier][label] += energy
        src_kind[(carrier, label)] = kind

    def add_sink(carrier: str, label: str, energy: float, kind: str) -> None:
        if energy <= _EPS:
            return
        sinks[carrier][label] += energy
        snk_kind[(carrier, label)] = kind

    # ── Generators → source on their bus's carrier, grouped by fuel carrier ──
    gp = network.generators_t.p
    for g in network.generators.index:
        if str(g).startswith("load_shedding_"):
            continue
        if g not in gp.columns:
            continue
        c = bus_carrier.get(str(network.generators.at[g, "bus"]), "AC")
        fuel = str(network.generators.at[g, "carrier"]) or "generation"
        add_source(c, fuel, weighted_sum(gp[g].clip(lower=0.0), weights), "generation")

    # ── Loads → sink ("Demand") ──────────────────────────────────────────────
    lp = network.loads_t.p_set
    for load in network.loads.index:
        if load not in lp.columns:
            continue
        c = bus_carrier.get(str(network.loads.at[load, "bus"]), "AC")
        add_sink(c, "Demand", weighted_sum(lp[load].clip(lower=0.0), weights), "load")

    # ── Links → sink on bus0's carrier, source on each output port's carrier ─
    if len(network.links.index):
        links = network.links
        dyn = network.links_t
        p0 = dyn.p0
        has_lc = "carrier" in links.columns
        # Output ports: bus1 plus any multi-port columns (bus2, bus3, … — CHP
        # heat co-products and the like). A blank port cell = port unused.
        ports = ["1"] + sorted(
            c[3:] for c in links.columns
            if c.startswith("bus") and c[3:].isdigit() and c not in ("bus0", "bus1")
        )
        for lk in links.index:
            c0 = bus_carrier.get(str(links.at[lk, "bus0"]), "AC")
            c1 = bus_carrier.get(str(links.at[lk, "bus1"]), "AC")
            lcarr = (str(links.at[lk, "carrier"]) if has_lc else "") or ""
            if lk in p0.columns:
                add_sink(c0, lcarr or f"→ {c1}", weighted_sum(p0[lk].clip(lower=0.0), weights), "conversion")
            for port in ports:
                pi = dyn[f"p{port}"] if f"p{port}" in dyn else None
                if pi is None or lk not in pi.columns:
                    continue
                bus = str(links.at[lk, f"bus{port}"]).strip()
                if not bus or bus.lower() == "nan":
                    continue
                ci = bus_carrier.get(bus, "AC")
                add_source(ci, lcarr or f"{c0} →", weighted_sum((-pi[lk]).clip(lower=0.0), weights), "conversion")

    # ── Storage units + Stores → discharge source / charge sink ─────────────
    for comp, frame in (("storage_units", "storage_units_t"), ("stores", "stores_t")):
        idx = getattr(network, comp).index
        if not len(idx):
            continue
        pf = getattr(network, frame).p
        static = getattr(network, comp)
        disc_label = "Storage discharge" if comp == "storage_units" else "Store discharge"
        char_label = "Storage charge" if comp == "storage_units" else "Store charge"
        for unit in idx:
            if unit not in pf.columns:
                continue
            c = bus_carrier.get(str(static.at[unit, "bus"]), "AC")
            add_source(c, disc_label, weighted_sum(pf[unit].clip(lower=0.0), weights), "storage")
            add_sink(c, char_label, weighted_sum(pf[unit].clip(upper=0.0).abs(), weights), "storage")

    carriers_out: list[dict[str, Any]] = []
    for c in set(sources) | set(sinks):
        supply = sum(sources[c].values())
        demand = sum(sinks[c].values())
        if supply <= _EPS and demand <= _EPS:
            continue
        src = sorted(
            ({"label": k, "energyMWh": round(v, 1), "kind": src_kind[(c, k)]} for k, v in sources[c].items()),
            key=lambda r: r["energyMWh"], reverse=True,
        )
        snk = sorted(
            ({"label": k, "energyMWh": round(v, 1), "kind": snk_kind[(c, k)]} for k, v in sinks[c].items()),
            key=lambda r: r["energyMWh"], reverse=True,
        )
        carriers_out.append({
            "carrier": c,
            "supplyMWh": round(supply, 1),
            "demandMWh": round(demand, 1),
            "sources": src,
            "sinks": snk,
        })

    if not carriers_out:
        return None
    carriers_out.sort(key=lambda r: r["supplyMWh"], reverse=True)
    return {"carriers": carriers_out}
