"""Annual budgets read back from a stored run: budget, achieved value and dual (``GET /api/runs/{name}/annual-budgets``).

Both models are hand-checkable on four 1 h snapshots (100 MW of load, 400 MWh in all):

* e_sum: free wind is absent, gas (20/MWh) is held to 100 MWh by an ``e_sum_max`` budget, oil (80/MWh) serves the other
  300 MWh. The budget is stated per year (100 x 8760 / 4 = 219,000 MWh/yr) and written as the 100 MWh horizon total.
* CO2 cap: gas (20/MWh, eta 0.5, 0.2 tCO2/MWh_th = 0.4 tCO2/MWh_e) against bio (80/MWh, no emissions). A cap of 80 t
  (175,200 t/yr) lets gas run 200 MWh; the marginal tonne is replaced by 1 / 0.4 MWh of bio at 60/MWh more, so the dual
  is (80 - 20) / 0.4 = 150 per tonne (negative on a <= constraint).
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

HOURS = 4
SCENARIO = {"carbonPrice": 0.0, "discountRate": 0.05}
OPTIONS = {"enableLoadShedding": False}


def _base() -> dict[str, list[dict[str, Any]]]:
    snaps = pd.date_range("2030-01-01", periods=HOURS, freq="h")
    return {
        "buses": [{"name": "b", "carrier": "AC"}],
        "snapshots": [{"snapshot": s.isoformat(), "objective": 1.0, "generators": 1.0, "stores": 1.0} for s in snaps],
        "loads": [{"name": "l", "bus": "b", "p_set": 100.0}],
    }


def _esum_model() -> dict[str, list[dict[str, Any]]]:
    m = _base()
    m["carriers"] = [{"name": "AC"}, {"name": "gas"}, {"name": "oil"}]
    m["generators"] = [
        {"name": "gas", "bus": "b", "carrier": "gas", "p_nom": 200.0, "marginal_cost": 20.0},
        {"name": "oil", "bus": "b", "carrier": "oil", "p_nom": 200.0, "marginal_cost": 80.0},
    ]
    m["RAGNAROK_AnnualBudgets"] = [{"component": "generators", "name": "gas", "attribute": "e_sum_max", "annual": 100.0 * 8760 / HOURS}]
    return m


def _cap_model() -> dict[str, list[dict[str, Any]]]:
    m = _base()
    m["carriers"] = [{"name": "AC"}, {"name": "gas", "co2_emissions": 0.2}, {"name": "bio"}]
    m["generators"] = [
        {"name": "gas", "bus": "b", "carrier": "gas", "p_nom": 200.0, "marginal_cost": 20.0, "efficiency": 0.5},
        {"name": "bio", "bus": "b", "carrier": "bio", "p_nom": 200.0, "marginal_cost": 80.0},
    ]
    m["global_constraints"] = [{"name": "co2_cap", "type": "primary_energy", "carrier_attribute": "co2_emissions", "sense": "<=", "constant": 1.0e9}]
    m["RAGNAROK_AnnualBudgets"] = [{"component": "global_constraints", "name": "co2_cap", "attribute": "constant", "annual": 80.0 * 8760 / HOURS}]
    return m


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app import main, run_store, session_store

    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    monkeypatch.setattr(run_store, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setenv("RAGNAROK_DATA_DIR", str(tmp_path / "data"))
    return TestClient(main.app)


def _store(model: dict[str, Any]) -> str:
    import logging
    import warnings

    from backend.app import run_store
    from backend.app.routers import results_derived as router
    from backend.pypsa.results import run_pypsa

    logging.disable(logging.CRITICAL)
    warnings.simplefilter("ignore")
    try:
        result = run_pypsa(model, SCENARIO, OPTIONS)
    finally:
        logging.disable(logging.NOTSET)
    router._BUNDLE_CACHE.clear()
    meta = run_store.store_run(model, SCENARIO, OPTIONS, result)
    assert meta is not None
    return str(meta["name"])


def test_generator_budget_reports_the_energy_it_held_the_unit_to(client) -> None:
    body = client.get(f"/api/runs/{_store(_esum_model())}/annual-budgets").json()
    assert body["total"] == 1
    row = body["items"][0]
    assert (row["component"], row["name"], row["attribute"]) == ("generators", "gas", "e_sum_max")
    assert row["annual"] == pytest.approx(219_000.0) and row["value"] == pytest.approx(100.0)
    assert row["achieved"] == pytest.approx(100.0, rel=1e-6) and row["achievedUnit"] == "MWh"
    assert row["binding"] is True
    assert row["dual"] is None  # PyPSA stores no dual for e_sum


def test_co2_cap_reports_its_left_hand_side_and_dual(client) -> None:
    row = client.get(f"/api/runs/{_store(_cap_model())}/annual-budgets").json()["items"][0]
    assert row["component"] == "global_constraints" and row["value"] == pytest.approx(80.0)
    assert row["achieved"] == pytest.approx(80.0, rel=1e-6) and row["achievedUnit"] == "tCO2"
    assert row["binding"] is True
    assert abs(row["dual"]) == pytest.approx(150.0, rel=1e-4)


def test_a_slack_budget_is_not_binding(client) -> None:
    model = _cap_model()
    model["RAGNAROK_AnnualBudgets"][0]["annual"] = 1000.0 * 8760 / HOURS  # 1000 t is above the 160 t that gas alone emits (400 MWh x 0.4)
    row = client.get(f"/api/runs/{_store(model)}/annual-budgets").json()["items"][0]
    assert row["achieved"] == pytest.approx(160.0, rel=1e-6) and row["binding"] is False
    assert abs(row["dual"] or 0.0) == pytest.approx(0.0, abs=1e-9)


def test_a_run_without_budgets_has_no_items(client) -> None:
    model = _esum_model()
    model.pop("RAGNAROK_AnnualBudgets")
    body = client.get(f"/api/runs/{_store(model)}/annual-budgets").json()
    assert body == {"run": body["run"], "items": [], "total": 0}


def test_an_unknown_run_is_404(client) -> None:
    assert client.get("/api/runs/no-such-run/annual-budgets").status_code == 404
