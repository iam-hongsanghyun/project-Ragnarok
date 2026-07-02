"""B2 market simulation — merit order, pricing, storage rule, settlement.

Analytical cases small enough to verify by hand (per CLAUDE.md: numerical code
is tested against known solutions, not line coverage).
"""
from __future__ import annotations

import pandas as pd
import pypsa
import pytest

from backend.pypsa.results.simulation import (
    _storage_schedule,
    run_market_simulation,
)


def _network(hours: int = 2, load: float = 100.0) -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=hours, freq="h"))
    n.add("Bus", "b")
    n.add("Carrier", "wind")
    n.add("Carrier", "gas")
    n.add("Carrier", "oil")
    n.add("Load", "L", bus="b", p_set=load)
    n.add("Generator", "wind", bus="b", carrier="wind", p_nom=60.0, marginal_cost=0.0)
    n.add("Generator", "gas", bus="b", carrier="gas", p_nom=80.0, marginal_cost=50.0)
    n.add("Generator", "oil", bus="b", carrier="oil", p_nom=50.0, marginal_cost=120.0)
    return n


def test_merit_order_sets_marginal_price() -> None:
    # 100 MW load: wind 60 (mc 0) + gas 40 (mc 50) → gas is marginal, price 50.
    res = run_market_simulation(_network())
    assert res["summary"]["avgPrice"] == 50.0
    units = {u["name"]: u for u in res["units"]}
    assert units["wind"]["energyMWh"] == pytest.approx(120.0)  # 60 MW × 2 h
    assert units["gas"]["energyMWh"] == pytest.approx(80.0)   # 40 MW × 2 h
    assert units["oil"]["energyMWh"] == 0.0
    assert units["gas"]["priceSettingHours"] == 2
    # Uniform settlement: wind earns the clearing price at zero cost.
    assert units["wind"]["profit"] == pytest.approx(120.0 * 50.0)
    # Marginal unit earns zero margin.
    assert units["gas"]["profit"] == pytest.approx(0.0)


def test_scarcity_prices_at_voll() -> None:
    # 60+80+50 = 190 MW capacity < 200 MW load → 10 MW unserved at VOLL.
    res = run_market_simulation(_network(load=200.0), {"voll": 3000})
    assert res["summary"]["unservedMWh"] == pytest.approx(20.0)  # 10 MW × 2 h
    assert res["summary"]["peakPrice"] == 3000.0
    assert res["summary"]["unservedHours"] == 2


def test_pay_as_bid_pays_own_bid() -> None:
    res = run_market_simulation(_network(), {"pricing": "payAsBid"})
    units = {u["name"]: u for u in res["units"]}
    # Wind is paid its own (zero) bid → zero revenue under pay-as-bid.
    assert units["wind"]["revenue"] == 0.0
    assert units["gas"]["revenue"] == pytest.approx(80.0 * 50.0)


def test_bid_override_changes_dispatch_order_and_price() -> None:
    # Gas bids above oil → oil dispatches first, gas becomes marginal at its bid.
    res = run_market_simulation(_network(), {"bids": {"gas": 200.0}})
    units = {u["name"]: u for u in res["units"]}
    assert units["oil"]["energyMWh"] == pytest.approx(80.0)  # 40 MW × 2 h — beats gas now
    assert res["summary"]["avgPrice"] == 120.0  # oil's bid is marginal
    # Profit uses TRUE marginal cost, not the bid.
    assert units["oil"]["profit"] == pytest.approx(0.0)


def test_withholding_raises_the_price() -> None:
    # Withhold 40 MW of wind: gas must cover 80 MW; load still met, price still 50 —
    # withhold more: 60 MW wind gone → gas 80 + oil 20 → oil marginal at 120.
    res = run_market_simulation(_network(), {"withheldMw": {"wind": 60.0}})
    assert res["summary"]["avgPrice"] == 120.0


def test_availability_series_limits_dispatch() -> None:
    n = _network()
    n.generators_t.p_max_pu = pd.DataFrame({"wind": [1.0, 0.0]}, index=n.snapshots)
    res = run_market_simulation(n)
    # Hour 2 has no wind → gas covers 80, oil 20 → oil marginal (120).
    assert [p["value"] for p in res["priceSeries"]] == [50.0, 120.0]


