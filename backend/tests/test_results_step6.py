"""Core cleanup step 6: results come from PyPSA (``n.statistics``), and the run stops converting inputs.

D13 placeholder bounds, D14 ``v_ang_min``, D15 scenario weights, A6 dangling bus references,
A4 AC feasibility, A5 per-scenario summaries and the statistics-based per-asset results.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from backend.app import forge_helpers as fh
from backend.pypsa.model_check import check_model
from backend.pypsa.network import build_components, build_network
from backend.pypsa.network.placeholders import find_placeholders, is_placeholder

SCENARIO = {"carbonPrice": 0.0, "discountRate": 0.05}


def _model(hours: int = 4) -> dict[str, list[dict[str, Any]]]:
    snaps = pd.date_range("2030-01-01", periods=hours, freq="h")
    return {
        "buses": [{"name": "b", "carrier": "AC"}],
        "carriers": [{"name": "AC"}, {"name": "gas"}],
        "snapshots": [{"snapshot": s.isoformat()} for s in snaps],
        "loads": [{"name": "l", "bus": "b", "p_set": 100.0}],
        "generators": [{"name": "gas", "bus": "b", "carrier": "gas", "p_nom": 500.0, "marginal_cost": 20.0}],
    }


# ── D13: placeholders are found, cleaned visibly, never snapped by the run ─────────

def test_placeholder_rule_matches_the_old_snap() -> None:
    assert is_placeholder("p_nom_max", 1e12) and is_placeholder("lifetime", 1e9) and is_placeholder("e_sum_max", 5e9)
    assert is_placeholder("e_sum_min", -1e12) and not is_placeholder("e_sum_min", 1e12)
    assert not is_placeholder("p_nom_max", 5e8) and not is_placeholder("p_nom_max", float("inf"))
    assert not is_placeholder("marginal_cost", 1e12) and not is_placeholder("p_nom_max", True)


def test_run_passes_placeholders_to_pypsa_unchanged_and_the_forge_action_cleans_them() -> None:
    model = _model()
    model["generators"][0].update(p_nom_max=1e12, lifetime=1e12, e_sum_min=-1e12, e_sum_max=3600.0)
    network, _ = build_network(model, SCENARIO, {"enableLoadShedding": False})
    assert float(network.generators.at["gas", "p_nom_max"]) == 1e12  # not snapped
    assert float(network.generators.at["gas", "lifetime"]) == 1e12
    assert float(network.generators.at["gas", "e_sum_max"]) == 3600.0  # a genuine cap is untouched

    cells = {(c, v) for _, _, c, v in find_placeholders(model)}
    assert cells == {("p_nom_max", 1e12), ("lifetime", 1e12), ("e_sum_min", -1e12)}

    findings = check_model(model)["findings"]
    warn = next(f for f in findings if f["code"] == "placeholder_bounds")
    assert "3 bound cell" in warn["message"] and warn["action"]["id"] == "clean_placeholder_bounds"

    result = fh.clean_placeholder_bounds(model)
    assert result["cleaned"] == 3 and list(result["sheets"]) == ["generators"]
    assert model["generators"][0]["p_nom_max"] == 1e12  # input not mutated
    cleaned = result["sheets"]["generators"][0]
    assert "p_nom_max" not in cleaned and "lifetime" not in cleaned and cleaned["e_sum_max"] == 3600.0
    after, _ = build_network({**model, "generators": result["sheets"]["generators"]}, SCENARIO, {"enableLoadShedding": False})
    assert np.isinf(float(after.generators.at["gas", "p_nom_max"])) and np.isinf(float(after.generators.at["gas", "lifetime"]))
    assert float(after.generators.at["gas", "e_sum_min"]) == -np.inf
    assert not any(f["code"] == "placeholder_bounds" for f in check_model({**model, "generators": result["sheets"]["generators"]})["findings"])


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app import main, run_store, session_store

    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    monkeypatch.setattr(run_store, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setenv("RAGNAROK_DATA_DIR", str(tmp_path / "data"))
    return TestClient(main.app)


def test_forge_endpoint_previews_then_applies(client) -> None:
    model = _model()
    model["generators"][0]["p_nom_max"] = 1e12
    client.post("/api/session/model", json={"model": model, "sessionId": "d13"})
    preview = client.post("/api/forge/clean-placeholder-bounds", json={"sessionId": "d13"}).json()
    assert preview["cleaned"] == 1 and preview["applied"] is False
    assert client.get("/api/session/sheet/generators", params={"session_id": "d13"}).json()["rows"][0]["p_nom_max"] == 1e12
    done = client.post("/api/forge/clean-placeholder-bounds", json={"sessionId": "d13", "apply": True}).json()
    assert done["applied"] is True and done["sheets"] == {"generators": 1}
    assert "p_nom_max" not in client.get("/api/session/sheet/generators", params={"session_id": "d13"}).json()["rows"][0]


# ── A6: a dangling bus reference is refused, not dropped ────────────────────────────

def test_dangling_bus_reference_is_refused_with_pypsas_message() -> None:
    model = _model()
    model["generators"].append({"name": "typo", "bus": "bsu", "carrier": "gas", "p_nom": 10.0})
    for builder in (lambda m: build_network(m, SCENARIO, {}), lambda m: build_components(m, {})):
        with pytest.raises(HTTPException) as exc:
            builder(model)
        assert exc.value.status_code == 400
        assert "typo" in str(exc.value.detail) and "refused" in str(exc.value.detail)


def test_missing_bus_column_is_refused_and_optional_ports_are_not() -> None:
    model = _model()
    model["generators"][0].pop("bus")
    with pytest.raises(HTTPException):
        build_network(model, SCENARIO, {})
    ok = _model()
    ok["links"] = [{"name": "k", "bus0": "b", "bus1": "b", "p_nom": 1.0}]  # bus2.. are blank: unused ports
    build_network(ok, SCENARIO, {})


# ── A14 / A15 / A16: weighted per-asset results on a sampled run (non-uniform snapshot weights) ─────────

STAMPS = ["2030-01-01T00:00:00", "2030-01-01T01:00:00", "2030-01-01T02:00:00"]
HOURS = [1.0, 2.0, 5.0]   # snapshot t stands for HOURS[t] hours (a sampled run); uniform would be 8 / 3 each


def _sampled_model() -> dict[str, list[dict[str, Any]]]:
    """Gas (20/MWh, eta 0.5, 0.2 tCO2 per MWh_th) behind wind (free, p_max_pu 0.5 / 1.0 / 0.2) under a 30/tCO2 price.

    load 100, 100, 10 MW -> wind 40, 80, 10 (6 MW curtailed in t2) and gas 60, 20, 0.
    Weighted by HOURS: gas 100 MWh, wind 250 MWh, curtailment 30 MWh.
    """
    return {
        "snapshots": [{"snapshot": s, "objective": h, "generators": h, "stores": h} for s, h in zip(STAMPS, HOURS)],
        "buses": [{"name": "b", "carrier": "AC"}],
        "carriers": [{"name": "AC"}, {"name": "gas", "co2_emissions": 0.2}, {"name": "wind"}],
        "loads": [{"name": "l", "bus": "b", "p_set": 100.0}],
        "loads-p_set": [{"snapshot": s, "l": v} for s, v in zip(STAMPS, (100.0, 100.0, 10.0))],
        "generators": [
            {"name": "gas", "bus": "b", "carrier": "gas", "p_nom": 500.0, "marginal_cost": 20.0, "efficiency": 0.5},
            {"name": "wind", "bus": "b", "carrier": "wind", "p_nom": 80.0, "marginal_cost": 0.0},
        ],
        "generators-p_max_pu": [{"snapshot": s, "wind": v} for s, v in zip(STAMPS, (0.5, 1.0, 0.2))],
    }


@pytest.fixture(scope="module")
def sampled_run() -> dict[str, Any]:
    import logging
    import warnings

    from backend.pypsa.results import run_pypsa

    logging.disable(logging.CRITICAL)
    warnings.simplefilter("ignore")
    try:
        model = _sampled_model()
        scenario = {"carbonPrice": 30.0, "discountRate": 0.05}
        options = {"enableLoadShedding": False}
        result = run_pypsa(model, scenario, options)
    finally:
        logging.disable(logging.NOTSET)
    return {"model": model, "scenario": scenario, "options": options, "result": result}


@pytest.fixture()
def stored_sampled(client, tmp_path, monkeypatch, sampled_run) -> str:
    from backend.app import run_store
    from backend.app.routers import results_derived as router

    monkeypatch.setattr(run_store, "RUNS_DIR", tmp_path / "runs")
    router._BUNDLE_CACHE.clear()
    router._STATS_CACHE.clear()
    meta = run_store.store_run(sampled_run["model"], sampled_run["scenario"], sampled_run["options"], sampled_run["result"])
    assert meta is not None
    return str(meta["name"])


def test_the_solve_pins_the_dispatch_the_expectations_assume(sampled_run) -> None:
    n, _ = build_network(sampled_run["model"], sampled_run["scenario"], sampled_run["options"])
    np.testing.assert_allclose(n.snapshot_weightings["generators"].to_numpy(), HOURS)
    runMeta = sampled_run["result"]["runMeta"]
    np.testing.assert_allclose(runMeta["modeledHours"], sum(HOURS))                 # was count x first weight = 3
    np.testing.assert_allclose(runMeta["snapshotWeights"], HOURS)
    mix = {m["label"]: m["value"] for m in sampled_run["result"]["carrierMix"]}
    np.testing.assert_allclose([mix["gas"], mix["wind"]], [100.0, 250.0], rtol=1e-9)  # A7: n.statistics.supply


def test_derived_endpoint_is_pypsas_weighted_statistics(client, stored_sampled) -> None:
    body = client.get(f"/api/runs/{stored_sampled}/derived").json()
    np.testing.assert_allclose(body["weights"], HOURS)
    np.testing.assert_allclose(body["modeledHours"], 8.0)
    gas, wind = body["generators"]["gas"], body["generators"]["wind"]
    np.testing.assert_allclose(gas["energyMwh"], 100.0, rtol=1e-9)
    np.testing.assert_allclose(wind["energyMwh"], 250.0, rtol=1e-9)
    # Operating cost = statistics.opex (100 MWh x 20) + the carbon-pricing module's term (100 MWh x 30 x 0.2 / 0.5):
    # the old energy x static marginal_cost (x uniform weight) said 2000 here, no carbon, no weights.
    np.testing.assert_allclose(gas["carbonCost"], 1200.0, rtol=1e-9)
    np.testing.assert_allclose(gas["operatingCost"], 3200.0, rtol=1e-9)
    np.testing.assert_allclose(gas["emissionsTco2"], 100.0 * 0.2 / 0.5, rtol=1e-9)
    np.testing.assert_allclose(wind["curtailmentMwh"], 6.0 * 5.0, rtol=1e-9)         # 6 MW for 5 h
    bus = body["buses"]["b"]
    np.testing.assert_allclose(bus["loadMwh"], 100 * 1 + 100 * 2 + 10 * 5, rtol=1e-9)
    np.testing.assert_allclose(bus["generationMwh"], 350.0, rtol=1e-9)
    np.testing.assert_allclose([bus["carrierMwh"]["gas"], bus["carrierMwh"]["wind"]], [100.0, 250.0], rtol=1e-9)
    # price 32 in t0 and t1 (gas + carbon adder), 0 in t2; weighted by load x hours (100, 200, 50)
    np.testing.assert_allclose(bus["averagePrice"], (32.0 * 100 + 32.0 * 200) / 350.0, rtol=1e-6)


def test_asset_cards_and_kpis_read_the_statistics(client, stored_sampled) -> None:
    items = client.get(f"/api/runs/{stored_sampled}/assets", params={"kind": "generators"}).json()["items"]
    gas = next(i for i in items if i["name"] == "gas")
    summary = {row["label"]: row["value"] for row in gas["summary"]}
    assert summary["Energy"] == "100 MWh" and summary["Operating cost"] == "3,200 $" and summary["Emissions"] == "40 tCO2e"
    wind = next(i for i in items if i["name"] == "wind")
    assert {r["label"]: r["value"] for r in wind["summary"]}["Curtailment"] == "30 MWh"
    # load analysis energy is n.statistics.withdrawal(Load): 350 MWh, and the load factor is energy / hours / peak
    analysis = client.get(f"/api/runs/{stored_sampled}/analysis/load-analysis").json()
    np.testing.assert_allclose(analysis["systemEnergyMwh"], 350.0, rtol=1e-9)
    np.testing.assert_allclose(analysis["systemLoadFactor"], (350.0 / 8.0) / 100.0, rtol=1e-9)
    kpis = client.get(f"/api/runs/{stored_sampled}/kpis").json()["kpis"]
    np.testing.assert_allclose(kpis["loadFactor"], (350.0 / 8.0) / 100.0, rtol=1e-9)   # avg load = dispatch / modelled hours


def test_old_run_without_weights_is_backfilled_from_pypsa_and_persisted(client, stored_sampled) -> None:
    from backend.app import run_store

    with run_store._connect(stored_sampled) as conn:
        analytics = run_store._kv_get(conn, "analytics")
        analytics["result"]["runMeta"].pop("snapshotWeights")
        analytics["result"]["runMeta"]["modeledHours"] = 3.0   # the old count x first weight
        run_store._kv_set(conn, "analytics", analytics)
    out = run_store.get_run_analytics(stored_sampled)
    np.testing.assert_allclose(out["result"]["runMeta"]["snapshotWeights"], HOURS)
    np.testing.assert_allclose(out["result"]["runMeta"]["modeledHours"], 8.0)
    with run_store._connect(stored_sampled) as conn:
        assert run_store._kv_get(conn, "analytics")["result"]["runMeta"]["snapshotWeights"] == HOURS


# ── A9: piecewise money is n.statistics.opex / capex ──────────────────────────────────

def test_piecewise_totals_are_statistics_opex_and_capex() -> None:
    from backend.tests.test_piecewise import CONVEX, _model as pw_model

    from backend.pypsa.results import run_pypsa

    res = run_pypsa(pw_model(CONVEX), {"carbonPrice": 0}, {})
    n, _ = build_network(pw_model(CONVEX), {"carbonPrice": 0}, {})
    n.optimize(solver_name="highs", include_objective_constant=False)
    stat = n.statistics.opex(components=["Generator"], groupby=False, drop_zero=False, cost_types=["marginal_cost"])
    expected = float(stat.xs("g", level="name").sum())   # the curve-priced generator only (h has a scalar cost)
    np.testing.assert_allclose(res["piecewise"]["totalOperatingCost"], expected, rtol=1e-9)
    (curve,) = res["piecewise"]["curves"]
    np.testing.assert_allclose(curve["solved"]["operatingCost"], expected, rtol=1e-9)


# ── A17: congestion rent is n.statistics.revenue of the branches ───────────────────────

def test_congestion_rent_equals_statistics_revenue_under_uneven_weights() -> None:
    import pypsa

    from backend.pypsa.results.lmp_decomposition import build_lmp_decomposition

    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=3, freq="h"))
    for col, w in (("objective", HOURS), ("generators", HOURS), ("stores", HOURS)):
        n.snapshot_weightings[col] = w
    n.add("Bus", "A")
    n.add("Bus", "B")
    n.add("Generator", "ga", bus="A", p_nom=500, marginal_cost=10)
    n.add("Generator", "gb", bus="B", p_nom=500, marginal_cost=80)
    n.add("Load", "lb", bus="B", p_set=100)
    n.add("Line", "L1", bus0="A", bus1="B", x=0.1, s_nom=50)
    n.optimize(solver_name="highs", assign_all_duals=True, include_objective_constant=False)
    out = build_lmp_decomposition(n, {"lmpDecompositionConfig": {"enabled": True}})
    # LMP 10 at A, 80 at B, flow 50 MW A -> B on a binding line: 70 x 50 = 3500 per hour x 8 h
    np.testing.assert_allclose(out["totals"]["congestionRent"], 3500.0 * 8.0, rtol=1e-9)
    np.testing.assert_allclose(out["lines"][0]["congestionRent"], 3500.0 * 8.0, rtol=1e-9)
    np.testing.assert_allclose(out["series"]["congestionRent"], [3500.0] * 3, rtol=1e-9)
    stat = float(n.statistics.revenue(components=["Line"], groupby=False).sum())
    np.testing.assert_allclose(out["totals"]["congestionRent"], stat, rtol=1e-9)
    # the duals the old docstring said were empty are assigned: mu_upper = -(LMP spread) x hours
    np.testing.assert_allclose(n.lines_t.mu_upper["L1"].to_numpy(), [-70.0 * h for h in HOURS], rtol=1e-9)
