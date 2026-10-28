"""State machine of the self-provisioning pandapower environment (pandapower_env).

subprocess and shutil.which are replaced by a fake that builds the venv layout on
disk and returns scripted pip/probe results, so no network or real venv is needed.
The real build code path (build_now, the lock file, the stamp, the log) still runs.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.mcp import server, tools_components  # noqa: F401  (registers the tools)
from backend.mcp.client import Config, RagnarokClient, RagnarokSettingUp
from backend.pypsa.network import pandapower_env, pypsa_io

FIXTURE = Path(__file__).parent / "fixtures" / "pandapower_example_simple.json"


class FakeTools:
    """Scripted stand-in for ``subprocess.run`` used by the build steps."""

    def __init__(self, *, gate: threading.Event | None = None, pip_rc: int = 0,
                 probe_out: str = "3.5.6\n2.3.3\n") -> None:
        self.gate = gate
        self.reached_install = threading.Event()  # set when the install step starts
        self.pip_rc = pip_rc
        self.probe_out = probe_out
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        if "venv" in argv[:3]:  # python -m venv <dir>  |  uv venv --python X <dir>
            target = Path(argv[-1])
            (target / "bin").mkdir(parents=True, exist_ok=True)
            (target / "bin" / "python").write_text("#!fake interpreter\n", encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, "created venv\n")
        if "install" in argv:
            self.reached_install.set()
            if self.gate is not None:
                self.gate.wait(10)
            if self.pip_rc:
                return subprocess.CompletedProcess(argv, self.pip_rc, "ERROR: No matching distribution\n")
            return subprocess.CompletedProcess(argv, 0, "Successfully installed pandapower\n")
        if "-c" in argv:  # the import probe
            return subprocess.CompletedProcess(argv, 0, self.probe_out)
        raise AssertionError(f"unexpected subprocess call: {argv}")

    def steps(self, word: str) -> list[list[str]]:
        return [c for c in self.calls if word in c]


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point pandapower_env at a temp repo layout, with autosetup on and no override."""
    repo_logs = tmp_path / "logs"
    req = tmp_path / "requirements-pandapower.txt"
    req.write_text("pandapower>=3.5,<4\n", encoding="utf-8")
    monkeypatch.setattr(pandapower_env, "ENV_DIR", tmp_path / ".venv-pandapower")
    monkeypatch.setattr(pandapower_env, "REQUIREMENTS", req)
    monkeypatch.setattr(pandapower_env, "LOG_FILE", repo_logs / "pandapower-setup.log")
    monkeypatch.setattr(pandapower_env, "LOCK_FILE", repo_logs / "pandapower-setup.lock")
    monkeypatch.setattr(pandapower_env, "_thread", None)
    monkeypatch.setattr(pandapower_env, "_error", None)
    monkeypatch.setattr(pandapower_env, "_failed_at", 0.0)
    monkeypatch.setattr(pandapower_env, "_stage", "")
    monkeypatch.delenv("RAGNAROK_PANDAPOWER_PYTHON", raising=False)
    monkeypatch.setenv("RAGNAROK_PANDAPOWER_AUTOSETUP", "on")
    return tmp_path


@pytest.fixture()
def tools(env: Path, monkeypatch: pytest.MonkeyPatch) -> FakeTools:
    fake = FakeTools()
    monkeypatch.setattr(pandapower_env, "subprocess", SimpleNamespace(
        run=fake.run, PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT))
    monkeypatch.setattr(pandapower_env, "shutil", SimpleNamespace(
        which=lambda _name: None, rmtree=pandapower_env.shutil.rmtree))  # no uv on PATH
    return fake


def _wait_idle(timeout: float = 10.0) -> None:
    thread = pandapower_env._thread
    if thread is not None:
        thread.join(timeout)
        assert not thread.is_alive(), "build thread did not finish"


def _write_ready_env(env_dir: Path, stamp: str) -> Path:
    python = pandapower_env.env_python_path()
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("#!fake interpreter\n", encoding="utf-8")
    (env_dir / pandapower_env.STAMP_NAME).write_text(stamp + "\n", encoding="utf-8")
    return python


# ── transitions ───────────────────────────────────────────────────────────────


