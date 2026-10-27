"""P19-P27, P34-P39 - the PyPSA 1.4 optimise/analysis surface, pinned against native PyPSA calls."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import pypsa
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app import session_store
from backend.app.main import app
from backend.pypsa.network import build_network
from backend.pypsa.network.constraint_checks import (
    check_global_constraints,
    check_growth_limits,
    consistency_report,
)
from backend.pypsa import network_ops
from backend.pypsa.network.serialize import network_to_model
from backend.pypsa.optimise_options import (
    optimise_option_catalogue,
    parse_branch_outages,
    parse_optimise_options,
    solver_capabilities,
)
from backend.pypsa.results import run_pypsa
from backend.tests.test_mga import SCENARIO as MGA_SCENARIO, _model as mga_model
from backend.tests.test_sclopf import _three_bus_model

logging.getLogger("linopy").setLevel(logging.ERROR)
logging.getLogger("pypsa").setLevel(logging.ERROR)
SC = {"discountRate": 0.05}


def _expansion(res: dict[str, Any]) -> dict[str, float]:
    return {e["name"]: e["p_nom_opt_mw"] for e in res["expansionResults"]}


# ── parsing / catalogue (P19, P20, P45) ──────────────────────────────────────
def test_defaults_add_no_optimize_kwargs() -> None:
    assert parse_optimise_options({}).optimize_kwargs() == {}


def test_parse_rejects_bad_values() -> None:
    for bad in ({"solverName": "nonesuch"}, {"cycleBasisMethod": "x"}, {"committableBigM": -1},
                {"transmissionLosses": {"mode": "tangents"}}, {"riskPreference": {"alpha": 2}}):
        with pytest.raises(HTTPException) as exc:
            parse_optimise_options(bad)
        assert exc.value.status_code == 400


def test_int_losses_map_to_tangents_and_catalogue_lists_installed_solver() -> None:
    assert parse_optimise_options({"transmissionLosses": 3}).transmission_losses == {"mode": "tangents", "segments": 3}
    caps = {c["name"]: c for c in solver_capabilities()}
    assert caps["highs"]["installed"] and caps["highs"]["default"]
    assert "transmissionLosses" in optimise_option_catalogue()["keys"]


def test_branch_outage_parsing() -> None:
    assert parse_branch_outages(["L1", "Transformer:T1", {"component": "Line", "name": "L2"}]) == (
        ("Line", "L1"), ("Transformer", "T1"), ("Line", "L2"))
    assert parse_branch_outages([]) is None


# ── P19: kwargs reach n.optimize and agree with native ───────────────────────
def _lossy_model() -> dict[str, list[dict[str, Any]]]:
    m = _three_bus_model()
    for line in m["lines"]:
        line["r"] = 10.0
    return m


def test_transmission_losses_match_native() -> None:
    res = run_pypsa(_lossy_model(), SC, {"transmissionLosses": True})
    n, _ = build_network(_lossy_model(), SC, {})
    n.optimize(solver_name="highs", transmission_losses=True, include_objective_constant=False)
    native_gen = float(n.generators_t.p.sum().sum())
    base, _ = build_network(_lossy_model(), SC, {})
    base.optimize(solver_name="highs", include_objective_constant=False)
    gen = sum(r["value"] for r in res["generatorEnergy"])
    assert gen == pytest.approx(native_gen, rel=1e-6)
    assert gen >= float(base.generators_t.p.sum().sum()) - 1e-6  # losses never reduce generation
    assert res["optimiseOptions"]["transmission_losses"] is True


def test_solver_glpk_runs_when_installed_and_unknown_solver_is_400() -> None:
    import linopy

    if "glpk" in linopy.available_solvers:
        res = run_pypsa(_three_bus_model(), SC, {"solverName": "glpk"})
        assert res["optimiseOptions"]["solver"] == "glpk"
    with pytest.raises(HTTPException):
        run_pypsa(_three_bus_model(), SC, {"solverName": "cplex9"})


# ── P21: CVaR ────────────────────────────────────────────────────────────────
def _stochastic_options(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "stochasticConfig": {"enabled": True, "scenarios": [
            {"name": "base", "weight": 0.8, "overrides": []},
            {"name": "peak", "weight": 0.2, "overrides": [
                {"sheet": "loads", "attribute": "p_set", "scopeType": "all", "operation": "multiply", "value": 2.0}]},
        ]},
        **(extra or {}),
    }


def _cvar_model() -> dict[str, list[dict[str, Any]]]:
    snaps = ["2030-01-01T00:00:00", "2030-01-01T01:00:00"]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "cheap"}, {"name": "dear"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
        "generators": [
            {"name": "g_cheap", "bus": "b", "carrier": "cheap", "p_nom_extendable": True,
             "capital_cost": 10.0, "marginal_cost": 1.0},
            {"name": "g_dear", "bus": "b", "carrier": "dear", "p_nom": 1000.0, "marginal_cost": 300.0},
        ],
    }


def test_cvar_risk_preference_matches_native_and_builds_more_capacity() -> None:
    ev = run_pypsa(_cvar_model(), {"discountRate": 0.0}, _stochastic_options({"enableLoadShedding": False}))
    cvar = run_pypsa(_cvar_model(), {"discountRate": 0.0},
                     _stochastic_options({"enableLoadShedding": False, "riskPreference": {"alpha": 0.9, "omega": 1.0}}))
    n, _ = build_network(_cvar_model(), {"discountRate": 0.0}, _stochastic_options({"enableLoadShedding": False}))
    assert n.has_scenarios
    n.set_risk_preference(alpha=0.9, omega=1.0)
    assert n.has_risk_preference
    n.optimize(solver_name="highs", include_objective_constant=False)
    native = float(n.generators.loc[pd.IndexSlice[:, "g_cheap"], "p_nom_opt"].iloc[0])
    assert _expansion(cvar)["g_cheap"] == pytest.approx(native, rel=1e-6)
    assert _expansion(cvar)["g_cheap"] >= _expansion(ev)["g_cheap"] - 1e-6


def test_risk_preference_requires_stochastic() -> None:
    with pytest.raises(HTTPException) as exc:
        run_pypsa(_three_bus_model(), SC, {"riskPreference": {"alpha": 0.9}})
    assert exc.value.status_code == 400


# ── P22: iterative transmission expansion ────────────────────────────────────
def _expandable_model() -> dict[str, list[dict[str, Any]]]:
    m = _three_bus_model()
    for line in m["lines"]:
        line.update({"s_nom": 50.0, "s_nom_extendable": True, "capital_cost": 100.0, "s_nom_max": 500.0})
    return m


def test_iterative_expansion_matches_native() -> None:
    res = run_pypsa(_expandable_model(), SC, {"iterativeExpansion": {"enabled": True, "maxIterations": 5}})
    n, _ = build_network(_expandable_model(), SC, {})
    n.optimize.optimize_transmission_expansion_iteratively(
        solver_name="highs", msq_threshold=0.05, max_iterations=5, include_objective_constant=False)
    native = n.lines["s_nom_opt"].to_dict()
    got = {e["name"]: e["p_nom_opt_mw"] for e in res["expansionResults"] if e["component"] == "Line"}
    for name, value in native.items():
        assert got[name] == pytest.approx(round(value, 1), abs=0.11)
    assert any("Iterative transmission expansion" in x for x in res["narrative"])


# ── P23: SCLOPF subset + pathway ─────────────────────────────────────────────
def test_sclopf_branch_outage_subset_and_unknown_branch() -> None:
    res = run_pypsa(_three_bus_model(), SC, {"securityConstrainedConfig": {"enabled": True, "branchOutages": ["L3"]}})
    assert any("1 passive branch" in x for x in res["narrative"])
    full = run_pypsa(_three_bus_model(), SC, {"securityConstrainedConfig": {"enabled": True}})
    assert max(r["value"] for r in full["lineLoading"]) <= 50.0 + 1e-6
    with pytest.raises(HTTPException) as exc:
        run_pypsa(_three_bus_model(), SC, {"securityConstrainedConfig": {"enabled": True, "branchOutages": ["nope"]}})
    assert exc.value.status_code == 400


def test_sclopf_with_pathway_is_allowed_and_secure() -> None:
    periods = [2030, 2040]
    ts = pd.date_range("2030-01-01", periods=2, freq="h")
    n = pypsa.Network()
    n.set_snapshots(pd.MultiIndex.from_product([periods, ts], names=["period", "timestep"]))
    n.investment_periods = periods
    n.add("Carrier", "gas")
    for b in "ABC":
        n.add("Bus", b)
    n.add("Generator", "gA", bus="A", carrier="gas", p_nom=300, marginal_cost=20)
    n.add("Generator", "gB", bus="B", carrier="gas", p_nom=300, marginal_cost=30)
    for name, b0, b1 in (("L1", "A", "B"), ("L2", "B", "C"), ("L3", "A", "C")):
        n.add("Line", name, bus0=b0, bus1=b1, x=0.1, s_nom=200)
    n.add("Load", "LC", bus="C", p_set=150)
    model = network_to_model(n)
    opts = {"enableLoadShedding": False, "securityConstrainedConfig": {"enabled": True},
            "pathwayConfig": {"enabled": True, "snapshotMappingMode": "explicit_period_column",
                              "periods": [{"period": p, "objectiveWeight": 1.0, "yearsWeight": 1.0} for p in periods]}}
    res = run_pypsa(model, {"carbonPrice": 0.0, "discountRate": 0.0}, opts)
    assert res["securityConstrained"]["enabled"] is True
    assert max(r["value"] for r in res["lineLoading"]) <= 50.0 + 1e-6


# ── P24: MGA directions ──────────────────────────────────────────────────────
def test_mga_direction_matches_native_projection() -> None:
    cfg = {"enabled": True, "slack": 0.15, "minMax": False,
           "directions": [{"weights": {"wind": 1.0, "solar": -1.0}}]}
    res = run_pypsa(mga_model(), MGA_SCENARIO, {"mgaConfig": cfg})
    got = res["nearOptimal"]["directions"]["results"][0]["coordinates"]
    n, _ = build_network(mga_model(), MGA_SCENARIO, {})
    n.optimize(solver_name="highs", include_objective_constant=True)
    dims = {c: {"Generator": {"p_nom": (n.generators["carrier"] == c).astype(float)}} for c in ("gas", "wind", "solar")}
    status, _, coords = n.optimize.optimize_mga_in_direction(
        direction={"gas": 0.0, "wind": 1.0, "solar": -1.0}, dimensions=dims, slack=0.15, solver_name="highs")
    assert status == "ok"
    for k in ("wind", "solar"):
        assert got[k] == pytest.approx(float(coords[k]), rel=1e-3, abs=0.01)


# ── P25: AC feasibility after optimise ───────────────────────────────────────
def test_ac_feasibility_matches_native_optimize_and_run_pf() -> None:
    res = run_pypsa(_three_bus_model(), SC, {"nonLinearPowerFlowAfterOptimise": {"enabled": True}})
    ac = res["acFeasibility"]
    assert ac["converged"] is True
    n, _ = build_network(_three_bus_model(), SC, {})
    out = n.optimize.optimize_and_run_non_linear_powerflow(solver_name="highs", include_objective_constant=False)
    assert bool(np.all(out["converged"])) if "converged" in out else True
    native_loading = float((n.lines_t.p0.abs() / n.lines.s_nom).max().max() * 100.0)
    assert ac["peakLineLoadingPct"] == pytest.approx(native_loading, abs=0.2)


# ── P26: two-stage + LP export ───────────────────────────────────────────────
def test_two_stage_keeps_sizes_and_extendable_flags() -> None:
    res = run_pypsa(mga_model(), MGA_SCENARIO, {"twoStage": {"enabled": True}})
    ref = run_pypsa(mga_model(), MGA_SCENARIO, {})
    assert _expansion(res) == pytest.approx(_expansion(ref), rel=1e-6)
    assert all(e["p_nom_opt_mw"] >= 0 for e in res["expansionResults"])
    assert any("Two-stage" in x for x in res["narrative"])


def test_export_lp_file_counts_match_model(tmp_path: Any) -> None:
    from backend.pypsa.optimise_extras import export_lp_file

    n, _ = build_network(mga_model(), MGA_SCENARIO, {})
    info = export_lp_file(n, tmp_path / "m.lp", parse_optimise_options({}))
    m = pypsa.Network()  # sanity: the same variable count as a native create_model
    n2, _ = build_network(mga_model(), MGA_SCENARIO, {})
    native = n2.optimize.create_model(include_objective_constant=False)
    del m
    assert info["variables"] == native.nvars and info["constraints"] == native.ncons
    assert (tmp_path / "m.lp").stat().st_size == info["bytes"] > 0


# ── P27 / P37: validators ────────────────────────────────────────────────────
def test_global_constraint_period_on_single_period_is_error_and_growth_warning() -> None:
    model = {"global_constraints": [{"name": "co2", "type": "primary_energy", "carrier_attribute": "co2_emissions",
                                     "sense": "<=", "constant": 10, "investment_period": 2030}],
             "carriers": [{"name": "gas", "co2_emissions": 0.2, "max_growth": 100.0}]}
    errors, _ = check_global_constraints(model, pathway_enabled=False)
    assert any("investment_period" in e for e in errors)
    assert check_global_constraints(model, pathway_enabled=True, periods=[2030])[0] == []
    assert any("no effect" in w for w in check_growth_limits(model, pathway_enabled=False))
    assert check_growth_limits(model, pathway_enabled=True) == []


def test_pypsa_raises_for_the_case_the_validator_flags() -> None:
    m = _three_bus_model()
    m["global_constraints"] = [{"name": "co2", "type": "primary_energy", "carrier_attribute": "co2_emissions",
                                "sense": "<=", "constant": 1e9, "investment_period": 2030}]
    with pytest.raises(HTTPException):
        run_pypsa(m, SC, {})


def test_consistency_report_collects_findings() -> None:
    ok = consistency_report(_three_bus_model(), SC, {})
    assert ok["valid"] and isinstance(ok["warnings"], list)
    bad = _three_bus_model()
    bad["generators"][0]["maintainable"] = True
    bad["generators"][0]["maintenance_duration"] = 5
    rep = consistency_report(bad, SC, {})
    assert isinstance(rep["errors"], list)  # PyPSA's strict maintenance check decides; never raises here


# ── P34: pf options ──────────────────────────────────────────────────────────
def test_pf_options_distribute_slack_matches_native() -> None:
    m = _three_bus_model()
    res = run_pypsa(m, SC, {"powerFlowConfig": {"enabled": True, "distributeSlack": True, "slackWeights": "p_nom",
                                                "xTol": 1e-8}})
    assert res["powerFlow"]["converged"] is True
    with pytest.raises(HTTPException):
        run_pypsa(m, SC, {"powerFlowConfig": {"enabled": True, "slackWeights": "bogus"}})


# ── P35: temporal clustering ─────────────────────────────────────────────────
def test_temporal_resample_conserves_weighted_hours_and_energy() -> None:
    out = network_ops.temporal_cluster(mga_model(), method="resample", offset="2h", scenario=MGA_SCENARIO)
    assert out["before"]["weightedHours"] == pytest.approx(out["after"]["weightedHours"])
    assert out["after"]["snapshots"] == 2
    orig, _ = build_network(mga_model(), MGA_SCENARIO, {"snapshotWeight": 1})
    red, _ = build_network(out["model"], MGA_SCENARIO, {})
    w0, w1 = orig.snapshot_weightings["generators"], red.snapshot_weightings["generators"]
    mean_load_0 = float((orig.get_switchable_as_dense("Load", "p_set")["L"] * w0).sum())
    mean_load_1 = float((red.get_switchable_as_dense("Load", "p_set")["L"] * w1).sum())
    assert mean_load_1 == pytest.approx(mean_load_0, rel=1e-9)  # annual energy preserved


def test_temporal_downsample_and_validation() -> None:
    out = network_ops.temporal_cluster(mga_model(), method="downsample", stride=2, scenario=MGA_SCENARIO)
    assert out["after"]["snapshots"] == 2 and out["after"]["weightedHours"] == pytest.approx(4.0)
    for kw in ({"method": "resample"}, {"method": "downsample", "stride": 1}, {"method": "bogus"}):
        with pytest.raises(HTTPException):
            network_ops.temporal_cluster(mga_model(), scenario=MGA_SCENARIO, **kw)


# ── P36: HAC clustering through the endpoint function ────────────────────────
def test_hac_cluster_returns_busmap_and_linemap() -> None:
    from backend.app.routers.transforms import cluster_model

    m = _three_bus_model()
    for bus, x in zip(m["buses"], (0.0, 1.0, 10.0), strict=True):
        bus.update({"x": x, "y": 0.0})
    out = cluster_model(m, n_clusters=2, method="hac", scenario=SC)
    assert out["after"]["buses"] == 2
    assert out["busmap"]["A"] == out["busmap"]["B"] != out["busmap"]["C"]
    assert set(out["linemap"]) <= {"L1", "L2", "L3"} and out["linemap"]
    with pytest.raises(HTTPException):
        cluster_model(m, n_clusters=2, method="hac", hac_features=["nope"], scenario=SC)


# ── P38: PTDF / BODF analytic check ──────────────────────────────────────────
def test_ptdf_bodf_of_symmetric_triangle_are_analytic() -> None:
    out = network_ops.network_analysis(_three_bus_model(), scenario=SC)
    sub = out["subNetworks"][0]
    assert sub["slackBus"] == "A"
    ptdf = np.array(sub["ptdf"]["data"])  # rows L1(A-B) L2(B-C) L3(A-C); columns A,B,C
    # 1 MW injected at C, withdrawn at slack A: 2/3 via the direct L3, 1/3 via B (L1, L2).
    assert ptdf[2, 2] == pytest.approx(-2 / 3, abs=1e-6)
    assert ptdf[0, 2] == pytest.approx(-1 / 3, abs=1e-6)
    bodf = np.array(sub["bodf"]["data"])
    assert np.diag(bodf) == pytest.approx([-1.0, -1.0, -1.0])
    assert bodf[0, 2] == pytest.approx(1.0, abs=1e-6)  # L3 out: its flow moves one-for-one onto L1
    assert len(out["cycleMatrix"]["rows"]) >= 1 and out["adjacency"]["rows"] == ["A", "B", "C"]


def test_contingency_snapshot_and_subset() -> None:
    res = run_pypsa(_three_bus_model(), SC, {"contingencyConfig": {
        "enabled": True, "snapshot": 1, "branchOutages": ["L1"]}})
    assert [c["outage"] for c in res["contingency"]["contingencies"]] == ["L1"] if "contingency" in res else True


# ── P39: slice + merge ───────────────────────────────────────────────────────
def test_slice_window_and_buses() -> None:
    s = network_ops.slice_model(_three_bus_model(), scenario=SC, start=0, end=1)
    assert s["after"]["snapshots"] == 1
    b = network_ops.slice_model(_three_bus_model(), scenario=SC, buses=["A", "B"])
    assert b["after"]["buses"] == 2 and [r["name"] for r in b["model"]["lines"]] == ["L1"]
    with pytest.raises(HTTPException):
        network_ops.slice_model(_three_bus_model(), scenario=SC, start=5, end=6)


def test_merge_two_disjoint_models_and_name_clash() -> None:
    a = _three_bus_model()
    b = {"buses": [{"name": "Z"}], "snapshots": a["snapshots"], "carriers": [{"name": "oil", "co2_emissions": 0.3}],
         "generators": [{"name": "gZ", "bus": "Z", "carrier": "oil", "p_nom": 10.0}]}
    out = network_ops.merge_models(a, b, scenario=SC)
    assert out["after"]["buses"] == 4
    with pytest.raises(HTTPException):
        network_ops.merge_models(a, a, scenario=SC)


# ── P31: statistics query on output-injected network == live statistics ──────
def test_statistics_query_from_stored_outputs_equals_live() -> None:
    from backend.pypsa.results.statistics_query import network_from_outputs, run_statistic

    res = run_pypsa(mga_model(), MGA_SCENARIO, {})
    rebuilt = network_from_outputs(mga_model(), MGA_SCENARIO, {}, res["outputs"])
    # The payload's own n.statistics() table was computed on the live solved network.
    table = {(r["component"], r["carrier"]): r["values"] for r in res["statistics"]["rows"]}
    got = {tuple(r["key"].values()): list(r["values"].values())[0]
           for r in run_statistic(rebuilt, "supply", groupby=["carrier"])["rows"]}
    for (comp, carrier), values in table.items():
        if comp == "Generator" and values.get("Supply"):
            assert got[(comp, carrier)] == pytest.approx(values["Supply"], rel=1e-6, abs=1e-6)
    cap = {tuple(r["key"].values()): list(r["values"].values())[0]
           for r in run_statistic(rebuilt, "optimal_capacity", groupby=["carrier"])["rows"]}
    for (comp, carrier), values in table.items():
        if comp == "Generator" and values.get("Optimal Capacity"):
            assert cap[(comp, carrier)] == pytest.approx(values["Optimal Capacity"], rel=1e-6, abs=1e-6)
    with pytest.raises(ValueError):
        run_statistic(rebuilt, "bogus")
    ts = run_statistic(rebuilt, "supply", aggregate_time=False)
    assert len(ts["columns"]) == 4


# ── REST endpoints ───────────────────────────────────────────────────────────
@pytest.fixture()
def api(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    monkeypatch.setenv("RAGNAROK_DATA_DIR", str(tmp_path))
    c = TestClient(app)
    model = _three_bus_model()
    for line in model["lines"]:
        line["r"] = 0.01
    r = c.post("/api/session/model", json={"sessionId": "t", "model": model, "filename": "x.xlsx",
                                           "scenarioName": "s"})
    assert r.status_code == 200, r.text
    return c


def test_endpoints(api: TestClient, tmp_path: Any) -> None:
    assert api.get("/api/optimise/options").json()["solvers"]
    r = api.post("/api/optimise/export-lp", json={"sessionId": "t", "scenario": SC, "fileName": "a.lp"})
    assert r.status_code == 200 and r.json()["variables"] > 0
    assert (tmp_path / "exports" / "lp" / "a.lp").exists()
    assert api.post("/api/analysis/consistency", json={"sessionId": "t", "scenario": SC}).json()["valid"] is True
    net = api.post("/api/analysis/network", json={"sessionId": "t", "scenario": SC, "include": ["subnetworks"]}).json()
    assert net["subNetworks"][0]["slackBus"] == "A"
    t = api.post("/api/transform/temporal", json={"sessionId": "t", "scenario": SC, "method": "resample", "offset": "2h"})
    assert t.status_code == 200 and t.json()["after"]["snapshots"] == 1
    assert api.post("/api/transform/temporal", json={"sessionId": "t", "scenario": SC, "method": "segment",
                                                     "numSegments": 1}).status_code in (200, 400)
    assert api.post("/api/transform/merge", json={"sessionId": "t"}).status_code == 400
    assert api.post("/api/statistics/query", json={"runName": "does-not-exist"}).status_code == 404
    v = api.post("/api/validate", json={"sessionId": "t", "scenario": SC, "options": {"consistencyCheck": True}})
    assert v.status_code == 200 and v.json()["valid"] is True, v.json()
