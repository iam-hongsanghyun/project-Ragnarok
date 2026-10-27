"""Regression tests for the 2026-10-27 results review (RB1-RB7, RB10).

Each test pins an analytical value (hand-computed in the docstring) rather than
a captured baseline.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import pypsa
import pytest
from fastapi import HTTPException

from backend.pypsa.results import run_pypsa
from backend.pypsa.results.derived_series import derive_series
from backend.pypsa.results.dispatch import system_price_series, weighted_mean
from backend.pypsa.results.expansion import build_expansion_results
from backend.pypsa.results.market import CAPEX_WINDOW_SCALE_KEY
from backend.pypsa.network.serialize import network_to_model

logging.disable(logging.WARNING)

SNAPS = ["2025-01-01T00:00:00", "2025-01-01T01:00:00"]


def _two_gen_model(cap: float | None = None) -> dict[str, list[dict[str, Any]]]:
    """Cheap gas (20 $/MWh, 0.4 t/MWh) vs clean (50 $/MWh); 100 MW load."""
    model: dict[str, list[dict[str, Any]]] = {
        "buses": [{"name": "b0"}],
        "snapshots": [{"snapshot": s} for s in SNAPS],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}, {"name": "clean"}],
        "generators": [
            {"name": "g", "bus": "b0", "carrier": "gas", "p_nom": 500.0, "marginal_cost": 20.0},
            {"name": "g2", "bus": "b0", "carrier": "clean", "p_nom": 500.0, "marginal_cost": 50.0},
        ],
        "loads": [{"name": "L", "bus": "b0", "p_set": 100.0}],
    }
    if cap is not None:
        model["global_constraints"] = [
            {"name": "cap", "type": "primary_energy", "carrier_attribute": "co2_emissions",
             "sense": "<=", "constant": cap}
        ]
    return model


def _stochastic_options() -> dict[str, Any]:
    return {"stochasticConfig": {"enabled": True, "scenarios": [
        {"name": "a", "weight": 0.6, "overrides": []},
        {"name": "b", "weight": 0.4, "overrides": [
            {"sheet": "loads", "attribute": "p_set", "scopeType": "all", "scopeValue": "",
             "operation": "multiply", "value": 0.5}]},
    ]}}


def test_rb1_stochastic_duals_are_divided_by_scenario_weight() -> None:
    """Scenario a (weight 0.6, 100 MW) with a binding 40 t CO2 cap over 2 h.

    Gas emits 0.4 t/MWh, so the cap allows 100 MWh of gas; the other 100 MWh
    comes from the 50 $/MWh unit. Price = 50 (not 0.6 x 50 = 30). The CO2 dual is
    (50 - 20) / 0.4 = 75 $/t (not 0.6 x 75 = 45).
    """
    result = run_pypsa(_two_gen_model(cap=40.0), {"discountRate": 0.0}, _stochastic_options())
    assert result["stochastic"]["representativeScenario"] == "a"
    prices = [r["value"] for r in result["systemPriceSeries"]]
    np.testing.assert_allclose(prices, [50.0, 50.0], rtol=1e-6)
    shadow = result["co2Shadow"]
    assert shadow["status"] == "binding"
    np.testing.assert_allclose(shadow["shadow_price"], 75.0, rtol=1e-6)


def test_rb5_rolling_rejects_extendable_and_budgets() -> None:
    opts = {"rollingConfig": {"enabled": True, "horizonSnapshots": 1, "overlapSnapshots": 0}}
    ext = _two_gen_model()
    ext["generators"][0].update({"p_nom_extendable": True, "capital_cost": 1.0})
    with pytest.raises(HTTPException) as e1:
        run_pypsa(ext, {"discountRate": 0.0}, opts)
    assert e1.value.status_code == 400 and "p_nom_extendable" in e1.value.detail

    with pytest.raises(HTTPException) as e2:
        run_pypsa(_two_gen_model(cap=1000.0), {"discountRate": 0.0}, opts)
    assert e2.value.status_code == 400 and "global constraint" in e2.value.detail

    ok = run_pypsa(_two_gen_model(), {"discountRate": 0.0}, opts)
    assert ok["rolling"]["enabled"]


def test_rb6_system_price_is_load_weighted() -> None:
    """Prices 10 and 90 at buses carrying 75 and 25 MW: (75*10 + 25*90)/100 = 30
    (the unweighted mean would be 50). A zero-load snapshot falls back to the mean."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2025-01-01", periods=2, freq="h"))
    n.add("Bus", "a")
    n.add("Bus", "c")
    n.add("Load", "La", bus="a", p_set=pd.Series([75.0, 0.0], index=n.snapshots))
    n.add("Load", "Lc", bus="c", p_set=pd.Series([25.0, 0.0], index=n.snapshots))
    n.buses_t.marginal_price = pd.DataFrame({"a": [10.0, 10.0], "c": [90.0, 90.0]}, index=n.snapshots)
    price = system_price_series(n, None, n.get_switchable_as_dense("Load", "p_set"))
    np.testing.assert_allclose(price.to_numpy(), [30.0, 50.0], rtol=1e-12)
    # Snapshot-weighted average: weights 3 and 1 -> (3*30 + 1*50)/4 = 35.
    np.testing.assert_allclose(weighted_mean(price, pd.Series([3.0, 1.0], index=n.snapshots)), 35.0)


