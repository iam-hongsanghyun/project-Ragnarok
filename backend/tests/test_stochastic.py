"""Pins the two-stage stochastic flow end-to-end."""
from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from backend.lib.results import run_pypsa


def _model() -> dict[str, list[dict[str, Any]]]:
    return {
        "buses": [{"name": "b0", "v_nom": 380.0}],
        "snapshots": [
            {"snapshot": "2025-01-01T00:00:00"},
            {"snapshot": "2025-01-01T01:00:00"},
        ],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}],
        "generators": [
            {
                "name": "g",
                "bus": "b0",
                "carrier": "gas",
                "p_nom_extendable": True,
                "capital_cost": 50.0,
                "marginal_cost": 20.0,
            }
        ],
        "loads": [{"name": "L", "bus": "b0", "p_set": 100.0}],
        "loads-p_set": [
            {"snapshot": "2025-01-01T00:00:00", "L": 100.0},
            {"snapshot": "2025-01-01T01:00:00", "L": 100.0},
        ],
    }


def test_stochastic_solve_returns_per_scenario_summaries() -> None:
    """Two scenarios with different load multipliers must produce distinct
    energy / emissions / cost totals, with weights normalised to sum=1."""
    result = run_pypsa(
        _model(),
        {"discountRate": 0.05},
        {
            "stochasticConfig": {
                "enabled": True,
                "scenarios": [
                    {"name": "low", "weight": 0.6, "loadMultiplier": 0.8},
                    {"name": "high", "weight": 0.4, "loadMultiplier": 1.5},
                ],
            }
        },
    )

    stochastic = result["stochastic"]
    assert stochastic is not None
    assert stochastic["enabled"] is True
    assert stochastic["representativeScenario"] == "low"  # higher weight

    scenarios = {s["name"]: s for s in stochastic["scenarios"]}
    assert set(scenarios.keys()) == {"low", "high"}
    assert scenarios["low"]["weight"] == pytest.approx(0.6)
    assert scenarios["high"]["weight"] == pytest.approx(0.4)

    # low_demand: 100 × 0.8 × 2h = 160 MWh; high_demand: 100 × 1.5 × 2h = 300 MWh
    assert scenarios["low"]["totalEnergyMwh"] == pytest.approx(160.0)
    assert scenarios["high"]["totalEnergyMwh"] == pytest.approx(300.0)

    # Emissions at 0.4 tCO2/MWh
    assert scenarios["low"]["totalEmissionsTco2"] == pytest.approx(64.0)
    assert scenarios["high"]["totalEmissionsTco2"] == pytest.approx(120.0)

    # Operating cost at 20 $/MWh
    assert scenarios["low"]["totalOperatingCost"] == pytest.approx(3200.0)
    assert scenarios["high"]["totalOperatingCost"] == pytest.approx(6000.0)


def test_weights_normalise_to_one() -> None:
    """Unnormalised weights (e.g. 60 / 40) must be rescaled to 0.6 / 0.4."""
    result = run_pypsa(
        _model(),
        {"discountRate": 0.05},
        {
            "stochasticConfig": {
                "enabled": True,
                "scenarios": [
                    {"name": "a", "weight": 60.0, "loadMultiplier": 1.0},
                    {"name": "b", "weight": 40.0, "loadMultiplier": 1.0},
                ],
            }
        },
    )
    scenarios = {s["name"]: s for s in result["stochastic"]["scenarios"]}
    assert scenarios["a"]["weight"] == pytest.approx(0.6)
    assert scenarios["b"]["weight"] == pytest.approx(0.4)


def test_single_scenario_falls_back_to_deterministic() -> None:
    """A stochastic config with fewer than 2 scenarios must be ignored —
    a single scenario is just a deterministic solve."""
    result = run_pypsa(
        _model(),
        {"discountRate": 0.05},
        {
            "stochasticConfig": {
                "enabled": True,
                "scenarios": [
                    {"name": "only", "weight": 1.0, "loadMultiplier": 1.0},
                ],
            }
        },
    )
    assert result["stochastic"] is None


def test_stochastic_and_rolling_horizon_rejected() -> None:
    """The two cannot be combined in a single run."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        run_pypsa(
            _model(),
            {"discountRate": 0.05},
            {
                "stochasticConfig": {
                    "enabled": True,
                    "scenarios": [
                        {"name": "a", "weight": 0.5, "loadMultiplier": 1.0},
                        {"name": "b", "weight": 0.5, "loadMultiplier": 1.0},
                    ],
                },
                "rollingConfig": {"enabled": True, "horizonSnapshots": 24, "overlapSnapshots": 0},
            },
        )
    assert exc.value.status_code == 400
    assert "stochastic" in exc.value.detail.lower()
