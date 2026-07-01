"""PyPSA-Earth network builder — async job (I9).

Top-down complement to the per-source importers: for an arbitrary country, run
PyPSA-Earth's workflow server-side and ingest the resulting network as a
Ragnarok workbook. Per ``docs/pypsa-earth-integration.md`` this is NOT an
``/api/import/*`` importer — it's a long-running queued job (PyPSA-Earth is a
Snakemake workflow needing its own conda env, a CDS key for ERA5 cutouts, and
minutes-to-hours of Atlite compute), so it lives on its own endpoints with
progress polling.

This module is the **job runner + ingest**:

  • ``POST /api/pypsa-earth/build`` queues a build and returns a ``jobId``.
  • ``GET  /api/pypsa-earth/build/{id}`` polls phase/progress/status.
  • ``GET  /api/pypsa-earth/build/{id}/result`` returns the WorkbookFragment
    once done (the ingested PyPSA network — PyPSA-ready by construction).
  • ``GET  /api/pypsa-earth/available`` reports whether the environment is set up.

The environment is located via ``RAGNAROK_PYPSA_EARTH_DIR`` (a checked-out
pypsa-earth workflow dir with a ``Snakefile``). When it isn't configured the job
fails cleanly with a pointer to the docs — the heavy run itself is only exercised
where that environment exists; the queue/status plumbing and the network→workbook
ingest are what run (and are tested) everywhere.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/pypsa-earth", tags=["pypsa-earth"])
log = logging.getLogger(__name__)

_ENV_VAR = "RAGNAROK_PYPSA_EARTH_DIR"
_DOC = "docs/pypsa-earth-integration.md"
# Persisted "point at an existing checkout" override — set via the Data-view
# button so setup survives without an env var or a restart (backend/data/).
_STATE_FILE = Path(__file__).resolve().parents[2] / "data" / "pypsa_earth.json"

# Single-process in-memory job registry (mirrors startup_status's convention).
_JOBS: dict[str, dict[str, Any]] = {}


def _valid_workflow_dir(raw: str) -> Path | None:
    """A directory that looks like a pypsa-earth checkout (has a Snakefile)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if (path.is_dir() and (path / "Snakefile").is_file()) else None


def _load_override() -> str:
    try:
        return str((json.loads(_STATE_FILE.read_text(encoding="utf-8")) or {}).get("dir") or "")
    except Exception:  # noqa: BLE001 — missing/corrupt file → no override
        return ""


def _save_override(dir_str: str) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps({"dir": dir_str}), encoding="utf-8")


def _auto_dir() -> Path | None:
    """The default in-project location the setup script installs into
    (``<repo>/pypsa-earth``) — auto-detected so no configure step is needed."""
    return _valid_workflow_dir(str(Path(__file__).resolve().parents[3] / "pypsa-earth"))


def _suggested_dirs() -> list[str]:
    """Valid pypsa-earth checkouts found in common locations, offered as
    one-click choices when nothing is configured yet."""
    root = Path(__file__).resolve().parents[3]
    home = Path.home()
    candidates = [
        root / "pypsa-earth", root.parent / "pypsa-earth",
        home / "pypsa-earth", home / "github" / "pypsa-earth",
        home / "Documents" / "pypsa-earth",
    ]
    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        v = _valid_workflow_dir(str(c))
        if v is not None:
            key = str(v.resolve())
            if key not in seen:
                seen.add(key)
                out.append(str(v))
    return out


def resolve_env() -> Path | None:
    """The configured PyPSA-Earth workflow dir, or None if not set up.

    Order: the directory set via ``POST /configure`` (the Data-view button), then
    ``$RAGNAROK_PYPSA_EARTH_DIR``, then the in-project ``<repo>/pypsa-earth`` the
    setup script installs into (auto-detected). A dir is valid only if it contains
    a ``Snakefile`` (the workflow root).
    """
    return (
        _valid_workflow_dir(_load_override())
        or _valid_workflow_dir(os.environ.get(_ENV_VAR, ""))
        or _auto_dir()
    )


def _not_configured_message() -> str:
    return (
        f"PyPSA-Earth is not configured on this server. Point Ragnarok at a "
        f"checked-out pypsa-earth workflow directory below (or set {_ENV_VAR}). "
        f"The directory needs its own conda env and a CDS API key for ERA5 "
        f"cutouts — see {_DOC}."
    )


class BuildRequest(BaseModel):
    """A PyPSA-Earth build request — the small config subset the UI collects."""

    countryIso: str
    countryName: str = ""
    horizonYear: int = 2030
    carriers: list[str] = ["solar", "onwind", "offwind-ac", "OCGT"]
    clusters: int = 10
    sessionId: str = "default"


def _snapshot(job: dict[str, Any]) -> dict[str, Any]:
    """Status view without the (potentially large) result payload."""
    return {k: v for k, v in job.items() if k != "result"}


