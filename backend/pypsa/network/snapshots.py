from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pypsa

from ..pathway import PathwayConfig
from ..utils.coerce import number


def parse_snapshot_labels(labels: Any) -> pd.DatetimeIndex:
    """Parse snapshot labels to a **naive** ``DatetimeIndex`` (wall-clock time).

    A timezone designator (``Z``, ``+09:00``) is dropped keeping the wall-clock
    reading, so a time-series sheet stamped ``2025-01-01T00:00:00Z`` lines up
    with a snapshots sheet stamped ``2025-01-01 00:00`` instead of silently
    failing to match (every value would reindex to NaN and the bound vanish).
    Raises ``ValueError``/``TypeError`` when the labels are not datetimes — the
    caller falls back to string labels.
    """
    try:
        idx = pd.DatetimeIndex(pd.to_datetime(labels))
    except (ValueError, TypeError):
        # Mixed offsets: normalise each stamp to its own wall-clock reading.
        idx = pd.DatetimeIndex([pd.Timestamp(str(v)).tz_localize(None) for v in labels])
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return idx


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
            timesteps = parse_snapshot_labels(labels)
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
        idx = parse_snapshot_labels(unique_labels)
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


WEIGHTING_COLUMNS = ("objective", "stores", "generators")


def imported_weightings(
    model: dict[str, list[dict[str, Any]]],
    snapshots: pd.Index,
) -> pd.DataFrame | None:
    """Per-snapshot weightings carried by the ``snapshots`` sheet, or ``None``.

    PyPSA's ``snapshots.csv`` stores ``objective`` / ``stores`` / ``generators``
    columns (hours each snapshot represents). A 3-hourly network exported with
    weight 3 must keep it, or every energy and cost total is a third of the
    truth. Rows are matched to ``snapshots`` by label (first occurrence wins);
    blank/non-numeric cells and unmatched snapshots count as 1 h. Returns
    ``None`` when the sheet carries no weighting column at all.
    """
    rows = model.get("snapshots") or []
    present = [c for c in WEIGHTING_COLUMNS if any(r.get(c) not in (None, "") for r in rows)]
    if not present or len(snapshots) == 0:
        return None
    labels: list[str] = []
    values: dict[str, list[float]] = {c: [] for c in present}
    for r in rows:
        label = next(
            (str(r[k]) for k in ("snapshot", "name", "datetime", "timestep", "index")
             if r.get(k) not in (None, "")),
            None,
        )
        if label is None:
            continue
        labels.append(label)
        for c in present:
            values[c].append(number(r.get(c), float("nan")))
    try:
        keys: pd.Index = parse_snapshot_labels(labels)
    except Exception:
        keys = pd.Index(labels, dtype="object")
    frame = pd.DataFrame(values, index=keys)
    if "period" in (snapshots.names or []) and isinstance(snapshots, pd.MultiIndex):
        periods = [
            int(number(r.get("period"), 0)) for r in rows
            if any(r.get(k) not in (None, "") for k in ("snapshot", "name", "datetime", "timestep", "index"))
        ]
        frame.index = pd.MultiIndex.from_arrays([periods, keys], names=["period", "timestep"])
    frame = frame[~frame.index.duplicated(keep="first")]
    out = frame.reindex(snapshots).astype(float)
    return out.fillna(1.0)


def rescale_weightings(
    full_weights: pd.DataFrame,
    full: pd.Index,
    windowed: pd.Index,
    start: int,
    stop: int,
    step: int,
    sampled: bool,
) -> pd.DataFrame:
    """Weightings for the modelled snapshots, built from the imported ones.

    Contiguous / strided runs: each kept snapshot carries the SUM of the
    imported weights of the ``step`` rows it stands for (a stride of 1 keeps its
    own weight unchanged). Sampled runs: ``objective``/``generators`` keep their
    own imported weights, scaled so they integrate to the whole window
    ``[start, stop)`` the sample represents; ``stores`` stays the physical
    block-sum so the storage SOC recursion is hours-true.

    Algorithm:
        $$w_i = \\sum_{j=p_i}^{\\min(p_i+s,\\,e_i)-1} w^{imp}_j,\\qquad
          w^{samp}_i = w^{imp}_{p_i}\\,\\frac{\\sum_{j=a}^{b-1} w^{imp}_j}{\\sum_k w^{imp}_{p_k}}$$
        ASCII: w_i = sum(w_imp[p_i : min(p_i+s, e_i)]); sampled: w_i = w_imp[p_i]
        * sum(w_imp[a:b]) / sum(w_imp[kept]).
        p_i position of kept snapshot i in the full index, s the stride (rows),
        e_i the end of its investment period (or ``b``), [a, b) the window;
        weights in hours.
    """
    positions = full.get_indexer(windowed)
    if isinstance(full, pd.MultiIndex) and "period" in (full.names or []):
        period = np.asarray(full.get_level_values("period"))
        group_end = np.empty(len(full), dtype=int)
        end = len(full)
        for i in range(len(full) - 1, -1, -1):
            if i + 1 < len(full) and period[i + 1] != period[i]:
                end = i + 1
            group_end[i] = end
        limits = group_end[positions]
    else:
        limits = np.full(len(positions), stop, dtype=int)
    out = pd.DataFrame(index=windowed, columns=list(full_weights.columns), dtype=float)
    for col in full_weights.columns:
        w = full_weights[col].to_numpy(dtype=float)
        csum = np.concatenate([[0.0], np.cumsum(w)])
        ends = np.minimum(positions + step, np.maximum(limits, positions + 1))
        block = csum[ends] - csum[positions]
        if sampled and col != "stores":
            kept = w[positions]
            window_total = float(csum[stop] - csum[start])
            kept_total = float(kept.sum())
            out[col] = kept * (window_total / kept_total) if kept_total > 0 else block
        else:
            out[col] = block
    return out


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
