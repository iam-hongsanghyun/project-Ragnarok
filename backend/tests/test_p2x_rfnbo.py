"""RFNBO matching (Delegated Regulation (EU) 2023/1184) on a toy network.

Toy: 20 MW demand, wind (30 EUR/MWh, daytime only) and cheaper gas (20 EUR/MWh). A 30 MW electrolyser with a
flat 5 MW_LHV hydrogen offtake and an extendable tank.

* no matching: the electrolyser runs on gas at night;
* hourly matching: electrolyser power <= wind output in EVERY snapshot (exactly), so no night operation;
* monthly matching: only the monthly energy must match, so it is looser (no storage needed, lower cost).
"""
from __future__ import annotations

import numpy as np
import pytest
from fastapi import HTTPException
from numpy.testing import assert_allclose

from backend.app.run_options_reference import documented_paths
from backend.pypsa.network import rfnbo as rf
from backend.pypsa.results import run_pypsa

from ._p2x_fixtures import H2_SPEC, SCENARIO, night_gas_network, series, with_chain

HOURLY = {"rfnboConfig": {"enabled": True, "temporal": "hourly"}}
MONTHLY = {"rfnboConfig": {"enabled": True, "temporal": "monthly"}}
NIGHT = [i for i in range(48) if not 8 <= i % 24 < 20]


def _solve(options: dict, **net):
    model, _ = with_chain(night_gas_network(**net), H2_SPEC)
    return model, run_pypsa(model, SCENARIO, options)


def _total_cost(model, result) -> float:
    """The run's objective as the app reports it (operating + capital + FOM lines of ``costBreakdown``; PyPSA's own native-cost split)."""
    return float(sum(r["value"] for r in result["costBreakdown"]))


def test_without_matching_the_electrolyser_runs_on_grid_gas_at_night() -> None:
    _, res = _solve({})
    p0 = np.array(series(res, "links-p0", "p2x_electrolyser"))
    wind = np.array(series(res, "generators-p", "wind"))
    assert p0[NIGHT].sum() > 10.0                 # night operation on gas
    assert_allclose(wind.sum(), 0.0, atol=1e-6)   # wind (30) is never dispatched: gas (20) is cheaper


def test_hourly_matching_holds_exactly_in_every_snapshot() -> None:
    model, res = _solve(HOURLY)
    p0 = np.array(series(res, "links-p0", "p2x_electrolyser"))
    wind = np.array(series(res, "generators-p", "wind"))
    assert_allclose(p0[NIGHT], 0.0, atol=1e-9)
    assert (p0 - wind).max() <= 1e-9              # electrolyser <= designated output, per snapshot
    assert_allclose(np.minimum(p0, wind), p0, rtol=0, atol=1e-9)
    # the hydrogen demand is still met in full: 5 MW x 48 h = 240 MWh_LHV
    eff = model["links"][0]["efficiency"]
    assert_allclose(p0.sum() * eff, 5.0 * 48, rtol=1e-6)


def test_monthly_matching_is_looser_than_hourly() -> None:
    model_h, res_h = _solve(HOURLY)
    model_m, res_m = _solve(MONTHLY)
    p0_m = np.array(series(res_m, "links-p0", "p2x_electrolyser"))
    wind_m = np.array(series(res_m, "generators-p", "wind"))
    # monthly: energy matches over the month, but night operation is allowed
    assert p0_m[NIGHT].sum() > 10.0
    assert_allclose(p0_m.sum(), wind_m.sum(), rtol=1e-6)         # binding: electrolyser energy == designated energy
    assert p0_m.sum() <= wind_m.sum() * (1 + 1e-9)
    # looser => no more expensive; here strictly cheaper because no tank is needed
    cost_h, cost_m = _total_cost(model_h, res_h), _total_cost(model_m, res_m)
    assert cost_m < cost_h - 1.0
    assert res_m["outputs"]["static"]["stores"]["p2x_h2_store"]["e_nom_opt"] < res_h["outputs"]["static"]["stores"]["p2x_h2_store"]["e_nom_opt"]


