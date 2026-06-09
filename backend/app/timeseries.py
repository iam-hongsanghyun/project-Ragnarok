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
