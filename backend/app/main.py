from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing as mp
import os
import queue
import shutil
import sys
import time
import signal
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from starlette.background import BackgroundTask

from .backends import BackendError, available_backends, get_backend
from .log_capture import (
    clear_buffer as _log_clear,
    get_snapshot as _log_snapshot,
    install as _install_log_capture,
)
from .models import ExportProjectPayload, RunPayload
from . import model_store, run_store
from ..pypsa.network import build_network, validate_model
from ..pypsa.network.serialize import network_to_model as _network_to_model_json

# xlsx MIME used by the run export endpoint below.
_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Attach the in-process log handler at import time so the entire uvicorn
# startup sequence and all subsequent records flow into the ring buffer.
# Surfaced via GET /api/log (see endpoint below).
_install_log_capture()


# ── Suppress per-poll access log noise ───────────────────────────────────────
# Two routes are polled continuously by the frontend and would flood the
# terminal with one INFO line per poll:
#   • GET /api/run/{id} — every 1.5 s while a solve is in progress
#   • GET /api/log      — every 2 s while the Analytics → Log tab is open
# Drop these from the INFO access log; re-emit at DEBUG so they remain
# capturable when needed (e.g. uvicorn --log-level debug). Critically, the
# /api/log polls themselves must NOT be captured into the in-process log
# ring buffer or the buffer fills with its own poll traffic.

class _SuppressPollLogs(logging.Filter):
    _debug = logging.getLogger("pypsa_gui.poll")

    _POLL_ROUTES = ('"GET /api/run/', '"GET /api/log ')

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        msg = record.getMessage()
        for marker in self._POLL_ROUTES:
            if marker in msg and "HTTP" in msg:
                self._debug.debug(msg)
                return False
        return True


logging.getLogger("uvicorn.access").addFilter(_SuppressPollLogs())


# ── Job store ─────────────────────────────────────────────────────────────────

@dataclass
class _Job:
    id: str
    proc: mp.Process
    result_queue: "mp.Queue[tuple[str, Any]]"
    status: str = "running"   # running | done | error | cancelled
    result: dict | None = None
    error: str | None = None


_jobs: dict[str, _Job] = {}


# ── Subprocess worker ─────────────────────────────────────────────────────────
# Must be a module-level function so multiprocessing "spawn" can import it.

def _solve_worker(
    payload: RunPayload | str,
    result_queue: "mp.Queue[tuple[str, Any]]",
    thread_override: int | None = None,
) -> None:
    """Run in a child process. Puts ("ok", result) or ("err", message) on the queue.

    Solver output (HiGHS C-stdout, plus linopy / PyPSA Python logs) streams
    straight to the launching terminal: the child inherits the parent's
    stdout/stderr, so there is no fd redirection and no temp-file capture.
    Dropping the capture removes per-solve overhead and the temp-file leak
    that occurred when a solve was cancelled mid-run; the terminal is the
    natural place for a developer to watch verbose solver progress.

    A ``StreamHandler`` is attached to the root logger so Python-level solver
    logs (linopy / PyPSA INFO) reach the terminal alongside the C-level HiGHS
    output — the import-time capture handler only mirrors into the in-process
    ring buffer, which this short-lived child discards.

    The backend is selected from ``options["backend"]`` (default PyPSA) via the
    backend registry, so the worker stays engine-agnostic.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        stream = logging.StreamHandler()
        stream.setLevel(logging.INFO)
        stream.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        root.addHandler(stream)

    # Queue runs (payload is a path) also persist their OUTCOME next to the
    # payload on disk. That makes a solve survive a backend restart: the parent
    # that spawned us may be gone, but the new backend process finds outcome.json
    # and flips the queue card to done/error instead of losing the run.
    outcome_path = Path(payload).parent / _QUEUE_OUTCOME if isinstance(payload, str) else None

    def _write_outcome(status: str, run_name: str | None = None, error: str | None = None) -> None:
        if outcome_path is None:
            return
        try:
            _write_json_atomic(
                outcome_path,
                {
                    "status": status,
                    "runName": run_name,
                    "error": error,
                    "finishedAt": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception:  # noqa: BLE001
            logging.getLogger("pypsa_gui.queue").exception("Failed to write queue outcome")

    try:
        if isinstance(payload, str):
            payload = _read_queue_payload(Path(payload))
        options = payload.options or {}
        # The parent resolved this solve's core budget at dispatch (Auto =
        # cpu // concurrency); pin it so HiGHS uses exactly what the Queue UI
        # shows and concurrent solves don't oversubscribe the machine.
        if thread_override is not None and int(thread_override) > 0:
            options = {**options, "solverThreads": int(thread_override)}
        backend = get_backend(options.get("backend"))
        result = backend.run(payload.model, payload.scenario, options)
        if outcome_path is not None:
            # Queue run: the frontend reads the result from run HISTORY, never
            # from this mp.Queue — so persist first, then signal with a tiny
            # tuple. Not piping the (huge) result dict also lets an ORPHANED
            # worker exit cleanly (a big payload with no reader wedges the
            # queue's feeder thread and the process never exits).
            meta = None
            try:
                meta = run_store.store_run(payload.model, payload.scenario or {}, options, result)
            except Exception:  # noqa: BLE001
                logging.getLogger("pypsa_gui.run_store").exception(
                    "store_run raised after a successful solve"
                )
            run_name = str(meta.get("name")) if isinstance(meta, dict) else None
            _write_outcome("done", run_name=run_name)
            result_queue.put(("ok", run_name))
        else:
            # Direct run: the caller waits on this queue for the result itself.
            # Deliver it FIRST so the frontend isn't blocked while we persist.
            result_queue.put(("ok", result))
            try:
                run_store.store_run(payload.model, payload.scenario or {}, options, result)
            except Exception:  # noqa: BLE001
                logging.getLogger("pypsa_gui.run_store").exception(
                    "store_run raised after a successful solve"
                )
    except Exception as exc:  # noqa: BLE001
        _write_outcome("error", error=str(exc))
        result_queue.put(("err", str(exc)))


async def _collect_job(job_id: str) -> None:
    """Background asyncio task — waits for the worker process and updates job state.

    The worker puts a ``(status, payload)`` tuple onto its queue once the
    solve finishes (``payload`` is the result dict on success or an error
    message string on failure). Solver output (HiGHS / linopy / PyPSA)
    streams live to the launching terminal during the solve, so there is
    nothing to fan into the log buffer here.
    """
    job = _jobs.get(job_id)
    if job is None:
        return
    while True:
        try:
            status, data = job.result_queue.get_nowait()
            if status == "ok":
                job.status = "done"
                job.result = data
            else:
                job.status = "error"
                job.error = data
            return
        except queue.Empty:
            if not job.proc.is_alive():
                if job.status == "running":
                    job.status = "cancelled"
                return
            await asyncio.sleep(0.5)


# ── Run queue (serial, disk-backed payloads) ──────────────────────────────────
# A single FIFO queue runs one solve at a time. Enqueue returns immediately
# ("queued, position N"); a background pump runs each job to completion (which
# also persists it to History via the worker's store_run), then starts the next.
# Queue metadata is kept in memory for quick polling, but the submitted model
# payload is written to backend/data/queue/<job_id>/payload.json. That keeps
# large queued workbooks out of RAM and lets terminal queue rows be rerun until
# the user explicitly deletes them.

_queue_logger = logging.getLogger("pypsa_gui.queue")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_QUEUE_DIR = _REPO_ROOT / "backend" / "data" / "queue"
_QUEUE_PAYLOAD = "payload.json"
_QUEUE_META = "meta.json"
# Written by the WORKER when a queue solve finishes ({status, runName, error,
# finishedAt}) — the disk-based completion signal that lets a solve survive a
# backend restart (the new process adopts it instead of marking the job lost).
_QUEUE_OUTCOME = "outcome.json"
# Server-wide queue settings (currently just the concurrency limit). Persisted at
# the queue root so a user's Queue-vs-Concurrency choice survives restarts.
_QUEUE_SETTINGS = "settings.json"

# Cores available to divide between concurrent solves. Also the hard ceiling for
# the user-set concurrency (more parallel solves than cores only thrashes).
_CPU_COUNT = max(1, os.cpu_count() or 1)


def _read_queue_concurrency() -> int:
    """Startup default for max concurrent solves, from RAGNAROK_QUEUE_CONCURRENCY.

    Clamped to ``[1, _CPU_COUNT]``; any malformed value falls back to 1 (serial)
    with a warning rather than crashing module import (a bare ``int()`` would
    raise on ``"2.0"`` / ``""``). 1 reproduces the original serial queue exactly.
    """
    raw = os.environ.get("RAGNAROK_QUEUE_CONCURRENCY", "1")
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        _queue_logger.warning(
            "Invalid RAGNAROK_QUEUE_CONCURRENCY=%r; defaulting to 1 (serial).", raw
        )
        return 1
    return max(1, min(n, _CPU_COUNT))


# Mutable at runtime via POST /api/queue/concurrency; seeded from the env var,
# then overridden by the persisted value (if any) on startup. Read live by the
# pump each tick, so a change takes effect within one poll interval.
_queue_concurrency: int = _read_queue_concurrency()


def _queue_settings_path() -> Path:
    return _QUEUE_DIR / _QUEUE_SETTINGS


def _save_queue_concurrency() -> None:
    try:
        _write_json_atomic(_queue_settings_path(), {"concurrency": _queue_concurrency})
    except Exception:  # noqa: BLE001
        _queue_logger.exception("Failed to persist queue concurrency")


def _load_queue_concurrency() -> None:
    """Override the env default with the persisted value, if present and valid."""
    global _queue_concurrency
    path = _queue_settings_path()
    try:
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        n = int(data.get("concurrency"))
        _queue_concurrency = max(1, min(n, _CPU_COUNT))
    except Exception:  # noqa: BLE001
        _queue_logger.warning("Ignoring unreadable queue settings at %s", path)


def _resolve_cores(solver_threads: Any) -> int:
    """Cores a solve gets: an explicit positive count verbatim, else (Auto / 0)
    an equal share of the machine, ``cpu // concurrency`` (>= 1). With
    concurrency 1 the Auto share is all cores — the original behaviour."""
    try:
        n = int(solver_threads)
    except (TypeError, ValueError):
        n = 0
    if n > 0:
        return n
    return max(1, _CPU_COUNT // max(1, _queue_concurrency))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _QueueItem:
    id: str
    payload_path: Path
    label: str
    summary: dict[str, Any]
    submitted_at: str
    status: str = "queued"  # queued | staged | running | done | error | cancelled
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    proc: "mp.Process | None" = field(default=None, repr=False)
    result_queue: Any = field(default=None, repr=False)
    # OS pid of the worker, persisted in meta.json. After a backend restart the
    # mp.Process handle is gone, but the pid lets the new process check whether
    # the orphaned solver is still alive (recovery + cancel).
    pid: int | None = None
    # Cores assigned to this solve, resolved at dispatch (see _resolve_cores).
    # None until dispatched — to_dict then reports a live projection instead.
    cores: int | None = None

    def to_dict(self) -> dict[str, Any]:
        # Running/done items report the cores actually assigned at dispatch; a
        # still-queued item has none yet, so project from its solver-thread
        # setting + the current concurrency (the UI previews it this way).
        cores = self.cores if self.cores is not None else _resolve_cores(self.summary.get("solverThreads"))
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "submittedAt": self.submitted_at,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "error": self.error,
            "payloadAvailable": self.payload_path.exists(),
            "cores": cores,
            **self.summary,
        }


_run_queue: list[_QueueItem] = []


def _payload_to_dict(payload: RunPayload) -> dict[str, Any]:
    """Return a JSON-serialisable dict for Pydantic v1 or v2."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump(mode="json")  # type: ignore[attr-defined]
    return payload.dict()


