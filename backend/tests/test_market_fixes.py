"""Regression tests for the 2026-07 market/results review fixes.

Covers, with hand-checkable analytical cases:
  1. Strategic markup sweeps act through ``generators_t.marginal_cost`` (a
     time-varying true cost — e.g. a carbon-price schedule — no longer makes
     the sweep a silent no-op), and profit is measured against the dense
     per-snapshot TRUE cost.
  2. Strategic bidding (B4) carries the full B2 sim config — a two-sided
     demand curve caps the exercisable market power.
  3. The merit order keeps extendable generators on a never-optimised network
     (market-sim study mode) by falling back to installed ``p_nom``.
  4. Market-simulation energy/currency totals honour snapshot weighting.
  5. Weighted-basis consistency: price-formation per-carrier avgPrice and the
     PPA explorer's peak block both respect snapshot weights.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pypsa
import pytest

from backend.pypsa.results.bid_strategy import build_bid_strategy
from backend.pypsa.results.market import build_merit_order
from backend.pypsa.results.optimal_bid import build_optimal_bid
from backend.pypsa.results.ppa_explorer import _peak_block
from backend.pypsa.results.price_formation import build_price_formation
from backend.pypsa.results.simulation import run_market_simulation
from backend.pypsa.results.strategic import _strategy_config, build_strategic_bidding


# ── 1. Markup sweeps with time-varying marginal cost ──────────────────────────


def _tv_cost_market() -> tuple[pypsa.Network, dict[str, list[dict[str, Any]]]]:
    """Load 150 MW: base 100 @ 10 runs flat, Acme's gas covers the residual
    50 MW and is marginal — its TRUE cost is time-varying ([40, 60] via
    ``generators_t.marginal_cost``, the carbon-schedule pattern)."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.add("Bus", "b")
    n.add("Carrier", "base")
    n.add("Carrier", "gas")
    n.add("Carrier", "peak")
    n.add("Load", "L", bus="b", p_set=150.0)
    n.add("Generator", "base1", bus="b", carrier="base", p_nom=100.0, marginal_cost=10.0)
    n.add("Generator", "acme_gas", bus="b", carrier="gas", p_nom=120.0, marginal_cost=40.0)
    n.add("Generator", "peak1", bus="b", carrier="peak", p_nom=200.0, marginal_cost=100.0)
    n.generators_t.marginal_cost["acme_gas"] = pd.Series([40.0, 60.0], index=n.snapshots)
    model = {"generators": [{"name": "acme_gas", "owner": "Acme"}]}
    return n, model


def test_markup_moves_clearing_under_time_varying_cost() -> None:
    n, model = _tv_cost_market()
    n.optimize(solver_name="highs")
    bs = build_bid_strategy(
        n, model, owner="Acme", owner_column="owner",
        markup_type="percent", markup=0.5, currency="€",
    )
    assert bs is not None
    # Baseline: Acme is marginal both hours at its own (true) cost — zero profit,
    # measured against the DENSE cost ([40, 60]), not the stale static 40.
    np.testing.assert_allclose(bs["baseline"]["profit"], 0.0, rtol=0, atol=1e-6)
    np.testing.assert_allclose(bs["baseline"]["energyMWh"], 100.0, rtol=1e-9, atol=1e-6)
    # Offer = [60, 90] (both under the 100 peaker) → Acme keeps its 50 MW and
    # lifts the price it sets; profit at TRUE cost = (60−40+90−60)·50 = 2500.
    np.testing.assert_allclose(bs["strategic"]["profit"], 2500.0, rtol=1e-6, atol=1e-3)
    np.testing.assert_allclose(bs["deltaProfit"], 2500.0, rtol=1e-6, atol=1e-3)
    # The clearing actually moved — the regression was a flat no-op re-solve.
    assert bs["systemAvgPrice"]["strategic"] > bs["systemAvgPrice"]["baseline"]


