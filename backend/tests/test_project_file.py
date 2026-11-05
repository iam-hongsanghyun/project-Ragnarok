"""Project file (``project.db``) endpoints and the project's app state.

Round trip: build a file from a model with settings -> open it into a session -> the model and every setting
are there -> download it -> the same file opens again. Plus: app-state read/write, a non-project upload refused,
and a run's input snapshot carrying the settings it was solved with.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import app_state, model_store
from backend.app import session_store as ss


def _model() -> dict:
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(4)]
    return {
        "snapshots": [{"snapshot": s} for s in snaps],
        "buses": [{"name": "zone", "v_nom": 380.0}],
        "carriers": [{"name": "gas"}],
        "generators": [{"name": "gas", "bus": "zone", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 60.0}],
        "loads": [{"name": "demand", "bus": "zone"}],
        "loads-p_set": [{"snapshot": s, "demand": 50.0} for s in snaps],
    }


_STATE = {
    "ragnarok:settings": '{"enabledModules": "Data,Forge", "currencyCode": "KRW"}',
    "ragnarok:session:controls": '{"carbonPrice": 25}',
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "SESSION_DIR", tmp_path / "session")
    from backend.app.main import app

    return TestClient(app)


def test_build_open_download_round_trip(client, tmp_path) -> None:
    built = client.post("/api/project-file/build", json={"model": _model(), "appState": _STATE, "filename": "case.xlsx"})
    assert built.status_code == 200 and built.content.startswith(b"SQLite format 3")
    assert built.headers["content-disposition"].endswith('case.db"')

    opened = client.post("/api/project-file?session_id=pf", files={"file": ("case.db", built.content)})
    assert opened.status_code == 200, opened.text
    assert opened.json()["appState"] == _STATE
    names = [s["name"] for s in opened.json()["meta"]["sheets"]]
    assert {"snapshots", "buses", "generators", "loads-p_set", "RAGNAROK_Schema"} <= set(names)
    assert app_state.SHEET not in names  # settings live in _app_state, not among the sheets
    assert model_store.load_full_model("pf")["generators"][0]["marginal_cost"] == 60.0

    state = client.get("/api/session/app-state?session_id=pf").json()["state"]
    assert state == _STATE

    down = client.get("/api/project-file?session_id=pf")
    assert down.status_code == 200 and down.content.startswith(b"SQLite format 3")
    again = client.post("/api/project-file?session_id=pf2", files={"file": ("x.db", down.content)})
    assert again.status_code == 200 and again.json()["appState"] == _STATE


def test_app_state_endpoints(client) -> None:
    assert client.get("/api/session/app-state?session_id=none").json() == {"state": None}
    assert client.put("/api/session/app-state", json={"sessionId": "none", "state": {"k": "v"}}).status_code == 409
    model_store.save_model("as", _model())
    assert client.get("/api/session/app-state?session_id=as").json() == {"state": {}}
    put = client.put("/api/session/app-state", json={"sessionId": "as", "state": _STATE})
    assert put.json()["state"] == _STATE
    merged = client.put(
        "/api/session/app-state",
        json={"sessionId": "as", "state": {"ragnarok:session:controls": None, "ui:x": "1"}, "replace": False},
    )
    assert merged.json()["state"] == {"ragnarok:settings": _STATE["ragnarok:settings"], "ui:x": "1"}


def test_upload_refuses_a_non_project(client) -> None:
    bad = client.post("/api/project-file?session_id=bad", files={"file": ("x.db", b"not a database at all")})
    assert bad.status_code == 400
    assert model_store.get_meta("bad") is None


def test_run_snapshot_carries_the_settings(client) -> None:
    from backend.app.main import _resolve_payload_model
    from backend.app.models import RunPayload

    model_store.save_model("run", _model())
    model_store.set_app_state("run", _STATE)
    payload = _resolve_payload_model(RunPayload(sessionId="run", scenario={}, options={}))
    assert app_state.from_rows(payload.model[app_state.SHEET]) == _STATE


def test_guide_is_the_spec(client) -> None:
    body = client.get("/api/project-file/guide").json()
    assert body["path"] == "docs/project-file.md" and "_app_state" in body["markdown"]
