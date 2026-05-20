from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import queue
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .lib.config import load_system_defaults
from .lib.models import RunPayload
from .lib.module_host import discover_modules, execute_plugins_at_stage, install_module_from_upload, uninstall_module
from .lib.network import validate_model
from .lib.results import run_pypsa


# ── Suppress per-poll access log noise ───────────────────────────────────────
# GET /api/run/{id} fires every 1.5 s while a solve is in progress.
# These lines add no diagnostic value at INFO level; they are re-emitted at
# DEBUG so they remain capturable when needed (e.g. uvicorn --log-level debug).

class _SuppressPollLogs(logging.Filter):
    _debug = logging.getLogger("pypsa_gui.poll")

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        msg = record.getMessage()
        if '"GET /api/run/' in msg and "HTTP" in msg:
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
    """Run in a child process. Puts ("ok", result) or ("err", msg) into the queue."""
    try:
        result = run_pypsa(payload.model, payload.scenario, payload.options or {})
        result_queue.put(("ok", result))
    except Exception as exc:  # noqa: BLE001
        result_queue.put(("err", str(exc)))


async def _collect_job(job_id: str) -> None:
    """Background asyncio task — waits for the worker process and updates job state."""
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


@app.get("/api/modules")
def get_modules() -> dict[str, Any]:
    return discover_modules()


@app.post("/api/modules/install")
async def install_module(file: UploadFile) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are accepted.")
    try:
        zip_bytes = await file.read()
        return install_module_from_upload(zip_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/modules/{module_id}")
def delete_module(module_id: str) -> dict[str, Any]:
    try:
        return uninstall_module(module_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/modules/{module_id}/preview")
def preview_module(module_id: str, payload: RunPayload) -> dict[str, Any]:
    """Run a single pre-build plugin in-process and return the resulting model.

    Powers the SDK 'action' field type: the plugin's transform hook is
    invoked with the caller's current workbook as ``model``, and the
    returned dict replaces the workbook on the frontend. No solver runs.

    The plugin must declare ``stage: "pre-build"`` and a ``transform`` hook.
    Module enablement is **not** required — the caller can preview an
    installed-but-disabled module so users can compare outcomes.
    """
    outputs = execute_plugins_at_stage(
        "pre-build",
        [module_id],
        model=payload.model,
        scenario=payload.scenario,
        options=payload.options or {},
    )
    result = outputs.get(module_id)
    if result is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Module '{module_id}' did not return a model. Verify the manifest "
                "declares stage='pre-build' and hook='transform'."
            ),
        )
    if isinstance(result, dict) and "error" in result and len(result) == 1:
        raise HTTPException(status_code=400, detail=str(result["error"]))
    if not isinstance(result, dict):
        raise HTTPException(
            status_code=400,
            detail=f"Module '{module_id}' returned non-dict result: {type(result).__name__}",
        )
    return {"model": result}


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
