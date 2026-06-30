"""PyPSA ``statistics`` passthrough — the canonical per-carrier metrics table.

``network.statistics()`` returns PyPSA's standard summary (optimal / installed
capacity, supply, withdrawal, energy balance, capacity factor, curtailment,
capital & operational expenditure, revenue, market value, …) grouped by
component and carrier. We surface it verbatim as an analytics table rather than
re-deriving any of it — engine-feature parity, computed by PyPSA itself.
"""
from __future__ import annotations

from typing import Any

import pypsa


def build_statistics(network: pypsa.Network) -> dict[str, Any]:
    """Return ``{columns, rows}`` from ``network.statistics()``.

    ``columns`` is the metric column order; each row is
    ``{component, carrier, values: {column: number | null}}``. Best-effort: any
    failure (or an unsolved network) yields an empty table rather than raising.
    """
    try:
        st = network.statistics()
    except Exception:  # noqa: BLE001 — never let stats break a run's results
        return {"columns": [], "rows": []}
    if st is None or getattr(st, "empty", True):
        return {"columns": [], "rows": []}

    columns = [str(c) for c in st.columns]
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
        values: dict[str, Any] = {}
        for col in st.columns:
            v = row[col]
            try:
                f = float(v)
                values[str(col)] = None if f != f else round(f, 4)  # NaN guard
            except (TypeError, ValueError):
                values[str(col)] = None
        rows.append({"component": comp, "carrier": carrier, "values": values})
    return {"columns": columns, "rows": rows}
