"""Per-period helpers for multi-investment (pathway) results.

In a multi-investment run a component only exists in the investment periods
where ``build_year <= period < build_year + lifetime``. PyPSA's optimiser
masks inactive assets per period; the results layer must do the same, or it
counts not-yet-built and retired units in capacity, curtailment and CAPEX.
These helpers expose that mask and the objective weighting so every consumer
applies them the same way.
"""
from __future__ import annotations

from typing import Any

import pandas as pd


def is_pathway(network: Any) -> bool:
    """Whether the solved network carries (period, timestep) snapshots."""
    return isinstance(network.snapshots, pd.MultiIndex) and "period" in network.snapshots.names


def periods(network: Any) -> list[int]:
    """Investment periods in snapshot order (empty for a single-period network)."""
    if not is_pathway(network):
        return []
    return [int(p) for p in network.snapshots.get_level_values("period").unique()]


def period_objective_weights(network: Any) -> dict[int, float]:
    """Investment-period ``objective`` weighting per period (1.0 if absent)."""
    out: dict[int, float] = {}
    ipw = getattr(network, "investment_period_weightings", None)
    for p in periods(network):
        weight = 1.0
        if ipw is not None and "objective" in getattr(ipw, "columns", []) and p in ipw.index:
            weight = float(ipw.at[p, "objective"])
        out[p] = weight
    return out


def active_assets(network: Any, list_name: str, period: int) -> pd.Series:
    """Boolean mask (index = asset name) of assets active in ``period``.

    Args:
        network: Solved network.
        list_name: PyPSA components list name, e.g. ``"generators"``.
        period: Investment period (year).

    Returns:
        ``True`` where ``build_year <= period < build_year + lifetime``. All
        ``True`` when the mask cannot be resolved, so a failure never hides
        capacity.
    """
    static = getattr(network, list_name)
    try:
        mask = getattr(network.components, list_name).get_active_assets(investment_period=period)
        return mask.reindex(static.index).fillna(True).astype(bool)
    except Exception:  # noqa: BLE001 — fall back to "everything active"
        return pd.Series(True, index=static.index)


def snapshot_active_mask(network: Any, list_name: str) -> pd.DataFrame | None:
    """Snapshots x assets boolean activity mask, or ``None`` for single-period runs."""
    if not is_pathway(network):
        return None
    static = getattr(network, list_name)
    level = network.snapshots.get_level_values("period")
    frame = pd.DataFrame(True, index=network.snapshots, columns=static.index)
    for p in periods(network):
        active = active_assets(network, list_name, p)
        frame.loc[level == p, :] = active.to_numpy()[None, :]
    return frame


def capacity_by_period(network: Any, list_name: str, capacity: pd.Series) -> dict[int, float]:
    """Sum ``capacity`` (MW, index = asset name) over the assets active in each period."""
    return {
        p: float(capacity[active_assets(network, list_name, p).reindex(capacity.index).fillna(False)].sum())
        for p in periods(network)
    }
