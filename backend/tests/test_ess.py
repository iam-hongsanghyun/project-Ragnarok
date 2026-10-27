"""ESS business-case builder (DW3) — battery size sweep vs arbitrage revenue.

A spiky price (cheap and dear hours alternate) gives a battery real arbitrage
value. The sweep should return a size curve with NPV/IRR/payback and pick the
NPV-maximising size.
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.07, "carbonPrice": 0.0}


def _model() -> dict[str, list[dict[str, Any]]]:
    # Alternating cheap/dear hours → a wide price spread for arbitrage.
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(8)]
    load = [60, 200, 60, 200, 60, 200, 60, 200]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "base"}, {"name": "peak"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(snaps, load)],
        "generators": [
            {"name": "base1", "bus": "b", "carrier": "base", "p_nom": 120, "marginal_cost": 20},
            {"name": "peak1", "bus": "b", "carrier": "peak", "p_nom": 200, "marginal_cost": 150},
        ],
    }


def test_ess_business_case_size_sweep() -> None:
    res = run_pypsa(
        _model(), SCENARIO,
        {"essConfig": {"enabled": True, "maxHours": 4, "capitalCostPerMW": 30000,
                       "minSizeMW": 10, "maxSizeMW": 60, "steps": 4, "roundTripEfficiency": 0.9}},
    )
    ess = res["essBusinessCase"]
    assert ess is not None
    assert ess["bus"] == "b"
    assert len(ess["sizes"]) == 4
    for s in ess["sizes"]:
        assert s["sizeMW"] > 0
        assert s["arbitrageRevenue"] >= 0  # a battery never loses money arbitraging
        assert "npv" in s and "paybackYears" in s
    # Best size is the NPV-maximiser reported in the curve.
    assert ess["bestNpv"] == max(s["npv"] for s in ess["sizes"])
    assert any(s["sizeMW"] == ess["bestSizeMW"] for s in ess["sizes"])


def test_ess_business_case_absent_when_disabled() -> None:
    assert run_pypsa(_model(), SCENARIO, {})["essBusinessCase"] is None


def _solved_base(*, pathway: bool = False) -> Any:
    import logging

    import pypsa

    logging.disable(logging.CRITICAL)
    n = pypsa.Network()
    n.set_snapshots(range(8))
    if pathway:
        n.set_investment_periods([2030, 2040])
    n.add("Bus", "b")
    n.add("Carrier", ["base", "peak"])
    n.add("Load", "L", bus="b", p_set=[60, 200, 60, 200, 60, 200, 60, 200] * (2 if pathway else 1))
    n.add("Generator", "base1", bus="b", carrier="base", p_nom=120, marginal_cost=20)
    n.add("Generator", "peak1", bus="b", carrier="peak", p_nom=200, marginal_cost=150)
    n.optimize(solver_name="highs", multi_investment_periods=pathway, include_objective_constant=False)
    return n


_ARGS: dict[str, Any] = {
    "bus": "b", "max_hours": 4, "capital_cost_per_mw": 30000, "min_size_mw": 10, "max_size_mw": 10,
    "steps": 1, "round_trip_efficiency": 0.81, "discount_rate": 0.07, "currency": "$",
}


def test_ess_analytical_arbitrage_and_cycle_metrics() -> None:
    """10 MW / 40 MWh, one-way eta 0.9, prices alternate 20 / 150 over 8 h.

    Each cheap hour buys 10 MWh at 20; the next dear hour sells 10 * 0.81 = 8.1 MWh
    at 150. Four cycles: the LP result is pinned against these hand figures.
    """
    from backend.pypsa.results.ess import build_ess_business_case

    out = build_ess_business_case(_solved_base(), **_ARGS)
    assert out is not None
    row = out["sizes"][0]
    assert row["energyCapacityMWh"] == pytest.approx(40.0)
    # Cheap hours are t=0,2,4,6 (price 20), dear t=1,3,5,7 (price 150): 4 cycles of 10 MW x 1 h.
    assert row["chargedMWh"] == pytest.approx(40.0, rel=1e-6)
    assert row["throughputMWh"] == pytest.approx(40.0 * 0.81, rel=1e-6)
    assert row["equivalentFullCycles"] == pytest.approx(40.0 * 0.81 / 40.0, rel=1e-6)
    assert row["avgChargePrice"] == pytest.approx(20.0, rel=1e-6)
    assert row["avgDischargePrice"] == pytest.approx(150.0, rel=1e-6)
    assert row["priceSpread"] == pytest.approx(130.0, rel=1e-6)
    assert row["arbitrageRevenue"] == pytest.approx(40 * 0.81 * 150 - 40 * 20, rel=1e-6)
    # Window is 8 h: the annual figure is x 8760/8.
    assert row["annualArbitrageRevenue"] == pytest.approx(row["arbitrageRevenue"] * 8760 / 8, rel=1e-9)


def test_ess_costs_lifetime_and_standing_loss_inputs() -> None:
    from backend.pypsa.results.ess import build_ess_business_case
    from backend.pypsa.results.finance import _crf

    base = _solved_base()
    ref = build_ess_business_case(base, **_ARGS)
    assert ref is not None and any("No lifetime" in n for n in ref["notes"])
    with_costs = build_ess_business_case(
        base, **_ARGS, fixed_om_per_mw_year=1000.0, lifetime_years=10.0, capital_cost_per_mwh=500.0,
    )
    assert with_costs is not None and with_costs["lifetimeYears"] == 10.0 and not with_costs["notes"]
    row = with_costs["sizes"][0]
    margin = row["annualArbitrageRevenue"] - 1000.0 * 10
    assert row["annualMargin"] == pytest.approx(margin, rel=1e-9)
    annualised = 30000 * 10 + 500 * 40
    assert row["annualisedCapex"] == pytest.approx(annualised)
    overnight = annualised / _crf(0.07, 10.0)
    npv = -overnight + sum(margin / 1.07 ** t for t in range(1, 11))
    assert row["npv"] == pytest.approx(npv, rel=1e-6)
    lossy = build_ess_business_case(base, **_ARGS, standing_loss=0.2)
    assert lossy is not None
    assert lossy["sizes"][0]["arbitrageRevenue"] <= ref["sizes"][0]["arbitrageRevenue"] + 1e-6


def test_ess_business_case_runs_on_a_pathway_network() -> None:
    from backend.pypsa.results.ess import build_ess_business_case

    out = build_ess_business_case(_solved_base(pathway=True), **_ARGS)
    assert out is not None and out["pathway"] is True
    assert any("Pathway" in n for n in out["notes"])
    # 16 represented hours, same price shape: annualised margin per MWh equals the plain run's.
    plain = build_ess_business_case(_solved_base(), **_ARGS)
    assert plain is not None
    assert out["sizes"][0]["annualArbitrageRevenue"] == pytest.approx(plain["sizes"][0]["annualArbitrageRevenue"], rel=1e-6)


def test_ess_auto_bus_is_an_electricity_bus() -> None:
    import pypsa

    from backend.pypsa.results.ess import _electricity_candidates

    n = pypsa.Network()
    n.add("Bus", "ac", carrier="AC")
    n.add("Bus", "h2", carrier="H2")
    n.add("Load", "L", bus="ac", p_set=10)
    assert _electricity_candidates(n, ["ac", "h2"]) == ["ac"]


def test_ess_cost_kwargs_maps_new_keys_and_ignores_missing() -> None:
    from backend.pypsa.results.ess import ess_cost_kwargs

    assert ess_cost_kwargs({}) == {
        "capital_cost_per_mwh": 0.0, "fixed_om_per_mw_year": 0.0, "variable_cost_per_mwh": 0.0,
        "lifetime_years": None, "standing_loss": 0.0,
    }
    got = ess_cost_kwargs({"capitalCostPerMWh": 500, "fixedOmPerMWYear": "1000", "lifetimeYears": 12,
                           "standingLoss": 0.001, "variableCostPerMWh": None})
    assert got["capital_cost_per_mwh"] == 500.0 and got["fixed_om_per_mw_year"] == 1000.0
    assert got["lifetime_years"] == 12.0 and got["standing_loss"] == 0.001 and got["variable_cost_per_mwh"] == 0.0
