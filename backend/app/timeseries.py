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


TransformOp = Literal["scale", "offset", "shift", "interpolate", "clip"]
VALID_TRANSFORMS = ("scale", "offset", "shift", "interpolate", "clip")


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

    Algorithm (shift): ``out[i] = in[(i - shift) mod N]`` when ``wrap`` else
    ``out[i] = in[i - shift]`` with the exposed end held at the nearest value.
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
    else:
        raise ValueError(f"unknown transform op {op!r}")

    out = df.copy()
    for c in value_cols:
        out[c] = num[c]
    return out.replace({np.nan: None}).to_dict(orient="records")


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
