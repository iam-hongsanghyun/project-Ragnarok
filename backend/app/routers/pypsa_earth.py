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
import re
import shutil
import subprocess
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/pypsa-earth", tags=["pypsa-earth"])
log = logging.getLogger(__name__)

# Snakemake prints coarse progress like "12 of 45 steps (27%) done".
_PROGRESS_RE = re.compile(r"\((\d+)%\)\s*done")
_LOG_TAIL = 200  # lines kept in memory
_LOG_SHOWN = 60  # lines exposed to the poller each tick

_ENV_VAR = "RAGNAROK_PYPSA_EARTH_DIR"
# The pypsa-earth conda env name (snakemake + the workflow's deps live there,
# not in the backend's env). Overridable for non-default env names.
_CONDA_ENV_VAR = "RAGNAROK_PYPSA_EARTH_CONDA_ENV"
_DOC = "docs/pypsa-earth-integration.md"
# Persisted "point at an existing checkout" override — set via the Data-view
# button so setup survives without an env var or a restart (backend/data/).
_STATE_FILE = Path(__file__).resolve().parents[2] / "data" / "pypsa_earth.json"
# The running build's process-group id, persisted so a build orphaned by a
# backend restart can be reclaimed (it keeps running and holds snakemake's lock).
_PID_FILE = _STATE_FILE.parent / "pypsa_earth_run.pid"

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


# The scenario wildcards we pin in the per-request config overlay. Pinning all
# four makes the output filename deterministic, so the target can be derived.
_SIMPL, _LL, _OPTS = "", "copt", "Co2L-3h"


def _snap_cost_year(year: int) -> int:
    """Snap to the 5-year grid technology-data ships cost files for (2020–2050)."""
    return min(2050, max(2020, int(round(year / 5.0)) * 5))


def _build_overlay(req: BuildRequest, iso2: str) -> dict[str, Any]:
    """The per-request PyPSA-Earth config overlay (merged over the workflow's own
    config via snakemake ``--configfile``) — the picked country/clusters/horizon
    actually drive the build instead of the checkout's default config."""
    return {
        "run": {"name": f"ragnarok_{iso2}"},  # results/ragnarok_<iso2>/… per country
        "countries": [iso2],
        "scenario": {
            "simpl": [_SIMPL], "ll": [_LL],
            "clusters": [int(req.clusters)], "opts": [_OPTS],
        },
        "costs": {"year": _snap_cost_year(int(req.horizonYear))},
    }


def _target_for(iso2: str, clusters: int) -> str:
    """The PREPARED-network file the pinned scenario produces
    (``networks/<run>/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}.nc``).

    Deliberately the pre-solve stage: ``results/…`` would be the SOLVED network,
    which runs an LP inside PyPSA-Earth (default solver: restricted Gurobi — a
    real country model can exceed its size limits). Ragnarok solves the ingested
    network itself with HiGHS, so the prepared network is the right hand-off.
    """
    return f"networks/ragnarok_{iso2}/elec_s{_SIMPL}_{clusters}_ec_l{_LL}_{_OPTS}.nc"


def _runner_prefix() -> list[str]:
    """How to reach snakemake: bare (on PATH) or through the conda env.

    snakemake (and the workflow's deps) live in the pypsa-earth **conda env**, not
    the backend's env — a bare ``snakemake`` call fails with
    ``FileNotFoundError`` unless the backend itself runs inside that env. So: use
    ``snakemake`` directly when it's on PATH, else run it through the conda env via
    ``mamba run`` / ``conda run``. ``$RAGNAROK_PYPSA_EARTH_CONDA_ENV`` overrides
    the env name (default ``pypsa-earth``).
    """
    if shutil.which("snakemake"):
        return []
    runner = shutil.which("mamba") or shutil.which("conda")
    if runner:
        env_name = os.environ.get(_CONDA_ENV_VAR, "pypsa-earth")
        # --no-capture-output is a CONDA flag; mamba 2.x `run` rejects it (the
        # wrapper ends up exec'ing `--` → "exec: --: invalid option").
        if Path(runner).name == "conda":
            return [runner, "run", "--no-capture-output", "-n", env_name]
        return [runner, "run", "-n", env_name]
    raise RuntimeError(
        "snakemake is not on the backend's PATH and no conda/mamba was found to "
        "run the pypsa-earth env. Install it (scripts/setup_pypsa_earth.command) and "
        "ensure conda/mamba is on the PATH of the process running Ragnarok."
    )


