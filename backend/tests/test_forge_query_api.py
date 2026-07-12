"""End-to-end tests for ``/api/forge/query/*`` against a real (SQLite) session.

Saves a small model (buses with a province, generators on those buses, a
``loads-p_set`` series), then previews + applies a query and reads the sheet back
to confirm the stored data changed.
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
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    return tmp_path


def _load() -> None:
    model = {
        "buses": [
            {"name": "b1", "province": "Seoul"},
            {"name": "b2", "province": "Busan"},
        ],
        "generators": [
            {"name": "g1", "bus": "b1", "carrier": "gas", "p_nom": 100.0, "p_nom_max": 0.0},
            {"name": "g2", "bus": "b2", "carrier": "gas", "p_nom": 200.0, "p_nom_max": 0.0},
        ],
        "loads": [{"name": "L1", "bus": "b1"}, {"name": "L2", "bus": "b2"}],
        "snapshots": [{"snapshot": "2030-01-01T00:00:00"}, {"snapshot": "2030-01-01T01:00:00"}],
        "loads-p_set": [
            {"snapshot": "2030-01-01T00:00:00", "L1": 10.0, "L2": 20.0},
            {"snapshot": "2030-01-01T01:00:00", "L1": 12.0, "L2": 24.0},
        ],
    }
    resp = client.post(
        "/api/session/model",
        json={"sessionId": "default", "model": model, "filename": "c.xlsx", "scenarioName": "ref"},
    )
    assert resp.status_code == 200, resp.text


def _gen_page() -> list[dict]:
    return client.get("/api/session/sheet/generators", params={"limit": 100}).json()["rows"]


def _load_series() -> list[dict]:
    return client.get("/api/session/sheet/loads-p_set", params={"limit": 100}).json()["rows"]


def test_static_join_multiply(_session_dir: Path) -> None:
    _load()
    body = {
        "sessionId": "default",
        "target": "generators",
        "attribute": "p_nom",
        "temporal": False,
        "filters": [{"column": "province", "op": "eq", "value": "Seoul",
                     "join": {"component": "buses", "ref_column": "bus"}}],
        "edit": {"op": "multiply", "amount": 0.8},
    }
    prev = client.post("/api/forge/query/preview", json=body)
    assert prev.status_code == 200, prev.text
    assert prev.json()["matched"] == 1  # only g1 is on a Seoul bus

    applied = client.post("/api/forge/query/apply", json=body)
    assert applied.status_code == 200, applied.text
    assert applied.json()["changed"] == 1

    by_name = {r["name"]: r for r in _gen_page()}
    assert by_name["g1"]["p_nom"] == 80.0
    assert by_name["g2"]["p_nom"] == 200.0  # untouched


def test_static_derive(_session_dir: Path) -> None:
    _load()
    body = {
        "sessionId": "default",
        "target": "generators",
        "attribute": "p_nom_max",
        "temporal": False,
        "filters": [],
        "edit": {"op": "derive", "source_attr": "p_nom", "coefficient": 3.0, "constant": 0.0},
    }
    assert client.post("/api/forge/query/apply", json=body).status_code == 200
    by_name = {r["name"]: r for r in _gen_page()}
    assert by_name["g1"]["p_nom_max"] == 300.0
    assert by_name["g2"]["p_nom_max"] == 600.0


def test_temporal_join_add(_session_dir: Path) -> None:
    _load()
    body = {
        "sessionId": "default",
        "target": "loads",
        "attribute": "p_set",
        "temporal": True,
        "filters": [{"column": "province", "op": "eq", "value": "Seoul",
                     "join": {"component": "buses", "ref_column": "bus"}}],
        "edit": {"op": "add", "amount": 5.0},
    }
    applied = client.post("/api/forge/query/apply", json=body)
    assert applied.status_code == 200, applied.text
    assert applied.json()["seriesSheet"] == "loads-p_set"

    rows = _load_series()
    assert [r["L1"] for r in rows] == [15.0, 17.0]  # +5 on the Seoul load
    assert [r["L2"] for r in rows] == [20.0, 24.0]  # Busan load untouched


def test_temporal_set(_session_dir: Path) -> None:
    _load()
    body = {
        "sessionId": "default",
        "target": "loads",
        "attribute": "p_set",
        "temporal": True,
        "filters": [{"column": "name", "op": "eq", "value": "L2"}],
        "edit": {"op": "set", "amount": 7.0},
    }
    assert client.post("/api/forge/query/apply", json=body).status_code == 200
    rows = _load_series()
    assert [r["L2"] for r in rows] == [7.0, 7.0]
    assert [r["L1"] for r in rows] == [10.0, 12.0]


def test_temporal_set_fills_blank_cells(_session_dir: Path) -> None:
    # A 'set' overwrites every matched cell — including blanks — in one atomic
    # transform, and preview promises exactly that.
    model = {
        "buses": [{"name": "b1", "province": "Seoul"}],
        "loads": [{"name": "L1", "bus": "b1"}],
        "snapshots": [{"snapshot": "2030-01-01T00:00:00"}, {"snapshot": "2030-01-01T01:00:00"}],
        "loads-p_set": [
            {"snapshot": "2030-01-01T00:00:00", "L1": None},
            {"snapshot": "2030-01-01T01:00:00", "L1": 12.0},
        ],
    }
    resp = client.post("/api/session/model", json={"sessionId": "default", "model": model, "filename": "c.xlsx"})
    assert resp.status_code == 200, resp.text
    body = {
        "sessionId": "default", "target": "loads", "attribute": "p_set", "temporal": True,
        "filters": [], "edit": {"op": "set", "amount": 7.0},
    }
    prev = client.post("/api/forge/query/preview", json=body).json()
    # Preview reports period energy: before 12 MWh (one numeric cell), after
    # 7 MW × 2 snapshots × 1 h = 14 MWh — the blank cell counts once set.
    assert prev["sampleKind"] == "energyMwh"
    assert prev["sample"][0] == {"name": "L1", "before": 12.0, "after": 14.0}
    assert client.post("/api/forge/query/apply", json=body).status_code == 200
    rows = _load_series()
    assert [r["L1"] for r in rows] == [7.0, 7.0]  # the blank cell was filled


def test_temporal_add_mwh_total_proportional(_session_dir: Path) -> None:
    # E(L1)=22, E(L2)=44 MWh over the 2 hourly snapshots. +33 MWh on the group
    # total, proportional split → uniform factor (66+33)/66 = 1.5.
    _load()
    body = {
        "sessionId": "default",
        "target": "loads",
        "attribute": "p_set",
        "temporal": True,
        "filters": [],
        "edit": {"op": "add", "amount": 33.0, "unit": "mwh",
                 "scope": "total", "split": "proportional"},
    }
    prev = client.post("/api/forge/query/preview", json=body).json()
    assert prev["energyBeforeMwh"] == pytest.approx(66.0)
    assert prev["energyAfterMwh"] == pytest.approx(99.0)

    assert client.post("/api/forge/query/apply", json=body).status_code == 200
    rows = _load_series()
    assert [r["L1"] for r in rows] == [15.0, 18.0]
    assert [r["L2"] for r in rows] == [30.0, 36.0]


def test_temporal_add_mw_total_equal(_session_dir: Path) -> None:
    _load()
    body = {
        "sessionId": "default",
        "target": "loads",
        "attribute": "p_set",
        "temporal": True,
        "filters": [],
        "edit": {"op": "add", "amount": 10.0, "unit": "mw",
                 "scope": "total", "split": "equal"},
    }
    assert client.post("/api/forge/query/apply", json=body).status_code == 200
    rows = _load_series()
    assert [r["L1"] for r in rows] == [15.0, 17.0]  # +10/2 MW each
    assert [r["L2"] for r in rows] == [25.0, 29.0]


def test_temporal_add_below_zero_rejected(_session_dir: Path) -> None:
    _load()
    body = {
        "sessionId": "default",
        "target": "loads",
        "attribute": "p_set",
        "temporal": True,
        "filters": [{"column": "name", "op": "eq", "value": "L1"}],
        "edit": {"op": "add", "amount": -11.0, "unit": "mw", "scope": "each"},
    }
    resp = client.post("/api/forge/query/apply", json=body)
    assert resp.status_code == 400
    assert "below zero" in resp.json()["detail"]
    rows = _load_series()
    assert [r["L1"] for r in rows] == [10.0, 12.0]  # untouched


def test_temporal_derive_rejected(_session_dir: Path) -> None:
    _load()
    body = {
        "sessionId": "default",
        "target": "loads",
        "attribute": "p_set",
        "temporal": True,
        "filters": [],
        "edit": {"op": "derive", "source_attr": "p_set"},
    }
    assert client.post("/api/forge/query/apply", json=body).status_code == 400
