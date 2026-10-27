"""Pins the two-stage stochastic flow end-to-end.

Every scenario expresses uncertainty through ``overrides`` — there are
no special multiplier knobs. These tests target the same use cases
real users care about (load × 0.8, fuel × 2, hydro × 0.4) via the
override mechanism.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from backend.pypsa.results import run_pypsa
from backend.pypsa.stochastic import is_scenario_invariant


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


def _load_multiplier_override(value: float) -> dict[str, Any]:
    """An override that scales every ``loads.p_set`` row in this scenario."""
    return {
        "sheet": "loads",
        "attribute": "p_set",
        "scopeType": "all",
        "scopeValue": "",
        "operation": "multiply",
        "value": value,
    }


def test_stochastic_solve_returns_per_scenario_summaries() -> None:
    """Two scenarios with different load overrides produce distinct totals;
    weights normalised to sum=1."""
    result = run_pypsa(
        _model(),
        {"discountRate": 0.05},
        {
            "stochasticConfig": {
                "enabled": True,
                "scenarios": [
                    {"name": "low",  "weight": 0.6, "overrides": [_load_multiplier_override(0.8)]},
                    {"name": "high", "weight": 0.4, "overrides": [_load_multiplier_override(1.5)]},
                ],
            }
        },
    )

    stochastic = result["stochastic"]
    assert stochastic is not None
    assert stochastic["enabled"] is True
    assert stochastic["representativeScenario"] == "low"  # higher weight

    scenarios = {s["name"]: s for s in stochastic["scenarios"]}
    assert scenarios["low"]["weight"] == pytest.approx(0.6)
    assert scenarios["high"]["weight"] == pytest.approx(0.4)

    # 100 MW × 0.8 × 2h = 160 MWh; 100 × 1.5 × 2h = 300 MWh
    assert scenarios["low"]["totalEnergyMwh"] == pytest.approx(160.0)
    assert scenarios["high"]["totalEnergyMwh"] == pytest.approx(300.0)
    assert scenarios["low"]["totalEmissionsTco2"] == pytest.approx(64.0)
    assert scenarios["high"]["totalEmissionsTco2"] == pytest.approx(120.0)
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
                    {"name": "a", "weight": 60.0},
                    {"name": "b", "weight": 40.0},
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
                "scenarios": [{"name": "only", "weight": 1.0}],
            }
        },
    )
    assert result["stochastic"] is None


def test_marginal_cost_override_by_carrier_scales_per_scenario_cost() -> None:
    """A scope='carrier' override on `generators.marginal_cost` is the same as
    the old "fuel × N" knob; verify per-scenario dispatch cost reflects it."""
    result = run_pypsa(
        _model(),
        {"discountRate": 0.05},
        {
            "stochasticConfig": {
                "enabled": True,
                "scenarios": [
                    {
                        "name": "cheap_gas",
                        "weight": 0.5,
                        "overrides": [{
                            "sheet": "generators",
                            "attribute": "marginal_cost",
                            "scopeType": "carrier",
                            "scopeValue": "gas",
                            "operation": "multiply",
                            "value": 0.5,
                        }],
                    },
                    {
                        "name": "expensive_gas",
                        "weight": 0.5,
                        "overrides": [{
                            "sheet": "generators",
                            "attribute": "marginal_cost",
                            "scopeType": "carrier",
                            "scopeValue": "gas",
                            "operation": "multiply",
                            "value": 2.0,
                        }],
                    },
                ],
            }
        },
    )
    scenarios = {s["name"]: s for s in result["stochastic"]["scenarios"]}
    # Both dispatch 100 MW × 2h = 200 MWh, at 10 vs 40 $/MWh effective
    assert scenarios["cheap_gas"]["totalOperatingCost"] == pytest.approx(2000.0)
    assert scenarios["expensive_gas"]["totalOperatingCost"] == pytest.approx(8000.0)


def test_advanced_override_by_name_set_operation() -> None:
    """Scope='name' + op='set' replaces the value on one specific row."""
    model = _model()
    model["generators"].append({
        "name": "g2",
        "bus": "b0",
        "carrier": "gas",
        "p_nom_extendable": True,
        "capital_cost": 50.0,
        "marginal_cost": 20.0,
    })
    result = run_pypsa(
        model,
        {"discountRate": 0.05},
        {
            "stochasticConfig": {
                "enabled": True,
                "scenarios": [
                    {"name": "base", "weight": 0.5},
                    {
                        "name": "g2_only_expensive",
                        "weight": 0.5,
                        "overrides": [{
                            "sheet": "generators",
                            "attribute": "marginal_cost",
                            "scopeType": "name",
                            "scopeValue": "g2",
                            "operation": "set",
                            "value": 500.0,
                        }],
                    },
                ],
            }
        },
    )
    assert len(result["stochastic"]["scenarios"]) == 2


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
                        {"name": "a", "weight": 0.5},
                        {"name": "b", "weight": 0.5},
                    ],
                },
                "rollingConfig": {"enabled": True, "horizonSnapshots": 24, "overlapSnapshots": 0},
            },
        )
    assert exc.value.status_code == 400
    assert "stochastic" in exc.value.detail.lower()


@pytest.mark.parametrize(
    "attribute",
    ["bus", "bus1", "bus2", "carrier", "p_nom_set", "s_nom_set", "e_nom_set", "delay",
     "cyclic_delay2", "p_nom_extendable", "committable", "build_year", "lifetime", "type"],
)
def test_scenario_invariant_overrides_are_a_400(attribute: str) -> None:
    """PyPSA 1.4 raises ConsistencyError when these differ across scenarios; the
    run must stop up front with a 400 naming the scenario and attribute."""
    assert is_scenario_invariant(attribute)
    bad = {"sheet": "generators", "attribute": attribute, "scopeType": "all",
           "scopeValue": "", "operation": "set", "value": 1.0}
    with pytest.raises(HTTPException) as info:
        run_pypsa(
            _model(),
            {"discountRate": 0.05},
            {"stochasticConfig": {"enabled": True, "scenarios": [
                {"name": "a", "weight": 1.0, "overrides": [bad]},
                {"name": "b", "weight": 1.0},
            ]}},
        )
    assert info.value.status_code == 400
    assert "'a'" in info.value.detail and f"generators.{attribute}" in info.value.detail


@pytest.mark.parametrize("attribute", ["marginal_cost", "p_set", "p_max_pu", "capital_cost", "efficiency"])
def test_operating_attributes_are_not_invariant(attribute: str) -> None:
    assert not is_scenario_invariant(attribute)