def test_rb7_cost_breakdown_includes_link_and_storage_marginal_cost() -> None:
    """Gas serves 100 MW load at b0 plus 20 MW sent over a 0.7 $/MWh link to a
    20 MW load at b1 (lossless), over two 1-h snapshots.
    Fuel = 120 MW x 2 h x 20 = 4800; link = 20 x 2 x 0.7 = 28."""
    model = _two_gen_model()
    model["generators"] = model["generators"][:1]
    model["buses"].append({"name": "b1"})
    model["loads"].append({"name": "L1", "bus": "b1", "p_set": 20.0})
    model["links"] = [{"name": "k", "bus0": "b0", "bus1": "b1", "p_nom": 100.0,
                       "marginal_cost": 0.7, "efficiency": 1.0}]
    result = run_pypsa(model, {"discountRate": 0.0}, {})
    costs = {row["label"]: row["value"] for row in result["costBreakdown"]}
    assert costs["Fuel cost"] == 4800
    assert costs["Link operating cost"] == 28


def _pathway_model() -> dict[str, Any]:
    ts = pd.date_range("2030-01-01", periods=3, freq="h")
    periods = [2030, 2040]
    n = pypsa.Network()
    n.set_snapshots(pd.MultiIndex.from_product([periods, ts], names=["period", "timestep"]))
    n.investment_periods = periods
    n.add("Carrier", "gas", co2_emissions=0.4)
    n.add("Bus", "b")
    n.add("Load", "L", bus="b", p_set=[100, 150, 120] * 2)
    n.add("Generator", "gas_old", bus="b", carrier="gas", p_nom=200, marginal_cost=60,
          build_year=2020, lifetime=15)
    n.add("Generator", "gas_new", bus="b", carrier="gas", p_nom_extendable=True, capital_cost=1000,
          marginal_cost=60, build_year=2040, lifetime=30)
    n.add("Generator", "wind40", bus="b", carrier="gas", p_nom=50, marginal_cost=0,
          build_year=2040, lifetime=30, p_max_pu=[0.5, 0.2, 0.8] * 2)
    return network_to_model(n)


def _run_pathway() -> dict[str, Any]:
    opts = {"enableLoadShedding": False, "pathwayConfig": {
        "enabled": True, "snapshotMappingMode": "explicit_period_column",
        "periods": [{"period": p, "objectiveWeight": 10.0, "yearsWeight": 10.0} for p in (2030, 2040)]}}
    return run_pypsa(_pathway_model(), {"carbonPrice": 0.0, "discountRate": 0.0}, opts)


@pytest.fixture(scope="module")
def pathway_result() -> dict[str, Any]:
    return _run_pathway()


