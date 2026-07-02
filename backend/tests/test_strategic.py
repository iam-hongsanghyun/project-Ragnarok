"""B4 strategic bidding — best-response market power over the B2 simulator.

The canonical two-firm market-power setup: a strategic owner holding cheap
capacity that the market NEEDS (residual demand > rivals' capacity) can mark up
its bid to just under the next rival's cost — or withhold — and the best
response finds exactly that.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import pypsa
import pytest

from backend.pypsa.results.strategic import build_strategic_bidding

SIM_CFG = {"pricing": "uniform", "voll": 3000}


def _market() -> tuple[pypsa.Network, dict[str, list[dict[str, Any]]]]:
    """Load 100 MW. AlphaCo owns 80 MW @ mc 10 — pivotal up to the rival's
    120 €/MWh peaker (60 MW). Competitive price: 120 only for the residual…
    actually merit order: alpha 80 @10 + rival 20 @120 → price 120? No: rival
    unit is the marginal one at 120. Alpha already earns 120. Use a rival mid
    unit so alpha is marginal at baseline instead."""
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
    return n, model


def test_markup_best_response_finds_the_rivals_cost_ceiling() -> None:
    n, model = _market()
    res = build_strategic_bidding(
        n, model,
        config={"enabled": True, "owner": "AlphaCo", "strategy": "markup",
                "maxAdder": 200.0, "steps": 20},
        sim_config=SIM_CFG, owner_column="owner", currency="€",
    )
    assert res is not None
    # Baseline: alpha covers all 100 MW and is marginal at its own 10 €/MWh —
    # zero profit. Marking up raises the price alpha itself sets… until the bid
    # crosses the rival's 120: then the rival undercuts and alpha loses volume.
    assert res["baseline"]["profit"] == pytest.approx(0.0)
    assert res["best"]["ownerProfit"] > 0
    best_bid = 10.0 + res["best"]["level"]
    assert best_bid <= 120.0  # never bids past the rival's cost
    assert best_bid >= 100.0  # …but pushes close to it
    assert res["best"]["profitUplift"] == res["best"]["ownerProfit"]
    # Exercising market power raised what consumers pay.
    assert res["best"]["consumerCostDelta"] > 0


def test_withholding_forces_the_peaker_to_set_the_price() -> None:
    n, model = _market()
    res = build_strategic_bidding(
        n, model,
        config={"enabled": True, "owner": "AlphaCo", "strategy": "withhold",
                "maxWithholdPct": 0.4, "steps": 16},  # below the scarcity threshold
        sim_config=SIM_CFG, owner_column="owner", currency="€",
    )
    assert res is not None
    # Withholding >1/6 of 120 MW leaves alpha under the 100 MW load, so the
    # 120 €/MWh peaker becomes marginal; the best response is the SMALLEST such
    # level (keeps alpha's volume) — price 120, big margin on ~99 MW.
    assert res["best"]["level"] == pytest.approx(0.175, abs=1e-9)
    assert res["best"]["avgPrice"] == pytest.approx(120.0)
    assert res["best"]["ownerProfit"] > 0


def test_withholding_into_scarcity_prices_at_voll_when_allowed() -> None:
    # Given room to withhold past total-capacity < load, the profit maximiser
    # DOES create scarcity and earns the VOLL price — the classic (and reported)
    # market-power extreme; consumer cost explodes accordingly.
    n, model = _market()
    res = build_strategic_bidding(
        n, model,
        config={"enabled": True, "owner": "AlphaCo", "strategy": "withhold",
                "maxWithholdPct": 0.8, "steps": 16},
        sim_config=SIM_CFG, owner_column="owner", currency="€",
    )
    assert res is not None
    assert res["best"]["avgPrice"] == pytest.approx(3000.0)  # VOLL
    assert res["best"]["consumerCostDelta"] > 0
    assert max(r["unservedMWh"] for r in res["curve"]) > 0


def test_unknown_owner_returns_none() -> None:
    n, model = _market()
    assert build_strategic_bidding(
        n, model, config={"enabled": True, "owner": "NoSuchCo"},
        sim_config=SIM_CFG, owner_column="owner", currency="€",
    ) is None


def test_two_owner_best_response_converges() -> None:
    n, model = _market()
    res = build_strategic_bidding(
        n, model,
        config={"enabled": True, "owner": "AlphaCo", "strategy": "markup",
                "maxAdder": 200.0, "steps": 10, "rivalOwner": "BetaCo", "rounds": 4},
        sim_config=SIM_CFG, owner_column="owner", currency="€",
    )
    assert res is not None
    eq = res["equilibrium"]
    assert eq is not None and eq["rivalOwner"] == "BetaCo"
    assert eq["rounds"], "best-response history recorded"
    assert eq["converged"] is True  # this tiny market settles


def test_study_payload_carries_strategic_result() -> None:
    from backend.pypsa.results import run_pypsa

    snaps = ["2030-01-01T00:00:00", "2030-01-01T01:00:00"]
    model = {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [
            {"name": "alpha_1", "bus": "b", "carrier": "gas", "p_nom": 120.0,
             "marginal_cost": 10.0, "owner": "AlphaCo"},
            {"name": "rival_peak", "bus": "b", "carrier": "gas", "p_nom": 60.0,
             "marginal_cost": 120.0, "owner": "BetaCo"},
        ],
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
        "loads-p_set": [{"snapshot": s, "L": 100.0} for s in snaps],
    }
    res = run_pypsa(model, {"discountRate": 0.0, "carbonPrice": 0.0}, {
        "ownerColumn": "owner",
        "marketSimConfig": {
            "enabled": True,
            "strategic": {"enabled": True, "owner": "AlphaCo", "strategy": "markup",
                          "maxAdder": 150.0, "steps": 10},
        },
    })
    assert res["runMeta"]["studyMode"] == "marketSim"
    sb = res["strategicBidding"]
    assert sb is not None and sb["owner"] == "AlphaCo"
    assert sb["best"]["ownerProfit"] > sb["baseline"]["profit"]
