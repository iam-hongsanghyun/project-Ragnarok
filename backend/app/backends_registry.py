"""Find every Ragnarok backend running on this machine, and the sessions each one holds.

One machine often runs more than one backend: the app's own (``:8000``) and one a host started for an agent
(VOID, a bridge) on another port with its own data folder (``RAGNAROK_DATA_DIR``). Each holds its own
sessions, so a browser on the first never sees what an agent does in the second. This module lists them so
the browser can connect to any of them (Settings -> Sessions, ``?api=<base>&session=<id>``).

How a backend is found (both, merged by port):

* **registry** - every backend writes ``<registry>/<pid>.json`` (``{pid, port, host, dataDir}``) when it starts
  and deletes it when it stops; ``<registry>`` is ``RAGNAROK_REGISTRY_DIR`` or ``~/.ragnarok/backends``. A file
  whose process is gone is ignored and removed.
* **scan** - for backends started before the registry existed: the listening processes whose command runs
  ``backend.app.main:app`` (``lsof`` + ``ps``, macOS / Linux; skipped where those are missing).

Each candidate is then asked over HTTP for its sessions (``GET /api/sessions``; an older backend without it is
read from its data folder plus ``GET /api/session/meta``). A candidate that does not answer is left out.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from .data_root import data_root
from .model_store import component_counts

logger = logging.getLogger("pypsa_gui.backends_registry")

_PROBE_TIMEOUT_S = 2.0
_APP_MARKER = "backend.app.main:app"


def registry_dir() -> Path:
    """Where running backends announce themselves."""
    return Path(os.environ.get("RAGNAROK_REGISTRY_DIR") or (Path.home() / ".ragnarok" / "backends"))


def own_port(argv: list[str] | None = None) -> int:
    """This process's listening port: ``RAGNAROK_PORT``, else uvicorn's ``--port`` argument, else 8000."""
    env = os.environ.get("RAGNAROK_PORT", "").strip()
    if env.isdigit():
        return int(env)
    args = list(sys.argv if argv is None else argv)
    for i, arg in enumerate(args):
        if arg == "--port" and i + 1 < len(args) and args[i + 1].isdigit():
            return int(args[i + 1])
        if arg.startswith("--port=") and arg.split("=", 1)[1].isdigit():
            return int(arg.split("=", 1)[1])
    return 8000


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def register_self() -> Path | None:
    """Announce this backend; returns the file written (``None`` when the registry cannot be written)."""
    entry: dict[str, Any] = {"pid": os.getpid(), "port": own_port(), "host": "127.0.0.1", "dataDir": str(data_root())}
    started_by = os.environ.get("RAGNAROK_STARTED_BY", "").strip()
    if started_by:
        entry["startedBy"] = started_by  # opened from Ragnarok (open_folder): Ragnarok may stop it
    path = registry_dir() / f"{os.getpid()}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entry), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write the backend registry entry %s: %s", path, exc)
        return None
    return path


def unregister_self() -> None:
    try:
        (registry_dir() / f"{os.getpid()}.json").unlink(missing_ok=True)
    except OSError:
        pass


def _from_registry() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    root = registry_dir()
    if not root.is_dir():
        return out
    for path in root.glob("*.json"):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            pid = int(entry["pid"])
            port = int(entry["port"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if not _pid_alive(pid):
            path.unlink(missing_ok=True)
            continue
        out.append({"pid": pid, "port": port, "host": str(entry.get("host") or "127.0.0.1"),
                    "dataDir": str(entry.get("dataDir") or ""), "startedBy": str(entry.get("startedBy") or "")})
    return out


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _from_scan() -> list[dict[str, Any]]:
    """Listening Ragnarok backends found from the process table (no registry entry needed)."""
    if not shutil.which("lsof") or not shutil.which("ps"):
        return []
    out: list[dict[str, Any]] = []
    listing = _run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpn"])
    pid = 0
    ports: dict[int, int] = {}
    for line in listing.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid:
            match = re.search(r":(\d+)$", line)
            if match and pid not in ports:
                ports[pid] = int(match.group(1))
    for pid, port in ports.items():
        command = _run(["ps", "eww", "-o", "command=", "-p", str(pid)])
        if _APP_MARKER not in command:
            continue
        match = re.search(r"(?:^|\s)RAGNAROK_DATA_DIR=(\S+)", command)
        out.append({"pid": pid, "port": port, "host": "127.0.0.1", "dataDir": match.group(1) if match else ""})
    return out


def _sessions_of(base: str, data_dir: str) -> list[dict[str, Any]] | None:
    """The backend's sessions, or ``None`` when it does not answer."""
    with httpx.Client(timeout=_PROBE_TIMEOUT_S) as client:
        try:
            resp = client.get(f"{base}/api/sessions")
        except httpx.HTTPError:
            return None
        if resp.status_code == 200:
            sessions = resp.json().get("sessions")
            return sessions if isinstance(sessions, list) else []
        if resp.status_code != 404:
            return None
        # An older backend: list its session folders and ask for each one's meta.
        root = Path(data_dir) / "session" if data_dir else None
        if root is None or not root.is_dir():
            return []
        out: list[dict[str, Any]] = []
        for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
            try:
                meta_resp = client.get(f"{base}/api/session/meta", params={"session_id": folder.name})
            except httpx.HTTPError:
                continue
            meta = meta_resp.json() if meta_resp.status_code == 200 else None
            if not isinstance(meta, dict) or not meta.get("sheets"):
                continue
            out.append({"id": folder.name, "filename": meta.get("filename") or "",
                        "scenarioName": meta.get("scenarioName") or "", "savedAt": meta.get("savedAt") or "",
                        "snapshotCount": meta.get("snapshotCount"),
                        "componentCounts": component_counts(meta)})
        out.sort(key=lambda s: str(s["savedAt"]), reverse=True)
        return out


