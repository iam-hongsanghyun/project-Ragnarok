"""Demand response — shiftable load (M2).

Distinct from load shedding (which *drops* demand at a penalty), demand response
here *moves* demand in time while conserving total energy: consumption fills
cheap hours and empties expensive ones. Each shiftable load is rewired into the
standard PyPSA demand-shifting pattern:

    parent_bus ──Link(η=1)──▶ dr_bus ──▶ Load L
                                dr_bus ──▶ Store (e_cyclic)

The Link carries the actual grid draw (bounded so it can pre-consume above the
load's peak); the cyclic Store buffers the timing difference between grid draw
and the load's nominal profile, so total drawn energy over the horizon equals
total demanded energy. The Store's energy capacity (power × duration) bounds how
much can be shifted at once. Nothing is curtailed and no new energy is created.

Feasibility: the Link alone can always meet the load (``p_nom ≥ peak``), so the
trivial "Link = load, Store idle" solution exists — demand response never makes a
model infeasible, it only ever lowers cost.
"""
from __future__ import annotations

from typing import Any

import pypsa

from ..utils.series import weighted_sum


def _load_peak(network: pypsa.Network, load: str) -> float:
    """Peak demand (MW) of a load, from its time series or static ``p_set``."""
    try:
        if load in network.loads_t.p_set.columns:
            v = float(network.loads_t.p_set[load].abs().max())
            if v > 0:
                return v
    except Exception:  # noqa: BLE001
        pass
    try:
        return abs(float(network.loads.at[load, "p_set"]))
    except Exception:  # noqa: BLE001
        return 0.0


def apply_demand_response(
    network: pypsa.Network,
    notes: list[str],
    *,
    enabled: bool = False,
    loads: list[str] | None = None,
    shift_fraction: float = 0.2,
    max_shift_hours: float = 4.0,
) -> None:
    """Rewire selected loads into the shiftable (DR bus + Link + Store) pattern.

    Args:
        loads: load names to make shiftable; empty/``None`` = all loads.
        shift_fraction: buffer power as a fraction of each load's peak (0–1).
        max_shift_hours: buffer duration; Store ``e_nom`` = power × hours.
    """
    if not enabled:
        return
    shift_fraction = max(0.0, min(1.0, float(shift_fraction or 0.0)))
    max_shift_hours = max(0.0, float(max_shift_hours or 0.0))
    if shift_fraction <= 0 or max_shift_hours <= 0:
        notes.append("Demand response enabled but shift fraction/hours are zero — no loads shifted.")
        return

    wanted = set(loads or [])
    targets = [str(load) for load in network.loads.index if (not wanted or str(load) in wanted)]
    has_bus_carrier = "carrier" in network.buses.columns
    count = 0
    for load in targets:
        parent = str(network.loads.at[load, "bus"])
        if parent not in network.buses.index:
            continue
        peak = _load_peak(network, load)
        if peak <= 0:
            continue
        shift_power = shift_fraction * peak
        e_nom = shift_power * max_shift_hours
        if e_nom <= 0:
            continue
        dr_bus = f"dr_{load}"
        if dr_bus in network.buses.index:
            continue
        # Keep the parent's carrier so DR introduces no phantom energy vector.
        carrier = str(network.buses.at[parent, "carrier"]) if has_bus_carrier else "AC"
        network.add("Bus", dr_bus, carrier=carrier)
        network.loads.at[load, "bus"] = dr_bus
        network.add(
            "Link", f"drlink_{load}",
            bus0=parent, bus1=dr_bus, p_nom=peak + shift_power, efficiency=1.0, marginal_cost=0.0,
        )
        network.add("Store", f"drstore_{load}", bus=dr_bus, e_nom=e_nom, e_cyclic=True, marginal_cost=0.0)
        count += 1

    if count:
        notes.append(
            f"Demand response: {count} load(s) made shiftable "
            f"(buffer {shift_fraction * 100:.0f}% of peak × {max_shift_hours:.0f} h)."
        )
    else:
        notes.append("Demand response enabled but no eligible loads found.")


_ELASTIC_PREFIX = "load_shedding_elastic_"


