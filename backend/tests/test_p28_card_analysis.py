"""P28 close: the Analytics-card metrics (load factor, coincidence, carrier performance, transition
risk, duration curves, totals) are server values, served by ``GET /api/runs/{name}/analysis/{topic}``.

Reference values are closed form. Model: one bus ``b``, constant 80 MW load for 4 h in each of two
periods (2030, 2040), ``gas_old`` and ``gas_new`` of 100 MW (see ``test_p28_period_views``):

    system energy  = 80 MW * 4 h * 2 periods = 640 MWh   (320 MWh per period)
    load factor    = mean / peak = 80 / 80 = 1,  coincidence = 80 / 80 = 1 (one bus)
    nameplate      = 200 MW whole horizon, 100 MW per period (CF = 0.8 per period)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import results_derived as rd
from backend.app import run_store
from backend.app.main import app
from backend.app.routers import results_derived as rd_router
from backend.pypsa.results.statistics_query import network_from_outputs
from backend.tests.test_p28_period_views import OPTIONS, SCENARIO, solved  # noqa: F401  (fixture)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(run_store, "RUNS_DIR", tmp_path / "runs")
    rd_router._BUNDLE_CACHE.clear()
    rd_router._PERIOD_CACHE.clear()
    return TestClient(app)


@pytest.fixture()
def name(client: TestClient, solved: dict[str, Any]) -> str:  # noqa: F811
    meta = run_store.store_run(solved["model"], dict(SCENARIO), dict(OPTIONS), solved["result"])
    assert meta is not None
    return str(meta["name"])


def _get(client: TestClient, name: str, topic: str, **params: Any) -> dict[str, Any]:
    resp = client.get(f"/api/runs/{name}/analysis/{topic}", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_load_analysis_closed_form_and_statistics(client: TestClient, name: str, solved: dict[str, Any]) -> None:  # noqa: F811
    whole = _get(client, name, "load-analysis")
    np.testing.assert_allclose(whole["systemPeakMw"], 80.0)
    np.testing.assert_allclose(whole["systemEnergyMwh"], 640.0)
    np.testing.assert_allclose(whole["systemLoadFactor"], 1.0)
    np.testing.assert_allclose(whole["coincidenceFactor"], 1.0)
    assert [b["name"] for b in whole["buses"]] == ["b"]
    np.testing.assert_allclose(whole["buses"][0]["share"], 1.0)
    # The per-bus energy is PyPSA's own withdrawal statistic of the Load component.
    network = network_from_outputs(solved["model"], dict(SCENARIO), dict(OPTIONS), solved["result"]["outputs"])
    stat = network.statistics.withdrawal(components=["Load"], groupby="bus", groupby_time=True)
    np.testing.assert_allclose(float(np.asarray(stat).sum()), whole["systemEnergyMwh"], rtol=1e-9)
    # A period is its own slice: half the energy.
    p2040 = _get(client, name, "load-analysis", period=2040)
    np.testing.assert_allclose(p2040["systemEnergyMwh"], 320.0)


def test_load_analysis_two_buses_diversity() -> None:
    """Peaks 100 (t0) and 100 (t1) at different times: system peak 100, sum of peaks 200 -> coincidence 0.5."""
    def bus(name: str, loads: list[float]) -> dict[str, Any]:
        return {"name": name, "netSeries": [{"load": v} for v in loads]}

    out = rd.load_analysis({"a": bus("a", [100.0, 0.0]), "c": bus("c", [0.0, 100.0])}, {"a": 200.0, "c": 200.0}, 4.0)
    np.testing.assert_allclose(out["systemPeakMw"], 100.0)
    np.testing.assert_allclose(out["coincidenceFactor"], 0.5)
    np.testing.assert_allclose(out["systemLoadFactor"], 1.0)  # flat 100 MW system load
    np.testing.assert_allclose(out["systemEnergyMwh"], 400.0)
    np.testing.assert_allclose([b["loadFactor"] for b in out["buses"]], [0.5, 0.5])
    np.testing.assert_allclose([b["share"] for b in out["buses"]], [0.5, 0.5])


def test_load_analysis_without_load_has_no_rows() -> None:
    out = rd.load_analysis({"a": {"name": "a", "netSeries": [{"load": 0.0}]}}, {"a": 0.0}, 1.0)
    assert out["buses"] == [] and out["systemLoadFactor"] is None and out["coincidenceFactor"] is None


def test_carrier_performance_whole_and_period(client: TestClient, name: str) -> None:
    whole = _get(client, name, "carrier-performance")
    (row,) = whole["rows"]
    assert row["carrier"] == "gas" and row["generatorCount"] == 2
    np.testing.assert_allclose(row["nameplateMw"], 200.0)
    np.testing.assert_allclose(row["generatedMw"], 200.0)
    np.testing.assert_allclose(row["energyMwh"], 640.0)
    np.testing.assert_allclose(row["capacityFactor"], 0.8, rtol=1e-3)
    np.testing.assert_allclose(whole["totals"]["energyMwh"], 640.0)
    # 2040: gas_old is retired (no energy), so generated capacity is the 100 MW unit that ran.
    p = _get(client, name, "carrier-performance", period=2040)
    (prow,) = p["rows"]
    np.testing.assert_allclose(prow["energyMwh"], 320.0)
    np.testing.assert_allclose(prow["nameplateMw"], 100.0)  # gas_old (retired 2040) is masked: re-baselined from 200
    np.testing.assert_allclose(prow["generatedMw"], 100.0)


def test_carrier_performance_nameplate_fallback_and_shedding() -> None:
    """p_nom_opt wins over the input p_nom; zero p_nom_opt falls back; load shedding is excluded."""
    result = {
        "runMeta": {"snapshotCount": 4, "snapshotWeight": 1},
        "generatorEnergy": [
            {"name": "w1", "value": 30.0, "carrier": "wind", "curtailmentMwh": 5.0},
            {"name": "g1", "value": 0.0, "carrier": "gas", "curtailmentMwh": None},
            {"name": "load_shedding_b", "value": 9.0, "carrier": "shed"},
        ],
    }
    static = {"generators": [
        {"name": "w1", "carrier": "wind", "p_nom": 10}, {"name": "g1", "carrier": "gas", "p_nom": 50},
        {"name": "load_shedding_b", "carrier": "shed", "p_nom": 1e6},
    ]}
    out = rd.carrier_performance(result, static, {"generators": {"w1": {"p_nom_opt": 25.0}, "g1": {"p_nom_opt": 0.0}}})
    by = {r["carrier"]: r for r in out["rows"]}
    assert set(by) == {"wind", "gas"}
    assert by["wind"]["nameplateMw"] == 25.0 and by["wind"]["curtailmentMwh"] == 5.0
    assert by["gas"]["nameplateMw"] == 50.0 and by["gas"]["generatedMw"] == 0.0 and by["gas"]["curtailmentMwh"] is None
    assert out["totals"]["nameplateMw"] == 75.0 and out["totals"]["curtailmentMwh"] == 5.0
    np.testing.assert_allclose(by["wind"]["generationShare"], 1.0)


STATEMENT = {"currency": "$", "companies": [
    {"company": "A", "revenue": 1000.0, "fuelVomCost": 400.0, "capexAnnual": 100.0, "interest": 50.0, "emissionsTonnes": 2.0},
    {"company": "Clean", "revenue": 500.0, "fuelVomCost": 100.0, "capexAnnual": 100.0, "interest": 0.0, "emissionsTonnes": 0.0},
]}


def test_transition_risk_closed_form() -> None:
    """margin_i = 1000 - 400 - 150 - 2 * 50 * 2^i = 450 - 100 * 2^i  (price doubles each year)."""
    out = rd.transition_risk(STATEMENT, base_year=2030, years=3, base_price=50.0, escalation_pct=100.0)
    a = next(c for c in out["companies"] if c["company"] == "A")
    np.testing.assert_allclose([p["netMargin"] for p in a["byYear"]], [350.0, 250.0, 50.0, -350.0])
    assert a["strandedYear"] == 2033
    np.testing.assert_allclose(a["marginErosion"], 100.0 + 300.0 + 700.0)
    np.testing.assert_allclose(a["baseNetMargin"], 350.0)
    clean = next(c for c in out["companies"] if c["company"] == "Clean")
    assert clean["strandedYear"] is None and clean["marginErosion"] == 0.0
    assert [c["company"] for c in out["companies"]] == ["A", "Clean"]  # most at risk first
    assert out["summary"] == {"companyCount": 2, "strandedCount": 1, "earliestStrandedYear": 2033, "totalMarginAtRisk": 1100.0}
    assert [t["price"] for t in out["trajectory"]] == [50.0, 100.0, 200.0, 400.0]


def test_transition_risk_demand_and_fuel_growth() -> None:
    out = rd.transition_risk(
        STATEMENT, base_year=2030, years=1, base_price=0.0, escalation_pct=0.0,
        demand_growth_pct=10.0, fuel_growth_pct=50.0,
    )
    a = next(c for c in out["companies"] if c["company"] == "A")
    # i=1: revenue 1100, fuel 400 * 1.1 * 1.5 = 660, fixed 150 -> 290
    np.testing.assert_allclose(a["byYear"][1]["netMargin"], 1100.0 - 660.0 - 150.0)


def test_transition_risk_route_errors(client: TestClient, name: str) -> None:
    assert client.get(f"/api/runs/{name}/analysis/transition-risk").status_code == 404  # no owner tags in the fixture
    assert client.get(f"/api/runs/{name}/analysis/nope").status_code == 400
    assert client.get("/api/runs/no_such/analysis/totals").status_code == 404


def test_duration_curve_is_ranked_and_per_period(client: TestClient, name: str) -> None:
    load = _get(client, name, "duration-curve", source="load")
    np.testing.assert_allclose(load["values"], [80.0] * 8)
    assert _get(client, name, "duration-curve", source="load", period=2030)["total"] == 4
    price = _get(client, name, "duration-curve", source="price", period=2040)["values"]  # the system price chart's series
    assert price == sorted(price, reverse=True)
    np.testing.assert_allclose(price, [82.0] * 4)  # gas_new marginal 80 + carbon 0.2 * 10
    assert client.get(f"/api/runs/{name}/analysis/duration-curve?source=x").status_code == 400
    assert rd.duration_curve([3.0, -1.0, 0.0, 5.0], drop_non_positive=True) == [5.0, 3.0]
    assert rd.duration_curve([3.0, -1.0, 5.0], drop_non_positive=False) == [5.0, 3.0, -1.0]


def test_totals_sum_the_result_rows() -> None:
    result = {
        "expansionResults": [
            {"delta_mw": 10.0, "capex_annual": 5.0},
            {"delta_mw": -4.0, "capex_annual": 2.0},
            {"name": "siting_a", "component": "Generator", "bus": "b1", "delta_mw": 6.0, "capex_annual": 3.0},
            {"name": "siting_b", "component": "Generator", "bus": "b1", "delta_mw": 2.0, "capex_annual": 1.0},
            {"name": "siting_c", "component": "Generator", "bus": "b2", "delta_mw": 0.0, "capex_annual": 9.0},
        ],
        "emissionsBreakdown": {"byCarrier": [
            {"carrier": "gas", "emissions_tco2": 300.0, "energy_mwh": 600.0}, {"carrier": "wind", "emissions_tco2": 100.0, "energy_mwh": 400.0},
        ]},
        "companies": {"companies": [{"emissionsTonnes": 3.0}, {"emissionsTonnes": 4.0}], "unassignedEmissionsTonnes": 2.5},
        "companyStatement": {"totals": {"emissionsTonnes": 7.0}, "unassignedEmissionsTonnes": 1.5},
        "companyFinance": {"companies": [{"npv": 10.0}, {"npv": -4.0}]},
        "meritOrder": [{"p_nom": 5.0, "marginal_cost": 30.0}, {"p_nom": 7.0, "marginal_cost": 12.5}],
        "stochastic": {"scenarios": [
            {"weight": 0.25, "totalEnergyMwh": 100.0, "totalEmissionsTco2": 8.0, "totalOperatingCost": 40.0, "loadShedEnergyMwh": 4.0},
            {"weight": 0.75, "totalEnergyMwh": 200.0, "totalEmissionsTco2": 4.0, "totalOperatingCost": 80.0, "loadShedEnergyMwh": 0.0},
        ]},
        "maintenance": {"units": [{"hoursInMaintenance": 6.0}, {"hoursInMaintenance": 2.5}]},
    }
    t = rd.result_totals(result, 12.0)
    assert t["expansion"] == {"newBuildCount": 3, "totalCapexAnnual": 20.0, "totalNewBuildMw": 18.0}
    assert t["siting"] == {
        "builtMwBySiteBus": {"b1": 8.0}, "builtTotalMw": 8.0, "capexAnnual": 4.0, "assets": ["siting_a", "siting_b", "siting_c"],
    }
    np.testing.assert_allclose(t["emissions"]["averageIntensityKgPerMwh"], 400.0 / 1000.0 * 1000)
    assert [c["sharePct"] for c in t["emissions"]["byCarrier"]] == [75.0, 25.0]
    assert t["companies"] == {"ownerEmissionsTonnes": 7.0, "systemEmissionsTonnes": 9.5, "totalNpv": 6.0}
    assert t["statement"] == {"systemEmissionsTonnes": 8.5}
    assert t["meritOrder"] == {"totalMw": 12.0, "systemPeakLoadMw": 12.0, "minMarginalCost": 12.5, "maxMarginalCost": 30.0}
    np.testing.assert_allclose(t["stochastic"]["expectedEnergyMwh"], 175.0)
    np.testing.assert_allclose(t["stochastic"]["expectedEmissionsTco2"], 5.0)
    np.testing.assert_allclose(t["stochastic"]["expectedOperatingCost"], 70.0)
    np.testing.assert_allclose(t["stochastic"]["expectedLoadShedMwh"], 1.0)
    assert t["maintenance"] == {"hoursInMaintenance": 8.5}
    empty = rd.result_totals({})
    assert all(v is None for v in empty.values())


def test_bus_detail_carries_the_mean_nodal_price(client: TestClient, name: str) -> None:
    body = client.get(f"/api/runs/{name}/assets", params={"kind": "buses"}).json()
    np.testing.assert_allclose(body["items"][0]["averageSmp"], (52.0 + 82.0) / 2)
    p = client.get(f"/api/runs/{name}/assets", params={"kind": "buses", "period": 2040}).json()
    np.testing.assert_allclose(p["items"][0]["averageSmp"], 82.0)


def test_setpoint_duals_binding_hours_peak_and_strip() -> None:
    """gas binds at t1 (-12.5), t2 (-30) and t4 (5): weights 2, 2, 2 -> 6 binding hours, peak -30 at t2.

    The hours are the sum of each binding snapshot's own weight: with weights (1, 2, 3, 4, 5) the same pattern binds
    for 2 + 3 + 5 = 10 hours."""
    rows = [
        {"snapshot": "2030-01-01T00:00:00", "gas": 0, "coal": 0},
        {"snapshot": "2030-01-01T01:00:00", "gas": -12.5, "coal": 0},
        {"snapshot": "2030-01-01T02:00:00", "gas": -30, "coal": 0},
        {"snapshot": "2030-01-01T03:00:00", "gas": 0, "coal": 0},
        {"snapshot": "2030-01-01T04:00:00", "gas": 5, "coal": 0},
    ]
    out = rd.setpoint_duals({"generators-mu_ramp_limit_down": rows, "generators-p": rows}, [2.0] * 5)
    assert out["sheets"] == ["generators-mu_ramp_limit_down"]  # only the four dual sheets
    assert out["assetsChecked"] == 2 and out["total"] == 1
    (row,) = out["rows"]
    assert (row["asset"], row["bindingSnapshots"], row["bindingHours"], row["peakShadowPrice"]) == ("gas", 3, 6.0, -30.0)
    assert row["peakAt"] == "2030-01-01T02:00:00"
    np.testing.assert_allclose(row["meanShadowPrice"], (12.5 + 30 + 5) / 3)
    assert row["segments"] == [
        {"on": False, "length": 1}, {"on": True, "length": 2}, {"on": False, "length": 1}, {"on": True, "length": 1},
    ]
    np.testing.assert_allclose(out["bindingHours"], 6.0)
    uneven = rd.setpoint_duals({"generators-mu_ramp_limit_down": rows}, [1.0, 2.0, 3.0, 4.0, 5.0])
    np.testing.assert_allclose(uneven["rows"][0]["bindingHours"], 10.0)
    # Numerical noise is slack; a non-dual sheet is ignored.
    assert rd.summarise_dual_sheet("generators-mu_p_set", [{"snapshot": "a", "g": 1e-9}], [1.0])["rows"] == []
    assert rd.summarise_dual_sheet("generators-p", rows, [1.0]) == {"rows": [], "assetsChecked": 0}


def test_setpoint_duals_route_reads_the_stored_sheet_per_period(client: TestClient, name: str) -> None:
    body = _get(client, name, "setpoint-duals")
    assert body["sheets"] == [] and body["rows"] == [] and body["bindingHours"] == 0  # the fixture has no ramp limits


# ── a pathway whose periods differ: carrier performance masks inactive assets ──────────────────
#
# One bus. 2030: load 80 MW, wind p_max_pu 0.5 (25 MW of 50), ``gas_old`` (100 MW, 50/MWh) built 2030
# with a 10 year life, so it is gone in 2040. 2040: load 120 MW, wind p_max_pu 0.2 (10 MW), and
# ``gas_new`` (150 MW, 80/MWh) built 2040. Four hours per period, snapshot weight 1:
#
#     2030: wind 25 * 4 = 100 MWh, gas_old (80 - 25) * 4 = 220 MWh   -> gas 1 unit, 100 MW
#     2040: wind 10 * 4 =  40 MWh, gas_new (120 - 10) * 4 = 440 MWh  -> gas 1 unit, 150 MW
#     horizon: gas 2 units, 250 MW, 660 MWh; wind 140 MWh, 50 MW

def _differing_pathway() -> dict[str, Any]:
    import logging
    import warnings

    import pandas as pd
    import pypsa

    from backend.pypsa.network.serialize import network_to_model
    from backend.pypsa.results import run_pypsa

    periods = [2030, 2040]
    ts = pd.date_range("2030-01-01", periods=4, freq="h")
    n = pypsa.Network()
    n.set_snapshots(pd.MultiIndex.from_product([periods, ts], names=["period", "timestep"]))
    n.investment_periods = periods
    n.add("Carrier", ["gas", "wind"], co2_emissions=[0.2, 0.0])
    n.add("Bus", "b")
    n.add("Load", "L", bus="b", p_set=pd.Series([80.0] * 4 + [120.0] * 4, index=n.snapshots))
    n.add("Generator", "wind", bus="b", carrier="wind", p_nom=50, marginal_cost=0.0, build_year=2030, lifetime=30,
          p_max_pu=pd.Series([0.5] * 4 + [0.2] * 4, index=n.snapshots))
    n.add("Generator", "gas_old", bus="b", carrier="gas", p_nom=100, marginal_cost=50.0, build_year=2030, lifetime=10)
    n.add("Generator", "gas_new", bus="b", carrier="gas", p_nom=150, marginal_cost=80.0, build_year=2040, lifetime=30)
    model = network_to_model(n)
    scenario = {"carbonPrice": 10.0, "discountRate": 0.05}
    options = {**OPTIONS}
    logging.disable(logging.CRITICAL)
    warnings.simplefilter("ignore")
    try:
        result = run_pypsa(model, dict(scenario), dict(options))
    finally:
        logging.disable(logging.NOTSET)
    return {"model": model, "scenario": scenario, "options": options, "result": result}


@pytest.fixture(scope="module")
def differing() -> dict[str, Any]:
    return _differing_pathway()


def test_carrier_performance_masks_assets_inactive_in_the_period(client: TestClient, differing: dict[str, Any]) -> None:
    """Re-baselined: a period view used to sum the nameplate of every installed unit (250 MW of gas in
    both periods); a unit not yet built or already retired now contributes 0, as in the other period views."""
    meta = run_store.store_run(differing["model"], differing["scenario"], differing["options"], differing["result"])
    name = str(meta["name"])
    by_period = {p: {r["carrier"]: r for r in _get(client, name, "carrier-performance", period=p)["rows"]} for p in (2030, 2040)}
    # Energy differs between the periods, so a period view that leaked the other period would show it.
    np.testing.assert_allclose(by_period[2030]["gas"]["energyMwh"], 220.0)
    np.testing.assert_allclose(by_period[2040]["gas"]["energyMwh"], 440.0)
    np.testing.assert_allclose(by_period[2030]["wind"]["energyMwh"], 100.0)
    np.testing.assert_allclose(by_period[2040]["wind"]["energyMwh"], 40.0)
    # Nameplate and count: only the unit that exists in the period.
    assert (by_period[2030]["gas"]["generatorCount"], by_period[2030]["gas"]["nameplateMw"]) == (1, 100.0)
    assert (by_period[2040]["gas"]["generatorCount"], by_period[2040]["gas"]["nameplateMw"]) == (1, 150.0)
    np.testing.assert_allclose(by_period[2040]["gas"]["generatedMw"], 150.0)
    np.testing.assert_allclose(by_period[2030]["gas"]["capacityShare"], 100.0 / 150.0)
    np.testing.assert_allclose(by_period[2040]["gas"]["capacityShare"], 150.0 / 200.0)
    # The horizon keeps every installed unit.
    whole = {r["carrier"]: r for r in _get(client, name, "carrier-performance")["rows"]}
    assert (whole["gas"]["generatorCount"], whole["gas"]["nameplateMw"]) == (2, 250.0)
    np.testing.assert_allclose(whole["gas"]["energyMwh"], 660.0)
    np.testing.assert_allclose(whole["wind"]["energyMwh"], 140.0)
    # The periods add up to the horizon for energy.
    np.testing.assert_allclose(
        sum(by_period[p]["gas"]["energyMwh"] for p in by_period), whole["gas"]["energyMwh"])


def test_active_in_period_rule() -> None:
    row = {"build_year": 2030, "lifetime": 10}
    assert [rd._active_in_period(row, p) for p in (2020, 2030, 2039, 2040)] == [False, True, True, False]
    assert rd._active_in_period({}, 1999)  # blank build year 0, unlimited life
    assert rd._active_in_period({"build_year": 0, "lifetime": float("inf")}, 2100)
    assert not rd._active_in_period({"build_year": 0, "active": False}, 2030)
