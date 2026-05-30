from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import queue
import uuid
from dataclasses import dataclass
from typing import Any

import io
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

import os
import sys

from .backends import BackendError, available_backends, get_backend
from .config import load_system_defaults
from .log_capture import (
    emit_solver_log as _emit_solver_log,
    get_snapshot as _log_snapshot,
    install as _install_log_capture,
)
from .models import RunPayload
from ..pypsa.network import build_network, validate_model

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
    payload: RunPayload,
    result_queue: "mp.Queue[tuple[str, Any, str]]",
) -> None:
    """Run in a child process. Puts ("ok"|"err", result-or-msg, captured-stdout)
    into the queue. The third element is the C-level stdout/stderr written by
    HiGHS / PyPSA / linopy during the solve — Python ``logging`` cannot see
    those because they go through C ``printf``, so we dup the fd to a temp
    file for the duration of the run, then read it back and ship the contents
    home for the parent to fan into its in-process log buffer.

    The backend is selected from ``options["backend"]`` (default PyPSA) via the
    backend registry, so the worker stays engine-agnostic.
    """
    capture_path: str | None = None
    saved_stdout_fd: int | None = None
    saved_stderr_fd: int | None = None
    capture_fd: int | None = None
    status: str = "err"
    payload_out: Any = "worker setup failed"
    try:
        # ── Redirect stdout (fd 1) and stderr (fd 2) to a temp file ────────
        capture_path = tempfile.NamedTemporaryFile(
            mode="w", suffix=".solverlog", delete=False
        ).name
        capture_fd = os.open(capture_path, os.O_WRONLY | os.O_TRUNC)
        sys.stdout.flush()
        sys.stderr.flush()
        saved_stdout_fd = os.dup(1)
        saved_stderr_fd = os.dup(2)
        os.dup2(capture_fd, 1)
        os.dup2(capture_fd, 2)

        try:
            options = payload.options or {}
            backend = get_backend(options.get("backend"))
            result = backend.run(payload.model, payload.scenario, options)
            status = "ok"
            payload_out = result
        except Exception as exc:  # noqa: BLE001
            status = "err"
            payload_out = str(exc)
        finally:
            # ── Restore fd 1 and 2 BEFORE reading the capture file ───────
            sys.stdout.flush()
            sys.stderr.flush()
            if saved_stdout_fd is not None:
                os.dup2(saved_stdout_fd, 1)
                os.close(saved_stdout_fd)
                saved_stdout_fd = None
            if saved_stderr_fd is not None:
                os.dup2(saved_stderr_fd, 2)
                os.close(saved_stderr_fd)
                saved_stderr_fd = None
            if capture_fd is not None:
                try:
                    os.close(capture_fd)
                except OSError:
                    pass
                capture_fd = None
    except Exception as exc:  # noqa: BLE001
        status = "err"
        payload_out = str(exc)

    # ── Read captured solver output (best-effort) ──────────────────────────
    captured_text = ""
    if capture_path is not None:
        try:
            with open(capture_path, "r", encoding="utf-8", errors="replace") as f:
                captured_text = f.read()
        except OSError:
            captured_text = ""
        try:
            os.unlink(capture_path)
        except OSError:
            pass

    result_queue.put((status, payload_out, captured_text))


async def _collect_job(job_id: str) -> None:
    """Background asyncio task — waits for the worker process and updates job state.

    The worker puts a ``(status, payload, solver_stdout)`` tuple onto its
    queue once the solve finishes. We update the job state and then fan the
    captured solver stdout (HiGHS / linopy / PyPSA C-level output) into the
    in-process log buffer so the Analytics → Log tab sees the solver
    transcript alongside everything else.
    """
    job = _jobs.get(job_id)
    if job is None:
        return
    while True:
        try:
            msg = job.result_queue.get_nowait()
            # Tolerate the legacy 2-tuple shape in case a worker was started
            # before this change (e.g. mid-deploy upgrade in dev).
            if isinstance(msg, tuple) and len(msg) == 3:
                status, data, solver_stdout = msg
            else:
                status, data = msg  # type: ignore[misc]
                solver_stdout = ""
            if status == "ok":
                job.status = "done"
                job.result = data
            else:
                job.status = "error"
                job.error = data
            # Fan captured solver output into the log buffer — surfaces in
            # the Analytics → Log tab on its next refresh (which fires from
            # the frontend's run-completion path, so it's near-instant).
            if solver_stdout:
                _emit_solver_log(solver_stdout, job_id)
            return
        except queue.Empty:
            if not job.proc.is_alive():
                if job.status == "running":
                    job.status = "cancelled"
                return
            await asyncio.sleep(0.5)


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="Ragnarok Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    cfg = load_system_defaults()
    sim = cfg.get("simulation", {})
    return {
        "maxSnapshots": int(sim.get("max_snapshots", 8760)),
        "defaultSnapshotCount": int(sim.get("default_snapshot_count", 24)),
        "defaultSnapshotWeight": float(sim.get("default_snapshot_weight", 1.0)),
    }


