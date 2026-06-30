"""MGA (modelling-to-generate-alternatives) — the near-optimal capacity space.

A one-bus system with a cheap gas generator and pricier renewables. The cost
optimum leans on gas; within a cost slack, MGA should be able to push the
renewable carriers *up* (and still respect the budget). We assert the corridor
exists and that every alternative stays within ``1 + slack`` of the optimum.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _model() -> dict[str, list[dict[str, Any]]]:
    snaps = [f"2030-01-01T0{h}:00:00" for h in range(4)]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}, {"name": "wind"}, {"name": "solar"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(snaps, [100, 140, 90, 120])],
        "generators": [
            {"name": "g_gas", "bus": "b", "carrier": "gas", "p_nom_extendable": True,
             "capital_cost": 80000, "marginal_cost": 60},
            {"name": "g_wind", "bus": "b", "carrier": "wind", "p_nom_extendable": True,
             "capital_cost": 90000, "marginal_cost": 0},
            {"name": "g_solar", "bus": "b", "carrier": "solar", "p_nom_extendable": True,
             "capital_cost": 85000, "marginal_cost": 0},
        ],
        "generators-p_max_pu": [
            {"snapshot": s, "g_wind": w, "g_solar": so}
            for s, w, so in zip(snaps, [0.6, 0.3, 0.8, 0.5], [0.2, 0.7, 0.9, 0.4])
        ],
    }


def test_mga_maps_near_optimal_corridor() -> None:
    slack = 0.15
    res = run_pypsa(_model(), SCENARIO, {"mgaConfig": {"enabled": True, "slack": slack, "carriers": ["wind", "solar"]}})
    mga = res["nearOptimal"]
    assert mga is not None
    assert mga["slack"] == pytest.approx(slack)
    assert set(mga["carriers"]) == {"wind", "solar"}
    # Two senses per carrier = up to four alternatives.
    assert len(mga["alternatives"]) >= 2
    # Every alternative must respect the cost budget (within the slack, modulo
    # solver tolerance) and carry a full capacity mix.
    for alt in mga["alternatives"]:
        assert alt["sense"] in ("min", "max")
        assert alt["costRatio"] is not None and alt["costRatio"] <= 1 + slack + 1e-4
        assert alt["capacityByCarrier"]
    # The optimum mix is reported alongside the alternatives.
    assert mga["optimum"]["cost"] > 0
    # Maximising a renewable carrier should build at least as much of it as the
    # cost optimum (the corridor opens upward, not collapses).
    wind_max = next((a for a in mga["alternatives"] if a["carrier"] == "wind" and a["sense"] == "max"), None)
    if wind_max is not None:
        opt_wind = mga["optimum"]["capacityByCarrier"].get("wind", 0.0)
        assert wind_max["capacityByCarrier"].get("wind", 0.0) >= opt_wind - 1e-6


def test_mga_absent_when_disabled() -> None:
    res = run_pypsa(_model(), SCENARIO, {})
    assert res["nearOptimal"] is None


def test_mga_rejects_incompatible_mode() -> None:
    with pytest.raises(HTTPException) as exc:
        run_pypsa(
            _model(),
            SCENARIO,
            {"mgaConfig": {"enabled": True}, "powerFlowConfig": {"enabled": True}},
        )
    assert exc.value.status_code == 400
