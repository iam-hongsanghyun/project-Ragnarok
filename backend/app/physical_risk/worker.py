"""CLIMADA worker bridge — the REAL engine behind the physical-risk run kinds.

The worker (``backend/physical_risk_worker/``, vendored from the standalone
``climaterisk`` project) runs in a separate Python 3.11 conda env because
CLIMADA's conda-forge geo stack (older numpy/pandas) cannot share an interpreter
with ``.venv-pypsa`` (Python 3.13, numpy 2.4, pandas 3.0). This module NEVER
imports CLIMADA — it speaks the worker's ``request.json`` / ``result.json`` file
contract (climaterisk ``engines/base.py`` shapes, snake_case) over a subprocess,
translating from/to OUR camelCase entities at this boundary.

Env vars (all optional):

* ``RAGNAROK_CLIMADA_WORKER`` — ``auto`` (default: use the worker when its env
  exists), ``1``/``true``/``on`` (force-select; a missing env falls back to the
  stub with a note), ``0``/``false``/``off`` (never use the worker).
* ``RAGNAROK_CLIMADA_WORKER_ENV`` — conda prefix env dir (default
  ``<repo>/.climada-env``; build it with ``scripts/setup_climada_worker.sh``).
* ``RAGNAROK_CLIMADA_TIMEOUT`` — wall-clock cap per run in seconds (default 900).
* ``CLIMATERISK_HAZARD_DB`` — local hazard-catalog dir passed through to the
  worker (default ``<repo>/data/hazard_db``, matching the vendored catalog).

Request/response field translation (camelCase <-> snake_case) is centralised in
:func:`build_request` / :func:`parse_result`, so the tests can exercise the
contract without conda.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .entities import (
    AssetImpact,
    CalibrationResult,
    CostBenefitResult,
    ForecastResult,
    FreqCurve,
    MeasureResult,
    MeasureSpec,
    PhysicalRunOutput,
    PhysicalRunResult,
    Portfolio,
    Scenario,
    SupplyChainResult,
    SupplyChainSector,
    UncertaintyPerilBand,
    UncertaintyResult,
)
from .libraries import _ENERGY_CLASS_BASE, load_libraries

logger = logging.getLogger(__name__)

# Repo root: backend/app/physical_risk/worker.py -> parents[3].
_REPO_ROOT = Path(__file__).resolve().parents[3]
# The worker package's import root (spawn cwd): backend/ contains physical_risk_worker/.
_WORKER_IMPORT_ROOT = _REPO_ROOT / "backend"
_WORKER_MODULE = "physical_risk_worker.run_job"

_DEFAULT_ENV_DIR = _REPO_ROOT / ".climada-env"
_DEFAULT_TIMEOUT_S = 900.0
_DEFAULT_HAZARD_DB = _REPO_ROOT / "data" / "hazard_db"

# Our run kind -> the worker request ``mode`` (physical is the worker's default: no mode).
_KIND_MODE: dict[str, str | None] = {
    "physical": None,
    "uncertainty": "uncertainty",
    "cost-benefit": "cost_benefit",
    "supply-chain": "supplychain",
    "calibration": "calibration",
    "forecast": "forecast",
}


class WorkerError(RuntimeError):
    """Any failure on the worker path — the caller falls back to the stub."""


# ── selection ─────────────────────────────────────────────────────────────────


def mode() -> str:
    """The worker-selection mode: ``off`` | ``auto`` | ``on`` (from the env gate)."""
    raw = os.environ.get("RAGNAROK_CLIMADA_WORKER", "auto").strip().lower()
    if raw in ("", "auto"):
        return "auto"
    if raw in ("0", "false", "off", "no"):
        return "off"
    return "on"


def env_dir() -> Path:
    """The conda prefix env directory holding the worker interpreter."""
    raw = os.environ.get("RAGNAROK_CLIMADA_WORKER_ENV", "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_ENV_DIR


def worker_python() -> Path:
    """The worker interpreter inside the prefix env (POSIX layout, as upstream)."""
    return env_dir() / "bin" / "python"


def timeout_seconds() -> float:
    """Wall-clock cap per worker run (``RAGNAROK_CLIMADA_TIMEOUT``, default 900s)."""
    raw = os.environ.get("RAGNAROK_CLIMADA_TIMEOUT", "").strip()
    try:
        value = float(raw) if raw else _DEFAULT_TIMEOUT_S
    except ValueError:
        return _DEFAULT_TIMEOUT_S
    return value if value > 0 else _DEFAULT_TIMEOUT_S


def available() -> bool:
    """True when the worker interpreter AND the vendored package are both present."""
    return (
        worker_python().is_file()
        and (_WORKER_IMPORT_ROOT / "physical_risk_worker" / "run_job.py").is_file()
    )


def selected() -> bool:
    """True when a run should go to the real worker (mode allows it AND it exists)."""
    return mode() != "off" and available()


def forced_but_missing() -> bool:
    """True when the worker is explicitly enabled but its env is absent."""
    return mode() == "on" and not available()


# ── request translation (our camelCase -> worker snake_case) ──────────────────


def _resolve_asset_specs(portfolio: Portfolio) -> list[dict[str, Any]]:
    """Resolve each asset's vulnerability class into concrete per-peril curve params.

    Faithful port of climaterisk ``engines/base.py::resolve_asset_specs``: the
    backend resolves the library curves (plus any studio overrides) here, so the
    CLIMADA worker needs no access to the methodology library. Energy-flavoured
    classes (thermal/renewable/...) borrow their curves from the vendored building
    class they are based on (see ``libraries._ENERGY_CLASS_BASE``); overrides may
    be keyed by either the asset's class id or the base building-class id.
    """
    libs = load_libraries()
    impf = libs["impact_functions"]
    classes = {c["id"]: c for c in impf["classes"]}
    flood_depth_m = [float(x) for x in impf["flood_depth_m"]]
    eq_mmi = [float(x) for x in impf["eq_mmi"]]
    sector_default = {
        s["id"]: s["default_vulnerability_class"] for s in libs["sectors"]["sectors"]
    }
    fallback = impf["classes"][0]

    overrides = portfolio.scenario.vulnerabilityOverrides
    specs: list[dict[str, Any]] = []
    for a in portfolio.assets:
        vc_id = a.vulnerabilityClass or sector_default.get(a.sector, fallback["id"])
        base_id = _ENERGY_CLASS_BASE.get(vc_id, (vc_id, ""))[0]
        vc = classes.get(base_id, fallback)
        ov = overrides.get(vc_id) or overrides.get(vc["id"])
        tc_v_half = float(ov.tcVHalf) if ov and ov.tcVHalf is not None else float(vc["tc_v_half"])
        wf = float(ov.wfMaxMdd) if ov and ov.wfMaxMdd is not None else float(vc["wf_max_mdd"])
        fmdr = [float(x) for x in (ov.floodMdr if ov and ov.floodMdr else vc["flood_mdr"])]
        emdr = [float(x) for x in (ov.eqMdr if ov and ov.eqMdr else vc["eq_mdr"])]
        specs.append(
            {
                "id": a.id,
                "name": a.name,
                "lat": a.lat,
                "lon": a.lon,
                "sector": a.sector,
                "value": a.value,
                "currency": a.currency,
                "vulnerability_class": vc["id"],
                "tc_v_half": tc_v_half,
                "wf_max_mdd": wf,
                "flood_depth_m": flood_depth_m,
                "flood_mdr": fmdr,
                "eq_mmi": eq_mmi,
                "eq_mdr": emdr,
                "geometry": None,
            }
        )
    return specs


def _anchor_years(portfolio: Portfolio, scenario: Scenario) -> list[int]:
    """Anchor years for the worker; the run's horizon is always the max (= target year).

    The worker targets ``max(anchor_years)``, so intermediate portfolio anchors are
    kept only up to the requested horizon.
    """
    years = {int(y) for y in portfolio.scenario.anchorYears if int(y) <= scenario.horizon}
    years.add(int(scenario.horizon))
    return sorted(years)


def _measures_snake(measures: list[Any]) -> list[dict[str, Any]]:
    """Translate our camelCase MeasureSpec list into the worker's snake_case dicts."""
    out: list[dict[str, Any]] = []
    for m in measures:
        spec = m if isinstance(m, MeasureSpec) else MeasureSpec.model_validate(m)
        out.append(
            {
                "name": spec.name,
                "cost": spec.cost,
                "damage_reduction": spec.damageReduction,
                "hazard_freq_cutoff": spec.hazardFreqCutoff,
                "risk_transf_attach": spec.riskTransfAttach,
                "risk_transf_cover": spec.riskTransfCover,
            }
        )
    return out