def test_rb3_pathway_capacity_counts_only_active_assets(pathway_result: dict[str, Any]) -> None:
    """2030: gas_old (200 MW, built 2020 retires 2035) = 200 MW. 2040: gas_old gone;
    gas_new (p_nom_opt) + wind40 50 MW. The KPI is the largest per-period fleet,
    not the 200 + p_nom_opt + 50 sum over every row."""
    by_period = {s["period"]: s["installedCapacityMw"] for s in pathway_result["pathway"]["summaries"]}
    gas_new = next(e for e in pathway_result["expansionResults"] if e["name"] == "gas_new")
    np.testing.assert_allclose(by_period[2030], 200.0, atol=1e-6)
    np.testing.assert_allclose(by_period[2040], gas_new["p_nom_opt_mw"] + 50.0, atol=1e-6)
    kpi = next(k for k in pathway_result["summary"] if k["label"] == "Generator capacity")
    assert kpi["value"] == f"{round(max(by_period.values())):,} MW"


def test_rb3_pathway_capex_is_period_weighted(pathway_result: dict[str, Any]) -> None:
    """gas_new is active only in 2040: capex_weighted = objective weight 10 x
    capital_cost x p_nom_opt, and 2030 contributes nothing."""
    gas_new = next(e for e in pathway_result["expansionResults"] if e["name"] == "gas_new")
    assert gas_new["active_periods"] == [2040]
    annual = gas_new["capital_cost"] * gas_new["p_nom_opt_mw"]
    np.testing.assert_allclose(gas_new["capex_by_period"]["2040"], annual, rtol=1e-3)
    assert gas_new["capex_by_period"]["2030"] == 0
    np.testing.assert_allclose(gas_new["capex_weighted"], 10.0 * annual, rtol=1e-3)
    capex_row = next(c for c in pathway_result["costBreakdown"] if c["label"].startswith("Capital cost"))
    np.testing.assert_allclose(capex_row["value"], gas_new["capex_weighted"], atol=1.0)


def test_rb3_pathway_cost_breakdown_matches_objective_weighting(pathway_result: dict[str, Any]) -> None:
    """Total of fuel + capex equals the statistics opex+capex (which carry the
    investment-period weightings), i.e. the LP objective."""
    stats = pathway_result["statistics"]
    opex = sum(r["values"].get("Operational Expenditure") or 0.0 for r in stats["rows"] if r["component"] == "Generator")
    fuel = next(c["value"] for c in pathway_result["costBreakdown"] if c["label"] == "Fuel cost")
    np.testing.assert_allclose(fuel, opex, rtol=1e-6)


def test_rb4_pathway_labels_and_statistics_are_period_aware(pathway_result: dict[str, Any]) -> None:
    first = pathway_result["nodalPriceSeries"][0]
    assert first["label"] == "2030-01-01T00:00:00" and first["period"] == 2030
    assert "(" not in first["label"]
    stats = pathway_result["statistics"]
    assert stats["periods"] == [2030, 2040]
    assert all("(" not in c for c in stats["columns"])
    assert {r.get("period") for r in stats["rows"]} == {2030, 2040}
    pf = pathway_result["priceFormation"]
    if pf:
        assert all("(" not in row["snapshot"] for row in pf["series"])


def test_rb4_derived_series_ignores_period_column() -> None:
    """Load 100 MW in two periods: the period year (2030) must not be summed in."""
    rows = [{"period": 2030, "snapshot": "t0", "L": 100.0}, {"period": 2040, "snapshot": "t0", "L": 100.0}]
    out = derive_series(["period", "snapshot", "L"], rows, "snapshot", metric="load", carriers={})
    np.testing.assert_allclose(out["series"][0]["values"], [100.0, 100.0])
    assert out["periods"] == [2030, 2040]


def test_pathway_curtailment_masks_inactive_assets(pathway_result: dict[str, Any]) -> None:
    """wind40 (50 MW, built 2040) cannot curtail in 2030: rows 0-2 are empty."""
    first_period = pathway_result["curtailmentSeries"][:3]
    assert all(r["values"] == {} and r["period"] == 2030 for r in first_period)