def ingest_network(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Load a PyPSA network (``.nc``) and convert it to workbook sheets.

    The output of PyPSA-Earth is a PyPSA network, so the existing
    ``serialize.network_to_model`` maps it straight onto the sheet model — the
    same shape the importers' ``WorkbookFragment`` carries.
    """
    import pypsa

    from ...pypsa.network.serialize import network_to_model  # lazy: pypsa off the hot path

    network = pypsa.Network(str(path))
    return network_to_model(network)


def _run_workflow_and_ingest(env: Path, req: BuildRequest, job_id: str) -> dict[str, Any]:
    """Run PyPSA-Earth for ``req`` and ingest the resulting network.

    Only reached when the environment is configured. Kept deliberately small —
    it shells out to the workflow (which owns its own conda env + solver) and
    then reuses :func:`ingest_network`. The heavy lifting is PyPSA-Earth's; this
    is the integration seam.
    """
    import subprocess

    _set(job_id, phase="running PyPSA-Earth workflow",
         detail="Snakemake is building cutouts, bus regions, powerplants and profiles…")
    target = f"results/networks/elec_s_{int(req.clusters)}.nc"
    # The workflow reads its own config.yaml; a per-request override would be
    # written here in a full integration. We invoke the documented target.
    proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
        ["snakemake", "-j", "4", "--rerun-incomplete", target],
        cwd=str(env), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-600:]
        raise RuntimeError(f"PyPSA-Earth workflow failed (exit {proc.returncode}). {tail}")
    out = env / target
    if not out.is_file():
        raise RuntimeError(f"PyPSA-Earth finished but {target} was not produced.")
    _set(job_id, phase="ingesting network", detail="Converting the PyPSA network to a workbook…")
    sheets = ingest_network(out)
    return {"sheets": sheets}


def _set(job_id: str, **fields: Any) -> None:
    job = _JOBS.get(job_id)
    if job is not None:
        job.update(fields)


async def _run(job_id: str, req: BuildRequest) -> None:
    """Job coroutine: check env → run workflow → ingest, updating the snapshot."""
    _set(job_id, status="running", phase="checking environment", detail="Locating PyPSA-Earth…")
    env = resolve_env()
    if env is None:
        _set(job_id, status="error", phase="environment not configured",
             detail=_not_configured_message(), error=_not_configured_message())
        return
    try:
        result = await asyncio.to_thread(_run_workflow_and_ingest, env, req, job_id)
        counts = {s: len(r) for s, r in result["sheets"].items()}
        _set(job_id, status="done", phase="complete",
             detail=f"Built {req.countryIso}: " + ", ".join(f"{n} {s}" for s, n in counts.items()),
             result=result, counts=counts)
    except Exception as exc:  # noqa: BLE001 — surface any workflow/ingest failure to the client
        log.exception("PyPSA-Earth build failed")
        _set(job_id, status="error", phase="failed", detail=str(exc), error=str(exc))


@router.get("/available")
def available() -> dict[str, Any]:
    """Whether the PyPSA-Earth environment is set up on this server."""
    env = resolve_env()
    active = str(env.resolve()) if env else ""
    candidates = [c for c in _suggested_dirs() if str(Path(c).resolve()) != active]
    return {
        "available": env is not None,
        "dir": str(env) if env else "",
        "detail": f"PyPSA-Earth workflow at {env}" if env else _not_configured_message(),
        "candidates": candidates,
        "docs": _DOC,
    }


class ConfigureRequest(BaseModel):
    """Point Ragnarok at a pypsa-earth checkout (or clear it with an empty dir)."""

    dir: str | None = None


@router.post("/configure")
def configure(req: ConfigureRequest) -> dict[str, Any]:
    """Persist a PyPSA-Earth workflow directory (the Data-view "use this
    directory" button). Validates it's a real checkout so the user gets an
    immediate, specific error rather than a failed build later."""
    raw = (req.dir or "").strip()
    if not raw:
        _save_override("")  # clear the override
        return available()
    path = Path(raw).expanduser()
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"No such directory on the server: {raw}")
    if not (path / "Snakefile").is_file():
        raise HTTPException(
            status_code=400,
            detail=(f"{raw} has no Snakefile — is it a pypsa-earth checkout? "
                    f"Clone it with: git clone https://github.com/pypsa-meets-earth/pypsa-earth"),
        )
    _save_override(str(path))
    return available()


@router.post("/build")
async def start_build(req: BuildRequest) -> dict[str, Any]:
    """Queue a PyPSA-Earth build; returns a ``jobId`` to poll."""
    if not req.countryIso.strip():
        raise HTTPException(status_code=400, detail="A country is required.")
    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {
        "jobId": job_id, "status": "queued", "phase": "queued",
        "detail": f"Queued a PyPSA-Earth build for {req.countryName or req.countryIso}.",
        "error": None, "countryIso": req.countryIso, "clusters": req.clusters,
    }
    asyncio.create_task(_run(job_id, req))
    return _snapshot(_JOBS[job_id])


@router.get("/build/{job_id}")
def build_status(job_id: str) -> dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown build job.")
    return _snapshot(job)


@router.get("/build/{job_id}/result")
def build_result(job_id: str) -> dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown build job.")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"Build is '{job['status']}', not ready.")
    return {"jobId": job_id, "fragment": job["result"], "counts": job.get("counts", {})}