def _queue_of(base: str) -> dict[str, int]:
    try:
        jobs = httpx.get(f"{base}/api/queue", timeout=_PROBE_TIMEOUT_S).json().get("jobs") or []
    except (httpx.HTTPError, ValueError, AttributeError):
        return {"running": 0, "queued": 0}
    return {"running": sum(1 for j in jobs if j.get("status") == "running"),
            "queued": sum(1 for j in jobs if j.get("status") == "queued")}


def discover() -> list[dict[str, Any]]:
    """Every answering Ragnarok backend on this machine with its sessions; this one first.

    Each: ``apiBase``, ``port``, ``pid``, ``dataDir``, ``self`` (this backend), ``sessions`` (as
    ``GET /api/sessions``) and ``queue`` (``running`` / ``queued`` solves).
    """
    me = os.getpid()
    by_port: dict[int, dict[str, Any]] = {}
    for cand in _from_scan() + _from_registry():  # the registry wins: it knows the data folder for sure
        by_port[cand["port"]] = {**by_port.get(cand["port"], {}), **{k: v for k, v in cand.items() if v}}
    by_port.setdefault(own_port(), {"pid": me, "port": own_port(), "host": "127.0.0.1", "dataDir": str(data_root())})

    def probe(cand: dict[str, Any]) -> dict[str, Any] | None:
        base = f"http://{cand.get('host') or '127.0.0.1'}:{cand['port']}"
        sessions = _sessions_of(base, str(cand.get("dataDir") or ""))
        if sessions is None:
            return None
        is_self = cand.get("pid") == me or cand["port"] == own_port()
        return {"apiBase": base, "port": cand["port"], "pid": cand.get("pid"), "dataDir": cand.get("dataDir") or "",
                "self": is_self, "sessions": sessions, "queue": _queue_of(base),
                "startedFromRagnarok": bool(cand.get("startedBy"))}

    with ThreadPoolExecutor(max_workers=8) as pool:
        found = [b for b in pool.map(probe, by_port.values()) if b is not None]
    found.sort(key=lambda b: (not b["self"], b["port"]))
    return found


# ── working folders: open one (a backend on it), stop one, the default for the next start ──────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
_START_TIMEOUT_S = 60.0


class FolderError(ValueError):
    """A working folder cannot be used (surfaced as HTTP 400)."""


def resolve_folder(path: str) -> Path:
    """An absolute working folder from what the user typed (``~`` expanded); its parent must exist."""
    raw = (path or "").strip()
    if not raw:
        raise FolderError("Give a folder path.")
    folder = Path(raw).expanduser()
    if not folder.is_absolute():
        raise FolderError(f"{raw!r} is not an absolute path (start with / or ~).")
    folder = folder.resolve()
    if folder.exists() and not folder.is_dir():
        raise FolderError(f"{folder} is a file, not a folder.")
    if not folder.exists() and not folder.parent.is_dir():
        raise FolderError(f"Neither {folder} nor its parent folder exists.")
    return folder


