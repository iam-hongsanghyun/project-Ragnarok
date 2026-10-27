"""PyPSA ``statistics`` passthrough — the canonical per-carrier metrics table.

``network.statistics()`` returns PyPSA's standard summary (optimal / installed
capacity, supply, withdrawal, energy balance, capacity factor, curtailment,
capital & operational expenditure, revenue, market value, …) grouped by
component and carrier. We surface it verbatim as an analytics table rather than
re-deriving any of it — engine-feature parity, computed by PyPSA itself.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import pypsa


def _number(v: Any) -> float | None:
    """Rounded float, or ``None`` for NaN / non-numeric / infinite cells."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if (f != f or f in (float("inf"), float("-inf"))) else round(f, 4)


def build_statistics(network: pypsa.Network) -> dict[str, Any]:
    """Return ``{columns, rows, periods}`` from ``network.statistics()``.

    ``columns`` is the metric column order; each row is
    ``{component, carrier, values: {column: number | null}}``. Best-effort: any
    failure (or an unsolved network) yields an empty table rather than raising.

    A multi-investment (pathway) run gives PyPSA ``(metric, period)`` columns.
    Those are emitted in long form: one row **per component, carrier and
    period**, carrying ``period`` (the investment-period year), with ``values``
    keyed by the plain metric name. ``columns`` lists metric names (no tuple
    strings) and ``periods`` the investment periods; both stay empty / absent
    for a single-period run, whose rows have no ``period`` key. Metrics PyPSA
    reports outside any period (``Transmission``, period 0) repeat on every
    period's row.
    """
    try:
        st = network.statistics()
    except Exception:  # noqa: BLE001 — never let stats break a run's results
        return {"columns": [], "rows": [], "periods": []}
    if st is None or getattr(st, "empty", True):
        return {"columns": [], "rows": [], "periods": []}

    multi_period = isinstance(st.columns, pd.MultiIndex)
    if multi_period:
        metrics = list(dict.fromkeys(str(c[0]) for c in st.columns))
        period_values = sorted({int(c[1]) for c in st.columns if int(c[1]) != 0})
        if not period_values:  # only period-less metrics — plain table
            multi_period = False
    if not multi_period:
        st = st.copy()
        st.columns = [str(c[0]) if isinstance(c, tuple) else str(c) for c in st.columns]
        metrics = [str(c) for c in st.columns]
        period_values = []

    rows: list[dict[str, Any]] = []
    for idx, row in st.iterrows():
        if isinstance(idx, tuple):
            comp = str(idx[0])
            carrier = str(idx[1]) if len(idx) > 1 else ""
        else:
            comp = str(idx)
            carrier = ""
        if carrier in ("-", "nan", "None"):
            carrier = ""
        if not multi_period:
            rows.append({
                "component": comp,
                "carrier": carrier,
                "values": {m: _number(row[m]) for m in metrics},
            })
            continue
        for period in period_values:
            values: dict[str, Any] = {}
            for col in st.columns:
                if int(col[1]) in (period, 0):
                    values[str(col[0])] = _number(row[col])
            if all(v is None for v in values.values()):
                continue  # component not active in this period
            rows.append({"component": comp, "carrier": carrier, "period": period, "values": values})
    return {"columns": metrics, "rows": rows, "periods": period_values}
