"""Bid-strategy simulator (Tier 2) — markup vs price-taker baseline.

Acme owns a pivotal mid-merit gas unit: cheap baseload can't cover peak, so
Acme is needed and the peaker is the only pricier alternative. Bidding just
under the peaker should lift the clearing price and raise Acme's profit — a
clear market-power gain (positive delta).
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _model() -> dict[str, list[dict[str, Any]]]:
    snaps = [f"2030-01-01T0{h}:00:00" for h in range(4)]
    load = [120, 180, 150, 200]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "base"}, {"name": "gas"}, {"name": "peak"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(snaps, load)],
        "generators": [
            {"name": "base1", "bus": "b", "carrier": "base", "p_nom": 100, "marginal_cost": 10},
            {"name": "acme_gas", "bus": "b", "carrier": "gas", "p_nom": 120, "marginal_cost": 40, "owner": "Acme"},
            {"name": "peak1", "bus": "b", "carrier": "peak", "p_nom": 200, "marginal_cost": 100},
        ],
    }


def test_bid_strategy_market_power_gain() -> None:
    res = run_pypsa(
        _model(), SCENARIO,
        {"bidStrategyConfig": {"enabled": True, "owner": "Acme", "markupType": "percent", "markup": 1.0}},
    )
    bs = res["bidStrategy"]
    assert bs is not None
    assert bs["owner"] == "Acme"
    # A pivotal unit bidding above cost lifts the price ⇒ higher profit.
    assert bs["strategic"]["profit"] > bs["baseline"]["profit"]
    assert bs["deltaProfit"] > 0
    # The market clearing price rises on average.
    assert bs["systemAvgPrice"]["strategic"] >= bs["systemAvgPrice"]["baseline"]


def test_bid_strategy_absent_when_disabled() -> None:
    assert run_pypsa(_model(), SCENARIO, {})["bidStrategy"] is None


def test_bid_strategy_unknown_owner_returns_none() -> None:
    res = run_pypsa(_model(), SCENARIO, {"bidStrategyConfig": {"enabled": True, "owner": "Nobody", "markup": 0.5}})
    assert res["bidStrategy"] is None


def test_bid_strategy_rejects_incompatible_mode() -> None:
    with pytest.raises(HTTPException) as exc:
        run_pypsa(
            _model(), SCENARIO,
            {"bidStrategyConfig": {"enabled": True, "owner": "Acme"}, "contingencyConfig": {"enabled": True}},
        )
    assert exc.value.status_code == 400