def test_capex_window_scale_is_not_prorated_again() -> None:
    """capital_cost x p_nom_opt is the window share when the solve scaled it:
    with scale 0.25 the annual figure is that / 0.25."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2025-01-01", periods=2, freq="h"))
    n.add("Bus", "b")
    n.add("Load", "L", bus="b", p_set=10.0)
    n.add("Generator", "g", bus="b", p_nom_extendable=True, capital_cost=2.0)
    n.optimize(solver_name="highs", include_objective_constant=False)
    plain = build_expansion_results(n)[0]
    np.testing.assert_allclose(plain["capex_annual"], 2.0 * 10.0, atol=1.0)
    n.meta[CAPEX_WINDOW_SCALE_KEY] = 0.25
    scaled = build_expansion_results(n)[0]
    np.testing.assert_allclose(scaled["capex_annual"], 2.0 * 10.0 / 0.25, atol=1.0)


def test_rb10_generator_economics_recovery_uses_unrounded_values() -> None:
    """Carrier recovery = 100 * margin / fixed from raw sums: a 0.4-margin unit
    would round to 0 and make the carrier recovery 0 instead of 80 %."""
    from backend.pypsa.results.market import build_generator_economics

    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2025-01-01", periods=1, freq="h"))
    n.add("Carrier", "x")
    n.add("Bus", "b")
    n.add("Generator", "g", bus="b", carrier="x", p_nom=1.0, marginal_cost=0.0, capital_cost=8760.0 * 0.5)
    n.generators_t.p = pd.DataFrame({"g": [1.0]}, index=n.snapshots)
    n.buses_t.marginal_price = pd.DataFrame({"b": [0.4]}, index=n.snapshots)
    econ = build_generator_economics(n)
    # margin 0.4; fixed horizon = 4380 x 1/8760 = 0.5 -> 80 %
    np.testing.assert_allclose(econ["byCarrier"][0]["recoveryPct"], 80.0, atol=0.05)
    np.testing.assert_allclose(econ["system"]["recoveryPct"], 80.0, atol=0.05)


def test_rb10_derive_from_outputs_keeps_sampling_weights() -> None:
    """A sampled run (2 blocks of 6 from a 48-row window, weight 4) re-derived from
    its stored outputs must keep the weight: carrier energy is identical."""
    from backend.pypsa.results.derive_outputs import derive_results_from_outputs
    from backend.tests.test_sampling import _model as sampling_model

    options = {"snapshotCount": 48, "samplingConfig": {
        "enabled": True, "mode": "count", "blockSize": 6, "blockCount": 2}}
    scenario = {"discountRate": 0.0, "carbonPrice": 0.0}
    model = sampling_model(48)
    fresh = run_pypsa(model, scenario, dict(options))
    derived = derive_results_from_outputs(model, fresh["outputs"], scenario, dict(options))
    assert fresh["runMeta"]["snapshotWeight"] == pytest.approx(4.0)
    np.testing.assert_allclose(
        [m["value"] for m in derived["carrierMix"]],
        [m["value"] for m in fresh["carrierMix"]],
        rtol=1e-6,
    )
    assert derived["runMeta"]["sampling"]["representedSnapshots"] == 48


def test_rb8_export_network_is_the_authored_model() -> None:
    """Export of a model with an extendable asset, carbon price and shedding:
    capital_cost stays the authored overnight value, marginal_cost has no carbon
    adder, no load_shedding_* generators, and a re-export is idempotent."""
    from backend.app.main import RunPayload, _model_payload_to_network

    model = _two_gen_model()
    model["generators"][0].update({"p_nom_extendable": True, "capital_cost": 1000.0, "lifetime": 20.0})
    payload = RunPayload(
        model=model,
        scenario={"carbonPrice": 100.0, "discountRate": 0.05},
        options={"enableLoadShedding": True, "snapshotWeight": 3, "forceLp": True},
    )
    n = _model_payload_to_network(payload)
    assert float(n.generators.at["g", "capital_cost"]) == pytest.approx(1000.0)
    assert float(n.generators.at["g", "marginal_cost"]) == pytest.approx(20.0)
    assert not any(str(g).startswith("load_shedding_") for g in n.generators.index)
    assert len(n.snapshots) == len(SNAPS)
    np.testing.assert_allclose(n.snapshot_weightings["objective"].to_numpy(), 1.0)
