from __future__ import annotations

from typing import Any

import pandas as pd
import pypsa

from ..utils.emissions import primary_energy_emissions
from ..utils.shedding import is_shedding



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
    *,
    generator_capacity_by_period: dict[int, float] | None = None,
    storage_capacity_by_period: dict[int, float] | None = None,
    expansion_results: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Per-investment-period totals.

    Beyond the dispatch / emission / price / peak-load figures, each period
    reports ``installedCapacityMw`` and ``storageCapacityMw`` (assets active in
    that period only) and ``capexAnnual`` (annuity of the extendable assets
    active in it, before the investment-period weighting). ``averagePrice`` is
    the snapshot-weighted mean.
    """
    if not isinstance(network.snapshots, pd.MultiIndex):
        return []
    summaries: list[dict[str, Any]] = []
    dispatch_only = dispatch_frame.clip(lower=0.0)
    # The injected load_shedding_ backstop is a modelling artifact, not real
    # generation — exclude it from the period energy total, matching the
    # carrier_energy / generator_energy exclusion in the same payload.
    real_cols = [c for c in dispatch_only.columns if not is_shedding(c)]
    # Per-snapshot generator emissions on PyPSA's primary_energy basis (RB10): p/eta * co2_emissions
    # (signed, tCO2/h). A period's total is sum_t w_t * rate_t - the run total weights it again by the
    # period's ``yearsWeight``; storage depletion is a whole-horizon stock change and is not split by period.
    rate = primary_energy_emissions(network, emissions_factors).generator_rate_tph
    for period in network.snapshots.get_level_values("period").unique():
        period_index = network.snapshots[network.snapshots.get_level_values("period") == period]
        # Energy totals use the `generators` snapshot weighting — the same basis
        # as every other energy total in the payload (carrier_energy,
        # generator_energy). `modeledHours` reports the sum of that same
        # weighting, so totalDispatch / modeledHours is the period's average
        # supplied MW.
        weight = network.snapshot_weightings["generators"].reindex(period_index).fillna(1.0)
        dispatch_period = dispatch_only.loc[period_index]
        total_dispatch = float((dispatch_period[real_cols].sum(axis=1) * weight).sum())
        total_emissions = float(rate.reindex(period_index).mul(weight, axis=0).sum().sum()) if rate.shape[1] else 0.0
        summaries.append({
            "period": int(period),
            "snapshotCount": int(len(period_index)),
            "modeledHours": float(weight.sum()),
            "totalDispatch": total_dispatch,
            "totalEmissions": total_emissions,
            "averagePrice": (
                float((price_series.loc[period_index] * weight).sum() / weight.sum())
                if len(period_index) and float(weight.sum()) > 0.0
                else 0.0
            ),
            "peakLoad": float(load_dispatch.loc[period_index].max()) if len(period_index) else 0.0,
            "objectiveWeight": float(network.investment_period_weightings.at[int(period), "objective"]),
            "yearsWeight": float(network.investment_period_weightings.at[int(period), "years"]),
            "installedCapacityMw": (generator_capacity_by_period or {}).get(int(period)),
            "storageCapacityMw": (storage_capacity_by_period or {}).get(int(period)),
            "capexAnnual": (
                float(sum(r.get("capex_by_period", {}).get(str(int(period)), 0.0) for r in expansion_results))
                if expansion_results is not None
                else None
            ),
        })
    return summaries
