"""Self-provisioning of the isolated pandapower environment (``.venv-pandapower``).

pandapower 3.x pins ``pandas~=2.3`` and PyPSA 1.4 needs pandas 3, so pandapower
lives in its own venv and is driven through ``backend/scripts/pandapower_dump.py``.
This module builds that venv on first use, in a background thread, so a user never
runs a setup script: the first ``POST /api/import/pandapower`` starts the build and
the endpoint answers "setting up, retry shortly" until it is ready.

States, as reported by :func:`status` (key ``state``)::

    ready       interpreter present and built from the current requirements file
    setting_up  a build is running (this process, or another Ragnarok process)
    failed      the last build failed; ``error`` says why, ``log`` says where
    disabled    no environment and RAGNAROK_PANDAPOWER_AUTOSETUP=off
    absent      no environment yet; the next import starts the build

Transitions::

    absent -> setting_up -> ready
                         -> failed -> (after RETRY_FAILED_AFTER_S) -> setting_up

The retry window stops an agent that polls every few seconds from forking pip on
each poll after a failure.

Environment variables:
    RAGNAROK_PANDAPOWER_PYTHON     interpreter to use instead. Never built or rebuilt here.
    RAGNAROK_PANDAPOWER_AUTOSETUP  ``on`` (default) or ``off``.

Files:
    ``<repo>/.venv-pandapower``             the environment; ``.req_hash`` inside it stamps
                                            the requirements file it was built from.
    ``<repo>/logs/pandapower-setup.log``    pip output and tracebacks of every build.
    ``<repo>/logs/pandapower-setup.lock``   present while a build runs (cross-process guard).

This file is stdlib-only and runnable as a script, so the setup script can build the
environment without importing the PyPSA stack::

    python backend/pypsa/network/pandapower_env.py     # exit 0 ready, 1 failed, 2 busy

Algorithm: none (environment provisioning). Build steps, in order::

    1. create venv from the running interpreter (``uv venv`` when uv is on PATH, else ``python -m venv``)
    2. install ``backend/requirements-pandapower.txt`` (``uv pip`` or ``pip``)
    3. probe ``import pandapower, pandas``; require pandas major version 2
    4. write ``.req_hash``
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, TextIO

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_DIR = _REPO_ROOT / ".venv-pandapower"
REQUIREMENTS = _REPO_ROOT / "backend" / "requirements-pandapower.txt"
LOG_FILE = _REPO_ROOT / "logs" / "pandapower-setup.log"
LOCK_FILE = _REPO_ROOT / "logs" / "pandapower-setup.lock"
STAMP_NAME = ".req_hash"

RETRY_AFTER_S = 15  # advised client wait while a build runs
RETRY_FAILED_AFTER_S = 60  # a failed build is not retried sooner than this
STEP_TIMEOUT_S = 15 * 60  # one pip/uv/probe step
LOCK_STALE_S = 45 * 60  # a lock older than this belongs to a dead build


class PandapowerUnavailable(RuntimeError):
    """No usable pandapower interpreter, and none is being built."""


class PandapowerSettingUp(PandapowerUnavailable):
    """The pandapower environment is being built; retry after ``retry_after_s``.

    Attributes:
        status: The :func:`status` dict at the time of the raise.
        retry_after_s: Seconds the caller should wait before retrying.
    """

    def __init__(self, status: dict[str, Any]) -> None:
        self.status = status
        self.retry_after_s = RETRY_AFTER_S
        super().__init__(setting_up_message(status))


_lock = threading.RLock()
_thread: threading.Thread | None = None
_stage = ""
_started_at = 0.0
_error: str | None = None
_failed_at = 0.0


# ── paths and markers ─────────────────────────────────────────────────────────


def env_python_path() -> Path:
    """Interpreter inside the managed environment (exists or not)."""
    if os.name == "nt":
        return ENV_DIR / "Scripts" / "python.exe"
    return ENV_DIR / "bin" / "python"


def requirements_hash() -> str:
    """SHA-256 of ``backend/requirements-pandapower.txt``; stamps the environment."""
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def _override() -> str | None:
    value = os.environ.get("RAGNAROK_PANDAPOWER_PYTHON", "").strip()
    return value or None


def _autosetup_enabled() -> bool:
    value = os.environ.get("RAGNAROK_PANDAPOWER_AUTOSETUP", "on").strip().lower()
    return value not in ("off", "0", "false", "no")


def _is_current() -> bool:
    """True when the managed environment exists and was built from the current requirements."""
    stamp = ENV_DIR / STAMP_NAME
    if not env_python_path().is_file() or not stamp.is_file():
        return False
    return stamp.read_text(encoding="utf-8").strip() == requirements_hash()


def _lock_age_s() -> float | None:
    try:
        return time.time() - LOCK_FILE.stat().st_mtime
    except FileNotFoundError:
        return None


def _build_lock_held() -> bool:
    age = _lock_age_s()
    return age is not None and age < LOCK_STALE_S


def _acquire_lock() -> bool:
    """Create the cross-process lock; False when another live build holds it."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _build_lock_held():
                return False
            LOCK_FILE.unlink(missing_ok=True)  # stale: the builder died
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"{os.getpid()} {time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
        return True
    return False


