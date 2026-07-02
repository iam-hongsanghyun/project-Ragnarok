"""PP2 procurement optimizer — CVaR-constrained instrument mix.

Analytical anchors: on a flat price the buyer is indifferent to hedging;
CVaR is monotone in the tail; the efficient frontier trades expected cost for
risk monotonically; a fixed-price PPA at strike < E[spot] both lowers cost and
cuts tail risk, so it dominates when available.
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.app.procurement import (
    empirical_cvar,
    generate_scenarios,
    optimize_portfolio,
)


def test_empirical_cvar_is_worst_tail_mean() -> None:
    costs = np.array([10.0, 20, 30, 40, 100])
    # alpha 0.8 → worst 20% = 1 scenario = the max.
    assert empirical_cvar(costs, 0.8) == pytest.approx(100.0)
    # alpha 0.6 → worst 40% = 2 scenarios = mean(40, 100).
    assert empirical_cvar(costs, 0.6) == pytest.approx(70.0)
    assert empirical_cvar(np.array([]), 0.95) == 0.0


def test_scenarios_lead_with_observed_and_append_stress() -> None:
    prices = np.arange(24.0)
    scen, labels = generate_scenarios(prices, n_bootstrap=10, block_hours=6,
                                      stress=[{"label": "x2", "multiplier": 2.0}])
    assert scen.shape == (12, 24)  # observed + 10 bootstrap + 1 stress
    assert labels[0] == "observed"
    np.testing.assert_allclose(scen[0], prices)          # first row is the truth
    np.testing.assert_allclose(scen[-1], prices * 2.0)   # last is the stress case
    assert labels[-1] == "x2"


def test_flat_price_makes_a_fair_forward_irrelevant() -> None:
    # Constant 50 €/MWh, forward priced exactly at 50 → the forward's payoff is
    # zero in every scenario, so expected cost equals the spot baseline.
    prices = np.full(24, 50.0)
    scen, _ = generate_scenarios(prices, n_bootstrap=0)
    load = np.full(24, 10.0)
    res = optimize_portfolio(scen, load, {
        "forward": {"enabled": True, "price": 50.0, "maxMw": 10.0},
    }, alpha=0.95)
    assert res["optimal"]["expectedCost"] == pytest.approx(res["baseline"]["expectedCost"])


def test_cheap_ppa_dominates_lowering_both_cost_and_risk() -> None:
    # A spiky price with a PPA struck below the mean: taking it must reduce both
    # expected cost and the CVaR tail versus pure spot.
    rng = np.random.default_rng(1)
    prices = np.abs(rng.normal(60, 40, 48))
    scen, _ = generate_scenarios(prices, n_bootstrap=80, block_hours=6, seed=1)
    load = np.full(48, 100.0)
    res = optimize_portfolio(scen, load, {
        "ppa": {"enabled": True, "strike": 45.0, "maxMw": 100.0, "profile": None},
    }, alpha=0.95)
    assert res["optimal"]["mix"]["ppa"] == pytest.approx(100.0, abs=1e-3)  # take the max
    assert res["optimal"]["expectedCost"] < res["baseline"]["expectedCost"]
    assert res["optimal"]["cvar"] < res["baseline"]["cvar"]


def test_frontier_is_monotone_cost_falls_as_risk_budget_rises() -> None:
    # For a genuine cost-vs-risk tradeoff the hedge must be a STABILISER priced
    # at a premium: a PPA struck ABOVE the mean caps the tail (cuts CVaR) but
    # raises expected cost. Min-expected-cost then stays on spot (risky, cheap)
    # while min-CVaR buys the PPA — the two anchors differ, so the frontier has
    # interior points.
    rng = np.random.default_rng(2)
    prices = np.abs(rng.normal(60, 45, 48))
    scen, _ = generate_scenarios(prices, n_bootstrap=100, block_hours=6, seed=2)
    load = np.full(48, 100.0)
    res = optimize_portfolio(scen, load, {
        "ppa": {"enabled": True, "strike": 65.0, "maxMw": 100.0, "profile": None},
    }, alpha=0.9, frontier_points=6)
    pts = res["frontier"]
    assert len(pts) >= 2
    costs = [p["expectedCost"] for p in pts]
    cvars = [p["cvar"] for p in pts]
    # As we allow more risk (higher CVaR budget), expected cost is non-increasing.
    assert all(costs[i + 1] <= costs[i] + 1e-6 for i in range(len(costs) - 1))
    assert all(cvars[i + 1] >= cvars[i] - 1e-6 for i in range(len(cvars) - 1))


def test_risk_budget_binds_and_is_respected() -> None:
    rng = np.random.default_rng(3)
    prices = np.abs(rng.normal(60, 50, 48))
    scen, _ = generate_scenarios(prices, n_bootstrap=120, block_hours=6, seed=3)
    load = np.full(48, 100.0)
    unc = optimize_portfolio(scen, load, {
        "ppa": {"enabled": True, "strike": 55.0, "maxMw": 100.0, "profile": None},
        "forward": {"enabled": True, "price": 57.0, "maxMw": 100.0},
    }, alpha=0.9)
    lo = unc["riskRange"]["minCvar"]
    hi = unc["riskRange"]["maxCvar"]
    budget = lo + 0.3 * (hi - lo)
    res = optimize_portfolio(scen, load, {
        "ppa": {"enabled": True, "strike": 55.0, "maxMw": 100.0, "profile": None},
        "forward": {"enabled": True, "price": 57.0, "maxMw": 100.0},
    }, alpha=0.9, cvar_budget=budget)
    assert res["optimal"]["cvar"] <= budget + 1.0  # respects the budget


def test_no_instruments_reports_error() -> None:
    scen, _ = generate_scenarios(np.full(24, 50.0), n_bootstrap=0)
    res = optimize_portfolio(scen, np.full(24, 10.0), {}, alpha=0.95)
    assert res["optimal"] is None
    assert "instruments" in res["error"].lower()