def test_optimal_bid_sweep_is_not_flat_under_time_varying_cost() -> None:
    n, model = _tv_cost_market()
    n.optimize(solver_name="highs")
    ob = build_optimal_bid(
        n, model, owner="Acme", owner_column="owner",
        markup_type="percent", max_markup=2.0, steps=4, currency="€",
    )
    assert ob is not None
    profits = [c["profit"] for c in ob["curve"]]
    assert len(set(profits)) > 1, "sweep must change the clearing, not be flat"
    assert ob["optimalMarkup"] > 0
    assert ob["deltaProfit"] > 0
    # The markup-0.5 point is the analytical 2500 (see the fixed-markup test).
    by_markup = {c["markup"]: c["profit"] for c in ob["curve"]}
    np.testing.assert_allclose(by_markup[0.5], 2500.0, rtol=1e-6, atol=1e-3)


# ── 2. Strategic bidding carries the full B2 sim config ──────────────────────


def test_strategic_respects_two_sided_demand_curve() -> None:
    """30 MW of the 100 MW load walks away above €100/MWh: the profit-maximising
    markup stops at the elastic WTP (bid 100 on the full 100 MW beats bid ~120
    on the 70 MW firm rump) — dropping the clearing config (the regression)
    instead found the single-sided optimum at the rival's 120 ceiling."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.add("Bus", "b")
    n.add("Carrier", "gas")
    n.add("Load", "L", bus="b", p_set=100.0)
    n.add("Generator", "alpha_1", bus="b", carrier="gas", p_nom=120.0, marginal_cost=10.0)
    n.add("Generator", "rival_peak", bus="b", carrier="gas", p_nom=60.0, marginal_cost=120.0)
    model = {"generators": [
        {"name": "alpha_1", "owner": "AlphaCo"},
        {"name": "rival_peak", "owner": "BetaCo"},
    ]}
    res = build_strategic_bidding(
        n, model,
        config={"enabled": True, "owner": "AlphaCo", "strategy": "markup",
                "maxAdder": 200.0, "steps": 20},
        sim_config={"pricing": "uniform", "voll": 3000, "clearingModel": "twoSided",
                    "demandElasticFraction": 0.3, "demandWtp": 100.0},
        owner_column="owner", currency="€",
    )
    assert res is not None
    # Best bid = 10 + 90 = 100 = the elastic WTP; price capped at 100, not 120.
    np.testing.assert_allclose(res["best"]["level"], 90.0, rtol=0, atol=1e-9)
    np.testing.assert_allclose(res["best"]["avgPrice"], 100.0, rtol=1e-9, atol=1e-6)
    # 100 MW × (100 − 10) €/MWh × 2 h at the optimum.
    np.testing.assert_allclose(res["best"]["ownerProfit"], 18000.0, rtol=1e-9, atol=1e-3)


def test_strategy_config_preserves_base_bid_overrides() -> None:
    cfg = _strategy_config(
        {"voll": 3000, "bids": {"other_unit": 55.0}},
        "markup", 5.0, ["u1"], {"u1": 10.0}, {"u1": 100.0},
    )
    # The user's own bid override survives; the owner's strategic bid is added.
    assert cfg["bids"] == {"other_unit": 55.0, "u1": 15.0}
    assert cfg["voll"] == 3000


# ── 3. Merit order keeps extendable generators pre-optimise ──────────────────


def test_merit_order_falls_back_to_p_nom_for_unsolved_extendables() -> None:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=1, freq="h"))
    n.add("Bus", "b")
    n.add("Carrier", "wind")
    n.add("Generator", "exp_wind", bus="b", carrier="wind",
          p_nom=200.0, p_nom_extendable=True, marginal_cost=5.0)
    rows = build_merit_order(n)  # never optimised: p_nom_opt is 0/NaN
    assert [r["name"] for r in rows] == ["exp_wind"]
    np.testing.assert_allclose(rows[0]["p_nom"], 200.0, rtol=0, atol=1e-9)
    # Once a solve produced a capacity, the optimised value wins.
    n.generators.loc["exp_wind", "p_nom_opt"] = 150.0
    rows = build_merit_order(n)
    np.testing.assert_allclose(rows[0]["p_nom"], 150.0, rtol=0, atol=1e-9)


# ── 4. Market-sim totals honour snapshot weighting ────────────────────────────


def _sim_network(load: float = 200.0) -> pypsa.Network:
    """190 MW of capacity vs a 200 MW load → 10 MW unserved every hour."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.add("Bus", "b")
    n.add("Carrier", "wind")
    n.add("Carrier", "gas")
    n.add("Carrier", "oil")
    n.add("Load", "L", bus="b", p_set=load)
    n.add("Generator", "wind", bus="b", carrier="wind", p_nom=60.0, marginal_cost=0.0)
    n.add("Generator", "gas", bus="b", carrier="gas", p_nom=80.0, marginal_cost=50.0)
    n.add("Generator", "oil", bus="b", carrier="oil", p_nom=50.0, marginal_cost=120.0)
    return n


