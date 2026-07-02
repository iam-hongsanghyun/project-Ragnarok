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


_HOUR_RE = None  # lazily compiled in _extract_hour


def _extract_hour(label: Any) -> int | None:
    """Hour-of-day (0–23) from a snapshot label like '2020-01-01 04:00' or '04:00'."""
    global _HOUR_RE
    if _HOUR_RE is None:
        import re
        _HOUR_RE = re.compile(r"(\d{1,2}):(\d{2})")
    m = _HOUR_RE.search(str(label))
    return int(m.group(1)) if m else None


def duration_curve(rows: list[dict[str, Any]], column: str, *, max_points: int = 800) -> dict[str, Any]:
    """Sorted-descending values of ``column`` (the load/price duration curve),
    downsampled to at most ``max_points`` by striding (order preserved)."""
    vals = [_num(r.get(column)) for r in rows if r.get(column) not in (None, "")]
    vals.sort(reverse=True)
    n = len(vals)
    if max_points and n > max_points:
        step = n / max_points
        vals = [vals[min(n - 1, int(i * step))] for i in range(max_points)]
    return {"mode": "duration", "column": column, "values": [round(v, 6) for v in vals]}


def daily_profile(rows: list[dict[str, Any]], index_col: str, columns: list[str]) -> dict[str, Any]:
    """Mean of each column by hour-of-day (0–23), from the snapshot label."""
    sums = {c: [0.0] * 24 for c in columns}
    counts = [0] * 24
    for r in rows:
        h = _extract_hour(r.get(index_col))
        if h is None or not (0 <= h < 24):
            continue
        counts[h] += 1
        for c in columns:
            sums[c][h] += _num(r.get(c))
    hours = list(range(24))
    series = [
        {"key": c, "values": [round(sums[c][h] / counts[h], 6) if counts[h] else 0.0 for h in hours]}
        for c in columns
    ]
    return {"mode": "daily_profile", "hours": hours, "series": series}


def grouped_aggregate(
    rows: list[dict[str, Any]], group_col: str, value_col: str, agg: str = "sum",
) -> dict[str, Any]:
    """Aggregate ``value_col`` grouped by ``group_col`` (sum/mean/max/min/count),
    sorted by value descending."""
    import numpy as np

    buckets: dict[str, list[float]] = {}
    for r in rows:
        g = str(r.get(group_col, "")).strip() or "(blank)"
        buckets.setdefault(g, []).append(_num(r.get(value_col)))

    def _agg(vals: list[float]) -> float:
        if not vals:
            return 0.0
        a = np.asarray(vals, dtype=float)
        return float({"sum": a.sum, "mean": a.mean, "max": a.max, "min": a.min,
                      "count": lambda: float(a.size)}.get(agg, a.sum)())

    out = [{"label": g, "value": round(_agg(v), 6)} for g, v in buckets.items()]
    out.sort(key=lambda d: d["value"], reverse=True)
    return {"mode": "grouped", "groupBy": group_col, "value": value_col, "agg": agg, "bars": out}


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


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
