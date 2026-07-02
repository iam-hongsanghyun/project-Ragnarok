"""Server-side derived chart-series (X1).

For a stored run, the dashboard's *system* charts want aggregated series —
dispatch by carrier, total load, mean nodal price — which the browser currently
derives from the raw per-asset output series (thousands of columns × snapshots
for a large network). This computes those aggregates on the backend from a
windowed+downsampled series slice, so the browser fetches ready-to-plot data.

Pure over the ``run_series_window`` shape (``{columns, rows, indexCol}``) + the
run's generator→carrier map, so it is unit-tested directly and reused by the
run endpoint.
"""
from __future__ import annotations

from typing import Any

# metric → the output series sheet it aggregates.
METRIC_SHEET = {
    "dispatch_by_carrier": "generators-p",
    "load": "loads-p",
    "system_price": "buses-marginal_price",
}


def carrier_map(model: dict[str, Any] | None) -> dict[str, str]:
    """generator name → carrier, from the run's model (blank carrier → name)."""
    out: dict[str, str] = {}
    for row in (model or {}).get("generators", []) or []:
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        out[name] = str(row.get("carrier", "")).strip() or name
    return out


def derive_series(
    columns: list[str],
    rows: list[dict[str, Any]],
    index_col: str,
    *,
    metric: str,
    carriers: dict[str, str],
) -> dict[str, Any]:
    """Aggregate a windowed series slice into a system chart series.

    - ``dispatch_by_carrier``: sum each generator's positive dispatch into its
      carrier bucket.
    - ``load``: sum across all load columns per snapshot.
    - ``system_price``: mean across all bus columns per snapshot.
    """
    data_cols = [c for c in columns if c != index_col]
    labels = [r.get(index_col) for r in rows]
    n = len(rows)

    if metric == "dispatch_by_carrier":
        buckets: dict[str, list[float]] = {}
        for c in data_cols:
            buckets.setdefault(carriers.get(c, c), [0.0] * n)
        for i, r in enumerate(rows):
            for c in data_cols:
                v = _num(r.get(c))
                if v > 0:
                    buckets[carriers.get(c, c)][i] += v
        series = [
            {"key": k, "values": [round(x, 4) for x in v]}
            for k, v in sorted(buckets.items())
        ]
    elif metric == "load":
        vals = [round(sum(_num(r.get(c)) for c in data_cols), 4) for r in rows]
        series = [{"key": "load", "values": vals}]
    elif metric == "system_price":
        vals: list[float] = []
        for r in rows:
            xs = [_num(r.get(c)) for c in data_cols if r.get(c) is not None]
            vals.append(round(sum(xs) / len(xs), 4) if xs else 0.0)
        series = [{"key": "price", "values": vals}]
    else:
        raise ValueError(f"Unknown derived metric {metric!r}. Options: {sorted(METRIC_SHEET)}.")

    return {"metric": metric, "indexCol": index_col, "labels": labels, "series": series}


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