def build_request(
    kind: str,
    portfolio: Portfolio,
    perils: list[str],
    scenario: Scenario,
    options: dict[str, Any],
) -> dict[str, Any]:
    """The worker ``request.json`` body for one run (snake_case, engines/base.py shapes)."""
    assets = _resolve_asset_specs(portfolio)
    anchor_years = _anchor_years(portfolio, scenario)
    request: dict[str, Any] = {"session_id": portfolio.sessionId, "assets": assets}
    worker_mode = _KIND_MODE.get(kind)
    if worker_mode is not None:
        request["mode"] = worker_mode

    if kind == "physical":
        request.update(
            perils=list(perils),
            climate_scenario=scenario.rcp,
            anchor_years=anchor_years,
            options={},
        )
    elif kind == "uncertainty":
        request.update(
            climate_scenario=scenario.rcp,
            anchor_years=anchor_years,
            n_samples=int(options.get("nSamples", 50)),
        )
    elif kind == "cost-benefit":
        request.update(
            peril=options.get("peril") or (perils[0] if perils else "tropical_cyclone"),
            climate_scenario=scenario.rcp,
            anchor_years=anchor_years,
            discount_rate=float(options.get("discountRate", 0.05)),
            discount_schedule=None,
            measures=_measures_snake(list(options.get("measures") or [])),
        )
    elif kind == "supply-chain":
        request.update(
            climate_scenario=scenario.rcp,
            anchor_years=anchor_years,
            mriot_type=str(options.get("mriotType", "WIOD16")),
            mriot_year=int(options.get("mriotYear", 2010)),
        )
    elif kind == "calibration":
        request.update(climate_scenario=scenario.rcp, anchor_years=anchor_years)
    elif kind == "forecast":
        pass  # forecast uses the live feed: session_id + assets only
    else:
        raise WorkerError(f"unknown run kind '{kind}'")
    return request


