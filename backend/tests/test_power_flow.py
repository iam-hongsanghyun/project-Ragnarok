"""Power-flow study mode (pf / lpf) — runs network physics, not an LP.

Builds a tiny AC-feasible network (buses with v_nom, a line with reactance, one
generator that becomes the slack, a load) and runs it through ``run_pypsa`` with
``powerFlowConfig``. Asserts convergence + a sane voltage band for AC, lossless
behaviour for linear, and that the mode rejects being combined with an optimise
mode.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _two_bus_model(load_mw: float = 100.0) -> dict[str, list[dict[str, Any]]]:
    """Two 380 kV buses joined by one line; a generator at A feeds a load at B."""
    snaps = ["2030-01-01T00:00:00", "2030-01-01T01:00:00"]
    return {
        "buses": [{"name": "A", "v_nom": 380.0}, {"name": "B", "v_nom": 380.0}],
        "carriers": [{"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "lines": [
            {
                "name": "AB",
                "bus0": "A",
                "bus1": "B",
                "x": 0.1,
                "r": 0.01,
                "s_nom": 400.0,
            }
        ],
        "generators": [
            {
                "name": "G",
                "bus": "A",
                "carrier": "gas",
                "p_nom": 500.0,
                "marginal_cost": 10.0,
            }
        ],
        "loads": [{"name": "L", "bus": "B", "p_set": load_mw}],
        "loads-p_set": [{"snapshot": s, "L": load_mw} for s in snaps],
    }


def test_ac_power_flow_converges_and_reports_voltages() -> None:
    res = run_pypsa(_two_bus_model(), SCENARIO, {"powerFlowConfig": {"enabled": True}})
    pf = res["powerFlow"]
    assert pf["linear"] is False
    assert pf["error"] is None
    assert pf["converged"] is True
    assert pf["iterations"] >= 1  # Newton-Raphson took at least one step
    # Both buses reported, magnitudes in a sane band (slack stays ~1.0, B sags a bit).
    assert len(pf["voltageProfile"]) == 2
    assert all(0.9 < v["min"] <= v["max"] < 1.1 for v in pf["voltageProfile"])
    # The line carries roughly the load.
    assert res["lineLoading"] and res["lineLoading"][0]["value"] > 0
    assert res["runMeta"]["studyMode"] == "pf"


def test_linear_power_flow_runs_lossless() -> None:
    res = run_pypsa(
        _two_bus_model(),
        SCENARIO,
        {"powerFlowConfig": {"enabled": True, "linear": True}},
    )
    pf = res["powerFlow"]
    assert pf["linear"] is True
    assert pf["error"] is None
    assert pf["converged"] is True  # a direct linear solve always "converges"
    assert pf["lossesMwh"] == 0.0  # DC power flow is lossless
    assert res["lineLoading"]  # flows still computed
    assert res["runMeta"]["studyMode"] == "lpf"


def test_power_flow_carries_no_cost_or_price_fields() -> None:
    # Power flow is physics-only; the optimise-only analytics must be empty.
    res = run_pypsa(_two_bus_model(), SCENARIO, {"powerFlowConfig": {"enabled": True}})
    assert res["costBreakdown"] == []
    assert res["systemPriceSeries"] == []
    assert res["carrierMix"] == []
    assert res["generatorEconomics"] is None


def test_power_flow_rejects_combination_with_optimise_modes() -> None:
    with pytest.raises(HTTPException):
        run_pypsa(
            _two_bus_model(),
            SCENARIO,
            {
                "powerFlowConfig": {"enabled": True},
                "securityConstrainedConfig": {"enabled": True},
            },
        )
