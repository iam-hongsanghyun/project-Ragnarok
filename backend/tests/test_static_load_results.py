"""Static-only ``p_set`` loads through the full solve → results path.

Regression: results extraction used a strict ``.loc`` on ``loads_t.p_set``,
so a load defined only statically (no ``loads-p_set`` column — exactly what
the MCP ``add_load`` tool writes) raised ``KeyError`` after a successful
solve, and the whole run was reported as failed. Static loads were also
invisible to peak-demand and nodal-balance metrics.
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.pypsa.results import run_pypsa


def _model() -> dict[str, list[dict[str, Any]]]:
    """Two buses; one load is time-varying, the other static-only."""
    return {
        "buses": [{"name": "b0", "v_nom": 380.0}, {"name": "b1", "v_nom": 380.0}],
        "lines": [{"name": "l01", "bus0": "b0", "bus1": "b1", "x": 0.1, "r": 0.01, "s_nom": 500.0}],
        "snapshots": [
            {"snapshot": "2025-01-01T00:00:00"},
            {"snapshot": "2025-01-01T01:00:00"},
        ],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}],
        "generators": [
            {"name": "g", "bus": "b0", "carrier": "gas", "p_nom": 200.0, "marginal_cost": 20.0},
        ],
        "loads": [
            {"name": "Lstatic", "bus": "b1", "p_set": 50.0},
            {"name": "Lts", "bus": "b0"},
        ],
        "loads-p_set": [
            {"snapshot": "2025-01-01T00:00:00", "Lts": 30.0},
            {"snapshot": "2025-01-01T01:00:00", "Lts": 30.0},
        ],
    }


def test_static_only_load_solves_and_counts_toward_demand() -> None:
    result = run_pypsa(_model(), {"discountRate": 0.05}, {})

    # The run completes (the strict .loc used to raise KeyError here) and the
    # static load counts toward peak demand: 50 + 30 = 80 MW.
    summary = {row["label"]: row["value"] for row in result["summary"]}
    assert summary["Peak demand"] == "80 MW"

    # Nodal balance sees the static load on its bus.
    balance = {row["label"]: row for row in result["nodalBalance"]}
    assert balance["b1"]["load"] == pytest.approx(50.0)
    assert balance["b0"]["load"] == pytest.approx(30.0)
