"""Session bugs found by Bifrost: lost filename on merge-fragment, 400 on first static sync."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

MODEL = {"buses": [{"name": "b1"}], "generators": [{"name": "g1", "bus": "b1", "p_nom": 10}]}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from backend.app import session_store
    from backend.app.main import app

    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    return TestClient(app)


def test_merge_fragment_apply_keeps_filename_and_scenario(client) -> None:
    sid = "t-label"
    r = client.post("/api/session/model", json={
        "model": MODEL, "sessionId": sid, "filename": "case.xlsx", "scenarioName": "ref"})
    assert r.status_code == 200
    out = client.post("/api/session/merge-fragment", json={
        "sessionId": sid, "fragment": {"sheets": {"buses": [{"name": "b2"}]}}, "apply": True}).json()
    assert out["applied"] is True
    assert out["meta"]["filename"] == "case.xlsx" and out["meta"]["scenarioName"] == "ref"
    meta = client.get("/api/session/meta", params={"session_id": sid}).json()
    assert meta["filename"] == "case.xlsx" and meta["scenarioName"] == "ref"


def test_transform_endpoints_share_the_label_keeping_resave(client) -> None:
    from backend.app import model_store

    sid = "t-resave"
    client.post("/api/session/model", json={"model": MODEL, "sessionId": sid, "filename": "keep.xlsx"})
    model_store.resave_model(sid, {**MODEL, "loads": [{"name": "l1", "bus": "b1"}]})
    assert model_store.get_meta(sid)["filename"] == "keep.xlsx"


def test_static_sync_on_empty_session_seeds_it(client) -> None:
    sid = "t-seed"
    assert client.get("/api/session/meta", params={"session_id": sid}).json() == {}
    r = client.post("/api/session/model/static", json={"model": MODEL, "sessionId": sid})
    assert r.status_code == 200, r.text
    assert r.json()["componentCounts"]["generators"] == 1
    rows = client.get("/api/session/sheet/generators", params={"session_id": sid}).json()["rows"]
    assert rows[0]["name"] == "g1"


def test_static_sync_of_empty_model_creates_nothing(client) -> None:
    sid = "t-seed-empty"
    r = client.post("/api/session/model/static", json={"model": {"buses": [], "generators": []}, "sessionId": sid})
    assert r.status_code == 200 and r.json() == {}
    assert client.get("/api/session/meta", params={"session_id": sid}).json() == {}


def test_static_sync_of_config_only_model_creates_nothing(client) -> None:
    """A fresh editor holds only config sheets (scenarios, ...): nothing worth seeding."""
    sid = "t-seed-config"
    r = client.post("/api/session/model/static", json={
        "model": {"buses": [], "scenarios": [{"name": "Base case"}]}, "sessionId": sid})
    assert r.status_code == 200 and r.json() == {}
    assert client.get("/api/session/meta", params={"session_id": sid}).json() == {}


def test_static_sync_never_overwrites_nonempty_session_series(client) -> None:
    sid = "t-keep"
    client.post("/api/session/model", json={"model": MODEL, "sessionId": sid, "filename": "case.xlsx"})
    r = client.post("/api/session/model/static", json={
        "model": {"buses": [{"name": "b1"}, {"name": "b9"}]}, "sessionId": sid})
    assert r.status_code == 200
    assert r.json()["filename"] == "case.xlsx"
    assert len(client.get("/api/session/sheet/buses", params={"session_id": sid}).json()["rows"]) == 2
