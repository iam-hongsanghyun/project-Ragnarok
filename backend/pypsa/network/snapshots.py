from __future__ import annotations

from typing import Any

import pandas as pd
import pypsa

from ..pathway import PathwayConfig
from ..utils.coerce import number


def _snapshots_index(
    model: dict[str, list[dict[str, Any]]],
    pathway: PathwayConfig,
    notes: list[str] | None = None,
) -> pd.Index:
    """Build the snapshot index from the `snapshots` sheet, if present.

    Snapshot date strings are expected to already be ISO (the frontend
    normalizes input dates to ISO using the user's Date format setting before
    the model is sent here), so they parse unambiguously.

    The index is **sorted chronologically**: PyPSA steps through snapshots in
    index order and inter-temporal physics (storage state-of-charge, ramping,
    rolling horizon) are path-dependent, so a non-chronological sheet — e.g. a
    union of imported date ranges — would otherwise corrupt the solve and the
    time-axis of every chart. Reordering is reported via ``notes``.
    """
    rows = model.get("snapshots") or []
    labels: list[str] = []
    periods: list[int] = []
    for r in rows:
        for k in ("snapshot", "name", "datetime", "timestep", "index"):
            v = r.get(k)
            if v not in (None, ""):
                labels.append(str(v))
                break
        if pathway.enabled and pathway.snapshot_mapping_mode == "explicit_period_column":
            period_value = r.get("period")
            if period_value in (None, ""):
                periods.append(0)
            else:
                periods.append(int(number(period_value)))
    if not labels:
        return pd.Index([], dtype="object")
    if pathway.enabled and pathway.snapshot_mapping_mode == "explicit_period_column":
        try:
            timesteps = pd.to_datetime(labels)
        except Exception:
            timesteps = pd.Index(labels, dtype="object")
        snapshots = pd.MultiIndex.from_arrays([periods, timesteps], names=["period", "timestep"])
        snapshots.name = "snapshot"
        ordered = snapshots.sort_values()
        if notes is not None and not ordered.equals(snapshots):
            notes.append(
                f"Snapshots were not in chronological order — reordered {len(ordered)} "
                "snapshots by (period, time) so storage/ramping dynamics are correct."
            )
        return ordered
    # Single-period run: dedupe labels so a pathway workbook (which lists the
    # same timestamp once per period via the `period` column) still produces
    # a unique snapshot index. Without this PyPSA's internal reindexing
    # raises "Reindexing only valid with uniquely valued Index objects".
    seen: set[str] = set()
    unique_labels: list[str] = []
    for label in labels:
        if label in seen:
            continue
        seen.add(label)
        unique_labels.append(label)
    try:
        idx = pd.to_datetime(unique_labels)
    except Exception:
        # Non-datetime labels (e.g. "now" / integer steps) — keep input order.
        return pd.Index(unique_labels, dtype="object")
    ordered = idx.sort_values()
    if notes is not None and not ordered.equals(idx):
        notes.append(
            f"Snapshots were not in chronological order — reordered {len(ordered)} "
            "snapshots by time so storage/ramping dynamics and chart time-axes are correct."
        )
    return ordered


def _apply_pathway_config(
    network: pypsa.Network,
    pathway: PathwayConfig,
    notes: list[str],
) -> None:
    if not pathway.enabled or not pathway.periods:
        return
    periods = [row.period for row in pathway.periods]
    network.set_investment_periods(periods)
    network.investment_period_weightings = network.investment_period_weightings.reindex(periods).fillna(1.0)
    for row in pathway.periods:
        network.investment_period_weightings.at[row.period, "objective"] = float(row.objective_weight)
        network.investment_period_weightings.at[row.period, "years"] = float(row.years_weight)
    notes.append(
        "Enabled pathway planning for periods "
        + ", ".join(str(period) for period in periods)
        + "."
    )


def _normalize_dynamic_snapshot_index_names(network: pypsa.Network) -> None:
    for component in network.all_components:
        dynamic = network.c[component].dynamic
        for attr in dynamic:
            dynamic[attr].index.name = "snapshot"
