"""Server-side import analysis (X2).

Per-column statistics for a workbook sheet, computed on the backend so the
browser never has to crunch thousands of rows just to show a summary. Mirrors
the KPIs the in-browser analyser produced (count / nulls / min / max / mean /
median / std / sum / quartiles + a small histogram for numeric columns;
distinct + top values for categorical), so the frontend just renders.

Pure over a list of row dicts (the shape the session store returns), so it is
unit-tested directly and reused by the session endpoint.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

_MAX_TOP = 10       # categorical: top-N values to return
_HIST_BINS = 20     # numeric: histogram resolution


def _numeric_stats(s: pd.Series) -> dict[str, Any]:
    vals = pd.to_numeric(s, errors="coerce").dropna()
    n = int(vals.size)
    if n == 0:
        return {"kind": "numeric", "count": 0, "nulls": int(s.size)}
    arr = vals.to_numpy(dtype=float)
    counts, edges = np.histogram(arr, bins=min(_HIST_BINS, max(1, n)))
    return {
        "kind": "numeric",
        "count": n,
        "nulls": int(s.size - n),
        "min": round(float(arr.min()), 6),
        "max": round(float(arr.max()), 6),
        "mean": round(float(arr.mean()), 6),
        "median": round(float(np.median(arr)), 6),
        "std": round(float(arr.std(ddof=0)), 6),
        "sum": round(float(arr.sum()), 6),
        "p25": round(float(np.percentile(arr, 25)), 6),
        "p75": round(float(np.percentile(arr, 75)), 6),
        "histogram": {
            "counts": [int(c) for c in counts],
            "edges": [round(float(e), 6) for e in edges],
        },
    }


def _categorical_stats(s: pd.Series) -> dict[str, Any]:
    nonblank = s[s.astype(str).str.strip() != ""]
    vc = nonblank.astype(str).value_counts()
    return {
        "kind": "categorical",
        "count": int(nonblank.size),
        "nulls": int(s.size - nonblank.size),
        "distinct": int(vc.size),
        "top": [{"value": str(k), "count": int(v)} for k, v in vc.head(_MAX_TOP).items()],
    }


def _is_numeric_column(s: pd.Series) -> bool:
    """A column is numeric when most non-blank values parse as numbers."""
    nonblank = s[s.astype(str).str.strip() != ""]
    if nonblank.size == 0:
        return False
    parsed = pd.to_numeric(nonblank, errors="coerce")
    return int(parsed.notna().sum()) >= max(1, int(0.5 * nonblank.size))


def column_statistics(rows: list[dict[str, Any]], columns: list[str] | None = None) -> dict[str, Any]:
    """Per-column statistics for a sheet's rows.

    Args:
        rows: The sheet's row dicts.
        columns: Optional subset/order; default = union of keys across rows.

    Returns:
        ``{total, columns: [{name, kind, ...stats}]}``.
    """
    if not rows:
        return {"total": 0, "columns": []}
    df = pd.DataFrame(rows)
    cols = columns or list(df.columns)
    out: list[dict[str, Any]] = []
    for col in cols:
        if col not in df.columns:
            continue
        s = df[col]
        stats = _numeric_stats(s) if _is_numeric_column(s) else _categorical_stats(s)
        out.append({"name": col, **stats})
    return {"total": int(len(df)), "columns": out}