def _snakemake_argv(target: str, configfile: str | None = None) -> list[str]:
    """The full snakemake invocation for a build target."""
    # Target BEFORE --configfile: snakemake's --configfile is greedy (nargs='+')
    # and would swallow a trailing target as a second config file.
    base = ["snakemake", "-j", "4", "--rerun-incomplete", target]
    if configfile:
        base += ["--configfile", configfile]
    return [*_runner_prefix(), *base]


def _unlock(env: Path) -> None:
    """Clear snakemake's directory lock (safe: only called when no build of ours
    is running — after a kill/power-loss the lock is stale)."""
    try:
        subprocess.run(  # noqa: S603
            [*_runner_prefix(), "snakemake", "--unlock"],
            cwd=str(env), capture_output=True, text=True, timeout=300,
        )
    except Exception:  # noqa: BLE001 — best-effort; the retry surfaces real errors
        log.warning("snakemake --unlock failed", exc_info=True)


def _record_child(pid: int) -> None:
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(json.dumps({"pid": pid}), encoding="utf-8")


def _clear_child() -> None:
    _PID_FILE.unlink(missing_ok=True)


def _kill_orphaned_child() -> bool:
    """Kill a build left running by a previous backend process, if any.

    A backend restart orphans the snakemake child (it keeps running and holds the
    workflow lock, so new builds fail with LockException). The pid file records
    OUR child's process group; verify the pid is still a snakemake before
    killing, so a recycled pid is never harmed. Returns True if one was killed.
    """
    import signal
    import time

    try:
        pid = int(json.loads(_PID_FILE.read_text(encoding="utf-8"))["pid"])
    except Exception:  # noqa: BLE001 — no/corrupt pid file → nothing to do
        return False
    try:
        out = subprocess.run(  # noqa: S603
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=10,
        )
        cmd = (out.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return False
    if not cmd or "snakemake" not in cmd:
        _clear_child()  # dead or a recycled pid — just drop the record
        return False
    log.warning("Reclaiming orphaned PyPSA-Earth build (pid %s)", pid)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)  # child is a session leader → pgid == pid
        except ProcessLookupError:
            break
        except PermissionError:
            return False
        for _ in range(20):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.5)
        else:
            continue
        break
    _clear_child()
    return True


