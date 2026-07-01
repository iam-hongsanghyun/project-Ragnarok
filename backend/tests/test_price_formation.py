"""Price-formation view (Tier 0) — residual demand & the price-setting carrier.

A one-bus system: cheap wind (weather-driven), mid gas, and a peaker. As demand
rises and wind falls, the price-setting carrier should climb the merit order and
the price should rise with residual demand.
"""
from __future__ import annotations

from typing import Any

from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _model() -> dict[str, list[dict[str, Any]]]:
    snaps = [f"2030-01-01T0{h}:00:00" for h in range(6)]
    load = [90, 160, 240, 120, 200, 100]
    wind_pu = [0.8, 0.3, 0.1, 0.7, 0.2, 0.9]  # high wind ⇒ low residual demand
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "wind"}, {"name": "gas"}, {"name": "peaker"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(snaps, load)],
        "generators": [
            {"name": "wind1", "bus": "b", "carrier": "wind", "p_nom": 150, "marginal_cost": 0},
            {"name": "gas1", "bus": "b", "carrier": "gas", "p_nom": 150, "marginal_cost": 40},
            {"name": "peak1", "bus": "b", "carrier": "peaker", "p_nom": 200, "marginal_cost": 120},
        ],
        "generators-p_max_pu": [{"snapshot": s, "wind1": w} for s, w in zip(snaps, wind_pu)],
    }


def test_price_formation_marginal_carrier_and_residual() -> None:
    res = run_pypsa(_model(), SCENARIO, {})
    pf = res["priceFormation"]
    assert pf is not None
    assert len(pf["series"]) == 6
    for row in pf["series"]:
        assert "price" in row and "residualDemand" in row and "marginalCarrier" in row
        assert 0.0 <= row["renewableShare"] <= 1.0
    # The peaker (highest marginal cost) sets the price in the tightest hour
    # (snapshot 2: demand 240, wind pu 0.1) — residual demand is highest there.
    peak_row = max(pf["series"], key=lambda r: r["residualDemand"])
    assert peak_row["marginalCarrier"] in ("gas", "peaker")
    assert peak_row["price"] >= 40
    # Summary lists price-setting carriers with hour shares summing to ~1.
    assert pf["marginalSummary"]
    # Shares are rounded to 4 dp, so allow small rounding drift from exactly 1.
    assert abs(sum(c["shareOfHours"] for c in pf["marginalSummary"]) - 1.0) < 1e-3


def test_price_formation_absent_without_prices() -> None:
    # A pure power-flow study has no marginal prices ⇒ no price-formation view.
    res = run_pypsa(_model(), SCENARIO, {"powerFlowConfig": {"enabled": True, "linear": True}})
    assert res.get("priceFormation") is None
