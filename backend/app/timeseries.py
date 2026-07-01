"""Shared time-series windowing + downsampling for the thin-client API.

Both the working-model session store (:mod:`session_store`) and the stored-run
results (:mod:`run_store`) serve time-series the same way: the client asks for a
row window ``[start, end)`` and a maximum number of points, and the server slices
and reduces server-side so the browser only ever receives what it draws.

Centralising the maths here keeps the two call sites identical and gives the
downsampling one well-tested home.
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

# Candidate index columns for a time-series sheet, in priority order. A series
# row is ``{<index>: <timestamp>, <assetA>: value, …}``.
INDEX_KEYS = ("snapshot", "name", "datetime", "period")

Agg = Literal["mean", "point", "max", "min"]
VALID_AGG = ("mean", "point", "max", "min")


def series_index_col(columns: list[str]) -> str:
    """Return the index (time-axis) column among ``columns``."""
    for key in INDEX_KEYS:
        if key in columns:
            return key
    return columns[0] if columns else "snapshot"


def df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame → JSON-safe list of row dicts (NaN/NaT → None)."""
    return df.replace({np.nan: None}).to_dict(orient="records")


TransformOp = Literal["scale", "offset", "shift", "interpolate", "clip", "grow"]
VALID_TRANSFORMS = ("scale", "offset", "shift", "interpolate", "clip", "grow")


def transform_rows(
    rows: list[dict[str, Any]],
    index_col: str,
    op: TransformOp,
    *,
    columns: list[str] | None = None,
    factor: float = 1.0,
    delta: float = 0.0,
    shift: int = 0,
    wrap: bool = True,
    min_value: float | None = None,
    max_value: float | None = None,
    growth_pct: float = 0.0,
) -> list[dict[str, Any]]:
    """Apply a bulk transform to the value columns of wide series ``rows`` (T1).

    ``rows`` are ``{index_col: <ts>, <asset>: <value>, …}``. Only the value
    columns are touched (all columns except ``index_col``, optionally restricted
    to ``columns``); the timestamp column is preserved. Non-numeric cells coerce
    to NaN → ``None``.

    Ops:
        scale       ``v → v · factor``
        offset      ``v → v + delta``
        shift       roll each column by ``shift`` steps; ``wrap`` cyclically (no
                    gaps, reversible) or edge-fill the exposed end
        interpolate linear-fill blank/None/NaN cells (edge → nearest neighbour)
        clip        bound to ``[min_value, max_value]``
        grow        ramp-scale for a demand-growth forecast: the first snapshot is
                    unchanged and the last is scaled by ``1 + growth_pct/100``,
                    linearly in between

    Algorithm (shift): ``out[i] = in[(i - shift) mod N]`` when ``wrap`` else
    ``out[i] = in[i - shift]`` with the exposed end held at the nearest value.
    Algorithm (grow): ``out[i] = in[i] · (1 + (growth_pct/100)·i/(N-1))``.
    """
    if not rows:
        return rows
    df = pd.DataFrame(rows)
    value_cols = [c for c in df.columns if c != index_col]
    if columns:
        wanted = set(columns)
        value_cols = [c for c in value_cols if c in wanted]
    if not value_cols:
        return rows

    num = df[value_cols].apply(pd.to_numeric, errors="coerce")

    if op == "scale":
        num = num * float(factor)
    elif op == "offset":
        num = num + float(delta)
    elif op == "shift":
        k = int(shift)
        if wrap:
            num = pd.DataFrame(
                {c: np.roll(num[c].to_numpy(dtype=float), k) for c in value_cols},
                index=num.index,
            )
        else:
            num = num.shift(k).ffill().bfill()
    elif op == "interpolate":
        num = num.interpolate(method="linear", limit_direction="both")
    elif op == "clip":
        lo = None if min_value is None else float(min_value)
        hi = None if max_value is None else float(max_value)
        num = num.clip(lower=lo, upper=hi)
    elif op == "grow":
        n = len(num)
        if n > 1:
            ramp = 1.0 + (float(growth_pct) / 100.0) * (np.arange(n) / (n - 1))
            num = num.mul(pd.Series(ramp, index=num.index), axis=0)
    else:
        raise ValueError(f"unknown transform op {op!r}")

    out = df.copy()
    for c in value_cols:
        out[c] = num[c]
    return out.replace({np.nan: None}).to_dict(orient="records")