def _same_folder(a: str, b: Path) -> bool:
    try:
        return bool(a) and Path(a).expanduser().resolve() == b
    except OSError:
        return False


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def open_folder(path: str) -> dict[str, Any]:
    """The backend working in ``path``: the one already running there, else a new one started on a free port.

    A new backend runs this checkout's code with ``RAGNAROK_DATA_DIR=<path>`` (as
    ``RAGNAROK_DATA_DIR=<path> run.command`` would), in its own process group so it outlives a reload of this
    one, logging to ``<path>/backend.log``. Returns ``{apiBase, port, pid, dataDir, started}``.
    """
    import time

    folder = resolve_folder(path)
    for backend in discover():
        if _same_folder(str(backend.get("dataDir") or ""), folder):
            return {"apiBase": backend["apiBase"], "port": backend["port"], "pid": backend.get("pid"),
                    "dataDir": str(folder), "started": False}
    folder.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    env = {**os.environ, "RAGNAROK_DATA_DIR": str(folder), "RAGNAROK_PORT": str(port),
           "RAGNAROK_STARTED_BY": str(os.getpid())}
    env.pop("RAGNAROK_JOURNAL_DIR", None)  # the journal goes with the folder (its default sits under it)
    log = (folder / "backend.log").open("ab")
    proc = subprocess.Popen(  # our own interpreter and module, no shell
        [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", str(port),
         "--timeout-graceful-shutdown", "3"],
        cwd=str(_REPO_ROOT), env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + _START_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise FolderError(f"The backend for {folder} stopped while starting; see {folder / 'backend.log'}.")
        try:
            if httpx.get(f"{base}/api/health", timeout=1.0).status_code == 200:
                logger.info("Started a backend for %s on %s (pid %s)", folder, base, proc.pid)
                return {"apiBase": base, "port": port, "pid": proc.pid, "dataDir": str(folder), "started": True}
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    proc.terminate()
    raise FolderError(f"The backend for {folder} did not answer within {int(_START_TIMEOUT_S)} s.")


def stop_backend(port: int) -> dict[str, Any]:
    """Shut down a backend this app started (``open_folder``); never this one or one another host started."""
    import signal

    for path in registry_dir().glob("*.json"):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if int(entry.get("port") or 0) != int(port):
            continue
        pid = int(entry.get("pid") or 0)
        if pid == os.getpid():
            raise FolderError("This is the backend this screen talks to; it cannot stop itself.")
        if not entry.get("startedBy"):
            raise FolderError(f"The backend on port {port} was not started from Ragnarok; stop it where it was started.")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        path.unlink(missing_ok=True)
        return {"port": int(port), "pid": pid, "stopped": True}
    raise FolderError(f"No backend started from Ragnarok runs on port {port}.")


def default_folder() -> dict[str, Any]:
    """The working folder a plain start uses (``RAGNAROK_DATA_DIR`` in ``backend/.env``) and this backend's."""
    from backend.env_file import ENV_FILE, parse_env_text

    saved = ""
    if ENV_FILE.is_file():
        saved = parse_env_text(ENV_FILE.read_text(encoding="utf-8")).get("RAGNAROK_DATA_DIR", "")
    return {"default": saved or str(Path(__file__).resolve().parents[1] / "data"), "savedInEnvFile": bool(saved),
            "current": str(data_root()), "envFile": str(ENV_FILE)}


def set_default_folder(path: str | None) -> dict[str, Any]:
    """Make ``path`` the working folder of the next plain start (``backend/.env``); ``None`` / empty restores
    ``backend/data``. A ``RAGNAROK_DATA_DIR`` given on the command line still wins over the file."""
    from backend.env_file import ENV_FILE

    folder = resolve_folder(path) if (path or "").strip() else None
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.is_file() else []
    kept = [ln for ln in lines if not re.match(r"^\s*(export\s+)?RAGNAROK_DATA_DIR\s*=", ln)]
    if folder is not None:
        kept.append(f"RAGNAROK_DATA_DIR={folder}")
    ENV_FILE.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return default_folder()


# ── per-session working folders ─────────────────────────────────────────────────────────────────────────────
# A session's working folder is the folder of the backend that serves it. The choice is remembered per session
# id, so an agent restarted under the same session (``RAGNAROK_SESSION_ID``) goes back to its folder, while
# other sessions (the browser's ``default``) keep theirs.

def _session_folders_file() -> Path:
    return registry_dir().parent / "session_folders.json"


def session_folders() -> dict[str, str]:
    """``{session id: working folder}`` as remembered on this machine."""
    try:
        data = json.loads(_session_folders_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def remember_session_folder(session_id: str, folder: str | None) -> dict[str, str]:
    """Remember (or, with ``None`` / empty, forget) the working folder of ``session_id``."""
    folders = session_folders()
    if folder:
        folders[session_id] = str(resolve_folder(folder))
    else:
        folders.pop(session_id, None)
    path = _session_folders_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(folders, indent=2, sort_keys=True), encoding="utf-8")
    return folders


def pick_folder(start: str = "") -> str | None:
    """Show the system's folder picker on this machine and return the chosen folder (``None`` when cancelled).

    The backend runs on the user's own machine, so the picker opens on their screen: Finder on macOS
    (``osascript``), ``zenity`` on Linux, the Windows folder dialog through PowerShell.
    """
    begin = start if start and Path(start).expanduser().is_dir() else ""
    if sys.platform == "darwin":
        script = 'POSIX path of (choose folder with prompt "Ragnarok working folder"'
        if begin:
            script += f' default location (POSIX file "{Path(begin).expanduser()}")'
        script += ")"
        cmd = ["osascript", "-e", script]
    elif sys.platform.startswith("linux") and shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", "--directory", "--title=Ragnarok working folder"]
        if begin:
            cmd.append(f"--filename={Path(begin).expanduser()}/")
    elif sys.platform.startswith("win"):
        ps = ("Add-Type -AssemblyName System.Windows.Forms; $d = New-Object System.Windows.Forms.FolderBrowserDialog; "
              "$d.Description = 'Ragnarok working folder'; if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }")
        cmd = ["powershell", "-NoProfile", "-Command", ps]
    else:
        raise FolderError("No folder picker is available on this machine.")
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise FolderError(f"The folder picker could not open: {exc}") from exc
    chosen = done.stdout.strip()
    if done.returncode != 0 or not chosen:
        return None  # cancelled
    return str(Path(chosen).expanduser().resolve())
