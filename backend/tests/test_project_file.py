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


# ── template -> open -> run as it is ─────────────────────────────────────────────


def test_template_opens_and_runs_with_the_settings_it_states(client) -> None:
    """The xlsx template, imported like a user's file, carries its run settings and monthly limits into the run:
    rolling 744 h windows, and the hydro plant's January (40 000 MWh) and February (30 000 MWh) budgets hold."""
    import pandas as pd

    from backend.app import project_workbook
    from backend.app.main import _resolve_payload_model
    from backend.app.models import RunPayload
    from backend.pypsa.results import run_pypsa

    resp = client.get("/api/project-file/template?format=xlsx")
    assert resp.status_code == 200
    bundle = project_workbook.import_bundle_from_upload(resp.content, "ragnarok_template.xlsx")
    model = bundle["model"]
    assert "RAGNAROK_RunSettings" in model and "RAGNAROK_PeriodBudgets" in model and "README" not in model
    model_store.save_model("tpl", model, filename="ragnarok_template.xlsx")
    stored = model_store.load_full_model("tpl")
    assert "RAGNAROK_RunSettings" not in stored and "RAGNAROK_PeriodBudgets" in stored

    settings = {r["setting"]: r["value"] for r in client.get("/api/session/run-settings?session_id=tpl").json()["settings"]}
    assert settings["rolling"] is True and settings["rollingWindowHours"] == 744 and settings["currencyCode"] == "USD"

    payload = _resolve_payload_model(RunPayload(sessionId="tpl", scenario={}, options={}))
    assert payload.options["rollingConfig"]["enabled"] is True
    assert payload.options["rollingConfig"]["horizonSnapshots"] == 124  # 744 h / 6 h
    res = run_pypsa(payload.model, payload.scenario, payload.options)  # exactly what the file states
    frame = pd.DataFrame(res["outputs"]["series"]["generators-p"])
    frame["month"] = pd.to_datetime(frame["snapshot"]).dt.strftime("%Y-%m")
    hydro = {m: float(g["hydro_north"].sum() * 6) for m, g in frame.groupby("month")}
    assert hydro["2030-01"] <= 40_000 * (1 + 1e-6) and hydro["2030-02"] <= 30_000 * (1 + 1e-6)
    gas_t = float(frame["gas_north"].sum() * 6) * 0.2 / 0.5
    assert gas_t <= 250_000 * (1 + 1e-6)  # the whole-run CO2 budget
    assert hydro["2030-01"] == pytest.approx(40_000, rel=1e-6)  # cheap hydro uses its whole monthly budget


def test_run_settings_round_trip_and_validation(client) -> None:
    model_store.save_model("rs", _model())
    bad = client.put("/api/session/run-settings", json={"sessionId": "rs", "values": {"solverType": "magic"}})
    assert bad.status_code == 400 and "auto" in bad.json()["detail"]
    unknown = client.put("/api/session/run-settings", json={"sessionId": "rs", "values": {"nope": 1}})
    assert unknown.status_code == 400 and "Known" in unknown.json()["detail"]
    ok = client.put("/api/session/run-settings", json={"sessionId": "rs", "values": {
        "windowStart": "2030-01-01T01:00:00", "windowEnd": "2030-01-01T02:00:00", "carbonPrice": 30, "rolling": True,
        "rollingWindowHours": 2, "rollingOverlapHours": 0}})
    assert ok.status_code == 200, ok.text
    table = {r["setting"]: r["value"] for r in ok.json()["settings"]}
    assert table["windowStart"] == "2030-01-01T01:00:00" and table["windowEnd"] == "2030-01-01T02:00:00"
    assert table["carbonPrice"] == 30 and table["rolling"] is True
    from backend.app import run_settings

    scenario, options = run_settings.payload_defaults(model_store.get_app_state("rs"))
    assert options["snapshotStart"] == 1 and options["snapshotEnd"] == 3 and scenario["carbonPrice"] == 30
    # an exported workbook carries the sheet back, and opening it again applies it
    from backend.app.main import _model_with_session_series

    exported = _model_with_session_series(None, "rs")
    rows = {r["setting"]: r["value"] for r in exported["RAGNAROK_RunSettings"]}
    assert rows["carbonPrice"] == 30
    rows_edit = [{**r, "value": 55} if r["setting"] == "carbonPrice" else r for r in exported["RAGNAROK_RunSettings"]]
    model_store.save_model("rs2", {**exported, "RAGNAROK_RunSettings": rows_edit})
    again = {r["setting"]: r["value"] for r in client.get("/api/session/run-settings?session_id=rs2").json()["settings"]}
    assert again["carbonPrice"] == 55 and again["rolling"] is True


def test_rfnbo_settings_live_in_the_project(client, tmp_path, monkeypatch) -> None:
    from backend.app.p2x import config_store

    model_store.save_model("p2x", _model())
    norm = config_store.set_rfnbo_config("p2x", {"enabled": True})
    assert config_store.get_rfnbo_config("p2x") == norm
    assert config_store.APP_STATE_KEY in (model_store.get_app_state("p2x") or {})