def generate_snapshots(start: str, end: str, step_hours: float = 1.0) -> list[str]:
    """Snapshot timestamps for ``[start, end]`` at ``step_hours`` (T1 retarget).

    Returns ``"YYYY-MM-DD HH:MM"`` strings (the app's canonical snapshot form).
    """
    step = max(step_hours, 1e-6)
    # pandas freq wants an integer-ish alias; minutes keep sub-hourly steps exact.
    freq = f"{int(round(step * 60))}min"
    idx = pd.date_range(start=start, end=end, freq=freq)
    return [ts.strftime("%Y-%m-%d %H:%M") for ts in idx]


def retarget_rows(
    rows: list[dict[str, Any]],
    index_col: str,
    new_snapshots: list[str],
    fill: str = "tile",
) -> list[dict[str, Any]]:
    """Reindex wide series ``rows`` onto ``new_snapshots`` positionally (T1).

    Each new snapshot takes the source row at the same position; when the new
    window is longer, ``tile`` cycles the source (reuse a base year to fill future
    years) and ``pad`` repeats the last row. Shorter windows truncate. The value
    columns carry over; the index column is set to the new snapshot.
    """
    out: list[dict[str, Any]] = []
    n_src = len(rows)
    for i, snap in enumerate(new_snapshots):
        row: dict[str, Any] = {}
        if n_src:
            if i < n_src:
                src = rows[i]
            elif fill == "pad":
                src = rows[-1]
            else:  # tile
                src = rows[i % n_src]
            row = {k: v for k, v in src.items() if k != index_col}
        row[index_col] = snap
        out.append(row)
    return out


def downsample(df: pd.DataFrame, max_points: int, agg: Agg, index_col: str) -> pd.DataFrame:
    """Reduce ``df`` to at most ``max_points`` rows using ``agg``.

    Algorithm:
        Split the N rows into ``min(N, max_points)`` contiguous buckets
        (``numpy.array_split``). Each bucket yields one output row, labelled by
        the bucket's first index value:
          * ``mean`` — arithmetic mean of each numeric column over the bucket
          * ``max`` / ``min`` — extremum of each numeric column over the bucket
          * ``point`` — the bucket's first row verbatim (decimation)
        ASCII: out[k] = reduce(rows[bucket_k]); buckets partition [0, N).

    Non-numeric value cells coerce to NaN under mean/max/min (not meaningful to
    aggregate); ``point`` preserves them.
    """
    n = len(df)
    if max_points <= 0 or n <= max_points:
        return df.reset_index(drop=True)

    value_cols = [c for c in df.columns if c != index_col]
    buckets = np.array_split(np.arange(n), max_points)
    out_rows: list[dict[str, Any]] = []
    for bucket in buckets:
        if len(bucket) == 0:
            continue
        sub = df.iloc[bucket]
        first = sub.iloc[0]
        row: dict[str, Any] = {index_col: first[index_col]}
        if agg == "point":
            for col in value_cols:
                row[col] = first[col]
        else:
            for col in value_cols:
                numeric = pd.to_numeric(sub[col], errors="coerce")
                if agg == "mean":
                    value = numeric.mean()
                elif agg == "max":
                    value = numeric.max()
                else:  # min
                    value = numeric.min()
                row[col] = None if pd.isna(value) else float(value)
        out_rows.append(row)
    return pd.DataFrame(out_rows)


def slice_and_reduce(
    df: pd.DataFrame,
    *,
    start: int,
    end: int | None,
    max_points: int,
    agg: str,
    index_col: str,
) -> dict[str, Any]:
    """Window ``df`` to ``[start, end)`` then downsample to ``max_points``.

    Returns ``{indexCol, total, window:{start,end}, returned, agg, columns, rows}``.
    Column selection (pushdown) is the caller's job — do it at the Parquet read so
    only needed columns are loaded.
    """
    if agg not in VALID_AGG:
        agg = "mean"
    max_points = max(1, int(max_points))
    total = len(df)
    start = max(0, int(start))
    end = total if end is None else min(total, int(end))
    if end < start:
        end = start
    window = df.iloc[start:end]
    reduced = downsample(window, max_points, agg, index_col)  # type: ignore[arg-type]
    return {
        "indexCol": index_col,
        "total": total,
        "window": {"start": start, "end": end},
        "returned": len(reduced),
        "agg": agg,
        "columns": [str(c) for c in reduced.columns],
        "rows": df_to_records(reduced),
    }
