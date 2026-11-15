"""Live updates for everything an agent can change: ``server.changed`` events and the session list."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.app import change_events, events_bus, journal, model_store
from backend.app import session_store as ss
from backend.app.actor_context import ActorContextMiddleware


@pytest.fixture()
def published(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    seen: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(events_bus, "publish_all", lambda event, data: seen.append((event, data)) or 1)
    return seen


@pytest.mark.parametrize(("method", "path", "area"), [
    ("POST", "/api/modules/install-path", "modules"),
    ("DELETE", "/api/modules/foo", "modules"),
    ("POST", "/api/queue/submit", "queue"),
    ("PATCH", "/api/runs/r1", "runs"),
    ("GET", "/api/modules", None),                    # a read
    ("POST", "/api/control-panel/preview", None),     # a POST that only reads
    ("POST", "/api/model-check", None),
    ("POST", "/api/session/model", None),             # the journal announces model changes
    ("POST", "/other/path", None),
    ("POST", "/api", None),
])
def test_change_area(method: str, path: str, area: str | None) -> None:
    assert change_events.change_area(method, path) == area


def _app() -> FastAPI:
    app = FastAPI()

    @app.post("/api/modules/ok")
    def ok() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/modules/bad")
    def bad() -> dict[str, bool]:
        raise HTTPException(status_code=400, detail="no")

    @app.post("/api/modules/preview")
    def preview() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(change_events.ChangeEventsMiddleware)
    app.add_middleware(ActorContextMiddleware)
    return app


def test_successful_write_is_announced_with_its_actor(published: list) -> None:
    client = TestClient(_app())
    assert client.post("/api/modules/ok", headers={"X-Ragnarok-Actor": "mcp"}).status_code == 200
    assert published == [("server.changed", {"area": "modules", "path": "/api/modules/ok", "method": "POST",
                                             "actor": "mcp"})]


def test_failed_write_and_read_only_post_are_not_announced(published: list) -> None:
    client = TestClient(_app())
    assert client.post("/api/modules/bad").status_code == 400
    assert client.post("/api/modules/preview").status_code == 200
    assert published == []


def test_publish_all_reaches_every_open_channel() -> None:
    events_bus.publish("chan-a", "noop", {})
    events_bus.publish("chan-b", "noop", {})
    assert events_bus.publish_all("server.changed", {"area": "x"}) >= 2
    for name in ("chan-a", "chan-b"):
        assert events_bus._channels[name].ring[-1][1:] == ("server.changed", {"area": "x"})


@pytest.fixture()
def sessions_root(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ss, "SESSION_DIR", tmp_path / "session")
    monkeypatch.setenv("RAGNAROK_JOURNAL_DIR", str(tmp_path / "journal"))
    journal.wrap_model_store()
    return tmp_path / "session"


def _model(n: int) -> dict[str, list[dict[str, Any]]]:
    return {"buses": [{"name": f"b{i}"} for i in range(n)], "snapshots": [{"snapshot": "2030-01-01 00:00"}]}


def test_list_sessions_lists_projects_newest_first_and_creates_nothing(sessions_root) -> None:
    assert model_store.list_sessions() == []
    model_store.save_model("alpha", _model(1), filename="alpha.xlsx")
    model_store.save_model("bifrost", _model(3), filename="agent.xlsx")
    (sessions_root / "empty").mkdir()  # a folder with no project is not a session
    listed = model_store.list_sessions()
    assert [s["id"] for s in listed] == ["bifrost", "alpha"]
    assert listed[0]["filename"] == "agent.xlsx"
    assert listed[0]["componentCounts"].get("buses") == 3
    assert sorted(p.name for p in sessions_root.iterdir()) == ["alpha", "bifrost", "empty"]


def test_session_counts_follow_an_edit(sessions_root) -> None:
    model_store.save_model("bifrost", _model(3), filename="agent.xlsx")
    model_store.patch_sheet("bifrost", "buses", [{"op": "addRow", "values": {"name": "added"}}])
    (listed,) = model_store.list_sessions()
    assert listed["componentCounts"]["buses"] == 4


def test_a_journaled_change_tells_every_screen_which_session_changed(sessions_root, published: list) -> None:
    model_store.save_model("bifrost", _model(2), filename="agent.xlsx")
    sessions = [d for e, d in published if e == "server.changed" and d.get("area") == "sessions"]
    assert sessions and sessions[-1]["sessionId"] == "bifrost"


def test_sessions_route() -> None:
    from backend.app.main import app

    body = TestClient(app).get("/api/sessions").json()
    assert isinstance(body["sessions"], list)


def test_own_port_reads_uvicorn_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app import backends_registry as br

    monkeypatch.delenv("RAGNAROK_PORT", raising=False)
    assert br.own_port(["uvicorn", "backend.app.main:app", "--port", "52185"]) == 52185
    assert br.own_port(["uvicorn", "--port=9001"]) == 9001
    assert br.own_port(["uvicorn"]) == 8000
    monkeypatch.setenv("RAGNAROK_PORT", "7000")
    assert br.own_port(["uvicorn", "--port", "1"]) == 7000


def test_registry_keeps_live_backends_and_drops_dead_ones(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    import os

    from backend.app import backends_registry as br

    monkeypatch.setenv("RAGNAROK_REGISTRY_DIR", str(tmp_path / "reg"))
    monkeypatch.setenv("RAGNAROK_PORT", "8123")
    written = br.register_self()
    assert written is not None and json.loads(written.read_text())["port"] == 8123
    dead = tmp_path / "reg" / "999999.json"
    dead.write_text(json.dumps({"pid": 999999, "port": 9, "dataDir": ""}))
    entries = br._from_registry()
    assert [e["pid"] for e in entries] == [os.getpid()]
    assert not dead.exists()
    br.unregister_self()
    assert br._from_registry() == []


def test_resolve_folder_rejects_what_cannot_be_a_working_folder(tmp_path) -> None:
    from backend.app import backends_registry as br

    assert br.resolve_folder(str(tmp_path / "new")) == (tmp_path / "new").resolve()
    for bad in ("", "relative/path", str(tmp_path / "missing" / "deeper")):
        with pytest.raises(br.FolderError):
            br.resolve_folder(bad)
    (tmp_path / "file.txt").write_text("x")
    with pytest.raises(br.FolderError):
        br.resolve_folder(str(tmp_path / "file.txt"))


def test_default_folder_is_written_to_and_removed_from_the_env_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend import env_file
    from backend.app import backends_registry as br

    env = tmp_path / ".env"
    env.write_text("RAGNAROK_QUEUE_CONCURRENCY=2\nRAGNAROK_DATA_DIR=/old\n")
    monkeypatch.setattr(env_file, "ENV_FILE", env)
    out = br.set_default_folder(str(tmp_path / "proj"))
    assert out["default"] == str((tmp_path / "proj").resolve()) and out["savedInEnvFile"]
    assert env.read_text().splitlines() == ["RAGNAROK_QUEUE_CONCURRENCY=2", f"RAGNAROK_DATA_DIR={(tmp_path / 'proj').resolve()}"]
    out = br.set_default_folder("")
    assert not out["savedInEnvFile"] and env.read_text() == "RAGNAROK_QUEUE_CONCURRENCY=2\n"


def test_stop_backend_refuses_one_ragnarok_did_not_start(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    import os

    from backend.app import backends_registry as br

    monkeypatch.setenv("RAGNAROK_REGISTRY_DIR", str(tmp_path / "reg"))
    (tmp_path / "reg").mkdir()
    (tmp_path / "reg" / "1.json").write_text(json.dumps({"pid": os.getppid(), "port": 52185, "dataDir": "/x"}))
    with pytest.raises(br.FolderError, match="not started from Ragnarok"):
        br.stop_backend(52185)
    with pytest.raises(br.FolderError, match="No backend"):
        br.stop_backend(1)


def test_pick_folder_returns_the_chosen_folder_or_none(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from backend.app import backends_registry as br

    monkeypatch.setattr(br.sys, "platform", "darwin")
    seen: list[list[str]] = []

    def fake_run(cmd, **_kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{tmp_path}/\n", stderr="")

    monkeypatch.setattr(br.subprocess, "run", fake_run)
    assert br.pick_folder(str(tmp_path)) == str(tmp_path.resolve())
    assert seen[0][0] == "osascript" and str(tmp_path) in seen[0][2]
    monkeypatch.setattr(br.subprocess, "run", lambda cmd, **_kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="cancel"))
    assert br.pick_folder() is None
