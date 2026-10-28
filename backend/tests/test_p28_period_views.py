"""P28 close: pathway period views and imported results come from ``n.statistics`` on the server.

The browser used to re-derive expansion CAPEX, the cost breakdown, emissions and dispatch for
(a) one investment period of a pathway run and (b) results imported with no stored run. Both are
now server payloads:

* ``GET /api/runs/{name}/period/{period}`` - the payload of one period's slice of the network;
* imports (project, netCDF / HDF5, results workbook) are stored as runs.

Reference values are closed-form. Model: one bus, constant 80 MW load for 4 h; ``gas_old`` (100 MW,
50/MWh) is built 2030 with a 10 year life so it is gone in 2040; ``gas_new`` (100 MW, 80/MWh) is
built 2040. Carbon price 10 currency/t, ``co2_emissions`` 0.2 t/MWh (efficiency 1). Objective
weights 1.0 (2030) and 0.5 (2040), years weights 10 each.

    energy_p        = 80 MW * 4 h = 320 MWh in each period
    fuel_2030       = 320 * 50 * 1.0 = 16000      carbon_2030 = 320 * 0.2 * 10 * 1.0 = 640
    fuel_2040       = 320 * 80 * 0.5 = 12800      carbon_2040 = 320 * 0.2 * 10 * 0.5 = 320
    capacity_p      = 100 MW (the retired / not-yet-built unit is masked)
"""
from __future__ import annotations

import io
import logging
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pypsa
import pytest
from fastapi.testclient import TestClient

from backend.app import run_store
from backend.app.main import app
from backend.app.routers import results_derived as rd_router
from backend.pypsa.network import build_network
from backend.pypsa.network import cost_basis as cb
from backend.pypsa.network.serialize import network_to_model
from backend.pypsa.results import run_pypsa
from backend.pypsa.results.derive_outputs import (
    derive_results_from_outputs,
    period_view_network,
    solved_network_to_bundle,
)
from backend.pypsa.results.statistics_query import network_from_outputs

PERIODS = [2030, 2040]
OBJECTIVE = {2030: 1.0, 2040: 0.5}
YEARS = 10.0
SCENARIO = {"carbonPrice": 10.0, "discountRate": 0.05}
OPTIONS: dict[str, Any] = {
    "enableLoadShedding": False,
    "pathwayConfig": {
        "enabled": True,
        "snapshotMappingMode": "explicit_period_column",
        "periods": [
            {"period": p, "objectiveWeight": OBJECTIVE[p], "yearsWeight": YEARS} for p in PERIODS
        ],
    },
}


def _model() -> dict[str, Any]:
    ts = pd.date_range("2030-01-01", periods=4, freq="h")
    n = pypsa.Network()
    n.set_snapshots(pd.MultiIndex.from_product([PERIODS, ts], names=["period", "timestep"]))
    n.investment_periods = PERIODS
    n.add("Carrier", ["gas"], co2_emissions=0.2)
    n.add("Bus", "b")
    n.add("Load", "L", bus="b", p_set=80.0)
    n.add("Generator", "gas_old", bus="b", carrier="gas", p_nom=100, marginal_cost=50.0,
          build_year=2030, lifetime=10)
    n.add("Generator", "gas_new", bus="b", carrier="gas", p_nom=100, marginal_cost=80.0,
          build_year=2040, lifetime=30)
    return network_to_model(n)


@pytest.fixture(scope="module")
def solved() -> dict[str, Any]:
    logging.disable(logging.CRITICAL)
    warnings.simplefilter("ignore")
    try:
        model = _model()
        result = run_pypsa(model, dict(SCENARIO), dict(OPTIONS))
    finally:
        logging.disable(logging.NOTSET)
    return {"model": model, "result": result}


