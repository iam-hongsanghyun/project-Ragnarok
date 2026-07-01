"""Optimal-bid finder (Tier 3a) — best-response markup sweep.

Acme owns a pivotal mid-merit unit (see test_bid_strategy). Sweeping the markup
should find a profit-maximising bid strictly better than the price-taker
baseline (markup 0), and return a monotone-indexed profit curve.
"""
from __future__ import annotations

from typing import Any

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


def test_optimal_bid_finds_profitable_markup() -> None:
    res = run_pypsa(
        _model(), SCENARIO,
        {"bidStrategyConfig": {"enabled": True, "mode": "optimal", "owner": "Acme",
                               "markupType": "percent", "maxMarkup": 2.0, "steps": 8}},
    )
    ob = res["optimalBid"]
    assert ob is not None
    assert res["bidStrategy"] is None  # optimal mode returns the sweep, not the fixed comparison
    # Curve includes the markup-0 baseline plus swept points.
    assert len(ob["curve"]) >= 2
    assert ob["curve"][0]["markup"] == 0.0
    # The optimal is at least as profitable as the price-taker baseline, and here
    # strictly better (pivotal unit ⇒ market power).
    assert ob["optimalProfit"] >= ob["baselineProfit"]
    assert ob["optimalMarkup"] > 0
    assert ob["deltaProfit"] > 0
    # Optimal profit is the max over the curve.
    assert ob["optimalProfit"] == max(c["profit"] for c in ob["curve"])


def test_optimal_bid_absent_in_fixed_mode() -> None:
    res = run_pypsa(
        _model(), SCENARIO,
        {"bidStrategyConfig": {"enabled": True, "mode": "fixed", "owner": "Acme", "markup": 0.5}},
    )
    assert res["optimalBid"] is None
    assert res["bidStrategy"] is not None
