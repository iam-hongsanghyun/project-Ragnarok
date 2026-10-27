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

import pandas as pd
import pypsa

from .market import COMMITTABLE_LISTS, event_cost_frame

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
    n_snap = len(network.snapshots)
    weights = network.snapshot_weightings["objective"]

    rows: list[dict[str, Any]] = []
    by_carrier: dict[str, dict[str, float]] = {}
    tot_starts = 0
    tot_start_cost = 0.0
    # Generators, committable Links and Processes share the status / start_up
    # machinery. ``start_up_cost`` is static_or_series in PyPSA >= 1.4, so the
    # price of each start is read per snapshot (event_cost_frame), not as a
    # static scalar.
    for list_name in COMMITTABLE_LISTS:
        if list_name not in network.components.keys():
            continue
        comp = network.components[list_name]
        gens = comp.static
        if gens.empty or "committable" not in gens.columns:
            continue
        committable = [g for g in gens.index if bool(gens.at[g, "committable"])]
        status_df = comp.dynamic.get("status")
        if not committable or status_df is None or status_df.empty:
            continue
        start_up_df = comp.dynamic.get("start_up")
        cost_frame = event_cost_frame(network, list_name, "start_up")
        cost_dense = (
            network.get_switchable_as_dense(list_name, "start_up_cost", inds=pd.Index(committable))
            if "start_up_cost" in gens.columns
            else None
        )
        for g in committable:
            if g not in status_df.columns:
                continue
            st = status_df[g].round().astype(int)
            starts = (
                int(start_up_df[g].round().sum())
                if start_up_df is not None and not start_up_df.empty and g in start_up_df.columns
                else int((st.diff() == 1).sum())
            )
            if not cost_frame.empty and g in cost_frame.columns:
                start_cost_total = float(cost_frame[g].sum())
            else:
                start_cost_total = 0.0
            if cost_dense is not None and g in cost_dense.columns and len(cost_dense):
                suc = float(cost_dense[g].mean())  # mean over the horizon when time-varying
            else:
                suc = 0.0
            online_hours = float((st * weights).sum())
            online_fraction = float(st.mean()) if n_snap else 0.0
            carrier = str(gens.at[g, "carrier"]) if "carrier" in gens.columns else ""
            rows.append({
                "name": g,
                "component": list_name,
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


def build_maintenance(network: pypsa.Network) -> dict[str, Any] | None:
    """Scheduled-maintenance summary for ``maintainable`` Generators/Links/Processes.

    Reads the solved ``maintenance`` (1 = in maintenance) and ``maintenance_start``
    series; per unit reports the events, hours in maintenance, the derated MW and
    the ``segments`` (run-length on/off, same shape as the commitment view).
    ``None`` when nothing is maintainable or no schedule was solved.
    """
    weights = network.snapshot_weightings["objective"]
    rows: list[dict[str, Any]] = []
    for list_name in COMMITTABLE_LISTS:
        if list_name not in network.components.keys():
            continue
        comp = network.components[list_name]
        static = comp.static
        if static.empty or "maintainable" not in static.columns:
            continue
        maint = comp.dynamic.get("maintenance")
        start = comp.dynamic.get("maintenance_start")
        if maint is None or maint.empty:
            continue
        for name in static.index[static["maintainable"].astype(bool)]:
            if name not in maint.columns:
                continue
            m = maint[name].round().astype(int)
            events = (
                int(start[name].round().sum())
                if start is not None and not start.empty and name in start.columns
                else int(((m.diff().fillna(m.iloc[0]) == 1)).sum())
            )
            rows.append({
                "name": str(name),
                "component": list_name,
                "events": events,
                "hoursInMaintenance": round(float((m * weights).sum()), 2),
                "maintenancePu": float(static.at[name, "maintenance_pu"]) if "maintenance_pu" in static.columns else 1.0,
                "segments": _segments(m.tolist()),
            })
    if not rows:
        return None
    return {
        "units": rows,
        "totals": {"unitCount": len(rows), "events": sum(r["events"] for r in rows)},
    }