# ── result translation (worker snake_case -> our camelCase models) ────────────


# Per-peril statuses the worker uses for a failed block within an overall-'partial'
# physical run (physical.py::compute_physical_risk).
_FAILED_BLOCK_STATUSES = ("error", "engine_not_ready")


def _check_status(data: dict[str, Any]) -> None:
    """Reject results the worker itself flagged as failed (caller falls back)."""
    status = str(data.get("status", ""))
    if status in _FAILED_BLOCK_STATUSES:
        raise WorkerError(data.get("detail") or f"worker returned status '{status}'")


def _parse_physical(data: dict[str, Any], portfolio: Portfolio) -> PhysicalRunOutput:
    blocks: list[PhysicalRunResult] = []
    failed_perils: list[str] = []
    for r in data.get("results") or []:
        peril = str(r.get("peril", ""))
        status = str(r.get("status", "ok"))
        block_detail: str | None = None
        if status in _FAILED_BLOCK_STATUSES:
            # An overall-'partial' run passes _check_status, but its failed peril
            # blocks carry no numbers — keep the zeroed block so the peril list
            # stays complete, and flag it so the zero reads as "not modeled"
            # (downstream finance would otherwise sum it as a genuine zero loss).
            reason = (
                r.get("detail")
                or r.get("interpretation")
                or f"worker returned status '{status}'"
            )
            block_detail = f"failed: {reason}"
            failed_perils.append(peril or status)
        fc = r.get("freq_curve") or {}
        blocks.append(
            PhysicalRunResult(
                peril=peril,
                perAsset=[
                    AssetImpact(assetId=str(p.get("id", "")), eai=float(p.get("eai") or 0.0))
                    for p in r.get("per_asset") or []
                ],
                aaiAgg=float(r.get("aai_agg") or 0.0),
                freqCurve=FreqCurve(
                    returnPeriods=[float(x) for x in fc.get("return_periods") or []],
                    losses=[float(x) for x in fc.get("impact") or []],
                ),
                deltaPct=(
                    float(r["delta_pct"]) if r.get("delta_pct") is not None else None
                ),
                detail=block_detail,
            )
        )
    currency = portfolio.assets[0].currency if portfolio.assets else "USD"
    detail = data.get("detail")
    if failed_perils:
        note = (
            f"Peril(s) failed on the worker: {', '.join(failed_perils)} — their zero "
            "losses are unmodeled, not modeled zeros (see each block's detail)."
        )
        detail = f"{detail} {note}" if detail else note
    return PhysicalRunOutput(currency=currency, perils=blocks, detail=detail)