@app.get("/api/backends")
def get_backends() -> dict[str, Any]:
    """List the available optimisation backends and their capabilities."""
    return {"backends": available_backends(), "default": "pypsa"}


@app.get("/api/log")
def get_log() -> dict[str, Any]:
    """Snapshot of the in-process log ring buffer.

    Fetched by the frontend Analytics → Log sub-tab on mount, on run
    completion, and on the Refresh button. Covers:
      • uvicorn HTTP access logs (with /api/run/{id} and /api/log polls
        already filtered out at INFO and dropped from the buffer);
      • uvicorn errors / startup;
      • anything emitted via ``logging.getLogger(...)`` in backend code;
      • the captured solver C-stdout (HiGHS / linopy / PyPSA) — the
        run worker dup's fd 1+2 to a temp file for the solve, then ships
        the captured text back so it lands here under the ``pypsa.solver``
        logger when the worker reports completion.
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


@app.post("/api/validate")
def validate_case(payload: RunPayload) -> dict[str, Any]:
    return validate_model(payload)


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
    """Terminate a running job's child process."""
    job = _jobs.get(job_id)
    if job is None:
        return {"jobId": job_id, "status": "not_found"}
    if job.proc.is_alive():
        job.proc.terminate()
        await asyncio.to_thread(job.proc.join, 3)
    job.status = "cancelled"
    _jobs.pop(job_id, None)
    return {"jobId": job_id, "status": "cancelled"}


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


def _network_to_model_json(network) -> dict[str, Any]:
    """Round-trip a built `pypsa.Network` back into the in-memory model shape.

    The frontend already knows how to consume `{sheet: rows[]}` payloads
    (it's what every workbook open / project import produces). For each
    schema-known component class we emit a row per component, copying the
    static columns and turning any non-empty `*_t` dynamic frame into a
    `<list_name>-<attr>` sheet with one row per snapshot.
    """
    from ..pypsa.pypsa_schema import (
        input_static_attributes,
        input_temporal_attributes,
        component_sheets,
    )
    model: dict[str, list[dict[str, Any]]] = {}
    # Snapshots
    model["snapshots"] = [{"snapshot": str(ts)} for ts in list(network.snapshots)]
    # network row
    if network.name:
        model["network"] = [{"name": str(network.name)}]
    for sheet in component_sheets():
        if sheet in {"network", "snapshots"}:
            continue
        if sheet not in network.components.keys():
            continue
        comp = network.components[sheet]
        static = comp.static
        if not isinstance(static, type(network.lines)):  # DataFrame
            pass
        allowed_static = input_static_attributes(sheet)
        if static is not None and len(static) > 0:
            rows: list[dict[str, Any]] = []
            for name, row in static.iterrows():
                d: dict[str, Any] = {"name": str(name)}
                for col, val in row.items():
                    if allowed_static and col not in allowed_static:
                        continue
                    if val is None or (hasattr(val, "__float__") and (val != val)):
                        continue  # NaN
                    d[str(col)] = val.item() if hasattr(val, "item") else val
                rows.append(d)
            if rows:
                model[sheet] = rows
        # Time-series sheets
        allowed_temporal = input_temporal_attributes(sheet)
        dynamic = getattr(comp, "dynamic", None)
        if dynamic is None:
            continue
        for attr in list(dynamic.keys()):
            if allowed_temporal and attr not in allowed_temporal:
                continue
            df = dynamic[attr]
            if df is None or df.empty:
                continue
            ts_rows: list[dict[str, Any]] = []
            for ts, ser in df.iterrows():
                row_d: dict[str, Any] = {"snapshot": str(ts)}
                for col, val in ser.items():
                    if val is None or (hasattr(val, "__float__") and (val != val)):
                        continue
                    row_d[str(col)] = val.item() if hasattr(val, "item") else val
                ts_rows.append(row_d)
            if ts_rows:
                model[f"{sheet}-{attr}"] = ts_rows
    return model


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
