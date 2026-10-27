"""Start the Ragnarok backend for the MCP server when nothing answers on its port.

Opt-in. Runs only when ``RAGNAROK_MCP_AUTOSTART`` is truthy. The Claude Desktop
connector (``connector/``) sets it; a plain ``python -m backend.mcp`` leaves it
unset, so existing setups behave exactly as before.

Control flow (no mathematics):

1. Nothing listens on the API port -> start ``uvicorn`` as a detached child of
   this process and mark it *owned*. Owned backends are stopped on exit.
2. Something listens and ``/api/identity`` reports app ``ragnarok`` with this
   checkout's root -> reuse it (not owned). If the backend recorded as owned by
   a launcher that has since died is still alive, take ownership of it.
3. Anything else on the port (another program, or a Ragnarok checkout at a
   different path) -> refuse, naming the port and the holder.
4. Poll ``/api/health`` until it answers 200 or the timeout elapses.

Environment (all optional):

* ``RAGNAROK_MCP_AUTOSTART``: ``1``/``true`` enables it (default off).
* ``RAGNAROK_API_BASE``: the backend URL. Only loopback hosts are autostarted;
  a remote URL disables autostart.
* ``RAGNAROK_REPO_ROOT``: checkout root (default: the checkout this file is in).
* ``RAGNAROK_CONNECTOR_DIR``: holds ``logs/backend.log`` and ``backend.json``
  (default ``<repo>/.connector``).
* ``RAGNAROK_FRONTEND_DIST``: built GUI to serve (default ``<repo>/build`` when present).
* ``RAGNAROK_AUTOSTART_TIMEOUT``: seconds to wait for ``/api/health`` (default 300).

Output: log records go to stderr only. stdout is the MCP stdio channel and must
never carry anything else. The backend's own output goes to ``backend.log``.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger("ragnarok.mcp.autostart")

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})
DEFAULT_API_BASE = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 300.0
# The connector reads this marker from the child's stderr to show a reason.
FAILURE_MARKER = "RAGNAROK_AUTOSTART_FAILED:"
EXIT_CODE_FAILED = 3

_PROBE_TIMEOUT_SECONDS = 3.0
_POLL_SECONDS = 0.5
_STOP_GRACE_SECONDS = 10.0
_TRUTHY = frozenset({"1", "true", "yes", "on"})
# Proxy-free opener: a user's HTTP_PROXY must never route the loopback probe.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class AutostartError(RuntimeError):
    """The backend can neither be reused nor started. The message names the fix."""


@dataclass(frozen=True)
class AutostartConfig:
    """Autostart settings read from the environment."""

    enabled: bool
    api_base: str
    host: str
    port: int
    repo_root: Path
    connector_dir: Path
    timeout_seconds: float

    @property
    def is_local(self) -> bool:
        return self.host in LOOPBACK_HOSTS

    @property
    def state_path(self) -> Path:
        return self.connector_dir / "backend.json"

    @property
    def log_path(self) -> Path:
        return self.connector_dir / "logs" / "backend.log"

    @classmethod
    def from_env(cls) -> AutostartConfig:
        """Read the autostart settings from ``os.environ``."""
        repo_env = os.environ.get("RAGNAROK_REPO_ROOT", "").strip()
        repo_root = Path(repo_env or Path(__file__).resolve().parents[2]).resolve()
        api_base = (os.environ.get("RAGNAROK_API_BASE", "").strip() or DEFAULT_API_BASE).rstrip("/")
        parts = urlsplit(api_base)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        connector_env = os.environ.get("RAGNAROK_CONNECTOR_DIR", "").strip()
        connector_dir = Path(connector_env) if connector_env else repo_root / ".connector"
        timeout = float(
            os.environ.get("RAGNAROK_AUTOSTART_TIMEOUT", "").strip() or DEFAULT_TIMEOUT_SECONDS
        )
        return cls(
            enabled=os.environ.get("RAGNAROK_MCP_AUTOSTART", "").strip().lower() in _TRUTHY,
            api_base=api_base,
            host=parts.hostname or "",
            port=port,
            repo_root=repo_root,
            connector_dir=connector_dir,
            timeout_seconds=timeout,
        )


@dataclass
class BackendHandle:
    """A backend this process is using. ``owned`` means we must stop it on exit."""

    owned: bool
    pid: int | None
    proc: subprocess.Popen[bytes] | None
    state_path: Path


_current: BackendHandle | None = None


# ── HTTP / socket probes ────────────────────────────────────────────────────────
def _get_json(url: str, timeout: float = _PROBE_TIMEOUT_SECONDS) -> tuple[int, Any] | None:
    """GET ``url``; return ``(status, parsed_json_or_None)``, or None if nothing answered."""
    try:
        with _OPENER.open(url, timeout=timeout) as resp:
            status = resp.status
            body = resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (OSError, ValueError):
        return None
    try:
        return status, json.loads(body)
    except ValueError:
        return status, None


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def _port_bindable(host: str, port: int) -> bool:
    """True if a server bound the same way uvicorn binds could take the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _port_holder(port: int) -> str:
    """Best-effort name of the process listening on ``port`` (POSIX, via lsof)."""
    if os.name != "posix" or shutil.which("lsof") is None:
        return "another program"
    try:
        out = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpc"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "another program"
    pid = command = None
    for line in out.splitlines():
        if line.startswith("p"):
            pid = line[1:]
        elif line.startswith("c") and pid is not None:
            command = line[1:]
            break
    if command is None:
        return "another program"
    return f"{command} (pid {pid})"