def _parse_uncertainty(data: dict[str, Any]) -> UncertaintyResult:
    band = UncertaintyPerilBand(
        peril=str(data.get("peril", "tropical_cyclone")),
        futureYear=data.get("future_year"),
        aaiMean=float(data.get("aai_mean") or 0.0),
        aaiStd=float(data.get("aai_std") or 0.0),
        aaiP5=float(data.get("aai_p5") or 0.0),
        aaiP50=float(data.get("aai_p50") or 0.0),
        aaiP95=float(data.get("aai_p95") or 0.0),
        distribution=[float(x) for x in data.get("distribution") or []],
        sensitivity=dict(data.get("sensitivity") or {}),
        sensitivityS1=dict(data.get("sensitivity_s1") or {}),
        sensitivitySt=dict(data.get("sensitivity_st") or {}),
        sensitivityMethod=str(data.get("sensitivity_method", "sobol")),
        presentAai=data.get("present_aai"),
        deltaMean=data.get("delta_mean"),
        deltaP5=data.get("delta_p5"),
        deltaP95=data.get("delta_p95"),
        detail=data.get("detail"),
    )
    return UncertaintyResult(
        status=str(data.get("status", "ok")),
        currency=str(data.get("currency", "USD")),
        nSamples=int(data.get("n_samples") or 0),
        perils=[band],
        detail=data.get("detail"),
    )


def _parse_cost_benefit(data: dict[str, Any]) -> CostBenefitResult:
    return CostBenefitResult(
        status=str(data.get("status", "ok")),
        peril=str(data.get("peril", "tropical_cyclone")),
        futureYear=data.get("future_year"),
        discountRate=float(data.get("discount_rate") or 0.05),
        currency=str(data.get("currency", "USD")),
        totClimateRisk=float(data.get("tot_climate_risk") or 0.0),
        measures=[
            MeasureResult(
                name=str(m.get("name", "")),
                cost=float(m.get("cost") or 0.0),
                benefit=float(m.get("benefit") or 0.0),
                benefitCostRatio=m.get("benefit_cost_ratio"),
            )
            for m in data.get("measures") or []
        ],
        detail=data.get("detail"),
    )


def _parse_supply_chain(data: dict[str, Any]) -> SupplyChainResult:
    return SupplyChainResult(
        status=str(data.get("status", "ok")),
        mriot=str(data.get("mriot", "")),
        currency=str(data.get("currency", "USD")),
        totalDirect=float(data.get("total_direct") or 0.0),
        totalIndirect=float(data.get("total_indirect") or 0.0),
        amplification=data.get("amplification"),
        bySector=[
            SupplyChainSector(sector=str(s.get("sector", "")), indirect=float(s.get("indirect") or 0.0))
            for s in data.get("by_sector") or []
        ],
        detail=data.get("detail"),
    )


def _parse_calibration(data: dict[str, Any]) -> CalibrationResult:
    return CalibrationResult(
        status=str(data.get("status", "ok")),
        peril=str(data.get("peril", "tropical_cyclone")),
        country=str(data.get("country", "")),
        param=str(data.get("param", "v_half")),
        initial=float(data.get("initial") or 0.0),
        calibrated=float(data.get("calibrated") or 0.0),
        observedAnnualLoss=float(data.get("observed_annual_loss") or 0.0),
        detail=data.get("detail"),
    )


def _parse_forecast(data: dict[str, Any], portfolio: Portfolio) -> ForecastResult:
    currency = portfolio.assets[0].currency if portfolio.assets else "USD"
    return ForecastResult(
        status=str(data.get("status", "ok")),
        peril=str(data.get("peril", "tropical_cyclone")),
        nTracks=int(data.get("n_tracks") or 0),
        totalImpact=float(data.get("total_impact") or 0.0),
        currency=currency,
        perAsset=[
            AssetImpact(assetId=str(p.get("id", "")), eai=float(p.get("eai") or 0.0))
            for p in data.get("per_asset") or []
        ],
        series=[],  # the live-feed forecast has no seasonal series (stub-only shape)
        detail=data.get("detail"),
    )


