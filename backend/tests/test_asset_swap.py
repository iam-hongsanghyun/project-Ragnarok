"""Asset-swap / repowering what-if (DW2) — before vs after delta.

Retire a gas fleet and replace it 1:1 with solar (which has an availability
profile in the model). Emissions must fall; the delta block must be internally
consistent (after − before).
"""
from __future__ import annotations

from typing import Any

from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.05, "carbonPrice": 50.0}


def _model() -> dict[str, list[dict[str, Any]]]:
    snaps = [f"2030-01-01T0{h}:00:00" for h in range(6)]
    load = [80, 120, 160, 100, 140, 90]
    solar_pu = [0.0, 0.6, 0.9, 0.7, 0.4, 0.0]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}, {"name": "solar"}, {"name": "backup"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(snaps, load)],
        "generators": [
            {"name": "gas1", "bus": "b", "carrier": "gas", "p_nom": 200, "marginal_cost": 60},
            # A small existing solar unit provides the cost + availability profile
            # the replacement inherits; a big battery-free backstop keeps feasibility.
            {"name": "solar0", "bus": "b", "carrier": "solar", "p_nom": 10, "marginal_cost": 0, "capital_cost": 90000},
            {"name": "backstop", "bus": "b", "carrier": "backup", "p_nom": 0, "p_nom_extendable": True,
             "marginal_cost": 300, "capital_cost": 1},
        ],
        "generators-p_max_pu": [{"snapshot": s, "solar0": v} for s, v in zip(snaps, solar_pu)],
    }


def test_asset_swap_gas_to_solar_cuts_emissions() -> None:
    # Retire gas → solar. A separate 'backup' carrier keeps the after-system
    # feasible in solar's zero-output hours.
    res = run_pypsa(
        _model(), SCENARIO,
        {"assetSwapConfig": {"enabled": True, "removeCarrier": "gas", "addCarrier": "solar"}},
    )
    sw = res["assetSwap"]
    assert sw is not None
    assert sw["removeCarrier"] == "gas" and sw["addCarrier"] == "solar"
    assert sw["addedCapacityMW"] > 0
    assert sw["replacementFirm"] is False  # inherited solar's profile
    # Emissions fall (gas retired) and the delta is consistent.
    assert sw["after"]["emissionsTonnes"] < sw["before"]["emissionsTonnes"]
    assert sw["delta"]["emissionsTonnes"] == round(
        sw["after"]["emissionsTonnes"] - sw["before"]["emissionsTonnes"], 2
    )


def test_asset_swap_absent_when_disabled() -> None:
    assert run_pypsa(_model(), SCENARIO, {})["assetSwap"] is None


def test_asset_swap_unknown_carrier_returns_none() -> None:
    res = run_pypsa(_model(), SCENARIO, {"assetSwapConfig": {"enabled": True, "removeCarrier": "nuclear", "addCarrier": "solar"}})
    assert res["assetSwap"] is None