def test_period_keys_hourly_monthly_and_auto() -> None:
    idx = ["2029-12-31T23:00:00", "2030-01-01T00:00:00", "2030-01-01T01:00:00", "2030-01-31T23:00:00"]
    assert rf.period_keys(idx, "hourly", "2030-01-01") == [0, 1, 2, 3]
    assert rf.period_keys(idx, "monthly", "2030-01-01") == [("m", 2029, 12), ("m", 2030, 1), ("m", 2030, 1), ("m", 2030, 1)]
    # Art. 6(1)/(2): monthly until 31 Dec 2029, hourly from 1 Jan 2030
    assert rf.period_keys(idx, "auto", "2030-01-01") == [("m", 2029, 12), 1, 2, 3]


def test_enabled_matching_without_electrolyser_or_eligible_generator_is_refused() -> None:
    plain = night_gas_network()
    with pytest.raises(HTTPException) as exc:
        run_pypsa(plain, SCENARIO, HOURLY)
    assert exc.value.status_code == 400 and "no electrolyser" in exc.value.detail
    model, _ = with_chain(night_gas_network(build_year=2020), H2_SPEC)   # wind older than 36 months
    opts = {"rfnboConfig": {"enabled": True, "enforceAdditionality": True}}
    with pytest.raises(HTTPException) as exc2:
        run_pypsa(model, SCENARIO, opts)
    assert exc2.value.status_code == 400 and "no designated renewable generator is eligible" in exc2.value.detail


def test_additionality_is_a_check_and_a_candidate_filter_not_an_lp_constraint() -> None:
    model, _ = with_chain(night_gas_network(build_year=2028), H2_SPEC)
    cfg = rf.normalise_config({"enabled": True})
    sets = rf.resolve_sets(model, cfg)
    assert sets["electrolysers"] == ["p2x_electrolyser"] and sets["designated"] == ["wind"]
    [row] = rf.check_additionality(model, cfg, sets)
    assert row["status"] == "pass" and row["buildYear"] == 2028 and row["electrolyserYear"] == 2030  # 24 months before: within 36
    old, _ = with_chain(night_gas_network(build_year=2026), H2_SPEC)
    [bad] = rf.check_additionality(old, cfg, rf.resolve_sets(old, cfg))
    assert bad["status"] == "fail"                                                                      # 48 months before
    # without enforcement the failing generator is still in the matching set (check only)
    plan = rf.resolve_plan(old, {"enabled": True})
    assert plan is not None and plan["designated"] == ["wind"]
    # with enforcement it is filtered out
    with pytest.raises(ValueError, match="eligible"):
        rf.resolve_plan(old, {"enabled": True, "enforceAdditionality": True})


def test_extendable_designated_generator_without_build_year_is_new() -> None:
    base = night_gas_network(build_year=None)
    base["generators"][0].update({"p_nom_extendable": True, "p_nom": 0, "capital_cost": 1000.0})
    model, _ = with_chain(base, H2_SPEC)
    cfg = rf.normalise_config({"enabled": True, "enforceAdditionality": True})
    [row] = rf.check_additionality(model, cfg, rf.resolve_sets(model, cfg))
    assert row["status"] == "pass" and "built in this run" in row["reason"]
    fixed, _ = with_chain(night_gas_network(build_year=None), H2_SPEC)   # fixed, no vintage -> unknown
    [unk] = rf.check_additionality(fixed, cfg, rf.resolve_sets(fixed, cfg))
    assert unk["status"] == "unknown"


