"""Pin the SCLOPF (security-constrained LOPF) workflow."""
from __future__ import annotations

from typing import Any

import pytest

from backend.pypsa.results import run_pypsa


def _three_bus_model() -> dict[str, list[dict[str, Any]]]:
    """Triangle network where N-1 capacity is tight without being infeasible."""
    return {
        "buses": [
            {"name": "A", "v_nom": 380.0},
            {"name": "B", "v_nom": 380.0},
            {"name": "C", "v_nom": 380.0},
        ],
        "snapshots": [
            {"snapshot": "2025-01-01T00:00:00"},
            {"snapshot": "2025-01-01T01:00:00"},
        ],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}],
        "generators": [
            {"name": "gA", "bus": "A", "carrier": "gas", "p_nom": 300.0, "marginal_cost": 20.0},
            {"name": "gB", "bus": "B", "carrier": "gas", "p_nom": 300.0, "marginal_cost": 30.0},
        ],
        "lines": [
            {"name": "L1", "bus0": "A", "bus1": "B", "x": 0.1, "s_nom": 200.0},
            {"name": "L2", "bus0": "B", "bus1": "C", "x": 0.1, "s_nom": 200.0},
            {"name": "L3", "bus0": "A", "bus1": "C", "x": 0.1, "s_nom": 200.0},
        ],
        "loads": [{"name": "LC", "bus": "C", "p_set": 150.0}],
        "loads-p_set": [
            {"snapshot": "2025-01-01T00:00:00", "LC": 150.0},
            {"snapshot": "2025-01-01T01:00:00", "LC": 150.0},
        ],
    }


def test_sclopf_keeps_lines_below_n_minus_1_capacity() -> None:
    """Without SCLOPF the cheapest dispatch would push L3 to 75% loading. With
    N-1 enforcement against every passive branch, no single line carries more
    than half its rating so any outage stays feasible."""
    result = run_pypsa(
        _three_bus_model(),
        {"discountRate": 0.05},
        {"securityConstrainedConfig": {"enabled": True}},
    )

    sclopf = result["securityConstrained"]
    assert sclopf is not None
    assert sclopf["enabled"] is True
    assert sclopf["branchCount"] == 3

    # Worst-case loading must satisfy N-1: ≤ 50% on any single line.
    line_loadings = {row["label"]: row["value"] for row in result["lineLoading"]}
    for name, loading in line_loadings.items():
        assert loading <= 50.0 + 1e-6, f"{name} loading {loading} exceeds N-1 budget"


def test_sclopf_rejected_with_rolling_horizon() -> None:
    """The two cannot be combined in a single run."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        run_pypsa(
            _three_bus_model(),
            {"discountRate": 0.05},
            {
                "securityConstrainedConfig": {"enabled": True},
                "rollingConfig": {"enabled": True, "horizonSnapshots": 24, "overlapSnapshots": 0},
            },
        )
    assert exc.value.status_code == 400
    assert "sclopf" in exc.value.detail.lower() or "security" in exc.value.detail.lower()


def test_sclopf_rejected_with_stochastic() -> None:
    """SCLOPF + stochastic combination must be rejected at the request level."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        run_pypsa(
            _three_bus_model(),
            {"discountRate": 0.05},
            {
                "securityConstrainedConfig": {"enabled": True},
                "stochasticConfig": {
                    "enabled": True,
                    "scenarios": [
                        {"name": "a", "weight": 0.5, "loadMultiplier": 1.0},
                        {"name": "b", "weight": 0.5, "loadMultiplier": 1.0},
                    ],
                },
            },
        )
    assert exc.value.status_code == 400