def _queue_item_dir(item_id: str) -> Path:
    return _QUEUE_DIR / item_id


def _queue_payload_path(item_id: str) -> Path:
    return _queue_item_dir(item_id) / _QUEUE_PAYLOAD


def _queue_meta_path(item_id: str) -> Path:
    return _queue_item_dir(item_id) / _QUEUE_META


def _queue_outcome_path(item_id: str) -> Path:
    return _queue_item_dir(item_id) / _QUEUE_OUTCOME


def _read_queue_outcome(item_id: str) -> dict[str, Any] | None:
    """The worker's on-disk completion record, or None if absent/unreadable."""
    path = _queue_outcome_path(item_id)
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _pid_alive(pid: int | None) -> bool:
    """True when ``pid`` is a live process we may signal (the orphaned worker).

    Platform split is load-bearing: on POSIX ``os.kill(pid, 0)`` is the
    standard liveness probe, but on Windows ``os.kill`` with ANY non-console
    signal — including 0 — calls TerminateProcess, i.e. it would KILL the
    orphaned solve we are checking on. Windows probes via OpenProcess instead.
    """
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _adopt_outcome(item: _QueueItem, outcome: dict[str, Any]) -> None:
    """Apply a worker-written outcome.json to the queue item (done/error)."""
    status = str(outcome.get("status") or "")
    item.status = "done" if status == "done" else "error"
    item.error = str(outcome["error"]) if outcome.get("error") else None
    item.finished_at = str(outcome.get("finishedAt") or _now_iso())


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _write_queue_payload(item_id: str, payload: RunPayload) -> Path:
    path = _queue_payload_path(item_id)
    _write_json_atomic(path, _payload_to_dict(payload))
    return path


def _read_queue_payload(path: Path) -> RunPayload:
    return RunPayload(**json.loads(path.read_text(encoding="utf-8")))


def _queue_meta(item: _QueueItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "label": item.label,
        "summary": item.summary,
        "submittedAt": item.submitted_at,
        "status": item.status,
        "startedAt": item.started_at,
        "finishedAt": item.finished_at,
        "error": item.error,
        "pid": item.pid,
        "cores": item.cores,
        "payloadFile": _QUEUE_PAYLOAD,
    }


def _persist_queue_meta(item: _QueueItem) -> None:
    try:
        _write_json_atomic(_queue_meta_path(item.id), _queue_meta(item))
    except Exception:  # noqa: BLE001
        _queue_logger.exception("Failed to persist queue metadata for %s", item.id)


