"""Per-carrier energy balance (M1 — sector coupling analytics).

A single-carrier (electricity-only) model has one trivial balance — supply meets
demand — so the carrier-mix donut already tells the story. A sector-coupled model
has several energy vectors (electricity, gas, H₂, heat) linked by conversion
``Link`` s, and the interesting question becomes: for each vector, where did the
energy come from and where did it go?

This builder answers that per bus-carrier, reading the solved flows:

Implementation: ``n.statistics.supply`` / ``withdrawal`` (``at_port="all"``) with a
custom grouper (P28), so Processes, multi-port conversions and reverse flows are
accounted natively. Reading guide:

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


_COMPONENTS = ["Generator", "Load", "Link", "Process", "StorageUnit", "Store"]
_SEP = "\x1f"  # kind/label separator inside a grouper key
_SKIP = "\x00skip"


def _label_grouper(direction: str) -> Any:
    """Grouper naming each asset by ``kind SEP label`` for one flow direction.

    ``direction`` is ``"supply"`` (energy injected into a bus) or ``"withdrawal"``.
    Labels reproduce the long-standing payload: generators by fuel carrier
    (``generation``), loads ``Demand`` (``load``), conversion devices by their
    carrier or ``→ <out carrier>`` / ``<in carrier> →`` (``conversion``), storage
    ``… discharge`` / ``… charge`` (``storage``). The load-shedding backstop is
    skipped. Registered through PyPSA's ``statistics.groupers`` mechanism.
    """

    def grouper(n: pypsa.Network, c: str, port: str = "", nice_names: bool = False) -> pd.Series:
        return _group_labels(n, c).rename("label")

    def _group_labels(n: pypsa.Network, c: str) -> pd.Series:
        static = n.c[c].static
        names = pd.Series(static.index.get_level_values("name") if isinstance(static.index, pd.MultiIndex) else static.index, index=static.index).astype(str)
        if c == "Generator":
            fuel = static["carrier"].astype(str).replace("", "generation")
            out = "generation" + _SEP + fuel
            return out.where(~names.str.startswith("load_shedding_"), _SKIP)
        if c == "Load":
            return pd.Series("load" + _SEP + "Demand", index=static.index)
        if c in ("Link", "Process"):
            own = static["carrier"].astype(str) if "carrier" in static.columns else pd.Series("", index=static.index)
            bus_carrier = _bus_carriers(n)
            c0 = static["bus0"].astype(str).map(bus_carrier).fillna("AC")
            c1 = static["bus1"].astype(str).map(bus_carrier).fillna("AC")
            fallback = ("→ " + c1) if direction == "withdrawal" else (c0 + " →")
            return "conversion" + _SEP + own.where(own != "", fallback)
        label = {
            ("StorageUnit", "supply"): "Storage discharge",
            ("StorageUnit", "withdrawal"): "Storage charge",
            ("Store", "supply"): "Store discharge",
            ("Store", "withdrawal"): "Store charge",
        }[(c, direction)]
        return pd.Series("storage" + _SEP + label, index=static.index)

    return grouper


def _flows(network: pypsa.Network, direction: str) -> dict[tuple[str, str, str], float]:
    """``{(bus carrier, kind, label): MWh}`` from ``n.statistics.supply/withdrawal``.

    ``at_port="all"`` evaluates every port of multi-port Links and Processes
    separately, clipping each port's flow per snapshot, so a CHP heat co-product
    or a Process output lands on its own bus carrier. PyPSA applies the
    ``generators`` snapshot weightings.
    """
    fn = getattr(network.statistics, direction)
    try:
        series = fn(
            components=_COMPONENTS,
            groupby=["bus_carrier", _label_grouper(direction)],
            at_port="all",
            nice_names=False,
        )
    except Exception:  # noqa: BLE001 - no matching components (e.g. no storage) is not an error
        return {}
    if isinstance(series, pd.DataFrame):  # multi-investment-period run: one column per period
        series = series.sum(axis=1)
    out: dict[tuple[str, str, str], float] = defaultdict(float)
    for key, value in series.items():
        if not isinstance(key, tuple) or len(key) < 2 or pd.isna(value):
            continue
        bus_c, grp = str(key[-2]), str(key[-1])
        if grp == _SKIP or _SEP not in grp:
            continue
        kind, label = grp.split(_SEP, 1)
        out[(bus_c if bus_c not in ("", "nan") else "AC", kind, label)] += float(value)
    return out


def build_energy_balance(network: pypsa.Network) -> dict[str, Any] | None:
    """Per-carrier source/sink energy balance, or ``None`` if single-carrier.

    Computed with ``n.statistics.supply`` / ``withdrawal`` (``at_port="all"``) so
    every port of every Link **and Process** is accounted (P28/P29) — the
    hand-rolled version ignored Processes and reverse flows.

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

    sources: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    sinks: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    src_kind: dict[tuple[str, str], str] = {}
    snk_kind: dict[tuple[str, str], str] = {}
    for (carrier, kind, label), energy in _flows(network, "supply").items():
        if energy > _EPS:
            sources[carrier][label] += energy
            src_kind[(carrier, label)] = kind
    for (carrier, kind, label), energy in _flows(network, "withdrawal").items():
        if energy > _EPS:
            sinks[carrier][label] += energy
            snk_kind[(carrier, label)] = kind

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
