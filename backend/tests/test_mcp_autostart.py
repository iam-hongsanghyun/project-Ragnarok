"""Tests for the MCP backend autostart (backend/mcp/autostart.py).

No PyPSA stack is needed: the backend is a tiny stand-in HTTP server that answers
``/api/health`` and ``/api/identity`` the way the real app does. Real loopback
sockets and real child processes are used, so the reuse / refuse / spawn / stop
decisions are exercised end to end.
"""

from __future__ import annotations

import http.server
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from backend.mcp import autostart
from backend.mcp.autostart import AutostartConfig, AutostartError

_FAKE_BACKEND = '''
import http.server, json, sys, time
port, root, delay = int(sys.argv[1]), sys.argv[2], float(sys.argv[3])
time.sleep(delay)  # simulate a slow first start: nothing listens until then
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/health"):
            body, code = {"status": "ok"}, 200
        elif self.path.startswith("/api/identity"):
            body, code = {"app": "ragnarok", "root": root}, 200
        else:
            body, code = {"detail": "nope"}, 404
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def log_message(self, *args):
        pass
http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
'''


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _serve_in_thread(port: int, payload: dict[str, Any] | None, status: int = 200) -> http.server.HTTPServer:
    """A stand-in backend (or a foreign program) on ``port``. ``payload=None`` means 404 everywhere."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if payload is None:
                code, body = 404, b"not found"
            else:
                code, body = status, json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, port: int, repo: Path) -> AutostartConfig:
    monkeypatch.setenv("RAGNAROK_MCP_AUTOSTART", "1")
    monkeypatch.setenv("RAGNAROK_API_BASE", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("RAGNAROK_REPO_ROOT", str(repo))
    monkeypatch.setenv("RAGNAROK_CONNECTOR_DIR", str(tmp_path / "connector"))
    monkeypatch.setenv("RAGNAROK_AUTOSTART_TIMEOUT", "20")
    monkeypatch.delenv("RAGNAROK_FRONTEND_DIST", raising=False)
    return AutostartConfig.from_env()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "ragnarok"
    (root / "backend" / "mcp").mkdir(parents=True)
    return root


def test_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAGNAROK_MCP_AUTOSTART", raising=False)
    assert autostart.start_from_env() is None


def test_remote_api_base_never_autostarts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repo: Path) -> None:
    _config(monkeypatch, tmp_path, 8123, repo)
    monkeypatch.setenv("RAGNAROK_API_BASE", "http://10.20.30.40:8000")
    assert autostart.start_from_env() is None


def test_reuses_ragnarok_backend_for_the_same_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repo: Path
) -> None:
    port = _free_port()
    server = _serve_in_thread(port, {"app": "ragnarok", "root": str(repo)})
    try:
        config = _config(monkeypatch, tmp_path, port, repo)

        def no_spawn(*_: Any, **__: Any) -> None:
            raise AssertionError("must reuse, not spawn")

        monkeypatch.setattr(autostart, "_spawn", no_spawn)
        handle = autostart.ensure_backend(config)
        assert handle.owned is False
    finally:
        server.shutdown()


def test_refuses_a_foreign_program_on_the_port(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repo: Path) -> None:
    port = _free_port()
    server = _serve_in_thread(port, None)
    try:
        config = _config(monkeypatch, tmp_path, port, repo)
        with pytest.raises(AutostartError) as info:
            autostart.ensure_backend(config)
        assert str(port) in str(info.value)
        assert "not Ragnarok" in str(info.value)
    finally:
        server.shutdown()


def test_refuses_a_ragnarok_checkout_at_another_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repo: Path
) -> None:
    port = _free_port()
    other = tmp_path / "other-clone"
    server = _serve_in_thread(port, {"app": "ragnarok", "root": str(other)})
    try:
        config = _config(monkeypatch, tmp_path, port, repo)
        with pytest.raises(AutostartError) as info:
            autostart.ensure_backend(config)
        assert str(other) in str(info.value)
        assert str(repo) in str(info.value)
    finally:
        server.shutdown()


@pytest.mark.skipif(os.name == "nt", reason="process-group stop is POSIX-only in this test")
def test_spawns_waits_for_health_and_stops_its_own_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repo: Path
) -> None:
    port = _free_port()
    fake = tmp_path / "fake_backend.py"
    fake.write_text(_FAKE_BACKEND, encoding="utf-8")
    config = _config(monkeypatch, tmp_path, port, repo)
    handle = autostart.ensure_backend(config, command=[sys.executable, str(fake), str(port), str(repo), "1.0"])
    try:
        assert handle.owned is True and handle.pid is not None
        assert autostart._port_open("127.0.0.1", port)
        state = json.loads(config.state_path.read_text(encoding="utf-8"))
        assert state["pid"] == handle.pid and state["owner"] == os.getpid()
    finally:
        autostart._current = handle
        autostart.stop_owned()
    deadline = time.monotonic() + 5
    while autostart._port_open("127.0.0.1", port) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not autostart._port_open("127.0.0.1", port)
    assert not config.state_path.exists()


@pytest.mark.skipif(os.name == "nt", reason="uses POSIX exit semantics")
def test_reports_the_exit_code_when_the_backend_dies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repo: Path
) -> None:
    config = _config(monkeypatch, tmp_path, _free_port(), repo)
    with pytest.raises(AutostartError) as info:
        autostart.ensure_backend(config, command=[sys.executable, "-c", "import sys; sys.exit(2)"])
    assert "exited with code 2" in str(info.value)
    assert str(config.log_path) in str(info.value)


def test_failure_is_marked_on_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    port = _free_port()
    server = _serve_in_thread(port, None)
    try:
        _config(monkeypatch, tmp_path, port, repo)
        with pytest.raises(AutostartError):
            autostart.start_from_env()
        captured = capsys.readouterr()
        assert captured.out == ""  # stdout is the MCP channel: nothing may be written there
        assert autostart.FAILURE_MARKER in captured.err
    finally:
        server.shutdown()