def parse_result(kind: str, data: dict[str, Any], portfolio: Portfolio) -> Any:
    """Translate a worker ``result.json`` body into OUR camelCase result model.

    Raises:
        WorkerError: when the worker flagged the run failed or the shape is invalid.
    """
    _check_status(data)
    try:
        if kind == "physical":
            return _parse_physical(data, portfolio)
        if kind == "uncertainty":
            return _parse_uncertainty(data)
        if kind == "cost-benefit":
            return _parse_cost_benefit(data)
        if kind == "supply-chain":
            return _parse_supply_chain(data)
        if kind == "calibration":
            return _parse_calibration(data)
        if kind == "forecast":
            return _parse_forecast(data, portfolio)
    except WorkerError:
        raise
    except Exception as exc:  # noqa: BLE001 — any malformed result falls back to the stub
        raise WorkerError(f"unparseable worker result: {type(exc).__name__}: {exc}") from exc
    raise WorkerError(f"unknown run kind '{kind}'")


# ── subprocess execution ──────────────────────────────────────────────────────


def _worker_env() -> dict[str, str]:
    """The worker subprocess environment (inherits ours; CLIMADA data vars injected)."""
    env = {**os.environ, "MPLBACKEND": "Agg", "PYTHONUNBUFFERED": "1"}
    env.setdefault("CLIMATERISK_HAZARD_DB", str(_DEFAULT_HAZARD_DB))
    return env


def _log_tail(job_dir: Path, n: int = 800) -> str:
    log = job_dir / "worker.log"
    if not log.is_file():
        return ""
    return f" worker.log tail: ...{log.read_text(encoding='utf-8', errors='replace')[-n:]}"


def run(
    kind: str,
    portfolio: Portfolio,
    perils: list[str],
    scenario: Scenario,
    options: dict[str, Any],
) -> Any:
    """Execute one run on the real CLIMADA worker (synchronous, wall-clock capped).

    Writes ``request.json`` into a per-run temp job dir, spawns
    ``<env>/bin/python -m physical_risk_worker.run_job <job_dir>``, reads back
    ``result.json`` and translates it into our result model. The job dir is
    removed on success and kept (with ``worker.log``) on failure for debugging.

    Raises:
        WorkerError: on any failure — env missing, spawn error, timeout, missing
            or malformed result — so the caller can fall back to the stub.
    """
    if not available():
        raise WorkerError(f"CLIMADA worker env not found at {env_dir()}")

    request = build_request(kind, portfolio, perils, scenario, options)
    job_dir = Path(tempfile.mkdtemp(prefix=f"ragnarok-climada-{kind.replace('/', '_')}-"))
    timeout = timeout_seconds()
    cmd = [str(worker_python()), "-m", _WORKER_MODULE, str(job_dir)]
    try:
        (job_dir / "request.json").write_text(
            json.dumps(request, indent=2), encoding="utf-8"
        )
        logger.info("physical-risk %s run: spawning CLIMADA worker (%s)", kind, cmd[0])
        try:
            with (job_dir / "worker.log").open("wb") as log:
                proc = subprocess.run(  # noqa: S603 — fixed interpreter + module, no shell
                    cmd,
                    cwd=str(_WORKER_IMPORT_ROOT),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=_worker_env(),
                    timeout=timeout,
                    check=False,
                )
        except subprocess.TimeoutExpired as exc:
            raise WorkerError(f"worker run timed out after {timeout:.0f}s") from exc
        except OSError as exc:
            raise WorkerError(f"could not spawn the worker: {exc}") from exc
        if proc.returncode != 0:
            raise WorkerError(
                f"worker exited with code {proc.returncode}.{_log_tail(job_dir)}"
            )
        result_path = job_dir / "result.json"
        if not result_path.is_file():
            raise WorkerError(f"worker wrote no result.json.{_log_tail(job_dir)}")
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — malformed JSON falls back to the stub
            raise WorkerError(f"unreadable result.json: {exc}") from exc
        result = parse_result(kind, data, portfolio)
    except WorkerError as exc:
        logger.warning(
            "physical-risk %s run: worker failed (%s); job dir kept at %s", kind, exc, job_dir
        )
        raise
    shutil.rmtree(job_dir, ignore_errors=True)
    return result