def test_geographic_correlation_same_bus_zone_column_or_unknown() -> None:
    base = night_gas_network()
    base["buses"] = [{"name": "grid", "carrier": "AC", "country": "DE"}, {"name": "north", "carrier": "AC", "country": "DK"}]
    base["generators"].append({"name": "wind_dk", "bus": "north", "carrier": "wind", "p_nom": 10, "marginal_cost": 30, "build_year": 2030})
    spec = {**H2_SPEC, "designatedGenerators": ["wind", "wind_dk"]}
    model, _ = with_chain(base, spec)
    cfg = rf.normalise_config({"enabled": True})
    rows = {r["generator"]: r for r in rf.check_geography(model, cfg, rf.resolve_sets(model, cfg))}
    assert rows["wind"]["status"] == "pass" and rows["wind_dk"]["status"] == "fail"
    kept, _rep = rf.eligible_generators(model, {**cfg, "enforceGeographic": True}, rf.resolve_sets(model, cfg))
    assert kept == ["wind"]
    # no zone column: different buses -> cannot be read
    nozone = night_gas_network()
    nozone["buses"].append({"name": "north", "carrier": "AC"})
    nozone["generators"].append({"name": "wind2", "bus": "north", "carrier": "wind", "p_nom": 10, "marginal_cost": 30})
    m2, _ = with_chain(nozone, {**H2_SPEC, "designatedGenerators": ["wind2"]})
    [r2] = rf.check_geography(m2, cfg, rf.resolve_sets(m2, cfg))
    assert r2["status"] == "unknown"


def test_compliance_table_hand_numbers() -> None:
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(4)]
    ely = np.array([10.0, 10.0, 0.0, 6.0])      # MW
    des = np.array([10.0, 4.0, 8.0, 6.0])
    w = np.ones(4)
    out = rf.compliance(snaps, ely, des, w)
    # hourly: hour 1 is short by 6 MWh; hours 0 and 3 comply; hour 2 is idle
    assert out["hourly"]["operatingPeriods"] == 3 and out["hourly"]["compliantOperatingPeriods"] == 2
    assert_allclose(out["hourly"]["unmatchedMwh"], 6.0, rtol=0, atol=1e-12)
    assert_allclose(out["hourly"]["compliantShareOfOperating"], 2 / 3, rtol=1e-12)
    # monthly: 26 MWh consumed vs 28 MWh designated in the month -> complies
    assert_allclose(out["monthly"]["unmatchedMwh"], 0.0, atol=1e-12)
    assert out["monthly"]["compliantShareOfOperating"] == 1.0
    assert_allclose(out["hourly"]["matchedMwh"], 20.0, rtol=1e-12)
    # Art. 6(3): hours at or below 20 EUR/MWh are compliant whatever the matching
    out2 = rf.compliance(snaps, ely, des, w, np.array([50.0, 15.0, 15.0, 50.0]), {"enabled": True})
    assert out2["art63"]["operatingPeriodsAtOrBelow"] == 1
    assert_allclose(out2["art63"]["unmatchedMwhHourlyAfterRule"], 0.0, atol=1e-12)


def test_grid_alternatives_are_reported_only() -> None:
    cfg = rf.normalise_config({"enabled": True})
    out = rf.grid_alternatives(res_energy_mwh=950.0, total_energy_mwh=1000.0, emissions_t=10.0, load_mwh=1000.0, cfg=cfg,
                               electrolyser_hours=7000.0, hours=8760.0)
    assert out["art41"]["pass"] is True
    assert_allclose(out["art41"]["maxFullLoadHours"], 8760 * 0.95, rtol=1e-12)
    # 10 t / 1000 MWh = 0.01 t/MWh = 2.7778 gCO2/MJ < 18
    assert_allclose(out["art42"]["emissionIntensityGPerMj"], 0.01 * 1e6 / 3600, rtol=1e-12)
    assert out["art42"]["pass"] is True


def test_rfnbo_options_are_documented_for_describe_run_options() -> None:
    from backend.app.routers import p2x  # noqa: F401  (registers the options on import)

    paths = documented_paths()
    for key in ("options.rfnboConfig", "options.rfnboConfig.enabled", "options.rfnboConfig.temporal",
                "options.rfnboConfig.designatedGenerators", "options.rfnboConfig.enforceAdditionality",
                "options.rfnboConfig.enforceGeographic", "options.rfnboConfig.gridAlternatives.intensityThresholdGPerMj"):
        assert key in paths