def _by_label(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {r["label"]: r["value"] for r in rows}


def _derive(solved: dict[str, Any], period: int | None) -> dict[str, Any]:
    return derive_results_from_outputs(
        solved["model"], solved["result"]["outputs"], dict(SCENARIO), dict(OPTIONS), period=period
    )


def test_whole_horizon_derivation_equals_the_solve_payload(solved: dict[str, Any]) -> None:
    """Multi-period outputs are now derivable server-side; the identity with the solve holds."""
    fresh = solved["result"]
    derived = _derive(solved, None)
    assert derived["summary"] == fresh["summary"]
    assert _by_label(derived["costBreakdown"]) == _by_label(fresh["costBreakdown"])
    assert {m["label"]: m["value"] for m in derived["carrierMix"]} == pytest.approx(
        {m["label"]: m["value"] for m in fresh["carrierMix"]}
    )
    assert [s["period"] for s in derived["pathway"]["summaries"]] == PERIODS


@pytest.mark.parametrize("period", PERIODS)
def test_period_payload_follows_the_stat_metrics_rules(solved: dict[str, Any], period: int) -> None:
    payload = _derive(solved, period)
    w = OBJECTIVE[period]
    price = {2030: 50.0, 2040: 80.0}[period]
    cost = _by_label(payload["costBreakdown"])
    # Money is weighted by the period objective weight; energy is not.
    np.testing.assert_allclose(cost["Fuel cost"], 320.0 * price * w, rtol=1e-9)
    np.testing.assert_allclose(cost["Carbon cost"], 320.0 * 0.2 * 10.0 * w, rtol=1e-9)
    assert sum(m["value"] for m in payload["carrierMix"]) == pytest.approx(320.0, rel=1e-9)
    # The retired / not-yet-built unit is masked from the capacity KPI.
    capacity = next(s for s in payload["summary"] if s["label"] == "Generator capacity")
    assert capacity["value"] == "100 MW"
    # Emissions carry the period's years weight (PyPSA primary_energy basis): 320 * 0.2 * 10.
    np.testing.assert_allclose(payload["emissionsBreakdown"]["totalTco2"], 320.0 * 0.2 * YEARS, rtol=1e-9)
    # Only this period's snapshots.
    assert len(payload["dispatchSeries"]) == 4
    assert [s["period"] for s in payload["pathway"]["summaries"]] == [period]


def test_periods_add_up_to_the_whole_horizon(solved: dict[str, Any]) -> None:
    whole = _derive(solved, None)
    parts = [_derive(solved, p) for p in PERIODS]
    for label in ("Fuel cost", "Carbon cost"):
        assert sum(_by_label(p["costBreakdown"])[label] for p in parts) == pytest.approx(
            _by_label(whole["costBreakdown"])[label], rel=1e-9)
    assert sum(sum(m["value"] for m in p["carrierMix"]) for p in parts) == pytest.approx(
        sum(m["value"] for m in whole["carrierMix"]), rel=1e-9)
    assert sum(p["emissionsBreakdown"]["totalTco2"] for p in parts) == pytest.approx(
        whole["emissionsBreakdown"]["totalTco2"], rel=1e-9)


def test_period_view_network_slices_snapshots_and_weights(solved: dict[str, Any]) -> None:
    network, _ = build_network(solved["model"], dict(SCENARIO), dict(OPTIONS))
    view = period_view_network(network, 2040)
    assert set(view.snapshots.get_level_values("period")) == {2040}
    assert list(view.investment_periods) == [2040]
    assert float(view.investment_period_weightings.at[2040, "objective"]) == OBJECTIVE[2040]
    with pytest.raises(ValueError, match="not an investment period"):
        period_view_network(network, 1999)


def test_network_from_outputs_aligns_pathway_series_on_period_and_timestep(solved: dict[str, Any]) -> None:
    """The same timestep repeats in every period: aligning on the timestamp alone raised
    'cannot reindex on an axis with duplicate labels'."""
    network = network_from_outputs(solved["model"], dict(SCENARIO), dict(OPTIONS), solved["result"]["outputs"])
    p = network.generators_t.p
    assert isinstance(p.index, pd.MultiIndex)
    np.testing.assert_allclose(p.loc[2030, "gas_old"].to_numpy(), 80.0)
    np.testing.assert_allclose(p.loc[2040, "gas_new"].to_numpy(), 80.0)
    np.testing.assert_allclose(p.loc[2040, "gas_old"].to_numpy(), 0.0, atol=1e-9)


# ── routes ──────────────────────────────────────────────────────────────────────


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(run_store, "RUNS_DIR", tmp_path / "runs")
    rd_router._BUNDLE_CACHE.clear()
    rd_router._PERIOD_CACHE.clear()
    return TestClient(app)


@pytest.fixture()
def stored_name(client: TestClient, solved: dict[str, Any]) -> str:
    meta = run_store.store_run(solved["model"], dict(SCENARIO), dict(OPTIONS), solved["result"])
    assert meta is not None
    return str(meta["name"])


def test_period_route_returns_the_period_payload(client: TestClient, stored_name: str) -> None:
    resp = client.get(f"/api/runs/{stored_name}/period/2040")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["period"] == 2040
    result = body["result"]
    assert "outputs" not in result  # series are read windowed from /series/{sheet}
    np.testing.assert_allclose(_by_label(result["costBreakdown"])["Fuel cost"], 320.0 * 80.0 * 0.5, rtol=1e-9)
    # The selector keeps every period; the selected one is marked.
    assert result["pathway"]["periods"] == PERIODS
    assert result["pathway"]["selectedPeriod"] == 2040
    assert result["runMeta"]["investmentPeriods"] == PERIODS


def test_period_route_errors(client: TestClient, stored_name: str) -> None:
    assert client.get(f"/api/runs/{stored_name}/period/1999").status_code == 400
    assert client.get("/api/runs/no_such_run/period/2030").status_code == 404
    assert client.get(f"/api/runs/{stored_name}/period/2030?fields=nope").status_code == 400
    only = client.get(f"/api/runs/{stored_name}/period/2030?fields=summary,costBreakdown").json()["result"]
    assert set(only) == {"summary", "costBreakdown"}


def test_period_route_rejects_a_single_period_run(client: TestClient) -> None:
    ts = pd.date_range("2030-01-01", periods=2, freq="h")
    n = pypsa.Network()
    n.set_snapshots(ts)
    n.add("Bus", "b")
    n.add("Load", "L", bus="b", p_set=10.0)
    n.add("Generator", "g", bus="b", p_nom=20, marginal_cost=5.0)
    logging.disable(logging.CRITICAL)
    try:
        model = network_to_model(n)
        result = run_pypsa(model, {"carbonPrice": 0.0, "discountRate": 0.05}, {"enableLoadShedding": False})
    finally:
        logging.disable(logging.NOTSET)
    meta = run_store.store_run(model, {"carbonPrice": 0.0, "discountRate": 0.05}, {}, result)
    assert meta is not None
    resp = client.get(f"/api/runs/{meta['name']}/period/2030")
    assert resp.status_code == 400
    assert "not a multi-period" in resp.json()["detail"]


def test_kpis_and_companies_take_the_period(client: TestClient, stored_name: str) -> None:
    whole = client.get(f"/api/runs/{stored_name}/kpis").json()
    p2030 = client.get(f"/api/runs/{stored_name}/kpis?period=2030").json()
    p2040 = client.get(f"/api/runs/{stored_name}/kpis?period=2040").json()
    assert p2030["period"] == 2030 and whole["period"] is None
    # 320 MWh served in each period; the whole horizon serves both.
    assert p2030["kpis"]["dispatchMwh"] == pytest.approx(320.0)
    assert p2040["kpis"]["dispatchMwh"] == pytest.approx(320.0)
    assert whole["kpis"]["dispatchMwh"] == pytest.approx(640.0)
    assert p2030["kpis"]["snapshotCount"] == 4
    assert client.get(f"/api/runs/{stored_name}/companies?period=2030").status_code == 200
    assert client.get(f"/api/runs/{stored_name}/kpis?period=1999").status_code == 400


def test_assets_route_windows_with_end(client: TestClient, stored_name: str) -> None:
    resp = client.get(f"/api/runs/{stored_name}/assets?kind=generators&names=gas_new&period=2040&end=2")
    assert resp.status_code == 200, resp.text
    (item,) = resp.json()["items"]
    assert len(item["outputSeries"]) == 2


# ── imports are stored as runs ──────────────────────────────────────────────────


def _solved_netcdf(tmp_path: Path, solved: dict[str, Any]) -> Path:
    network, _ = build_network(solved["model"], dict(SCENARIO), dict(OPTIONS))
    logging.disable(logging.CRITICAL)
    try:
        status, _ = network.optimize(multi_investment_periods=True, solver_name="highs")
    finally:
        logging.disable(logging.NOTSET)
    assert status == "ok"
    path = tmp_path / "solved.nc"
    network.export_to_netcdf(str(path))
    return path


def test_solved_netcdf_import_is_a_stored_pathway_run(client: TestClient, solved: dict[str, Any], tmp_path: Path) -> None:
    path = _solved_netcdf(tmp_path, solved)
    resp = client.post("/api/import/netcdf", files={"file": ("solved.nc", io.BytesIO(path.read_bytes()), "application/x-netcdf")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {r["name"] for r in body["model"]["generators"]} == {"gas_old", "gas_new"}
    name = body["runName"]
    assert name and run_store.list_runs()[0]["origin"] == "netcdf_import"

    analytics = client.get(f"/api/runs/{name}/analytics").json()["result"]
    assert analytics["pathway"]["periods"] == PERIODS
    # The file's marginal_cost is the fuel cost only: the carbon price is the carbon-pricing module's objective term,
    # a run setting that a PyPSA file does not carry (and this solve here, a bare n.optimize, did not add it).
    # Fuel: 50 * 320 * 1.0 in 2030 and 80 * 320 * 0.5 in 2040.
    p2030 = client.get(f"/api/runs/{name}/period/2030").json()["result"]
    p2040 = client.get(f"/api/runs/{name}/period/2040").json()["result"]
    np.testing.assert_allclose(_by_label(p2030["costBreakdown"])["Fuel cost"], 50.0 * 320.0, rtol=1e-9)
    np.testing.assert_allclose(_by_label(p2040["costBreakdown"])["Fuel cost"], 80.0 * 320.0 * 0.5, rtol=1e-9)
    # Emissions stay on the carrier co2_emissions: 320 MWh * 0.2 t/MWh * 10 years.
    np.testing.assert_allclose(p2030["emissionsBreakdown"]["totalTco2"], 640.0, rtol=1e-9)


def test_unsolved_netcdf_import_stores_nothing(client: TestClient, solved: dict[str, Any], tmp_path: Path) -> None:
    network, _ = build_network(solved["model"], dict(SCENARIO), dict(OPTIONS))
    path = tmp_path / "unsolved.nc"
    network.export_to_netcdf(str(path))
    resp = client.post("/api/import/netcdf", files={"file": ("unsolved.nc", io.BytesIO(path.read_bytes()), "application/x-netcdf")})
    assert resp.status_code == 200, resp.text
    assert resp.json()["runName"] is None
    assert run_store.list_runs() == []


def test_solved_network_to_bundle_is_stamped_as_pypsa_native(solved: dict[str, Any], tmp_path: Path) -> None:
    """A PyPSA-native file is already on PyPSA's cost semantics: the bundle is stamped with the current build version so a later
    re-derivation does not read its capital_cost as a legacy overnight price (and nothing annuitises twice)."""
    network = pypsa.Network()
    network.import_from_netcdf(str(_solved_netcdf(tmp_path, solved)))
    bundle = solved_network_to_bundle(network, "solved.nc")
    assert bundle["options"]["buildVersion"] == cb.CURRENT_SCHEMA_VERSION
    assert [p["period"] for p in bundle["options"]["pathwayConfig"]["periods"]] == PERIODS
    weights = {p["period"]: p["objectiveWeight"] for p in bundle["options"]["pathwayConfig"]["periods"]}
    assert weights == OBJECTIVE


def test_network_without_results_is_not_a_bundle(solved: dict[str, Any]) -> None:
    network, _ = build_network(solved["model"], dict(SCENARIO), dict(OPTIONS))
    with pytest.raises(ValueError, match="no results"):
        solved_network_to_bundle(network)