def _release_lock() -> None:
    LOCK_FILE.unlink(missing_ok=True)


# ── status ────────────────────────────────────────────────────────────────────


def status() -> dict[str, Any]:
    """Current state of the pandapower environment. Cheap: no subprocess, no network.

    Returns:
        A dict with keys ``state``, ``stage``, ``python`` (ready only), ``error``
        (failed only), ``elapsedSeconds`` and ``retryAfterSeconds`` (setting_up only),
        ``log`` and ``envDir``.
    """
    with _lock:
        override = _override()
        if override is not None:
            interp = Path(override)
            if interp.is_file():
                return _report("ready", python=interp)
            return _report("failed", error=f"RAGNAROK_PANDAPOWER_PYTHON points at {interp}, which does not exist")
        if _thread is not None and _thread.is_alive():
            return _report("setting_up", elapsed=time.time() - _started_at)
        if _is_current():
            return _report("ready", python=env_python_path())
        if _build_lock_held():
            age = _lock_age_s() or 0.0
            return _report("setting_up", stage="started by another Ragnarok process", elapsed=age)
        if _error is not None and time.time() - _failed_at < RETRY_FAILED_AFTER_S:
            return _report("failed", error=_error)
        if not _autosetup_enabled():
            return _report("disabled")
        return _report("absent")


def _report(state: str, *, python: Path | None = None, error: str | None = None,
            stage: str | None = None, elapsed: float | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "state": state,
        "stage": stage if stage is not None else _stage,
        "log": str(LOG_FILE),
        "envDir": str(ENV_DIR),
    }
    if python is not None:
        out["python"] = str(python)
    if error is not None:
        out["error"] = error
    if state == "setting_up":
        out["elapsedSeconds"] = round(elapsed or 0.0, 1)
        out["retryAfterSeconds"] = RETRY_AFTER_S
    return out


def setting_up_message(st: dict[str, Any]) -> str:
    """One-sentence user-facing text for the ``setting_up`` state."""
    stage = st.get("stage") or "starting"
    return (
        f"Setting up pandapower for the first time (one-time, about 1 minute; now: {stage}). "
        f"Retry this import in about {RETRY_AFTER_S} seconds."
    )


def unavailable_message(st: dict[str, Any]) -> str:
    """One-sentence user-facing text for the ``failed`` and ``disabled`` states."""
    if st["state"] == "disabled":
        return (
            "pandapower is not installed and automatic setup is off (RAGNAROK_PANDAPOWER_AUTOSETUP=off). "
            "Run backend/scripts/setup_pandapower_env.sh or set RAGNAROK_PANDAPOWER_PYTHON."
        )
    return (
        f"pandapower is not available: setup failed ({st.get('error', 'unknown error')}). "
        f"Fix the cause and retry in a minute, or set RAGNAROK_PANDAPOWER_PYTHON; full log: {LOG_FILE}"
    )


# ── requirement of the interpreter ───────────────────────────────────────────


def require_python() -> Path:
    """Interpreter for the pandapower subprocess.

    Starts a build when the environment is absent, then raises. Never blocks on a build.

    Raises:
        PandapowerSettingUp: a build is running or was just started.
        PandapowerUnavailable: setup failed recently, or is disabled.
    """
    st = status()
    if st["state"] == "ready":
        return Path(st["python"])
    if st["state"] == "absent":
        start()
        st = status()
        if st["state"] == "ready":
            return Path(st["python"])
    if st["state"] in ("setting_up", "absent"):
        raise PandapowerSettingUp(st)
    raise PandapowerUnavailable(unavailable_message(st))


def start() -> None:
    """Begin building the environment in a daemon thread. No-op when ready or already running."""
    global _thread, _stage, _started_at, _error
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        if _override() is not None or _is_current():
            return
        if not _acquire_lock():
            logger.info("pandapower setup already running in another process")
            return
        _stage = "queued"
        _started_at = time.time()
        _error = None
        _thread = threading.Thread(target=_background_build, name="pandapower-setup", daemon=True)
        _thread.start()
        logger.info("pandapower setup started (log: %s)", LOG_FILE)