# ── process helpers ─────────────────────────────────────────────────────────────
def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _looks_like_backend(pid: int) -> bool:
    """Guard against PID reuse before we ever signal a recorded PID (POSIX only)."""
    if os.name == "nt":
        return True
    try:
        out = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "backend.app.main:app" in out


def _terminate(pid: int, proc: subprocess.Popen[bytes] | None) -> None:
    """Stop the backend's whole process tree: SIGTERM, then SIGKILL after a grace period."""

    def gone(timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc is not None:
                if proc.poll() is not None:
                    return True
            elif not _pid_alive(pid):
                return True
            time.sleep(0.2)
        return False

    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/PID", str(pid)], capture_output=True, check=False)
        if not gone(_STOP_GRACE_SECONDS):
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, check=False)
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    if not gone(_STOP_GRACE_SECONDS):
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        gone(5.0)


# ── state file: which backend this checkout started, and which launcher owns it ──
def _read_state(config: AutostartConfig) -> dict[str, Any] | None:
    try:
        data = json.loads(config.state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_state(config: AutostartConfig, state: dict[str, Any]) -> None:
    config.state_path.parent.mkdir(parents=True, exist_ok=True)
    config.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _clear_state_if_pid(state_path: Path, pid: int) -> None:
    """Remove the state file only if it still records ``pid``.

    A concurrent launcher may have written its own record over ours; that record
    must survive so its backend can be adopted or stopped later.
    """
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(state, dict) and state.get("pid") == pid:
        state_path.unlink(missing_ok=True)


def _same_path(a: str | Path, b: str | Path) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


# ── the decision ────────────────────────────────────────────────────────────────
def _verify_same_checkout(config: AutostartConfig) -> None:
    """Raise unless whatever answers on the port is a Ragnarok backend for this checkout."""
    answer = _get_json(f"{config.api_base}/api/identity")
    if answer is None or answer[0] != 200 or not isinstance(answer[1], dict):
        raise AutostartError(
            f"Port {config.port} is in use by {_port_holder(config.port)}, which is not Ragnarok. "
            f"Stop it, or set backend_port to a free port."
        )
    payload = answer[1]
    if payload.get("app") != "ragnarok":
        raise AutostartError(
            f"Port {config.port} is in use by a program that is not Ragnarok "
            f"({_port_holder(config.port)}). Stop it, or set backend_port to a free port."
        )
    root = str(payload.get("root", ""))
    if not root or not _same_path(root, config.repo_root):
        raise AutostartError(
            f"Port {config.port} is served by the Ragnarok checkout at {root or 'unknown'}, "
            f"not {config.repo_root}. Stop that backend, or point the connector at that folder."
        )


def _adopt_recorded(config: AutostartConfig) -> bool:
    """Take ownership of a live backend whose launcher has died. Return True if adopted."""
    state = _read_state(config)
    if not state:
        return False
    pid = state.get("pid")
    if not isinstance(pid, int) or not _pid_alive(pid) or not _looks_like_backend(pid):
        config.state_path.unlink(missing_ok=True)  # stale record of a backend that is gone
        return False
    owner = state.get("owner")
    if isinstance(owner, int) and owner != os.getpid() and _pid_alive(owner):
        return False
    state["owner"] = os.getpid()
    _write_state(config, state)
    logger.info("adopted the Ragnarok backend pid=%s recorded by an exited launcher", pid)
    return True


def _wait_healthy(config: AutostartConfig, deadline: float, proc: subprocess.Popen[bytes] | None) -> bool:
    """Poll ``/api/health``. Return True if the backend we spawned lost a port race to a
    Ragnarok backend for this checkout, so we are reusing that one instead.
    """
    while True:
        answer = _get_json(f"{config.api_base}/api/health", timeout=_PROBE_TIMEOUT_SECONDS)
        if answer is not None and answer[0] == 200:
            return False
        if proc is not None and proc.poll() is not None:
            if _port_open(config.host, config.port):
                _verify_same_checkout(config)
                logger.info("another launcher started the backend on port %s first; reusing it", config.port)
                return True
            raise AutostartError(
                f"The Ragnarok backend exited with code {proc.returncode} before it answered on "
                f"port {config.port}. The reason is in {config.log_path}."
            )
        if time.monotonic() >= deadline:
            raise AutostartError(
                f"The Ragnarok backend did not answer /api/health on port {config.port} within "
                f"{config.timeout_seconds:.0f} s. The reason is in {config.log_path}."
            )
        time.sleep(_POLL_SECONDS)


def _spawn(config: AutostartConfig, command: list[str] | None) -> subprocess.Popen[bytes]:
    if not _port_bindable(config.host, config.port):
        raise AutostartError(
            f"Port {config.port} is in use by {_port_holder(config.port)}, which is not a "
            f"Ragnarok backend yet. Stop it, or set backend_port to a free port."
        )
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(config.repo_root), env.get("PYTHONPATH", "")) if p)
    mpl = config.repo_root / ".matplotlib"
    mpl.mkdir(parents=True, exist_ok=True)
    env.setdefault("MPLCONFIGDIR", str(mpl))
    if not env.get("RAGNAROK_FRONTEND_DIST") and (config.repo_root / "build").is_dir():
        env["RAGNAROK_FRONTEND_DIST"] = str(config.repo_root / "build")
    argv = command or [
        sys.executable, "-m", "uvicorn", "backend.app.main:app",
        "--host", "127.0.0.1", "--port", str(config.port),
    ]
    popen_kwargs: dict[str, Any] = {"cwd": str(config.repo_root), "env": env, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        popen_kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        )
    else:
        popen_kwargs["start_new_session"] = True  # own process group: killpg stops the tree
    with config.log_path.open("ab") as log:
        popen_kwargs.update(stdout=log, stderr=subprocess.STDOUT)
        proc = subprocess.Popen(argv, **popen_kwargs)  # noqa: S603 - fixed argv, no shell
    _write_state(
        config,
        {"pid": proc.pid, "port": config.port, "owner": os.getpid(), "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
    )
    logger.info("started the Ragnarok backend pid=%s on port %s (log: %s)", proc.pid, config.port, config.log_path)
    return proc


def ensure_backend(config: AutostartConfig, *, command: list[str] | None = None) -> BackendHandle:
    """Make sure a Ragnarok backend for this checkout answers on ``config.api_base``.

    Args:
        config: Autostart settings (see :meth:`AutostartConfig.from_env`).
        command: Override for the backend argv. Tests use it; production leaves it None.

    Returns:
        A handle; ``owned`` is True when this call started the backend.

    Raises:
        AutostartError: The port is held by something else, the backend exits, or it
            does not answer ``/api/health`` within the timeout.
    """
    deadline = time.monotonic() + config.timeout_seconds
    if not _port_open(config.host, config.port):
        proc = _spawn(config, command)
        try:
            reused = _wait_healthy(config, deadline, proc)
        except AutostartError:
            _terminate(proc.pid, proc)
            _clear_state_if_pid(config.state_path, proc.pid)
            raise
        if reused:
            # Our spawn exited on the port race; the backend serving the port is another launcher's.
            _clear_state_if_pid(config.state_path, proc.pid)
            return BackendHandle(owned=False, pid=None, proc=None, state_path=config.state_path)
        return BackendHandle(owned=True, pid=proc.pid, proc=proc, state_path=config.state_path)

    _verify_same_checkout(config)
    adopted = _adopt_recorded(config)
    _wait_healthy(config, deadline, proc=None)
    state = _read_state(config) if adopted else None
    pid = state.get("pid") if state else None
    return BackendHandle(owned=adopted, pid=pid if isinstance(pid, int) else None, proc=None, state_path=config.state_path)


def start_from_env(*, command: list[str] | None = None) -> BackendHandle | None:
    """Start or reuse the backend if ``RAGNAROK_MCP_AUTOSTART`` is on; otherwise do nothing.

    On failure, writes ``FAILURE_MARKER`` plus the reason to stderr and re-raises
    :class:`AutostartError`. The caller exits with :data:`EXIT_CODE_FAILED`.
    """
    global _current
    config = AutostartConfig.from_env()
    if not config.enabled:
        return None
    _configure_logging()
    if not config.is_local:
        logger.info("autostart skipped: RAGNAROK_API_BASE=%s is not a loopback address", config.api_base)
        return None
    try:
        handle = ensure_backend(config, command=command)
    except AutostartError as exc:
        logger.error("%s", exc)
        sys.stderr.write(f"{FAILURE_MARKER} {exc}\n")
        sys.stderr.flush()
        raise
    _current = handle
    if handle.owned:
        atexit.register(stop_owned)
        _install_signal_handlers()
    logger.info("backend ready on %s (%s)", config.api_base, "started" if handle.owned else "reused")
    return handle


def stop_owned() -> None:
    """Stop the backend if this process started it. Safe to call more than once."""
    global _current
    handle, _current = _current, None
    if handle is None or not handle.owned or handle.pid is None:
        return
    logger.info("stopping the Ragnarok backend pid=%s that this process started", handle.pid)
    _terminate(handle.pid, handle.proc)
    _clear_state_if_pid(handle.state_path, handle.pid)


def _install_signal_handlers() -> None:
    def _on_signal(signum: int, _frame: Any) -> None:
        stop_owned()
        os._exit(128 + signum)  # noqa: SLF001 - skip atexit: we already stopped the backend

    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, _on_signal)
            except (ValueError, OSError):
                pass


def _configure_logging() -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
