"""End-to-end tests for the native physical-risk capability (Phase 0 stub).

Exercises the ``/api/physical-risk/*`` router against the deterministic stub
engine — no CLIMADA / conda. A small 2-bus model (one generator, one storage
unit) is loaded into the session, seeded into a portfolio, and run.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import session_store
from backend.app.main import app

client = TestClient(app)


@pytest.fixture()
def _session_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the session store at a temp dir so nothing touches real session data.

    Both the sqlite and legacy stores resolve their session path through
    ``session_store.SESSION_DIR`` (see ``sqlite_store._db_path``), so patching it
    isolates whichever backend is active.
    """
    target = tmp_path / "session"
    monkeypatch.setattr(session_store, "SESSION_DIR", target)
    return target


def _load_model() -> None:
    """Load a 2-bus model: bus B1 (a gas gen), bus B2 (a battery storage unit)."""
    model = {
        "buses": [
            {"name": "B1", "x": 127.0, "y": 37.5},  # Seoul-ish
            {"name": "B2", "x": 129.0, "y": 35.2},  # Busan-ish
        ],
        "generators": [
            {"name": "gasCC", "bus": "B1", "carrier": "gas", "p_nom": 400.0, "capital_cost": 800.0},
        ],
        "storage_units": [
            {"name": "battery1", "bus": "B2", "carrier": "battery", "p_nom": 100.0},
        ],
        "snapshots": [{"snapshot": "2030-01-01T00:00:00"}],
    }
    resp = client.post(
        "/api/session/model",
        json={"sessionId": "default", "model": model, "filename": "case.xlsx", "scenarioName": "ref"},
    )
    assert resp.status_code == 200, resp.text


def test_seed_from_model_maps_gen_and_storage(_session_dir: Path) -> None:
    _load_model()
    resp = client.post("/api/physical-risk/seed-from-model", json={"defaultValuePerMw": 1_000_000.0})
    assert resp.status_code == 200, resp.text
    pf = resp.json()
    assert pf["sessionId"]
    assets = {a["name"]: a for a in pf["assets"]}
    assert set(assets) == {"gasCC", "battery1"}

    gen = assets["gasCC"]
    assert gen["kind"] == "generator"
    assert gen["lon"] == pytest.approx(127.0)  # bus x -> lon
    assert gen["lat"] == pytest.approx(37.5)   # bus y -> lat
    # capital_cost * p_nom = 800 * 400 = 320_000
    assert gen["value"] == pytest.approx(320_000.0)
    assert gen["vulnerabilityClass"] == "thermal"
    assert gen["carrier"] == "gas"

    sto = assets["battery1"]
    assert sto["kind"] == "storage"
    assert sto["lon"] == pytest.approx(129.0)
    assert sto["lat"] == pytest.approx(35.2)
    # no capital_cost -> default_value_per_mw * p_nom = 1e6 * 100 = 1e8
    assert sto["value"] == pytest.approx(1e8)
    assert sto["vulnerabilityClass"] == "grid"


def test_get_and_put_session_round_trips_an_edit(_session_dir: Path) -> None:
    _load_model()
    sid = client.post("/api/physical-risk/seed-from-model").json()["sessionId"]

    got = client.get(f"/api/physical-risk/session/{sid}")
    assert got.status_code == 200
    pf = got.json()

    # Edit the first asset's value + currency and PUT the whole document back.
    pf["assets"][0]["value"] = 42_000.0
    pf["assets"][0]["currency"] = "EUR"
    put = client.put(f"/api/physical-risk/session/{sid}", json=pf)
    assert put.status_code == 200, put.text
    assert put.json()["assets"][0]["value"] == pytest.approx(42_000.0)

    # The edit persists on the next GET.
    again = client.get(f"/api/physical-risk/session/{sid}").json()
    assert again["assets"][0]["value"] == pytest.approx(42_000.0)
    assert again["assets"][0]["currency"] == "EUR"


def test_get_session_unknown_is_404(_session_dir: Path) -> None:
    resp = client.get("/api/physical-risk/session/does-not-exist")
    assert resp.status_code == 404


