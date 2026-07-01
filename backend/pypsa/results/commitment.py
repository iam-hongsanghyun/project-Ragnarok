"""Unit-commitment view (Tier 1) — cold/hot-start economics.

When generators are ``committable`` the solve is a MILP with binary on/off
status, start-up costs and minimum up/down times. This surfaces the result:
per committable unit, how many times it started, how much those starts cost,
how much of the horizon it ran, and its on/off pattern — so the cost of cycling
plant (the reason a peaker's offer must cover its start) is visible.

Reads ``generators_t.status`` (on/off) and ``generators_t.start_up`` (start
events) straight off the solved network — no re-optimisation.
"""
from __future__ import annotations

import logging
from typing import Any

import pypsa

_log = logging.getLogger("pypsa.solver")


def _segments(status: list[int]) -> list[dict[str, Any]]:
    """Run-length encode an on/off series into ``{on, length}`` segments."""
    out: list[dict[str, Any]] = []
    for s in status:
        on = bool(s)
        if out and out[-1]["on"] == on:
            out[-1]["length"] += 1
        else:
            out.append({"on": on, "length": 1})
    return out


def build_commitment(network: pypsa.Network, *, currency: str) -> dict[str, Any] | None:
    """Per-unit commitment summary. ``None`` when nothing is committable/solved."""
    gens = network.generators
    if gens.empty or "committable" not in gens.columns:
        return None
    committable = [g for g in gens.index if bool(gens.at[g, "committable"])]
    status_df = network.generators_t.status
    if not committable or status_df is None or status_df.empty:
        return None

    start_up_df = network.generators_t.start_up
    weights = network.snapshot_weightings["objective"]
    n_snap = len(network.snapshots)

    rows: list[dict[str, Any]] = []
    by_carrier: dict[str, dict[str, float]] = {}
    tot_starts = 0
    tot_start_cost = 0.0
    for g in committable:
        if g not in status_df.columns:
            continue
        st = status_df[g].round().astype(int)
        starts = (
            int(start_up_df[g].round().sum())
            if start_up_df is not None and not start_up_df.empty and g in start_up_df.columns
            else int((st.diff() == 1).sum())
        )
        suc = float(gens.at[g, "start_up_cost"]) if "start_up_cost" in gens.columns else 0.0
        start_cost_total = starts * suc
        online_hours = float((st * weights).sum())
        online_fraction = float(st.mean()) if n_snap else 0.0
        carrier = str(gens.at[g, "carrier"])
        rows.append({
            "name": g,
            "carrier": carrier,
            "starts": starts,
            "startUpCost": round(suc, 2),
            "startUpCostTotal": round(start_cost_total, 2),
            "onlineHours": round(online_hours, 1),
            "onlineFraction": round(online_fraction, 4),
            "minUpTime": int(gens.at[g, "min_up_time"]) if "min_up_time" in gens.columns else 0,
            "minDownTime": int(gens.at[g, "min_down_time"]) if "min_down_time" in gens.columns else 0,
            "segments": _segments(st.tolist()),
        })
        tot_starts += starts
        tot_start_cost += start_cost_total
        c = by_carrier.setdefault(carrier, {"starts": 0.0, "startUpCostTotal": 0.0, "units": 0.0})
        c["starts"] += starts
        c["startUpCostTotal"] += start_cost_total
        c["units"] += 1

    if not rows:
        return None
    rows.sort(key=lambda r: r["startUpCostTotal"], reverse=True)
    carrier_rows = [
        {"carrier": k, "starts": int(v["starts"]), "startUpCostTotal": round(v["startUpCostTotal"], 2), "units": int(v["units"])}
        for k, v in sorted(by_carrier.items(), key=lambda kv: kv[1]["startUpCostTotal"], reverse=True)
    ]
    _log.info("commitment: %d committable units, %d total starts", len(rows), tot_starts)
    return {
        "currency": currency,
        "snapshotCount": n_snap,
        "generators": rows,
        "byCarrier": carrier_rows,
        "totals": {
            "committableCount": len(rows),
            "starts": tot_starts,
            "startUpCostTotal": round(tot_start_cost, 2),
        },
    }
