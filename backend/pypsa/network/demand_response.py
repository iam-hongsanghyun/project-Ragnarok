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