def test_libraries_lists_the_core_perils(_session_dir: Path) -> None:
    """The vendored perils library supersedes the Phase-0 five: core ids must remain."""
    resp = client.get("/api/physical-risk/libraries")
    assert resp.status_code == 200
    body = resp.json()
    peril_ids = {p["id"] for p in body["perils"]}
    assert {"tropical_cyclone", "river_flood", "wildfire", "earthquake"} <= peril_ids
    assert all(p["label"] for p in body["perils"])  # every peril has a label
    assert body["vulnerabilityClasses"]  # non-empty class list
    # The Phase-0 energy classes are still offered (with borrowed curve data).
    class_ids = {c["id"] for c in body["vulnerabilityClasses"]}
    assert {"thermal", "renewable", "hydro", "grid", "default"} <= class_ids


def test_submit_run_polls_to_done_with_output(_session_dir: Path) -> None:
    _load_model()
    sid = client.post("/api/physical-risk/seed-from-model").json()["sessionId"]
    n_assets = len(client.get(f"/api/physical-risk/session/{sid}").json()["assets"])

    perils = ["tropical_cyclone", "river_flood"]
    submit = client.post(
        f"/api/physical-risk/session/{sid}/run",
        json={"perils": perils, "scenario": {"rcp": "rcp85", "horizon": 2050}},
    )
    assert submit.status_code == 200, submit.text
    run = submit.json()
    assert run["status"] in ("queued", "running")
    rid = run["id"]

    poll = client.get(f"/api/physical-risk/session/{sid}/run/{rid}")
    assert poll.status_code == 200, poll.text
    done = poll.json()
    assert done["status"] == "done"

    out = done["result"]
    assert out is not None
    assert out["currency"]  # carried from the assets
    assert len(out["perils"]) == len(perils)
    for block in out["perils"]:
        assert block["peril"] in perils
        # Every asset is covered.
        assert len(block["perAsset"]) == n_assets
        assert {a["assetId"] for a in block["perAsset"]}  # ids present
        # freqCurve arrays are equal length.
        fc = block["freqCurve"]
        assert len(fc["returnPeriods"]) == len(fc["losses"])
        assert len(fc["returnPeriods"]) > 0


def test_submit_run_without_perils_is_400(_session_dir: Path) -> None:
    _load_model()
    sid = client.post("/api/physical-risk/seed-from-model").json()["sessionId"]
    resp = client.post(f"/api/physical-risk/session/{sid}/run", json={"perils": []})
    assert resp.status_code == 400


# ── Seed robustness against malformed model cells (review regressions) ────────


def test_seed_negative_p_nom_clamps_value_not_crash() -> None:
    """A negative p_nom must yield a 0 value (Asset.value ge=0), never a 500."""
    from backend.app.physical_risk.seed import portfolio_from_model

    model = {
        "buses": [{"name": "B1", "x": 127.0, "y": 37.5}],
        "generators": [{"name": "g", "bus": "B1", "carrier": "gas", "p_nom": -50}],
    }
    portfolio, _notes = portfolio_from_model(model, default_value_per_mw=1e6, currency="USD")
    assert len(portfolio.assets) == 1
    assert portfolio.assets[0].value == 0.0


def test_seed_projected_or_nonfinite_coords_are_skipped_and_flagged() -> None:
    """Out-of-range (projected CRS) or NaN bus coords must skip+flag, not 500."""
    from backend.app.physical_risk.seed import portfolio_from_model

    model = {
        "buses": [
            {"name": "B_proj", "x": 4321000, "y": 3210000},   # EPSG:3035 metres
            {"name": "B_nan", "x": "nan", "y": "nan"},
            {"name": "B_ok", "x": 127.0, "y": 37.5},
        ],
        "generators": [
            {"name": "g_proj", "bus": "B_proj", "carrier": "coal", "p_nom": 100},
            {"name": "g_nan", "bus": "B_nan", "carrier": "coal", "p_nom": 100},
            {"name": "g_ok", "bus": "B_ok", "carrier": "coal", "p_nom": 100},
        ],
    }
    portfolio, notes = portfolio_from_model(model, default_value_per_mw=1e6, currency="USD")
    placed = {a.name for a in portfolio.assets}
    assert placed == {"g_ok"}
    assert any("g_proj" in n for n in notes)
    assert any("g_nan" in n for n in notes)