def test_storage_schedule_arbitrages_the_spread() -> None:
    prices = pd.Series([10.0, 10.0, 100.0, 100.0]).to_numpy()
    sched = _storage_schedule(prices, power_mw=10.0, energy_mwh=20.0,
                              eta_round=1.0, q_charge=0.3, q_discharge=0.7)
    # Charges in both cheap hours, discharges in both expensive hours.
    assert sched[0] == -10.0 and sched[1] == -10.0
    assert sched[2] == 10.0 and sched[3] == 10.0


def test_storage_stays_idle_when_spread_cannot_pay_losses() -> None:
    prices = pd.Series([40.0, 50.0, 40.0, 50.0]).to_numpy()
    sched = _storage_schedule(prices, 10.0, 20.0, eta_round=0.5, q_charge=0.25, q_discharge=0.75)
    assert not sched.any()  # 50 × 0.5 ≤ 40 → arbitrage loses money


def test_run_pypsa_market_sim_study_mode() -> None:
    """End-to-end: marketSimConfig.enabled routes run_pypsa into the simulation
    study (no LP solve) and returns the standard payload shape with the
    simulated dispatch/price series filled."""
    from backend.pypsa.results import run_pypsa

    snaps = ["2030-01-01T00:00:00", "2030-01-01T01:00:00"]
    model = {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "wind"}, {"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [
            {"name": "wind", "bus": "b", "carrier": "wind", "p_nom": 60.0, "marginal_cost": 0.0},
            {"name": "gas", "bus": "b", "carrier": "gas", "p_nom": 80.0, "marginal_cost": 50.0},
        ],
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
        "loads-p_set": [{"snapshot": s, "L": 100.0} for s in snaps],
    }
    res = run_pypsa(model, {"discountRate": 0.0, "carbonPrice": 0.0},
                    {"marketSimConfig": {"enabled": True}})
    assert res["runMeta"]["studyMode"] == "marketSim"
    assert res["marketSimulation"]["summary"]["avgPrice"] == 50.0
    # The STANDARD chart series carry the simulated market.
    assert res["systemPriceSeries"][0]["value"] == 50.0
    assert res["dispatchSeries"][0]["values"]["wind"] == pytest.approx(60.0)
    assert res["meritOrder"], "supply stack should be present"
    # Optimise-only fields exist (empty) so the frontend payload shape holds.
    assert res["expansionResults"] == [] and res["costBreakdown"] == []


def test_storage_flattens_prices_in_the_simulation() -> None:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=4, freq="h"))
    n.add("Bus", "b")
    n.add("Carrier", "gas")
    n.add("Load", "L", bus="b", p_set=[50.0, 50.0, 100.0, 100.0])
    n.add("Generator", "cheap", bus="b", carrier="gas", p_nom=80.0, marginal_cost=20.0)
    n.add("Generator", "peaker", bus="b", carrier="gas", p_nom=60.0, marginal_cost=200.0)
    base = run_market_simulation(n)
    assert base["summary"]["peakPrice"] == 200.0
    n.add("StorageUnit", "batt", bus="b", p_nom=20.0, max_hours=2.0,
          efficiency_store=1.0, efficiency_dispatch=1.0)
    with_storage = run_market_simulation(n)
    # Battery charges in the two cheap hours and discharges 20 MW into both peak
    # hours → the peaker is no longer needed (80 ≥ 100 − 20) → peak price falls.
    assert with_storage["summary"]["peakPrice"] == 20.0
    assert with_storage["storage"][0]["energyDischargedMWh"] == pytest.approx(40.0)


# ── Two-sided auction, per-participant profit, auction book (clearing models) ──

