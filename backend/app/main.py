from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import queue
import uuid
from dataclasses import dataclass
from typing import Any

import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from .backends import BackendError, available_backends, get_backend
from .config import load_system_defaults
from .log_capture import (
    clear_buffer as _log_clear,
    get_snapshot as _log_snapshot,
    install as _install_log_capture,
)
from .models import ExportProjectPayload, RunPayload
from . import run_store
from ..pypsa.network import build_network, validate_model

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
    payload: RunPayload,
    result_queue: "mp.Queue[tuple[str, Any]]",
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

    try:
        options = payload.options or {}
        backend = get_backend(options.get("backend"))
        result = backend.run(payload.model, payload.scenario, options)
        # Deliver the result FIRST so the frontend isn't blocked while we persist
        # — store_run also pre-builds the (potentially large) xlsx, which can take
        # several seconds and would otherwise delay the result.
        result_queue.put(("ok", result))
        # Always persist the finished run server-side (the backend is the single
        # source of truth for run history). A store failure must NOT affect the
        # run — run_store logs and swallows internally, and we guard again here.
        try:
            run_store.store_run(payload.model, payload.scenario or {}, options, result)
        except Exception:  # noqa: BLE001
            logging.getLogger("pypsa_gui.run_store").exception(
                "store_run raised after a successful solve"
            )
    except Exception as exc:  # noqa: BLE001
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
    task = asyncio.ensure_future(startup_status.warm())
    try:
        yield
    finally:
        if not task.done():
            task.cancel()


app = FastAPI(title="Ragnarok Backend", version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
    """Return the full stored bundle for ``name`` (404 if missing)."""
    bundle = run_store.get_run(name)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Stored run not found.")
    return bundle


@app.delete("/api/runs/{name}")
def delete_backend_run(name: str) -> dict[str, Any]:
    """Delete the bundle + meta sidecar for ``name``."""
    return {"deleted": run_store.delete_run(name)}


@app.post("/api/export/project")
def export_project(payload: ExportProjectPayload) -> Response:
    """Build the full input + output project xlsx server-side and return it.

    Replaces the in-browser SheetJS export, which OOMed the tab while building a
    full-year workbook in RAM. The frontend POSTs ``{model, result}``; the
    workbook is assembled on the server via the same frame builder used by the
    stored-run download and streamed back as an xlsx attachment.
    """
    try:
        data = run_store._frames_to_excel({"model": payload.model, "result": payload.result})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Project export failed: {exc}") from exc
    return Response(
        content=data,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="ragnarok_project.xlsx"'},
    )


@app.get("/api/runs/{name}/xlsx")
def download_backend_run_xlsx(name: str) -> Response:
    """Return the human-readable xlsx for stored run ``name``.

    Serves the file pre-built at store time (fast — streamed straight off disk);
    falls back to building on demand for runs saved before pre-build existed.
    """
    pre = run_store.xlsx_path(name)
    if pre is not None:
        return FileResponse(
            path=pre,
            media_type=_XLSX_MEDIA_TYPE,
            filename=f"{name}.xlsx",
        )
    data = run_store.run_to_xlsx(name)
    if data is None:
        raise HTTPException(status_code=404, detail="Stored run not found.")
    return Response(
        content=data,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'},
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