def test_absent_then_setting_up_then_ready(env: Path, tools: FakeTools, monkeypatch: pytest.MonkeyPatch) -> None:
    gate = threading.Event()
    tools.gate = gate
    assert pandapower_env.status()["state"] == "absent"

    with pytest.raises(pandapower_env.PandapowerSettingUp) as info:
        pandapower_env.require_python()
    assert info.value.retry_after_s == pandapower_env.RETRY_AFTER_S

    assert tools.reached_install.wait(10), "build never reached the install step"
    during = pandapower_env.status()
    assert during["state"] == "setting_up"
    assert during["retryAfterSeconds"] == pandapower_env.RETRY_AFTER_S
    assert "installing pandapower" in during["stage"]
    assert pandapower_env.LOCK_FILE.exists()

    # A second request while the build runs must not start a second build.
    with pytest.raises(pandapower_env.PandapowerSettingUp):
        pandapower_env.require_python()
    assert len(tools.steps("venv")) == 1

    gate.set()
    _wait_idle()
    ready = pandapower_env.status()
    assert ready["state"] == "ready"
    assert ready["python"] == str(pandapower_env.env_python_path())
    assert pandapower_env.require_python() == pandapower_env.env_python_path()
    assert not pandapower_env.LOCK_FILE.exists()
    stamp = (pandapower_env.ENV_DIR / pandapower_env.STAMP_NAME).read_text(encoding="utf-8").strip()
    assert stamp == pandapower_env.requirements_hash()

    # The steps ran in order and the install used the requirements file, not a hardcoded spec.
    assert tools.calls[0][1:3] == ["-m", "venv"]
    assert any(c[-2:] == ["-r", str(pandapower_env.REQUIREMENTS)] for c in tools.steps("install"))
    log = pandapower_env.LOG_FILE.read_text(encoding="utf-8")
    assert "-- creating environment" in log and "-- ready" in log
    assert "pandapower 3.5.6 / pandas 2.3.3" in log


def test_uv_is_used_when_on_path(env: Path, tools: FakeTools, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pandapower_env, "shutil", SimpleNamespace(
        which=lambda name: "/usr/local/bin/uv" if name == "uv" else None,
        rmtree=pandapower_env.shutil.rmtree))
    pandapower_env.build_now(_null_log())
    assert tools.calls[0][:2] == ["/usr/local/bin/uv", "venv"]
    assert tools.calls[1][:3] == ["/usr/local/bin/uv", "pip", "install"]
    assert "--python" in tools.calls[1]