def test_simulation_totals_scale_with_snapshot_weight() -> None:
    base = run_market_simulation(_sim_network())
    weighted_net = _sim_network()
    weighted_net.snapshot_weightings["objective"] = 3.0
    weighted = run_market_simulation(weighted_net)

    sb, sw = base["summary"], weighted["summary"]
    # Energy and currency totals are ×3 (each snapshot represents 3 h).
    for key in ("totalLoadMWh", "totalCost", "unservedMWh"):
        np.testing.assert_allclose(sw[key], 3.0 * sb[key], rtol=1e-9, atol=1e-6)
    ub = {u["name"]: u for u in base["units"]}
    uw = {u["name"]: u for u in weighted["units"]}
    for name in ub:
        for key in ("energyMWh", "revenue", "cost", "profit"):
            np.testing.assert_allclose(uw[name][key], 3.0 * ub[name][key],
                                       rtol=1e-9, atol=1e-6)
        # Intensive quantities are weighting-invariant.
        np.testing.assert_allclose(uw[name]["capacityFactor"], ub[name]["capacityFactor"],
                                   rtol=1e-9, atol=1e-9)
    np.testing.assert_allclose(sw["avgPrice"], sb["avgPrice"], rtol=1e-9, atol=1e-9)
    np.testing.assert_allclose(sw["peakPrice"], sb["peakPrice"], rtol=1e-9, atol=1e-9)


def test_simulation_weighted_values_match_hand_calc() -> None:
    # 100 MW load, weight 3: wind 60 @ 0 + gas 40 @ 50 → price 50 both hours.
    n = _sim_network(load=100.0)
    n.snapshot_weightings["objective"] = 3.0
    res = run_market_simulation(n)
    units = {u["name"]: u for u in res["units"]}
    np.testing.assert_allclose(units["wind"]["energyMWh"], 60.0 * 2 * 3, rtol=1e-9, atol=1e-6)
    np.testing.assert_allclose(units["wind"]["profit"], 60.0 * 2 * 3 * 50.0, rtol=1e-9, atol=1e-6)
    np.testing.assert_allclose(res["summary"]["totalLoadMWh"], 100.0 * 2 * 3, rtol=1e-9, atol=1e-6)
    np.testing.assert_allclose(res["summary"]["totalCost"], 100.0 * 2 * 3 * 50.0, rtol=1e-9, atol=1e-6)
    # capacityFactor stays energy over weighted hours: wind runs full-out.
    np.testing.assert_allclose(units["wind"]["capacityFactor"], 1.0, rtol=0, atol=1e-9)


def test_simulation_storage_energy_is_weighted() -> None:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=4, freq="h"))
    n.add("Bus", "b")
    n.add("Carrier", "gas")
    n.add("Load", "L", bus="b", p_set=[50.0, 50.0, 100.0, 100.0])
    n.add("Generator", "cheap", bus="b", carrier="gas", p_nom=80.0, marginal_cost=20.0)
    n.add("Generator", "peaker", bus="b", carrier="gas", p_nom=60.0, marginal_cost=200.0)
    n.add("StorageUnit", "batt", bus="b", p_nom=20.0, max_hours=2.0,
          efficiency_store=1.0, efficiency_dispatch=1.0)
    n.snapshot_weightings["objective"] = 2.0
    res = run_market_simulation(n)
    # 20 MW discharged into both peak snapshots × 2 h/snapshot = 80 MWh.
    np.testing.assert_allclose(res["storage"][0]["energyDischargedMWh"], 80.0,
                               rtol=1e-9, atol=1e-6)


# ── 5. Weighted-basis consistency (price formation, PPA peak block) ──────────