def _conda_env_exists(runner: str, env_name: str) -> bool:
    """Whether ``<runner> env list`` shows an env named ``env_name``.

    Returns True (don't block) if the listing can't be obtained — the real run
    will then surface the actual error.
    """
    try:
        out = subprocess.run([runner, "env", "list"], capture_output=True, text=True, timeout=60)  # noqa: S603
    except Exception:  # noqa: BLE001
        return True
    if out.returncode != 0:
        return True
    for line in (out.stdout or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts and parts[0] == env_name:
            return True
        if parts and parts[-1].rstrip("/").endswith(f"/envs/{env_name}"):
            return True
    return False


def _preflight(env: Path, argv: list[str]) -> None:
    """Fast checks before the multi-hour run so mistakes fail in seconds.

    Verifies the conda env actually exists (the common "installed the checkout but
    not the env" case) and warns if no CDS API key is configured (ERA5 cutouts
    need it).
    """
    if len(argv) >= 5 and argv[1] == "run" and "-n" in argv:
        runner = argv[0]
        env_name = argv[argv.index("-n") + 1]
        if not _conda_env_exists(runner, env_name):
            raise RuntimeError(
                f"The '{env_name}' conda env does not exist. Create it with:\n"
                f"    conda env create -f {env / 'envs' / 'environment.yaml'}\n"
                f"(or run scripts/setup_pypsa_earth.command without --no-env). If your "
                f"env has a different name, set {_CONDA_ENV_VAR}."
            )
    if not (Path.home() / ".cdsapirc").is_file():
        log.warning("PyPSA-Earth: no ~/.cdsapirc found — ERA5 cutouts will fail until a CDS API key is set.")


# A tqdm-style progress redraw ("  2%|▏  | 2.0/100 [00:21<17:45, 10.87s/it]").
# In a terminal these overwrite one line via \r; through a pipe every redraw
# arrives as its own line and would flood the log tail.
_TQDM_RE = re.compile(r"^\s*\d{1,3}%\|")


def _stream_log(lines: Any, job_id: str) -> deque[str]:
    """Fold Snakemake output lines into the job snapshot as they arrive.

    Keeps a bounded tail, exposes the last ``_LOG_SHOWN`` lines to the poller as
    ``log``, and lifts a coarse ``progress`` % + ``detail`` from
    ``"(NN%) done"`` lines. Blank lines are dropped. Consecutive tqdm progress
    redraws REPLACE the previous one (in-place, like a terminal) instead of
    stacking hundreds of near-identical lines.
    """
    log_lines: deque[str] = deque(maxlen=_LOG_TAIL)
    for raw in lines:
        # tqdm writes \r-separated redraws; keep only the final state of a chunk.
        parts = [p for p in str(raw).rstrip("\r\n").split("\r") if p.strip()]
        line = parts[-1].rstrip() if parts else ""
        if not line:
            continue
        if _TQDM_RE.match(line) and log_lines and _TQDM_RE.match(log_lines[-1]):
            log_lines[-1] = line  # redraw in place
        else:
            log_lines.append(line)
        fields: dict[str, Any] = {"log": list(log_lines)[-_LOG_SHOWN:]}
        m = _PROGRESS_RE.search(line)
        if m:
            fields["progress"] = int(m.group(1))
            fields["detail"] = line
        _set(job_id, **fields)
    return log_lines


def _run_workflow_and_ingest(env: Path, req: BuildRequest, job_id: str) -> dict[str, Any]:
    """Run PyPSA-Earth for ``req`` and ingest the resulting network.

    Only reached when the environment is configured. Kept deliberately small —
    it shells out to the workflow (which owns its own conda env + solver) and
    then reuses :func:`ingest_network`. The heavy lifting is PyPSA-Earth's; this
    is the integration seam.
    """
    from ..importers.region import iso2_for

    iso2 = iso2_for(req.countryIso)
    if not iso2:
        raise RuntimeError(
            f"Could not resolve an ISO alpha-2 code for {req.countryIso!r} "
            f"(PyPSA-Earth selects countries by alpha-2). Pick the country on the "
            f"Data-view map and retry."
        )
    # Per-request config: written into the (gitignored) checkout and merged over
    # the workflow's own config — so the picked country/clusters/horizon drive
    # the build instead of the checkout's default (e.g. the Africa tutorial).
    overlay = _build_overlay(req, iso2)
    configfile = f"ragnarok_config_{iso2}.yaml"
    import yaml

    (env / configfile).write_text(yaml.safe_dump(overlay, sort_keys=False), encoding="utf-8")
    target = _target_for(iso2, int(req.clusters))
    argv = _snakemake_argv(target, configfile)
    _set(job_id, phase="checking environment",
         detail=f"Verifying the pypsa-earth conda env… (countries=[{iso2}], clusters={req.clusters})")
    _preflight(env, argv)

    _set(job_id, phase="running PyPSA-Earth workflow", progress=0,
         detail="Snakemake is building cutouts, bus regions, powerplants and profiles…")
    # A build orphaned by a backend restart keeps running and holds snakemake's
    # lock — reclaim it (it's ours: the pid file records our own child) so this
    # build doesn't die with a LockException.
    if _kill_orphaned_child():
        _unlock(env)

    # Stream stdout/stderr line-by-line into the job snapshot so the panel shows
    # a live log + coarse % instead of a spinner. One retry on a lock error —
    # a stale lock (kill signal / power loss) just needs `snakemake --unlock`.
    log_lines: deque[str] = deque()
    for attempt in (1, 2):
        proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
            argv, cwd=str(env), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, start_new_session=True,  # own pgid → killable as a group
        )
        _record_child(proc.pid)
        assert proc.stdout is not None
        try:
            log_lines = _stream_log(proc.stdout, job_id)
            proc.wait()
        finally:
            _clear_child()
        if proc.returncode == 0:
            break
        if attempt == 1 and any("cannot be locked" in line for line in log_lines):
            others = [j for j in _JOBS.values()
                      if j.get("status") == "running" and j.get("jobId") != job_id]
            if others:
                raise RuntimeError(
                    "Another PyPSA-Earth build is already running in this checkout — "
                    "wait for it to finish and retry."
                )
            _set(job_id, phase="clearing stale lock",
                 detail="A previous build was interrupted — unlocking and retrying…")
            _kill_orphaned_child()
            _unlock(env)
            continue
        tail = "\n".join(list(log_lines)[-40:]) or f"exit {proc.returncode}"
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