def apply_price_elastic(
    network: pypsa.Network,
    notes: list[str],
    *,
    enabled: bool = False,
    loads: list[str] | None = None,
    fraction: float = 0.2,
    wtp_max: float = 200.0,
    tiers: int = 4,
) -> None:
    """Make a slice of demand price-elastic via a stepped willingness-to-pay curve.

    Unlike shedding (one very-high VOLL tier), this splits an ``fraction`` slice of
    each load into ``tiers`` blocks whose willingness-to-pay ramps DOWN from
    ``wtp_max`` toward 0 — a linear demand curve. Each block is a shedding-style
    generator priced at its WTP, so it "serves" (i.e. the demand goes unmet) only
    when the LMP exceeds that block's value. Named with the ``load_shedding_``
    prefix so it's excluded from energy/emissions/mix like other shedding.
    """
    if not enabled:
        return
    fraction = max(0.0, min(1.0, float(fraction or 0.0)))
    tiers = max(1, int(tiers))
    wtp_max = max(0.0, float(wtp_max or 0.0))
    if fraction <= 0 or wtp_max <= 0:
        notes.append("Price-elastic demand enabled but fraction/WTP are zero — no elastic blocks added.")
        return

    wanted = set(loads or [])
    targets = [str(load) for load in network.loads.index if (not wanted or str(load) in wanted)]
    count = 0
    for load in targets:
        bus = str(network.loads.at[load, "bus"])
        if bus not in network.buses.index:
            continue
        peak = _load_peak(network, load)
        if peak <= 0:
            continue
        block = fraction * peak / tiers
        if block <= 0:
            continue
        for k in range(tiers):
            wtp = wtp_max * (1.0 - (k + 0.5) / tiers)  # tier midpoint WTP, ramps to ~0
            name = f"{_ELASTIC_PREFIX}{load}_{k}"
            if name in network.generators.index:
                continue
            network.add("Generator", name, bus=bus, carrier="elastic_demand", p_nom=block, marginal_cost=wtp)
            network.generators_t.p_max_pu.loc[:, name] = 1.0
        count += 1

    if count:
        notes.append(
            f"Price-elastic demand: {count} load(s) with {tiers}-tier WTP curve "
            f"({fraction * 100:.0f}% of peak, WTP ≤ {wtp_max:.0f})."
        )
    else:
        notes.append("Price-elastic demand enabled but no eligible loads found.")


def build_price_elastic(network: pypsa.Network) -> dict[str, Any] | None:
    """Post-solve elastic-demand outcome, or ``None`` if none configured/reduced.

    Reports demand voluntarily reduced (elastic blocks that cleared because the
    LMP beat their WTP) per load and system-wide, plus the volume-weighted average
    WTP of the reduced demand.
    """
    if not getattr(network, "is_solved", False):
        return None
    elastic = [str(g) for g in network.generators.index if str(g).startswith(_ELASTIC_PREFIX)]
    if not elastic:
        return None
    w = network.snapshot_weightings["objective"].reindex(network.snapshots).fillna(1.0)
    gp = network.generators_t.p

    per_load: dict[str, dict[str, float]] = {}
    total_reduced = 0.0
    for g in elastic:
        if g not in gp.columns:
            continue
        energy = float(weighted_sum(gp[g].clip(lower=0.0), w))
        if energy <= 1e-9:
            continue
        load = g[len(_ELASTIC_PREFIX):].rsplit("_", 1)[0]
        wtp = float(network.generators.at[g, "marginal_cost"])
        bucket = per_load.setdefault(load, {"reducedMWh": 0.0, "wtpValue": 0.0})
        bucket["reducedMWh"] += energy
        bucket["wtpValue"] += energy * wtp
        total_reduced += energy

    if total_reduced <= 1e-9:
        return None
    loads_out = [
        {
            "name": name,
            "reducedMWh": round(v["reducedMWh"], 1),
            "avgWtp": round(v["wtpValue"] / v["reducedMWh"], 2) if v["reducedMWh"] > 0 else 0.0,
        }
        for name, v in per_load.items()
    ]
    loads_out.sort(key=lambda r: r["reducedMWh"], reverse=True)
    return {"loads": loads_out, "totalReducedMWh": round(total_reduced, 1)}


def build_demand_response(network: pypsa.Network) -> dict[str, Any] | None:
    """Post-solve DR outcome per shiftable load, or ``None`` if none were shifted.

    Returns ``{"loads": [{name, shiftedMWh, peakBeforeMW, peakAfterMW,
    peakReductionPct}], "totalShiftedMWh"}``. ``shiftedMWh`` is the energy
    released from the buffer (Store discharge); the peaks compare the load's
    nominal profile against the actual grid draw on the DR Link.
    """
    if not getattr(network, "is_solved", False):
        return None
    dr_links = [str(link) for link in network.links.index if str(link).startswith("drlink_")]
    if not dr_links:
        return None
    w = network.snapshot_weightings["objective"].reindex(network.snapshots).fillna(1.0)
    store_p = network.stores_t.p if len(network.stores.index) else None
    link_p0 = network.links_t.p0

    loads_out: list[dict[str, Any]] = []
    total_shifted = 0.0
    for link in dr_links:
        name = link[len("drlink_"):]
        store = f"drstore_{name}"
        shifted = 0.0
        if store_p is not None and store in store_p.columns:
            # Positive store p = discharge (energy released back to the load).
            shifted = float(weighted_sum(store_p[store].clip(lower=0.0), w))
        demand = network.loads_t.p_set[name] if name in network.loads_t.p_set.columns else None
        peak_before = float(demand.max()) if demand is not None and len(demand) else 0.0
        peak_after = float(link_p0[link].max()) if link in link_p0.columns else peak_before
        reduction = (1.0 - peak_after / peak_before) * 100.0 if peak_before > 0 else 0.0
        loads_out.append({
            "name": name,
            "shiftedMWh": round(shifted, 1),
            "peakBeforeMW": round(peak_before, 1),
            "peakAfterMW": round(peak_after, 1),
            "peakReductionPct": round(reduction, 1),
        })
        total_shifted += shifted

    loads_out.sort(key=lambda r: r["shiftedMWh"], reverse=True)
    return {"loads": loads_out, "totalShiftedMWh": round(total_shifted, 1)}
