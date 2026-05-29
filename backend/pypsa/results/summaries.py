from __future__ import annotations

from typing import Any

import pandas as pd
import pypsa

from ..utils.series import weighted_sum


def _snapshot_label(snapshot: Any) -> str:
    if isinstance(snapshot, tuple) and len(snapshot) == 2:
        period, timestep = snapshot
        return f"{int(period)}|{pd.Timestamp(timestep).isoformat() if not isinstance(timestep, str) else timestep}"
    try:
        return pd.Timestamp(snapshot).isoformat()
    except Exception:
        return str(snapshot)


def _rolling_window_summaries(
    snapshots: pd.Index,
    horizon: int,
    overlap: int,
) -> list[dict[str, Any]]:
    step = max(1, horizon - overlap)
    windows: list[dict[str, Any]] = []
    starts = list(range(0, len(snapshots), step))
    for index, start in enumerate(starts):
        end = min(len(snapshots), start + horizon)
        accepted_end = end if index == len(starts) - 1 else min(len(snapshots), start + step)
        solved = snapshots[start:end]
        accepted = snapshots[start:accepted_end]
        periods: list[int] = []
        if isinstance(snapshots, pd.MultiIndex):
            periods = sorted({int(p) for p in solved.get_level_values("period").unique()})
        windows.append({
            "index": index + 1,
            "solvedStart": _snapshot_label(solved[0]),
            "solvedEnd": _snapshot_label(solved[-1]),
            "acceptedStart": _snapshot_label(accepted[0]),
            "acceptedEnd": _snapshot_label(accepted[-1]),
            "solvedCount": int(len(solved)),
            "acceptedCount": int(len(accepted)),
            "periods": periods,
        })
    return windows


def _pathway_period_summaries(
    network: pypsa.Network,
    dispatch_frame: pd.DataFrame,
    load_dispatch: pd.Series,
    price_series: pd.Series,
    emissions_factors: dict[str, float],
) -> list[dict[str, Any]]:
    if not isinstance(network.snapshots, pd.MultiIndex):
        return []
    summaries: list[dict[str, Any]] = []
    dispatch_only = dispatch_frame.clip(lower=0.0)
    for period in network.snapshots.get_level_values("period").unique():
        period_index = network.snapshots[network.snapshots.get_level_values("period") == period]
        weight = network.snapshot_weightings["objective"].reindex(period_index).fillna(1.0)
        dispatch_period = dispatch_only.loc[period_index]
        total_dispatch = float((dispatch_period.sum(axis=1) * weight).sum())
        total_emissions = 0.0
        for name in dispatch_period.columns:
            if name not in network.generators.index:
                continue
            carrier = str(network.generators.at[name, "carrier"])
            total_emissions += float((dispatch_period[name] * emissions_factors.get(carrier, 0.0) * weight).sum())
        summaries.append({
            "period": int(period),
            "snapshotCount": int(len(period_index)),
            "modeledHours": float(weight.sum()),
            "totalDispatch": total_dispatch,
            "totalEmissions": total_emissions,
            "averagePrice": float(price_series.loc[period_index].mean()) if len(period_index) else 0.0,
            "peakLoad": float(load_dispatch.loc[period_index].max()) if len(period_index) else 0.0,
            "objectiveWeight": float(network.investment_period_weightings.at[int(period), "objective"]),
            "yearsWeight": float(network.investment_period_weightings.at[int(period), "years"]),
        })
    return summaries