def _two_sided_network() -> pypsa.Network:
    """Wind 40 @ €0, gas 50 @ €40, peaker 50 @ €150; 100 MW load."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.add("Bus", "b")
    n.add("Carrier", "wind")
    n.add("Carrier", "gas")
    n.add("Load", "L", bus="b", p_set=100.0)
    n.add("Generator", "wind1", bus="b", carrier="wind", p_nom=40.0, marginal_cost=0.0)
    n.add("Generator", "gas1", bus="b", carrier="gas", p_nom=50.0, marginal_cost=40.0)
    n.add("Generator", "peak1", bus="b", carrier="gas", p_nom=50.0, marginal_cost=150.0)
    return n


def test_two_sided_elastic_demand_caps_the_price() -> None:
    n = _two_sided_network()
    # 30% of the 100 MW is elastic at WTP 100 (< the 150 peaker). It walks away
    # rather than pay for the peaker, so gas (€40) is marginal, not the peaker.
    res = run_market_simulation(n, {
        "clearingModel": "twoSided", "demandElasticFraction": 0.3, "demandWtp": 100.0,
    })
    assert res["clearingModel"] == "twoSided"
    assert res["summary"]["avgPrice"] == pytest.approx(40.0)
    # Firm 70 + elastic served 20 (gas cap 50: 30 firm + 20 elastic) → 10 curtailed/hr.
    assert res["summary"]["curtailedMWh"] == pytest.approx(20.0)  # 10 MW × 2 h
    assert res["summary"]["unservedMWh"] == pytest.approx(0.0)


def test_single_sided_serves_all_load_at_the_peaker_price() -> None:
    n = _two_sided_network()
    res = run_market_simulation(n, {"clearingModel": "singleSided"})
    assert res["clearingModel"] == "singleSided"
    assert res["summary"]["avgPrice"] == pytest.approx(150.0)   # peaker marginal
    assert res["summary"]["curtailedMWh"] == pytest.approx(0.0)  # nothing priced out


def test_auction_book_orders_offers_and_flags_the_marginal_unit() -> None:
    n = _two_sided_network()
    book = run_market_simulation(n, {"clearingModel": "singleSided"})["auctionBook"]
    assert [o["name"] for o in book["offers"]] == ["wind1", "gas1", "peak1"]  # by bid
    assert book["offers"][0]["cumulativeMW"] == pytest.approx(40.0)
    assert book["offers"][-1]["cumulativeMW"] == pytest.approx(140.0)
    marginal = [o for o in book["offers"] if o["marginal"]]
    assert len(marginal) == 1 and marginal[0]["name"] == "peak1"
    assert book["clearingPrice"] == pytest.approx(150.0)


def test_per_participant_profit_aggregates_by_owner() -> None:
    from backend.pypsa.results import run_pypsa

    snaps = ["2030-01-01T00:00:00", "2030-01-01T01:00:00"]
    model = {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "wind"}, {"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
        "generators": [
            {"name": "wind1", "bus": "b", "carrier": "wind", "p_nom": 40, "marginal_cost": 0, "owner": "WindCo"},
            {"name": "gas1", "bus": "b", "carrier": "gas", "p_nom": 50, "marginal_cost": 40, "owner": "GasCo"},
            {"name": "peak1", "bus": "b", "carrier": "gas", "p_nom": 50, "marginal_cost": 150, "owner": "GasCo"},
        ],
    }
    res = run_pypsa(model, {"discountRate": 0.0, "carbonPrice": 0.0}, {
        "ownerColumn": "owner",
        "marketSimConfig": {"enabled": True, "pricing": "uniform", "clearingModel": "singleSided"},
    })
    parts = res["marketSimulation"]["participants"]
    by = {p["participant"]: p for p in parts}
    # Uniform price 150: WindCo 40·150·2 = 12000; GasCo gas1 50·(150−40)·2 = 11000.
    assert by["WindCo"]["profit"] == pytest.approx(12000.0)
    assert by["GasCo"]["profit"] == pytest.approx(11000.0)
    assert by["GasCo"]["unitCount"] == 2               # gas1 + peak1 rolled up
    assert by["GasCo"]["priceSettingHours"] == 2       # peak1 marginal both hours
    # Ranked by profit, WindCo first.
    assert parts[0]["participant"] == "WindCo"