def _load_queue_from_disk() -> None:
    """Restore queued metadata and payload references from backend/data/queue."""
    _load_queue_concurrency()
    if not _QUEUE_DIR.exists():
        return
    restored: list[_QueueItem] = []
    for meta_path in sorted(_QUEUE_DIR.glob(f"*/{_QUEUE_META}")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            item_id = str(meta.get("id") or meta_path.parent.name)
            payload_path = meta_path.parent / str(meta.get("payloadFile") or _QUEUE_PAYLOAD)
            if not payload_path.exists():
                _queue_logger.warning("Skipping queue item %s without payload file", item_id)
                continue
            status = str(meta.get("status") or "queued")
            started_at = meta.get("startedAt")
            finished_at = meta.get("finishedAt")
            error = meta.get("error")
            pid_raw = meta.get("pid")
            pid = pid_raw if isinstance(pid_raw, int) else None
            cores_raw = meta.get("cores")
            cores = cores_raw if isinstance(cores_raw, int) else None
            if status == "running":
                # The previous backend died mid-solve. Three possibilities:
                # 1) the worker FINISHED while we were down → adopt its outcome;
                # 2) the worker is STILL solving (it's a separate OS process and
                #    survives the parent) → keep "running"; a watcher task
                #    (started in lifespan) flips it when outcome.json appears;
                # 3) the worker died with us → error, ask the user to rerun.
                outcome = _read_queue_outcome(item_id)
                if outcome is not None:
                    status = "done" if outcome.get("status") == "done" else "error"
                    error = outcome.get("error")
                    finished_at = outcome.get("finishedAt") or _now_iso()
                    _queue_logger.info("Adopted finished orphan run %s: %s", item_id, status)
                elif _pid_alive(pid):
                    _queue_logger.info("Queue item %s still solving in orphan pid %s", item_id, pid)
                else:
                    status = "error"
                    finished_at = _now_iso()
                    error = error or (
                        "Backend restarted mid-solve and the solver did not survive. "
                        "Rerun to try again."
                    )
            item = _QueueItem(
                id=item_id,
                payload_path=payload_path,
                label=str(meta.get("label") or item_id),
                summary=meta.get("summary") if isinstance(meta.get("summary"), dict) else {},
                submitted_at=str(meta.get("submittedAt") or _now_iso()),
                status=status,
                started_at=str(started_at) if started_at else None,
                finished_at=str(finished_at) if finished_at else None,
                error=str(error) if error else None,
                pid=pid,
                cores=cores,
            )
            restored.append(item)
            if status != meta.get("status") or finished_at != meta.get("finishedAt"):
                _persist_queue_meta(item)
        except Exception:  # noqa: BLE001
            _queue_logger.exception("Skipping unreadable queue metadata: %s", meta_path)
    restored.sort(key=lambda item: item.submitted_at)
    _run_queue[:] = restored


def _delete_queue_files(item_id: str) -> None:
    shutil.rmtree(_queue_item_dir(item_id), ignore_errors=True)


def _queue_label(payload: RunPayload) -> str:
    opts = payload.options or {}
    scen = payload.scenario or {}
    return str(
        opts.get("runLabel")
        or opts.get("scenarioLabel")
        or scen.get("label")
        or opts.get("filename")
        or "Run"
    )


def _queue_summary(payload: RunPayload) -> dict[str, Any]:
    """Small, display-only run settings for the Queue card."""
    opts = payload.options or {}
    scen = payload.scenario or {}
    start, end = opts.get("snapshotStart"), opts.get("snapshotEnd")
    snaps = (
        end - start
        if isinstance(start, (int, float)) and isinstance(end, (int, float))
        else opts.get("snapshotCount")
    )
    return {
        "snapshots": snaps,
        "snapshotWeight": opts.get("snapshotWeight"),
        "scenarioLabel": opts.get("scenarioLabel") or scen.get("label"),
        "solver": opts.get("solverType"),
        # Raw solver-thread setting (0 = Auto). Drives the projected core count
        # in the Queue UI before this job is dispatched.
        "solverThreads": opts.get("solverThreads", 0),
        "carbonPrice": scen.get("carbonPrice"),
        "rolling": bool((opts.get("rollingConfig") or {}).get("enabled")),
        "pathway": bool((opts.get("pathwayConfig") or {}).get("enabled")),
        "backend": opts.get("backend"),
        "filename": opts.get("filename"),
    }


def _queue_position() -> int:
    return sum(1 for it in _run_queue if it.status == "queued")


def _enqueue_payload(payload: RunPayload) -> tuple[_QueueItem, int]:
    item_id = str(uuid.uuid4())
    item = _QueueItem(
        id=item_id,
        payload_path=_write_queue_payload(item_id, payload),
        label=_queue_label(payload),
        summary=_queue_summary(payload),
        submitted_at=_now_iso(),
    )
    _persist_queue_meta(item)
    _run_queue.append(item)
    return item, _queue_position()


def _find_queue_item(item_id: str) -> _QueueItem | None:
    return next((it for it in _run_queue if it.id == item_id), None)


def _finalize_queue_item(item: _QueueItem) -> None:
    """Guarantee a dispatched item never stays stuck at "running".

    Each job runs as a fire-and-forget task (see _queue_pump), so an exception
    thrown before the terminal-status assignment — e.g. ctx.Process(...) or
    proc.start() raising — would otherwise leave status="running" forever and
    permanently consume a concurrency slot. Force it to error here; leave
    already-terminal states (done/error/cancelled) untouched.
    """
    if item.status == "running":
        item.status = "error"
        item.error = item.error or "Solve dispatch failed before completion."
        item.finished_at = _now_iso()
        _persist_queue_meta(item)
        _queue_logger.error("Queue item %s forced to error in finalizer", item.id)


async def _run_queue_item(item: _QueueItem) -> None:
    """Run one already-claimed (status=='running') job in a child process.

    The pump sets status/started_at/cores synchronously before scheduling this
    coroutine (so the same item is never dispatched twice); here we only spawn
    the worker, await its result, and record the terminal status. The try/finally
    guarantees the slot is released even on an unexpected failure.
    """
    try:
        ctx = mp.get_context("spawn")
        item.result_queue = ctx.Queue()
        item.proc = ctx.Process(
            target=_solve_worker,
            args=(str(item.payload_path), item.result_queue, item.cores),
            daemon=True,
        )
        # A rerun reuses this item's dir — drop any outcome from a previous
        # attempt so restart-recovery can never adopt a stale result.
        _queue_outcome_path(item.id).unlink(missing_ok=True)
        item.proc.start()
        item.pid = item.proc.pid  # persisted so a restarted backend can find the orphan
        _persist_queue_meta(item)

        # Read the result FIRST. The worker puts a (possibly large) result dict on
        # the queue and only then exits; a multiprocessing.Queue blocks the child's
        # exit until that payload is drained by the parent, so calling join() before
        # reading deadlocks (the job appears stuck "running" forever). Poll
        # get_nowait without blocking the event loop until the message arrives.
        status: str | None = None
        data: Any = None
        while True:
            if item.status == "cancelled":
                return
            try:
                status, data = item.result_queue.get_nowait()
                break
            except queue.Empty:
                if not item.proc.is_alive():
                    break  # exited without delivering a result
                await asyncio.sleep(0.3)

        # The result is drained, so the child can now finish persisting (store_run
        # runs after the put) and exit. Wait for that — process exit guarantees the
        # run + its xlsx are on disk. Bounded so a stuck child can never wedge its
        # slot indefinitely; other concurrent jobs are unaffected.
        await asyncio.to_thread(item.proc.join, 600)
        if item.proc.is_alive():
            _queue_logger.warning("Queue item %s did not exit within 600s after result", item.id)
        if item.status == "cancelled":
            _persist_queue_meta(item)
            return
        if status == "ok":
            item.status = "done"
        elif status == "err":
            item.status = "error"
            item.error = str(data)
        else:
            item.status = "error"
            item.error = "Worker exited without delivering a result."
        item.finished_at = _now_iso()
        _persist_queue_meta(item)
        _queue_logger.info("Queue item %s finished: %s", item.id, item.status)
    finally:
        _finalize_queue_item(item)


async def _watch_orphan(item: _QueueItem) -> None:
    """Track a solve that survived a backend restart (alive, but not our child).

    We can't ``join()`` a process we didn't spawn, but the worker writes
    ``outcome.json`` when it finishes — poll for that (or for the pid dying) and
    flip the queue card to done/error. While this item stays "running" the pump
    won't start another job, preserving the serial-queue guarantee.
    """
    while item.status == "running":
        outcome = _read_queue_outcome(item.id)
        if outcome is not None:
            _adopt_outcome(item, outcome)
            _persist_queue_meta(item)
            _queue_logger.info("Orphan run %s finished: %s", item.id, item.status)
            return
        if not _pid_alive(item.pid):
            # Give a just-exited worker a moment to flush its outcome file.
            await asyncio.sleep(2.0)
            outcome = _read_queue_outcome(item.id)
            if outcome is not None:
                _adopt_outcome(item, outcome)
            else:
                item.status = "error"
                item.error = "The solver process died without delivering a result. Rerun to try again."
                item.finished_at = _now_iso()
            _persist_queue_meta(item)
            _queue_logger.info("Orphan run %s ended: %s", item.id, item.status)
            return
        await asyncio.sleep(1.0)


# Monotonic timestamp of the pump's last loop iteration — the health check uses
# it to verify the background queue worker is actually ticking. The pump now
# dispatches jobs as fire-and-forget tasks and keeps ticking while they run, so
# the heartbeat stays fresh throughout a solve.
_PUMP_HEARTBEAT: float | None = None

# Strong references to in-flight job tasks. asyncio holds only weak refs to
# tasks created with ensure_future, so without this a job task could be
# garbage-collected mid-run ("Task was destroyed but it is pending"). Discarded
# in the done-callback.
_inflight_tasks: "set[asyncio.Task]" = set()


def _on_queue_task_done(task: "asyncio.Task") -> None:
    _inflight_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        # _run_queue_item's finally already forced a terminal status; just log.
        _queue_logger.error("Queue job task crashed", exc_info=exc)


async def _queue_pump() -> None:
    """Background loop: keep up to ``_queue_concurrency`` solves running.

    Each tick fills every free slot by claiming queued items in submitted order.
    The claim (status→running, started_at, cores) is done SYNCHRONOUSLY before
    ``ensure_future`` — with no ``await`` in between — so a second pump iteration
    can never re-dispatch the same item (it already reads as "running"). With
    concurrency 1 this is exactly the original one-at-a-time behaviour.
    """
    global _PUMP_HEARTBEAT
    while True:
        try:
            _PUMP_HEARTBEAT = time.monotonic()
            dispatched = False
            running = sum(1 for it in _run_queue if it.status == "running")
            free = _queue_concurrency - running
            if free > 0:
                for it in _run_queue:
                    if free <= 0:
                        break
                    if it.status != "queued":
                        continue
                    # --- synchronous claim: no await until ensure_future ---
                    it.status = "running"
                    it.started_at = _now_iso()
                    it.finished_at = None
                    it.error = None
                    it.cores = _resolve_cores(it.summary.get("solverThreads"))
                    _persist_queue_meta(it)
                    task = asyncio.ensure_future(_run_queue_item(it))
                    _inflight_tasks.add(task)
                    task.add_done_callback(_on_queue_task_done)
                    free -= 1
                    dispatched = True
            if not dispatched:
                await asyncio.sleep(0.4)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — the pump must never die
            _queue_logger.exception("Queue pump iteration failed")
            await asyncio.sleep(1.0)


# ── FastAPI app ───────────────────────────────────────────────────────────────

from contextlib import asynccontextmanager  # noqa: E402
from . import startup_status  # noqa: E402


@asynccontextmanager
async def _lifespan(_app: "FastAPI"):
    """Warm the config bundle in the background as soon as the server is up.

    Kicking the build off as a task (rather than awaiting it here) means
    the server starts accepting requests immediately, so the frontend's
    ``GET /api/status`` poll sees live progress instead of a hung
    connection. See ``startup_status.warm``.
    """
    _load_queue_from_disk()
    task = asyncio.ensure_future(startup_status.warm())
    pump = asyncio.ensure_future(_queue_pump())
    sweeper = asyncio.ensure_future(_export_sweeper())
    # Solves that survived a backend restart (status still "running"): watch
    # each orphaned worker until its on-disk outcome appears or its pid dies.
    watchers = [
        asyncio.ensure_future(_watch_orphan(it)) for it in _run_queue if it.status == "running"
    ]
    try:
        yield
    finally:
        if not task.done():
            task.cancel()
        if not pump.done():
            pump.cancel()
        if not sweeper.done():
            sweeper.cancel()
        for w in watchers:
            if not w.done():
                w.cancel()
        # Stop the physical-risk run executor without waiting for an in-flight
        # CLIMADA job, so shutdown/reload during a run returns promptly.
        from .physical_risk import store as _physical_risk_store

        _physical_risk_store.shutdown_executor()


app = FastAPI(title="Ragnarok Backend", version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Comprehensive health report — every subsystem in one structured probe.

    ``status`` stays "ok"/"degraded" (back-compat for simple monitors); the
    ``checks`` block carries per-subsystem detail: storage engine + live
    session, runs store, queue (incl. a pump heartbeat), loaded plugins,
    solver availability and disk headroom.
    """
    import importlib.util as _ilu

    from . import plugins as _plugins

    checks: dict[str, Any] = {}
    problems: list[str] = []

    # Storage: engine + the working session.
    try:
        checks["store"] = {
            "engine": "sqlite" if model_store.USE_SQLITE else "legacy",
            "sessionLoaded": model_store.has_model("default"),
        }
    except Exception as exc:  # noqa: BLE001
        checks["store"] = {"error": str(exc)}
        problems.append("store")

    # Stored runs: count + the dir is writable.
    try:
        run_store.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        writable = os.access(run_store.RUNS_DIR, os.W_OK)
        checks["runs"] = {"count": len(run_store.list_runs()), "dirWritable": writable}
        if not writable:
            problems.append("runs")
    except Exception as exc:  # noqa: BLE001
        checks["runs"] = {"error": str(exc)}
        problems.append("runs")

    # Queue: job counts + pump liveness. The pump keeps ticking while solves run
    # (they're fire-and-forget tasks), so the heartbeat alone is authoritative;
    # "running > 0" is kept as a harmless extra signal.
    running = sum(1 for it in _run_queue if it.status == "running")
    pump_fresh = _PUMP_HEARTBEAT is not None and (time.monotonic() - _PUMP_HEARTBEAT) < 10.0
    pump_alive = pump_fresh or running > 0
    checks["queue"] = {
        "jobs": len(_run_queue),
        "running": running,
        "queued": sum(1 for it in _run_queue if it.status == "queued"),
        "pumpAlive": pump_alive,
    }
    if not pump_alive:
        problems.append("queue")

    # Plugins (3rd-party, installed at runtime — zero is healthy).
    try:
        checks["plugins"] = {"ids": sorted(_plugins.registry())}
    except Exception as exc:  # noqa: BLE001
        checks["plugins"] = {"error": str(exc)}

    # Solver + disk headroom.
    checks["solver"] = {"highs": _ilu.find_spec("highspy") is not None}
    try:
        du = shutil.disk_usage(_REPO_ROOT)
        free_gb = round(du.free / 1e9, 1)
        checks["disk"] = {"freeGb": free_gb, "totalGb": round(du.total / 1e9, 1)}
        if free_gb < 2.0:  # a solve writing results can fail well before zero
            problems.append("disk")
    except Exception as exc:  # noqa: BLE001
        checks["disk"] = {"error": str(exc)}

    checks["version"] = {"app": app.version, "python": sys.version.split()[0]}
    return {"status": "degraded" if problems else "ok", "problems": problems, "checks": checks}


@app.get("/api/status")
def status() -> dict[str, Any]:
    """Startup progress — polled by the frontend's boot progress screen.

    Returns ``{phase, detail, ready, error, progress, steps, build_id}``.
    ``ready`` flips true once the config bundle is built; until then the
    frontend shows the progress bar + per-step checklist.
    """
    return startup_status.snapshot()


# Shared-config bundle (PyPSA schema, standard types, capabilities,
# simulation defaults, …) is served by the dedicated config router so
# the frontend can fetch everything it needs to agree with the backend
# in one boot call.
from .routers import config as _config_router  # noqa: E402
app.include_router(_config_router.router)

# External-data importer subsystem (Data view). The browser POSTs a
# filter blob to /api/import/run; fetch + convert run server-side.
from .routers import importers as _importers_router  # noqa: E402
app.include_router(_importers_router.router)
from .routers import transforms as _transforms_router  # noqa: E402
app.include_router(_transforms_router.router)

# Forge "Query & Edit" — database-query-like bulk edits (filters + one-hop joins,
# static or temporal attributes). Pure resolver in app/forge_resolver.py.
from .routers import forge_query as _forge_query_router  # noqa: E402
app.include_router(_forge_query_router.router)

# Server-side working model ("session"). The backend is the source of truth for
# the model; the frontend imports once and then fetches pages/windows on demand.
from .routers import session as _session_router  # noqa: E402
app.include_router(_session_router.router)

# Bundled starter projects ("Start with Examples" on the welcome screen).
from .routers import examples as _examples_router  # noqa: E402
app.include_router(_examples_router.router)

# Backend (server-side) plugins. Discovered from disk and run in-process — they
# import the bundled PyPSA source directly (no separate server / plugins.env).
from .routers import plugins as _plugins_router  # noqa: E402
app.include_router(_plugins_router.router)

# PyPSA-Earth network builder (I9) — an async, queued build job (own conda env +
# CDS key). Gated behind RAGNAROK_PYPSA_EARTH_DIR; reports availability so the UI
# can guide setup.
from .routers import pypsa_earth as _pypsa_earth_router  # noqa: E402
app.include_router(_pypsa_earth_router.router)

# Power procurement portfolio optimizer (PP2) — CVaR-constrained instrument mix
# over a price series. A decision surface on top of prices, not a solve option.
from .routers import procurement as _procurement_router  # noqa: E402
app.include_router(_procurement_router.router)

# Native physical-climate-risk capability (Phase 0 scaffold) — portfolio seeded
# from the model, evaluated by a deterministic stub engine (no CLIMADA/conda yet).
from .routers import physical_risk as _physical_risk_router  # noqa: E402
app.include_router(_physical_risk_router.router)

# Siting (location optimisation) — samples a candidate grid over a bounding
# box, fetches keyless weather per point, and returns extendable candidate
# assets for the ordinary capacity-expansion solve to pick winners from.
from .routers import siting as _siting_router  # noqa: E402
app.include_router(_siting_router.router)


@app.get("/api/backends")
def get_backends() -> dict[str, Any]:
    """List the available optimisation backends and their capabilities.

    Kept as its own focused endpoint in addition to the
    ``GET /api/config`` bundle (which carries the same data under
    ``capabilities``) — the run dialog calls this directly when the
    user opens it, since capability flags can change without a schema
    rebuild and the cheap probe avoids a full bundle round-trip.
    """
    return {"backends": available_backends(), "default": "pypsa"}


@app.get("/api/log")
def get_log() -> dict[str, Any]:
    """Snapshot of the in-process log ring buffer.

    Fetched by the frontend Analytics → Log sub-tab on mount, on run
    completion, and on the Refresh button. Covers:
      • uvicorn HTTP access logs (with /api/run/{id} and /api/log polls
        already filtered out at INFO and dropped from the buffer);
      • uvicorn errors / startup;
      • anything emitted via ``logging.getLogger(...)`` in backend code.

    Solver C-stdout (HiGHS) and the linopy / PyPSA solve logs are NOT
    mirrored here — they stream live to the terminal that launched the
    backend (the run worker no longer redirects file descriptors). Watch
    that terminal for verbose solver progress.
    """
    entries, cursor, capacity = _log_snapshot()
    return {
        "entries": [
            {"ts": e.ts, "logger": e.logger, "level": e.level, "message": e.message}
            for e in entries
        ],
        "cursor": cursor,
        "capacity": capacity,
    }


@app.delete("/api/log")
def clear_log() -> dict[str, Any]:
    """Empty the in-process log ring buffer.

    Called by the Analytics → Log tab's Clear button. The monotonic
    cursor is preserved so the client can still see how many entries
    accumulated since the server started.
    """
    _log_clear()
    _, cursor, capacity = _log_snapshot()
    return {"entries": [], "cursor": cursor, "capacity": capacity}


def _resolve_payload_model(payload: RunPayload) -> RunPayload:
    """Materialise the model a run will solve.

    A thin client submits only ``{sessionId, scenario, options}`` — the working
    model lives server-side. Snapshot it into the payload *now* (at submit time)
    so a later edit to the session never mutates an already-submitted or queued
    run. A legacy payload carrying an inline ``model`` is returned unchanged.
    """
    overrides = (payload.options or {}).get("modelOverrides") or []
    if payload.model is not None:
        model = payload.model
    elif payload.sessionId:
        model = model_store.load_full_model(payload.sessionId)
        if not model:
            raise HTTPException(
                status_code=400, detail=f"No model loaded in session {payload.sessionId!r}."
            )
    else:
        raise HTTPException(
            status_code=400, detail="Run payload must include a model or a sessionId."
        )
    # Per-scenario model overrides (capacity, etc.) — applied to the snapshot now
    # so the solved + stored run reflects them (batch scenario runs differ here).
    if overrides:
        from . import scenario_overrides
        model = scenario_overrides.apply_model_overrides(model, overrides)
    data = _payload_to_dict(payload)
    data["model"] = model
    # Opt-in physical-risk -> forced-outage-rate coupling: if
    # options.outageMcConfig.physicalRiskUplift is set, look up the
    # referenced physical-risk session's latest completed run and inject
    # options.outageMcConfig.forRateUplift before the snapshot is frozen, so
    # both /api/run and /api/queue (both call this) pick it up. No-op unless
    # the config opts in; never raises.
    from . import physical_risk_uplift
    data["options"] = physical_risk_uplift.apply_physical_risk_uplift(data.get("options"))
    return RunPayload(**data)


@app.post("/api/validate")
def validate_case(payload: RunPayload) -> dict[str, Any]:
    return validate_model(_resolve_payload_model(payload))


@app.post("/api/run")
async def start_run(payload: RunPayload) -> dict[str, Any]:
    """
    Start a PyPSA optimisation job in a child process and return immediately.

    The frontend POSTs the in-memory workbook as JSON:
    `{model: {sheet: rows[]}, scenario: {...}, options: {...}}`.
    The backend builds the PyPSA network directly from each sheet via
    bulk `network.add()` and optimises in a child process. The frontend
    polls GET /api/run/{job_id} for status and results.
    """
    # Fail fast on an unknown backend so the caller gets a 400 immediately
    # rather than a 500 after the first poll.
    try:
        get_backend((payload.options or {}).get("backend"))
    except BackendError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Resolve the model from the session when the client sent only a sessionId.
    payload = _resolve_payload_model(payload)

    # Prune completed/cancelled jobs to avoid unbounded memory growth
    stale = [jid for jid, j in list(_jobs.items()) if j.status in ("done", "error", "cancelled")]
    for jid in stale:
        _jobs.pop(jid, None)

    job_id = str(uuid.uuid4())
    ctx = mp.get_context("spawn")
    result_queue: mp.Queue = ctx.Queue()
    proc: mp.Process = ctx.Process(
        target=_solve_worker,
        args=(payload, result_queue),
        daemon=True,
    )
    proc.start()
    _jobs[job_id] = _Job(id=job_id, proc=proc, result_queue=result_queue)
    asyncio.create_task(_collect_job(job_id))
    return {"jobId": job_id, "status": "running"}


@app.get("/api/run/{job_id}")
async def poll_run(job_id: str) -> dict[str, Any]:
    """Poll the status of a running job. Returns result inline when done."""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or already cleaned up.")
    if job.status == "running":
        return {"jobId": job_id, "status": "running"}
    elif job.status == "done":
        result = job.result
        _jobs.pop(job_id, None)   # free memory after delivery
        return {"jobId": job_id, "status": "done", "result": result}
    elif job.status == "error":
        error = job.error
        _jobs.pop(job_id, None)
        raise HTTPException(status_code=500, detail=f"PyPSA optimization failed: {error}")
    else:  # cancelled
        _jobs.pop(job_id, None)
        raise HTTPException(status_code=499, detail="Optimization was cancelled.")


@app.delete("/api/run/{job_id}")
async def cancel_run(job_id: str) -> dict[str, Any]:
    """Terminate a running job's child process.

    Escalate SIGTERM → SIGKILL. ``terminate()`` only sends SIGTERM, which the
    worker honours when it returns to Python — but a long native solve does
    not. The rolling-horizon path is the worst case: it chains many HiGHS
    solves in one process, so SIGTERM is frequently not acted on within the
    grace window and the worker keeps grinding through the remaining windows
    as an orphan after the job is forgotten. So if it is still alive after a
    short grace period, send SIGKILL (uncatchable) and only then drop the job.
    """
    job = _jobs.get(job_id)
    if job is None:
        return {"jobId": job_id, "status": "not_found"}
    if job.proc.is_alive():
        job.proc.terminate()                       # SIGTERM — graceful
        await asyncio.to_thread(job.proc.join, 3)
        if job.proc.is_alive():
            job.proc.kill()                        # SIGKILL — forceful
            await asyncio.to_thread(job.proc.join, 3)
    job.status = "cancelled"
    _jobs.pop(job_id, None)
    return {"jobId": job_id, "status": "cancelled"}


# ── Run queue endpoints ───────────────────────────────────────────────────────


@app.post("/api/queue")
async def enqueue_run(payload: RunPayload, staged: bool = False) -> dict[str, Any]:
    """Add a solve to the queue and return immediately.

    ``staged=false`` (default, the "Run" button): the job runs now if the queue
    is idle, else it's next — the pump picks it up. ``staged=true`` (the "Queue
    next Run" button): the job is parked as ``staged`` and the pump skips it
    until the user activates it (per-card Run). Either way the session model is
    snapshotted into the item now, so later edits can't change it. Returns the
    new item id, status and 1-based queue position.
    """
    try:
        get_backend((payload.options or {}).get("backend"))
    except BackendError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Snapshot the session model into the payload at submit time (see
    # _resolve_payload_model) so the queued run is immune to later edits.
    payload = _resolve_payload_model(payload)
    item, position = _enqueue_payload(payload)
    if staged:
        item.status = "staged"
        _persist_queue_meta(item)
    return {"id": item.id, "status": item.status, "position": position}


@app.get("/api/queue")
def get_queue() -> dict[str, Any]:
    """List queue items, plus the concurrency setting + core budget for the UI."""
    return {
        "jobs": [it.to_dict() for it in _run_queue],
        "concurrency": _queue_concurrency,
        "maxConcurrency": _CPU_COUNT,
        "cpuCount": _CPU_COUNT,
    }


@app.post("/api/queue/concurrency")
def set_queue_concurrency(body: dict[str, Any]) -> dict[str, Any]:
    """Set max concurrent solves (1 = serial queue). Clamped to [1, cpuCount].

    Lowering it never kills running jobs — they finish and no new ones start
    until a slot frees. Raising it lets the pump fill the new slots on its next
    tick. Persisted so the choice survives a restart.
    """
    global _queue_concurrency
    try:
        n = int(body.get("value"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="`value` must be an integer.")
    _queue_concurrency = max(1, min(n, _CPU_COUNT))
    _save_queue_concurrency()
    return {"concurrency": _queue_concurrency, "maxConcurrency": _CPU_COUNT, "cpuCount": _CPU_COUNT}


@app.post("/api/queue/{item_id}/cancel")
async def cancel_queued(item_id: str) -> dict[str, Any]:
    """Cancel a queued job, or kill it if it is currently running.

    The queue row and payload file are intentionally retained so the user can
    rerun the same submitted model later. Use DELETE /api/queue/{item_id} to
    remove the queue record and its payload file.
    """
    item = _find_queue_item(item_id)
    if item is None:
        return {"id": item_id, "status": "not_found"}
    if item.status in ("queued", "staged"):
        item.status = "cancelled"
        item.finished_at = _now_iso()
    elif item.status == "running":
        item.status = "cancelled"
        item.finished_at = _now_iso()
        proc = item.proc
        if proc is not None and proc.is_alive():
            proc.terminate()
            await asyncio.to_thread(proc.join, 3)
            if proc.is_alive():
                proc.kill()
                await asyncio.to_thread(proc.join, 3)
        elif proc is None and _pid_alive(item.pid):
            # Orphaned worker (survived a backend restart) — no mp handle, only
            # the persisted pid. POSIX: SIGTERM → SIGKILL escalation. Windows:
            # os.kill with a non-console signal IS TerminateProcess (hard kill),
            # and SIGKILL does not exist there — one shot is both available and
            # sufficient.
            try:
                os.kill(item.pid, signal.SIGTERM)  # type: ignore[arg-type]
                if hasattr(signal, "SIGKILL"):
                    await asyncio.sleep(3.0)
                    if _pid_alive(item.pid):
                        os.kill(item.pid, signal.SIGKILL)
            except OSError:
                pass  # already gone
    else:
        return {"id": item_id, "status": item.status}
    _persist_queue_meta(item)
    return {"id": item_id, "status": "cancelled"}


@app.post("/api/queue/{item_id}/rerun")
async def rerun_queued(item_id: str) -> dict[str, Any]:
    """Activate a queue item IN PLACE — re-runs its retained model snapshot.

    Used by the per-card "Run" button on a staged or finished/cancelled card.
    The SAME card flips back to ``queued`` (no duplicate card, no duplicated
    model) and the pump picks it up. A running item is left as-is.
    """
    item = _find_queue_item(item_id)
    if item is None:
        return {"id": item_id, "status": "not_found"}
    if item.status == "running":
        return {"id": item_id, "status": "running"}
    if not item.payload_path.exists():
        raise HTTPException(status_code=404, detail="Queued payload file is missing.")
    payload = _read_queue_payload(item.payload_path)
    try:
        get_backend((payload.options or {}).get("backend"))
    except BackendError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    item.status = "queued"
    item.started_at = None
    item.finished_at = None
    item.error = None
    _persist_queue_meta(item)
    return {"id": item.id, "status": "queued", "position": _queue_position()}


@app.post("/api/queue/{item_id}/import")
async def import_queue_item(item_id: str) -> dict[str, Any]:
    """Load a queue item's model snapshot into the current working session.

    Lets the user pull a queued/finished run back into the editor to tweak and
    re-run as a NEW entry (the original card is untouched).
    """
    item = _find_queue_item(item_id)
    if item is None or not item.payload_path.exists():
        raise HTTPException(status_code=404, detail="Queue item not found.")
    payload = _read_queue_payload(item.payload_path)
    if not payload.model:
        raise HTTPException(status_code=400, detail="Queue item has no model to import.")
    meta = model_store.save_model(
        "default",
        payload.model,
        filename=str((payload.options or {}).get("filename") or item.label),
        scenario_name=str((payload.scenario or {}).get("label") or ""),
    )
    return meta


@app.delete("/api/queue/{item_id}")
async def delete_queue_item(item_id: str) -> dict[str, Any]:
    """Delete a queue item and its retained model payload.

    This intentionally does not delete History entries produced by completed
    runs; History lives under backend/data/runs and has its own endpoint.
    """
    item = _find_queue_item(item_id)
    if item is None:
        _delete_queue_files(item_id)
        return {"id": item_id, "deleted": False}
    if item.status == "running":
        proc = item.proc
        item.status = "cancelled"
        item.finished_at = _now_iso()
        if proc is not None and proc.is_alive():
            proc.terminate()
            await asyncio.to_thread(proc.join, 3)
            if proc.is_alive():
                proc.kill()
                await asyncio.to_thread(proc.join, 3)
    _run_queue[:] = [it for it in _run_queue if it.id != item_id]
    _delete_queue_files(item_id)
    return {"id": item_id, "deleted": True}


# ── Backend-stored runs ─────────────────────────────────────────────────────
#
# Every successful solve is persisted by the worker: the full bundle (model +
# result) is written to backend/data/runs via run_store. The backend is the
# single source of truth for run history. These endpoints surface those runs in
# the History tab: list lightweight metas, reopen a full bundle, download a
# human-readable xlsx on demand, or delete. Storing server-side avoids the
# browser-tab OOM that a full-year xlsx export triggers client-side.


@app.get("/api/runs")
def list_backend_runs() -> dict[str, Any]:
    """List every backend-stored run's lightweight meta, newest first."""
    return {"runs": run_store.list_runs()}


@app.get("/api/runs/{name}")
def get_backend_run(name: str) -> dict[str, Any]:
    """Return the full stored bundle for ``name`` (404 if missing).

    Heavy (model + every output series). Prefer the granular endpoints below —
    ``/analytics`` then ``/series/{sheet}`` on demand — to avoid freezing the tab.
    Kept for back-compat and as the lossless export source.
    """
    bundle = run_store.get_run(name)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Stored run not found.")
    return bundle


@app.get("/api/runs/{name}/analytics")
def get_backend_run_analytics(name: str) -> dict[str, Any]:
    """Lightweight analytics bundle (no input model, no output series).

    What "View Result" loads first: summary, KPIs, carrier mix, cost, merit
    order, narrative, and the ``seriesSheets`` name list. Renders instantly; the
    series themselves load per-sheet on demand from ``/series/{sheet}``.
    """
    analytics = run_store.get_run_analytics(name)
    if analytics is None:
        raise HTTPException(status_code=404, detail="Stored run not found.")
    return analytics


@app.get("/api/runs/{name}/series/{sheet}")
def get_backend_run_series(
    name: str,
    sheet: str,
    start: int = 0,
    end: int | None = None,
    columns: str | None = None,
    max_points: int | None = Query(None, alias="maxPoints", ge=1),
    agg: str = "mean",
) -> dict[str, Any]:
    """Windowed + downsampled slice of a stored run's output time-series sheet."""
    cols = [c.strip() for c in columns.split(",") if c.strip()] if columns else None
    window = run_store.run_series_window(
        name, sheet, start=start, end=end, columns=cols, max_points=max_points, agg=agg
    )
    if window is None:
        raise HTTPException(status_code=404, detail="Run series not found.")
    return window


@app.get("/api/runs/{name}/derived/{metric}")
def get_backend_run_derived(
    name: str,
    metric: str,
    start: int = 0,
    end: int | None = None,
    max_points: int | None = Query(None, alias="maxPoints", ge=1),
) -> dict[str, Any]:
    """Server-side derived chart-series for a stored run (X1).

    Aggregates the raw per-asset output series into a system chart series
    (``dispatch_by_carrier`` / ``load`` / ``system_price``) on the backend, so
    the browser fetches ready-to-plot data instead of crunching thousands of
    per-asset columns for a large network.
    """
    from ..pypsa.results.derived_series import METRIC_SHEET, carrier_map, derive_series

    sheet = METRIC_SHEET.get(metric)
    if sheet is None:
        raise HTTPException(status_code=400, detail=f"Unknown metric {metric!r}. Options: {sorted(METRIC_SHEET)}.")
    window = run_store.run_series_window(name, sheet, start=start, end=end, max_points=max_points, agg="mean")
    if window is None:
        raise HTTPException(status_code=404, detail=f"Run has no {sheet!r} series.")
    carriers = carrier_map(run_store.get_run_model(name)) if metric == "dispatch_by_carrier" else {}
    derived = derive_series(
        window["columns"], window["rows"], window["indexCol"],
        metric=metric, carriers=carriers,
    )
    derived["window"] = window["window"]
    derived["total"] = window["total"]
    return derived


@app.get("/api/runs/{name}/model/sheet/{sheet}")
def get_backend_run_model_sheet(
    name: str, sheet: str, offset: int = 0, limit: int = 200
) -> dict[str, Any]:
    """One page of a stored run's INPUT model sheet (re-edit / import-project)."""
    page = run_store.run_model_sheet_page(name, sheet, offset=offset, limit=limit)
    if page is None:
        raise HTTPException(status_code=404, detail="Run model sheet not found.")
    return page


@app.delete("/api/runs/{name}")
def delete_backend_run(name: str) -> dict[str, Any]:
    """Delete the bundle + meta sidecar for ``name``."""
    return {"deleted": run_store.delete_run(name)}


class RenameRunRequest(BaseModel):
    """Body for ``POST /api/runs/{name}/rename``."""

    newName: str = ""


@app.post("/api/runs/{name}/rename")
def rename_backend_run(name: str, body: RenameRunRequest) -> dict[str, Any]:
    """Rename a stored run (file, identity, and display labels together).

    Guarded: unsafe names → 400, missing run → 404, name collision → 409.
    Returns the updated meta so the client can patch its list in place.
    """
    meta, err = run_store.rename_run(name, body.newName)
    if err == "unsafe":
        raise HTTPException(status_code=400, detail="Invalid run name.")
    if err == "not_found":
        raise HTTPException(status_code=404, detail="Stored run not found.")
    if err == "exists":
        raise HTTPException(status_code=409, detail="A run with that name already exists.")
    if err or meta is None:
        raise HTTPException(status_code=500, detail="Rename failed — see server logs.")
    return meta


class PromoteRunRequest(BaseModel):
    """Body for ``POST /api/runs/{name}/promote``."""

    sessionId: str = "default"


@app.post("/api/runs/{name}/promote")
def promote_run_to_session(name: str, body: PromoteRunRequest) -> dict[str, Any]:
    """Make a stored run the editable working model — SERVER-SIDE.

    The History "Import project" fast path. Copies the run's input model
    (static sheets + input time-series) straight from the run db into the
    session, so a full year of series never travels DB → browser → session (the
    old path fetched the whole bundle, cloned it, then re-pushed it — doubled).
    The editor rehydrates static-only and pages the series on demand. Returns
    the session meta plus the run's scenario / window so the client can restore
    constraints + run controls without a second heavy fetch.
    """
    data = run_store.get_run_model(name)
    if data is None:
        raise HTTPException(status_code=404, detail="Stored run not found.")
    model = data.get("model") or {}
    scenario = data.get("scenario") or {}
    options = data.get("options") or {}
    filename = str(options.get("filename") or data.get("filename") or f"{name}.xlsx")
    try:
        meta = model_store.save_model(
            body.sessionId, model, filename=filename, scenario_name=str(scenario.get("label") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "meta": meta,
        "scenario": scenario,
        "snapshotStart": data.get("snapshotStart") if data.get("snapshotStart") is not None else options.get("snapshotStart"),
        "snapshotEnd": data.get("snapshotEnd") if data.get("snapshotEnd") is not None else options.get("snapshotEnd"),
        "snapshotWeight": data.get("snapshotWeight") if data.get("snapshotWeight") is not None else options.get("snapshotWeight"),
        "filename": filename,
    }


_ZIP_MEDIA_TYPE = "application/zip"


# ── Async export jobs ─────────────────────────────────────────────────────────
# Building a full-year workbook is CPU-bound and can take minutes. Doing it
# inside the download request blocks the event loop and leaves the browser
# hanging on a pending download with no feedback (and risks proxy timeouts).
#
# Instead: POST /api/exports kicks off a background build (run off-thread so the
# loop keeps serving), the client polls GET /api/exports/{id} for status, and
# GET /api/exports/{id}/download streams the finished file from disk and deletes
# it afterwards. A TTL sweeper reaps artefacts the client never collected.
_export_logger = logging.getLogger("pypsa_gui.exports")
_EXPORTS_DIR = _REPO_ROOT / "backend" / "data" / "exports"
_EXPORT_TTL_SECONDS = 30 * 60  # reap built-but-uncollected artefacts after 30 min
_EXPORT_PARTS = ("metadata", "model", "result")


@dataclass
class _ExportJob:
    id: str
    run_name: str
    kind: str  # 'xlsx' | 'package'
    parts: tuple[str, ...]  # for xlsx; ignored for package
    filename: str
    status: str = "pending"  # pending | running | ready | error
    error: str | None = None
    size: int = 0
    created_at: str = ""
    created_mono: float = 0.0
    file_path: Path | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "runName": self.run_name,
            "kind": self.kind,
            "parts": list(self.parts),
            "filename": self.filename,
            "status": self.status,
            "error": self.error,
            "size": self.size,
            "createdAt": self.created_at,
        }


_export_jobs: dict[str, _ExportJob] = {}


def _build_export_artifact(job: _ExportJob) -> None:
    """Build the export bytes and write them under the job's dir (off-thread)."""
    if job.kind == "package":
        data = run_store.run_to_package(job.run_name)
    else:
        data = run_store.run_to_xlsx(
            job.run_name,
            include_meta="metadata" in job.parts,
            include_model="model" in job.parts,
            include_result="result" in job.parts,
        )
    if data is None:
        raise RuntimeError("Stored run not found or produced no data.")
    out_dir = _EXPORTS_DIR / job.id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / job.filename
    path.write_bytes(data)
    job.file_path = path
    job.size = len(data)


async def _run_export_job(job: _ExportJob) -> None:
    """Drive one export build to completion without blocking the event loop."""
    job.status = "running"
    try:
        await asyncio.to_thread(_build_export_artifact, job)
        job.status = "ready"
        _export_logger.info("Export %s ready: %s (%d bytes)", job.id, job.filename, job.size)
    except Exception as exc:  # noqa: BLE001 — surfaced to the client as a failed job
        job.status = "error"
        job.error = str(exc)
        _export_logger.exception("Export %s failed", job.id)


def _discard_export_job(job_id: str) -> None:
    """Remove a job from the registry and delete its on-disk artefact."""
    _export_jobs.pop(job_id, None)
    shutil.rmtree(_EXPORTS_DIR / job_id, ignore_errors=True)


async def _export_sweeper() -> None:
    """Reap export artefacts the client never downloaded (older than the TTL)."""
    # Clear anything left on disk from a previous backend process at startup.
    shutil.rmtree(_EXPORTS_DIR, ignore_errors=True)
    while True:
        try:
            now = time.monotonic()
            stale = [
                jid for jid, job in _export_jobs.items()
                if now - job.created_mono > _EXPORT_TTL_SECONDS
            ]
            for jid in stale:
                _export_logger.info("Reaping stale export %s", jid)
                _discard_export_job(jid)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _export_logger.exception("Export sweeper iteration failed")
        await asyncio.sleep(300)


@app.post("/api/exports")
async def create_export_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Start a background export build; returns ``{jobId}`` for status polling.

    Body: ``{name, kind: 'xlsx'|'package', parts?: [...]}``. ``parts`` (a subset
    of metadata/model/result) applies to xlsx; the package always ships all
    three artefacts.
    """
    name = str(payload.get("name") or "")
    kind = str(payload.get("kind") or "xlsx").lower()
    if kind not in ("xlsx", "package"):
        raise HTTPException(status_code=400, detail="kind must be 'xlsx' or 'package'.")
    if not run_store.run_exists(name):
        raise HTTPException(status_code=404, detail="Stored run not found.")

    if kind == "package":
        parts: tuple[str, ...] = _EXPORT_PARTS
        filename = f"{name}.zip"
    else:
        raw = payload.get("parts")
        chosen = (
            {str(p).strip().lower() for p in raw if str(p).strip()}
            if isinstance(raw, list) and raw
            else set(_EXPORT_PARTS)
        )
        if not chosen <= set(_EXPORT_PARTS):
            raise HTTPException(status_code=400, detail=f"parts must be a subset of {list(_EXPORT_PARTS)}.")
        parts = tuple(p for p in _EXPORT_PARTS if p in chosen)
        filename = f"{name}.xlsx"

    job = _ExportJob(
        id=str(uuid.uuid4()),
        run_name=name,
        kind=kind,
        parts=parts,
        filename=filename,
        created_at=_now_iso(),
        created_mono=time.monotonic(),
    )
    _export_jobs[job.id] = job
    asyncio.ensure_future(_run_export_job(job))
    return {"jobId": job.id, **job.to_dict()}


@app.get("/api/exports/{job_id}")
def get_export_job(job_id: str) -> dict[str, Any]:
    """Poll an export job's status (pending / running / ready / error)."""
    job = _export_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Export job not found (it may have expired).")
    return job.to_dict()


@app.get("/api/exports/{job_id}/download")
def download_export_job(job_id: str) -> Response:
    """Stream a ready export, then delete its artefact + registry entry."""
    job = _export_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Export job not found (it may have expired).")
    if job.status == "error":
        raise HTTPException(status_code=500, detail=job.error or "Export failed.")
    if job.status != "ready" or job.file_path is None or not job.file_path.exists():
        raise HTTPException(status_code=409, detail="Export is not ready yet.")
    media_type = _ZIP_MEDIA_TYPE if job.kind == "package" else _XLSX_MEDIA_TYPE
    return FileResponse(
        path=job.file_path,
        media_type=media_type,
        filename=job.filename,
        # Delete the artefact (and forget the job) only after the bytes are
        # flushed to the client.
        background=BackgroundTask(_discard_export_job, job_id),
    )


@app.post("/api/export/project")
def export_project(payload: ExportProjectPayload) -> Response:
    """Build a Ragnarok Project package (.zip of canonical JSON + readable xlsx).

    For an *unsaved* live model with no stored run. The frontend POSTs
    ``{model, result}``; the server packs it into a lossless project zip
    (re-importable) and streams it back. (Stored runs use the richer
    ``GET /api/runs/{name}/package``, which has the full bundle.)
    """
    from . import project_workbook

    try:
        bundle = {"model": payload.model, "result": payload.result}
        meta = run_store.build_run_meta("ragnarok_project", bundle)
        data = project_workbook.bundle_to_package(bundle, "ragnarok_project", meta=meta)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Project export failed: {exc}") from exc
    return Response(
        content=data,
        media_type=_ZIP_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="ragnarok_project.zip"'},
    )


@app.post("/api/import/project/load")
async def import_project_load(file: UploadFile) -> dict[str, Any]:
    """Parse an uploaded project file into a bundle and RETURN it — no History.

    This is the default "Import Project" path. Importing a project is *opening a
    file*: the browser loads the returned model + its solved results into the
    editor (like File→Open), and nothing is persisted. History stays an audit
    trail of solves and explicit result imports
    (:func:`import_result_xlsx`) — re-run the loaded model to create a History
    entry. Accepts a Ragnarok Project ``.zip`` (canonical JSON + readable xlsx)
    or a bare ``.xlsx``; returns ``{model, scenario, options, result, filename}``.
    """
    from . import project_workbook

    raw = await file.read()
    filename = file.filename or "imported_project.zip"

    # Parsing the workbook is heavy, synchronous CPU work — run it off the event
    # loop so a large import never blocks other requests (incl. the boot poll).
    try:
        bundle = await asyncio.to_thread(
            project_workbook.import_bundle_from_upload, raw, filename
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Project import failed: {exc}") from exc

    options = bundle.get("options") or {}
    options.setdefault("filename", filename)
    return {
        "model": bundle.get("model") or {},
        "scenario": bundle.get("scenario") or {},
        "options": options,
        "result": bundle.get("result") or {},
        "filename": filename,
    }


@app.post("/api/import/project")
async def import_project(file: UploadFile) -> dict[str, Any]:
    """Parse an uploaded project file into a run bundle and store it in History.

    The explicit-persist variant: it converts the upload to the canonical
    bundle (verbatim from the package JSON when present) and persists it with
    ``run_store.store_run``, so the imported project becomes a History entry
    openable with full analytics like any solved run. Returns the new run's meta
    (its ``name`` lets the frontend open it immediately).

    The default "Import Project" button uses :func:`import_project_load`
    instead — opening a file should NOT create a History entry. This endpoint
    remains for API clients that *want* the imported project persisted.
    """
    from . import project_workbook

    raw = await file.read()
    filename = file.filename or "imported_project.zip"

    def _parse_and_store() -> dict[str, Any] | None:
        bundle = project_workbook.import_bundle_from_upload(raw, filename)
        return run_store.store_run(
            bundle.get("model") or {},
            bundle.get("scenario") or {},
            bundle.get("options") or {},
            bundle.get("result") or {},
        )

    # Parsing the workbook and (re)building the stored xlsx are heavy, synchronous
    # CPU work. Run them in a worker thread so they never block the event loop —
    # otherwise a large import freezes EVERY request, including the boot screen's
    # /api/status poll (which is why a mid-import browser reload hung on startup).
    try:
        meta = await asyncio.to_thread(_parse_and_store)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Project import failed: {exc}") from exc
    if meta is None:
        raise HTTPException(status_code=500, detail="Imported project could not be stored.")
    return {"meta": meta, "name": meta.get("name")}


@app.post("/api/import/result")
@app.post("/api/import/result/xlsx")  # legacy alias (pre-zip-support frontends)
async def import_result(file: UploadFile) -> dict[str, Any]:
    """Import a RESULT-bearing file as a persistent History entry (model + results).

    Accepts:

    * a **Ragnarok project ``.zip``** (or an ``.xlsx`` carrying the embedded
      bundle) — the full model **and** its solved results round-trip verbatim
      from the canonical bundle, so summary / carrier mix / dispatch are
      preserved exactly as they were exported (no re-derivation);
    * a **bare results ``.xlsx``** (third-party model, plugin output,
      hand-assembled table) — sheets are mapped to the canonical result schema
      (``outputs.static`` / ``outputs.series``) and the analytics the Result
      view renders are DERIVED from the stored outputs (network rebuilt + the
      outputs injected + the same extraction helpers a solve uses).

    Either way it persists via ``run_store.store_run(origin="xlsx_import")`` —
    so the result lands in History, opens with full analytics, is comparable
    like any solved run, and survives refresh / restart. Returns the new run's
    name. Distinct from :func:`import_project_load`, which only loads a project
    into the editor without persisting.
    """
    from . import project_workbook

    raw = await file.read()
    filename = file.filename or "imported_result.xlsx"
    if not filename.lower().endswith((".xlsx", ".xls", ".zip")):
        raise HTTPException(
            status_code=400, detail="Result import expects an .xlsx / .xls / .zip file."
        )

    def _parse_and_store() -> dict[str, Any] | None:
        # Handles both a project package (.zip / embedded-bundle .xlsx → full
        # model+results verbatim) and a bare workbook (reconstruct outputs).
        bundle = project_workbook.import_bundle_from_upload(raw, filename)
        model = bundle.get("model") or {}
        scenario = bundle.get("scenario") or {}
        options = bundle.get("options") or {}
        options.setdefault("filename", filename)
        result = bundle.get("result") or {}
        outputs = result.get("outputs") or {}
        # A project package already carries the derived analytics (summary,
        # carrierMix, …) — keep them verbatim. Only a bare results workbook
        # arrives with raw outputs and no derived analytics; rebuild + inject +
        # extract so the Result view populates. Best-effort: on failure the raw
        # outputs are still stored (openable, just sparser).
        has_derived = isinstance(result.get("summary"), list) and bool(result.get("summary"))
        if not has_derived and (outputs.get("series") or outputs.get("static")):
            try:
                from ..pypsa.results.from_outputs import derive_imported_result

                derived = derive_imported_result(model, scenario, options, outputs)
                result = {**result, **derived, "outputs": outputs}
            except Exception:  # noqa: BLE001
                logging.getLogger("pypsa_gui.import").exception(
                    "Could not derive analytics for imported result %s; storing raw outputs",
                    filename,
                )
        return run_store.store_run(model, scenario, options, result, origin="xlsx_import")

    try:
        meta = await asyncio.to_thread(_parse_and_store)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Result import failed: {exc}") from exc
    if meta is None:
        raise HTTPException(status_code=500, detail="Imported result could not be stored.")
    return {"meta": meta, "name": meta.get("name")}


@app.get("/api/runs/{name}/xlsx")
def download_backend_run_xlsx(name: str, parts: str = "metadata,model,result") -> Response:
    """Build and return the export xlsx for stored run ``name`` (explicit export).

    Excel is never auto-written — this endpoint derives the workbook from the
    canonical bundle ON each download. ``parts`` selects the sheet groups
    (comma-separated subset of ``metadata``/``model``/``result``; default all),
    mirroring the Export dialog's checkboxes. The full default selection stays
    PyPSA-import-ready.
    """
    chosen = {p.strip().lower() for p in parts.split(",") if p.strip()}
    valid = {"metadata", "model", "result"}
    if not chosen or not chosen <= valid:
        raise HTTPException(status_code=400, detail=f"parts must be a subset of {sorted(valid)}.")
    data = run_store.run_to_xlsx(
        name,
        include_meta="metadata" in chosen,
        include_model="model" in chosen,
        include_result="result" in chosen,
    )
    if data is None:
        raise HTTPException(status_code=404, detail="Stored run not found.")
    return Response(
        content=data,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'},
    )


@app.get("/api/runs/{name}/package")
def download_backend_run_package(name: str) -> Response:
    """Return a Ragnarok Project ``.zip`` for stored run ``name``.

    Packs ALL THREE artefacts — ``<name>.json`` (canonical bundle),
    ``<name>.meta.json`` (sidecar), ``<name>.xlsx`` (readable workbook) — from
    the files on disk. This is the export to share / re-import; the bare
    ``/xlsx`` endpoint is only for quick viewing in Excel.
    """
    data = run_store.run_to_package(name)
    if data is None:
        raise HTTPException(status_code=404, detail="Stored run not found.")
    return Response(
        content=data,
        media_type=_ZIP_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
    )


# ── PyPSA-native binary formats (netCDF / HDF5) ──────────────────────────────
#
# Browsers cannot read/write netCDF or HDF5 reliably (the only mature readers
# are Python-side: xarray for netCDF, pytables for HDF5). Ragnarok solves this
# by hosting the conversion on the backend: the frontend POSTs the in-memory
# workbook model, the backend builds a `pypsa.Network` with the existing
# schema-driven import path, calls `network.export_to_<format>(...)`, and
# returns the bytes. Import is the inverse — receive a file upload, parse with
# PyPSA, and return the in-memory model JSON. No solve happens here; these are
# pure format converters.


def _model_payload_to_network(payload: RunPayload):
    """Build a `pypsa.Network` from a RunPayload without solving.

    Mirrors the in-process flow that `/api/run` performs: applies the
    Ragnarok runtime-import rules, snapshots index, time-series sheets, and
    every deterministic post-load transformation. SCLOPF / stochastic /
    rolling-horizon flags in `options` are ignored here — the resulting
    network is the deterministic case the user authored, suitable for
    sharing with downstream PyPSA tooling.
    """
    network, _notes = build_network(payload.model, payload.scenario, payload.options or {})
    return network


@app.post("/api/export/netcdf")
async def export_netcdf(payload: RunPayload) -> Response:
    """Return the model as a PyPSA-native netCDF file."""
    try:
        network = _model_payload_to_network(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"netCDF build failed: {exc}") from exc
    with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp:
        path = Path(tmp.name)
    try:
        network.export_to_netcdf(str(path))
        data = path.read_bytes()
    finally:
        path.unlink(missing_ok=True)
    return Response(
        content=data,
        media_type="application/x-netcdf",
        headers={"Content-Disposition": 'attachment; filename="ragnarok_network.nc"'},
    )


@app.post("/api/export/hdf5")
async def export_hdf5(payload: RunPayload) -> Response:
    """Return the model as a PyPSA-native HDF5 file."""
    try:
        network = _model_payload_to_network(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"HDF5 build failed: {exc}") from exc
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        path = Path(tmp.name)
    try:
        network.export_to_hdf5(str(path))
        data = path.read_bytes()
    finally:
        path.unlink(missing_ok=True)
    return Response(
        content=data,
        media_type="application/x-hdf5",
        headers={"Content-Disposition": 'attachment; filename="ragnarok_network.h5"'},
    )


# `_network_to_model_json` (network → workbook-model JSON) now lives in
# `backend/pypsa/network/serialize.py` and is imported above — it's shared with
# the clustering transform. Imported under the old name to keep call sites stable.


@app.post("/api/import/netcdf")
async def import_netcdf(file: UploadFile) -> dict[str, Any]:
    """Accept a PyPSA-native netCDF upload and return the in-memory model JSON."""
    import pypsa

    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp:
        tmp.write(data)
        path = Path(tmp.name)
    try:
        network = pypsa.Network()
        network.import_from_netcdf(str(path))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"netCDF import failed: {exc}") from exc
    finally:
        path.unlink(missing_ok=True)
    return {"model": _network_to_model_json(network)}


@app.post("/api/import/hdf5")
async def import_hdf5(file: UploadFile) -> dict[str, Any]:
    """Accept a PyPSA-native HDF5 upload and return the in-memory model JSON."""
    import pypsa

    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp.write(data)
        path = Path(tmp.name)
    try:
        network = pypsa.Network()
        network.import_from_hdf5(str(path))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"HDF5 import failed: {exc}") from exc
    finally:
        path.unlink(missing_ok=True)
    return {"model": _network_to_model_json(network)}


# Note: the external-data importer subsystem (Data view) lives in the
# browser under ``frontend/Ragnarok_default/src/features/data/databases/``.
# Fetch + convert run client-side; the backend no longer exposes
# ``/api/import/databases``, ``/api/import/countries``,
# ``/api/import/boundaries/countries.geojson``, or ``/api/import/run``.
#
# The two endpoints retained above — ``POST /api/import/netcdf`` and
# ``POST /api/import/hdf5`` — accept a user-uploaded PyPSA-native file and
# convert it to the in-memory model JSON; they are not part of the external-
# data registry.


# ── Serve the built client (server mode) ─────────────────────────────────────
# Server mode: ONE process serves both the API and the SPA, so a browser on
# another machine just opens http://<this-host>:8000 — same-origin, which makes
# the client's relative API calls hit this backend with zero configuration.
# The mount is registered LAST so every /api/* route above wins. Dist lookup:
# RAGNAROK_FRONTEND_DIST if set; else ./build at the repo root (a deployment
# wrapper's committed copy); else the frontend package's own CRA output.
from fastapi.staticfiles import StaticFiles  # noqa: E402

_DIST_CANDIDATES = (
    _REPO_ROOT / "build",
    _REPO_ROOT / "frontend" / "Ragnarok_default" / "build",
)
_env_dist = os.environ.get("RAGNAROK_FRONTEND_DIST")
_FRONTEND_DIST = (
    Path(_env_dist)
    if _env_dist
    else next((p for p in _DIST_CANDIDATES if p.is_dir()), _DIST_CANDIDATES[0])
)
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="spa")
    logging.getLogger("pypsa_gui").info("Serving client from %s", _FRONTEND_DIST)
else:
    logging.getLogger("pypsa_gui").info(
        "No client build at %s — API-only mode (run `npm run build` or set RAGNAROK_FRONTEND_DIST)",
        _FRONTEND_DIST,
    )