def test_failed_build_reports_error_then_retries_after_window(env: Path, tools: FakeTools,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    tools.pip_rc = 1
    with pytest.raises(pandapower_env.PandapowerSettingUp):
        pandapower_env.require_python()
    _wait_idle()

    failed = pandapower_env.status()
    assert failed["state"] == "failed"
    assert "exited with code 1" in failed["error"]
    with pytest.raises(pandapower_env.PandapowerUnavailable) as info:
        pandapower_env.require_python()
    assert not isinstance(info.value, pandapower_env.PandapowerSettingUp)
    assert str(pandapower_env.LOG_FILE) in str(info.value)
    assert "setup failed" in str(info.value)
    assert "No matching distribution" in pandapower_env.LOG_FILE.read_text(encoding="utf-8")
    assert not pandapower_env.LOCK_FILE.exists()

    # Inside the retry window nothing new is started.
    assert len(tools.steps("venv")) == 1

    # After the window the next request retries: the failure was transient.
    tools.pip_rc = 0
    monkeypatch.setattr(pandapower_env, "_failed_at", time.time() - pandapower_env.RETRY_FAILED_AFTER_S - 1)
    assert pandapower_env.status()["state"] == "absent"
    with pytest.raises(pandapower_env.PandapowerSettingUp):
        pandapower_env.require_python()
    _wait_idle()
    assert pandapower_env.status()["state"] == "ready"


def test_wrong_pandas_major_fails_the_build(env: Path, tools: FakeTools) -> None:
    tools.probe_out = "3.5.6\n3.0.5\n"
    with pytest.raises(RuntimeError, match="expected pandas 2.x"):
        pandapower_env.build_now(_null_log())


def test_probe_ignores_import_warnings_before_versions(env: Path, tools: FakeTools) -> None:
    tools.probe_out = "UserWarning: something noisy\n3.5.6\n2.3.3\n"
    pandapower_env.build_now(_null_log())
    assert (pandapower_env.ENV_DIR / pandapower_env.STAMP_NAME).is_file()


def test_current_env_is_ready_without_any_subprocess(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_ready_env(pandapower_env.ENV_DIR, pandapower_env.requirements_hash())

    def boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("status() and require_python() must not run subprocesses")

    monkeypatch.setattr(pandapower_env, "subprocess", SimpleNamespace(run=boom))
    assert pandapower_env.status()["state"] == "ready"
    assert pandapower_env.require_python() == pandapower_env.env_python_path()


def test_changed_requirements_rebuild_in_place(env: Path, tools: FakeTools) -> None:
    """A stamp from older requirements triggers a reinstall into the existing venv."""
    _write_ready_env(pandapower_env.ENV_DIR, "0" * 64)
    assert pandapower_env.status()["state"] == "absent"
    with pytest.raises(pandapower_env.PandapowerSettingUp):
        pandapower_env.require_python()
    _wait_idle()
    assert pandapower_env.status()["state"] == "ready"
    assert tools.steps("venv") == []  # interpreter kept; only pip ran
    assert len(tools.steps("install")) == 1


def test_broken_leftover_directory_is_removed_before_rebuild(env: Path, tools: FakeTools) -> None:
    (pandapower_env.ENV_DIR / "half-written").mkdir(parents=True)
    pandapower_env.build_now(_null_log())
    assert tools.steps("venv"), "a directory without an interpreter must be rebuilt"
    assert not (pandapower_env.ENV_DIR / "half-written").exists()


# ── disabled, override, cross-process lock ───────────────────────────────────


def test_autosetup_off_is_disabled_and_starts_nothing(env: Path, tools: FakeTools,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAGNAROK_PANDAPOWER_AUTOSETUP", "off")
    assert pandapower_env.status()["state"] == "disabled"
    with pytest.raises(pandapower_env.PandapowerUnavailable) as info:
        pandapower_env.require_python()
    assert "RAGNAROK_PANDAPOWER_AUTOSETUP=off" in str(info.value)
    assert pandapower_env._thread is None
    assert tools.calls == []


def test_override_interpreter_is_used_and_never_built(env: Path, tools: FakeTools,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    interp = env / "elsewhere" / "python"
    interp.parent.mkdir()
    interp.write_text("#!fake\n", encoding="utf-8")
    monkeypatch.setenv("RAGNAROK_PANDAPOWER_PYTHON", str(interp))
    assert pandapower_env.status()["state"] == "ready"
    assert pandapower_env.require_python() == interp
    assert pandapower_env._thread is None and tools.calls == []


def test_missing_override_interpreter_is_failed_with_reason(env: Path, tools: FakeTools,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAGNAROK_PANDAPOWER_PYTHON", str(env / "nope" / "python"))
    st = pandapower_env.status()
    assert st["state"] == "failed"
    assert "does not exist" in st["error"]
    with pytest.raises(pandapower_env.PandapowerUnavailable):
        pandapower_env.require_python()
    assert tools.calls == []


def test_build_held_by_another_process_is_reported_not_repeated(env: Path, tools: FakeTools) -> None:
    pandapower_env.LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    pandapower_env.LOCK_FILE.write_text("4242 now\n", encoding="utf-8")
    st = pandapower_env.status()
    assert st["state"] == "setting_up"
    assert "another Ragnarok process" in st["stage"]
    pandapower_env.start()
    assert pandapower_env._thread is None and tools.calls == []


def test_stale_lock_from_a_dead_build_is_taken_over(env: Path, tools: FakeTools) -> None:
    pandapower_env.LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    pandapower_env.LOCK_FILE.write_text("4242 long ago\n", encoding="utf-8")
    old = time.time() - pandapower_env.LOCK_STALE_S - 60
    os.utime(pandapower_env.LOCK_FILE, (old, old))
    assert pandapower_env.status()["state"] == "absent"
    with pytest.raises(pandapower_env.PandapowerSettingUp):
        pandapower_env.require_python()
    _wait_idle()
    assert pandapower_env.status()["state"] == "ready"


# ── HTTP and MCP surfaces ─────────────────────────────────────────────────────


def _setting_up_error() -> pandapower_env.PandapowerSettingUp:
    return pandapower_env.PandapowerSettingUp({"state": "setting_up", "stage": "installing pandapower",
                                               "log": "x", "envDir": "y", "retryAfterSeconds": 15})


def test_endpoint_returns_202_with_retry_hint_and_leaves_model_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    def pending(_text: str) -> None:
        raise _setting_up_error()

    monkeypatch.setattr(pypsa_io, "pandapower_dump_via_subprocess", pending)
    r = TestClient(app).post("/api/import/pandapower", files={"file": ("n.json", FIXTURE.read_bytes())})
    assert r.status_code == 202
    assert r.headers["Retry-After"] == "15"
    body = r.json()
    assert body["status"] == "setting_up"
    assert body["retryAfterSeconds"] == 15
    assert "retry" in body["detail"].lower()
    assert body["pandapowerSetup"]["stage"] == "installing pandapower"


def test_endpoint_is_501_with_reason_when_disabled(env: Path, tools: FakeTools,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAGNAROK_PANDAPOWER_AUTOSETUP", "off")
    r = TestClient(app).post("/api/import/pandapower", files={"file": ("n.json", FIXTURE.read_bytes())})
    assert r.status_code == 501
    assert "RAGNAROK_PANDAPOWER_AUTOSETUP=off" in r.json()["detail"]


def test_capabilities_expose_setup_state(env: Path, tools: FakeTools) -> None:
    caps = TestClient(app).get("/api/import/pypsa-io/capabilities").json()
    assert caps["pandapowerInstalled"] is False
    assert caps["pandapowerSetup"]["state"] == "absent"  # autosetup on, nothing built, nothing started


def test_mcp_import_returns_setting_up_and_does_not_replace_model(env: Path, monkeypatch: pytest.MonkeyPatch,
                                                                 tmp_path: Path) -> None:
    """An agent gets status=setting_up; the client never saves the empty 202 body as a model."""
    saved: list[Any] = []

    def pending(_text: str) -> None:
        raise _setting_up_error()

    monkeypatch.setattr(pypsa_io, "pandapower_dump_via_subprocess", pending)
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", "auto")
    monkeypatch.setattr(server, "_FILE_DIR", tmp_path)
    (tmp_path / "net.json").write_bytes(FIXTURE.read_bytes())
    client = RagnarokClient(
        Config(api_base="http://testserver", session_id="t", timeout=30.0),
        transport=httpx.ASGITransport(app=app),
    )

    async def save_model(model: Any) -> None:
        saved.append(model)

    client.save_model = save_model  # type: ignore[method-assign]
    monkeypatch.setattr(server, "_client", client)

    out = asyncio.run(tools_components.import_pypsa_native("net.json"))
    assert out["status"] == "setting_up"
    assert out["model_changed"] is False
    assert out["retry_after_seconds"] == 15
    assert saved == []


def test_client_raises_setting_up_for_202_body() -> None:
    body = {"detail": "wait", "status": "setting_up", "retryAfterSeconds": 9, "pandapowerSetup": {"state": "setting_up"}}
    with pytest.raises(RagnarokSettingUp) as info:
        _raise_from_upload(body)
    assert info.value.retry_after_s == 9


def _raise_from_upload(body: dict[str, Any]) -> None:
    """Drive RagnarokClient.import_pypsa_file with a canned upload result."""
    client = RagnarokClient(Config(api_base="http://x", session_id="t", timeout=5.0))

    async def fake_upload(*_a: Any, **_k: Any) -> dict[str, Any]:
        return body

    client._upload = fake_upload  # type: ignore[method-assign]
    asyncio.run(client.import_pypsa_file("pandapower", b"{}", "n.json"))


# ── helpers ───────────────────────────────────────────────────────────────────


class _null_log:
    """Discarding text sink for build_now."""

    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        return None