def _background_build() -> None:
    global _error, _failed_at
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as log:
            log.write(f"\n=== pandapower setup {time.strftime('%Y-%m-%dT%H:%M:%S')} "
                      f"interpreter={sys.executable} ===\n")
            build_now(log)
    except Exception as exc:  # noqa: BLE001 - any failure becomes the failed state
        message = str(exc) or type(exc).__name__
        with LOG_FILE.open("a", encoding="utf-8") as log:
            log.write(traceback.format_exc())
        with _lock:
            _error = message
            _failed_at = time.time()
        logger.error("pandapower setup failed: %s (log: %s)", message, LOG_FILE)
    finally:
        _release_lock()


# ── build ─────────────────────────────────────────────────────────────────────


class _StepFailed(RuntimeError):
    pass


def _set_stage(stage: str, log: TextIO) -> None:
    global _stage
    with _lock:
        _stage = stage
    log.write(f"-- {stage}\n")
    log.flush()


def _run(argv: list[str], log: TextIO) -> str:
    log.write("$ " + " ".join(argv) + "\n")
    log.flush()
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", timeout=STEP_TIMEOUT_S, check=False,
    )
    output = proc.stdout or ""
    log.write(output)
    log.flush()
    if proc.returncode != 0:
        tail = [line.strip() for line in output.splitlines() if line.strip()][-1:]
        detail = f": {tail[0][:200]}" if tail else ""
        raise _StepFailed(f"{Path(argv[0]).name} exited with code {proc.returncode}{detail}")
    return output


def _remove_env() -> None:
    if ENV_DIR.exists():
        shutil.rmtree(ENV_DIR, ignore_errors=True)


def build_now(log: TextIO) -> None:
    """Build the environment synchronously, writing progress to ``log``.

    The caller owns the cross-process lock. Raises on failure.

    Raises:
        _StepFailed: a build step exited non-zero.
        RuntimeError: the probe found an unexpected pandas or pandapower install.
    """
    uv = shutil.which("uv")
    if not env_python_path().is_file():
        _remove_env()  # a leftover from an interrupted build has no usable interpreter
        _set_stage("creating environment", log)
        created = False
        if uv:
            try:
                _run([uv, "venv", "--python", sys.executable, str(ENV_DIR)], log)
                created = True
            except _StepFailed as exc:
                log.write(f"uv could not create the venv ({exc}); falling back to python -m venv\n")
                _remove_env()
        if not created:
            _run([sys.executable, "-m", "venv", str(ENV_DIR)], log)

    py = env_python_path()
    _set_stage("installing pandapower (about a minute)", log)
    if uv:
        _run([uv, "pip", "install", "--python", str(py), "-r", str(REQUIREMENTS)], log)
    else:
        _run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQUIREMENTS)], log)

    _set_stage("checking the install", log)
    probe = _run([str(py), "-c",
                  "import pandapower, pandas; print(pandapower.__version__); print(pandas.__version__)"], log)
    # pandapower may print import warnings before the two version lines: read the last two.
    versions = [line.strip() for line in probe.splitlines() if line.strip()][-2:]
    if len(versions) < 2 or not versions[1].startswith("2."):
        raise RuntimeError(
            f"pandapower environment has pandas {versions[-1] if versions else '?'}, "
            "expected pandas 2.x (pandapower pins pandas~=2.3)"
        )
    (ENV_DIR / STAMP_NAME).write_text(requirements_hash() + "\n", encoding="utf-8")
    _set_stage("ready", log)
    log.write(f"pandapower {versions[0]} / pandas {versions[1]} in {ENV_DIR}\n")
    log.flush()
    logger.info("pandapower environment ready: pandapower %s, pandas %s", versions[0], versions[1])


# ── command line ──────────────────────────────────────────────────────────────


def main() -> int:
    """Build the environment in the foreground. Exit 0 ready, 1 failed, 2 another build holds the lock."""
    if _override() is not None:
        print(f"RAGNAROK_PANDAPOWER_PYTHON is set; nothing to build. Using {_override()}")
        return 0
    if _is_current():
        print(f"pandapower environment is current: {ENV_DIR}")
        return 0
    if not _acquire_lock():
        print("another pandapower setup is running; wait for it or see " + str(LOG_FILE))
        return 2
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as log:
            log.write(f"\n=== pandapower setup (foreground) {time.strftime('%Y-%m-%dT%H:%M:%S')} "
                      f"interpreter={sys.executable} ===\n")
            build_now(_Tee(log, sys.stdout))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: pandapower setup failed: {exc}. Full log: {LOG_FILE}", file=sys.stderr)
        return 1
    finally:
        _release_lock()


class _Tee:
    """Write to the log file and the console at once."""

    def __init__(self, *streams: TextIO) -> None:
        self._streams = streams

    def write(self, text: str) -> int:
        for stream in self._streams:
            stream.write(text)
        return len(text)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


if __name__ == "__main__":
    sys.exit(main())