def test_price_formation_avg_price_is_weight_weighted() -> None:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.add("Bus", "b")
    n.add("Carrier", "gas")
    n.add("Load", "L", bus="b", p_set=[50.0, 150.0])
    n.add("Generator", "gas1", bus="b", carrier="gas", p_nom=100.0, marginal_cost=40.0)
    n.add("Generator", "gas2", bus="b", carrier="gas", p_nom=100.0, marginal_cost=60.0)
    n.snapshot_weightings["objective"] = [1.0, 3.0]
    n.optimize(solver_name="highs")
    pf = build_price_formation(n, currency="€")
    assert pf is not None
    row = next(r for r in pf["marginalSummary"] if r["carrier"] == "gas")
    np.testing.assert_allclose(row["hours"], 4.0, rtol=0, atol=1e-9)
    # Weighted mean (40·1 + 60·3) / 4 = 55 — the unweighted snapshot mean is 50.
    np.testing.assert_allclose(row["avgPrice"], 55.0, rtol=1e-9, atol=1e-6)


def test_ppa_peak_block_uses_weighted_quantile() -> None:
    n = pypsa.Network()
    snaps = pd.date_range("2030-01-01", periods=4, freq="h")
    n.set_snapshots(snaps)
    n.add("Bus", "b")
    n.buses_t.marginal_price["b"] = pd.Series([10.0, 20.0, 30.0, 100.0], index=snaps)
    n.snapshot_weightings["objective"] = [5.0, 1.0, 1.0, 1.0]
    # Total weight 8 h → the top 25% is 2 h: the 100 hour (1 h) AND the 30 hour
    # (1 h). An unweighted count quantile would take only the single 100 hour.
    res = _peak_block(n, flat_mw=10.0, strike=50.0)
    assert res is not None
    np.testing.assert_allclose(res["energyMWh"], 20.0, rtol=1e-9, atol=1e-6)
    np.testing.assert_allclose(res["avgSpotPrice"], 65.0, rtol=1e-9, atol=1e-6)
    np.testing.assert_allclose(res["sellerNet"], 50.0 * 20.0 - 1300.0, rtol=1e-9, atol=1e-6)


def test_ppa_peak_block_equal_weights_matches_count_quantile() -> None:
    n = pypsa.Network()
    snaps = pd.date_range("2030-01-01", periods=4, freq="h")
    n.set_snapshots(snaps)
    n.add("Bus", "b")
    n.buses_t.marginal_price["b"] = pd.Series([10.0, 20.0, 30.0, 100.0], index=snaps)
    res = _peak_block(n, flat_mw=10.0, strike=50.0)
    assert res is not None
    # Equal weights: top 25% of 4 hours = the single 100 €/MWh hour.
    np.testing.assert_allclose(res["energyMWh"], 10.0, rtol=1e-9, atol=1e-6)
    np.testing.assert_allclose(res["avgSpotPrice"], 100.0, rtol=1e-9, atol=1e-6)


def test_bid_strategy_static_cost_path_unchanged() -> None:
    """Guard: with purely static costs the fix must reproduce the old numbers
    (the offer now travels via generators_t.marginal_cost either way)."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.add("Bus", "b")
    n.add("Carrier", "base")
    n.add("Carrier", "gas")
    n.add("Carrier", "peak")
    n.add("Load", "L", bus="b", p_set=150.0)
    n.add("Generator", "base1", bus="b", carrier="base", p_nom=100.0, marginal_cost=10.0)
    n.add("Generator", "acme_gas", bus="b", carrier="gas", p_nom=120.0, marginal_cost=40.0)
    n.add("Generator", "peak1", bus="b", carrier="peak", p_nom=200.0, marginal_cost=100.0)
    n.optimize(solver_name="highs")
    bs = build_bid_strategy(
        n, {"generators": [{"name": "acme_gas", "owner": "Acme"}]},
        owner="Acme", owner_column="owner",
        markup_type="percent", markup=0.5, currency="€",
    )
    assert bs is not None
    # Offer 60 < peaker 100: Acme keeps 50 MW, price 40→60 → (60−40)·50·2 = 2000.
    np.testing.assert_allclose(bs["deltaProfit"], 2000.0, rtol=1e-6, atol=1e-3)
    assert pytest.approx(bs["baseline"]["profit"], abs=1e-6) == 0.0
