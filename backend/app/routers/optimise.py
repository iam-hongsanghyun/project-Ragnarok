"""Optimisation-adjacent endpoints on PyPSA 1.4's native APIs (P20, P26, P31, P35-P39).

* ``GET  /api/optimise/options``          solver capability + option-key catalogue (P20/P45)
* ``POST /api/optimise/export-lp``        write the LP file without solving (P26)
* ``POST /api/analysis/consistency``      ``n.consistency_check`` pre-flight (P37)
* ``POST /api/analysis/network``          PTDF / BODF / cycles / adjacency / incidence (P38)
* ``POST /api/statistics/query``          parametrised ``n.statistics`` on a stored run (P31)
* ``POST /api/transform/temporal``        temporal clustering: resample/downsample/segment (P35)
* ``POST /api/transform/slice``           ``n.slice_network`` window / bus subset (P39)
* ``POST /api/transform/merge``           ``n.merge`` two models (P39)

Thin wrappers: the logic is in :mod:`backend.pypsa.optimise_options`,
:mod:`backend.pypsa.optimise_extras`, :mod:`backend.pypsa.network_ops` and
:mod:`backend.pypsa.results.statistics_query`. Transforms return a reduced
workbook model for the caller to swap into the session (``POST /api/session/model``),
matching ``/api/transform/cluster``.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import model_store, run_store
from ..data_root import data_root
from ..run_options_reference import RunOption, register_options
from ...pypsa import network_ops
from backend.app.constraints.constraint_checks import consistency_report
from ...pypsa.optimise_options import optimise_option_catalogue, parse_optimise_options

router = APIRouter(tags=["optimise"])

_OO = "backend/pypsa/optimise_options.py (parse_optimise_options)"
_RES = "backend/pypsa/results/__init__.py (run_pypsa)"
_IT = "backend/pypsa/optimise_extras.py (run_iterative_expansion)"


def _o(path: str, type_: str, meaning: str, default: Any = None, *, allowed: list[Any] | None = None,
       unit: str | None = None, reader: str = _OO, source: str = "api") -> RunOption:
    return RunOption(path, type_, meaning, default, unit, allowed, reader, source)


# Run options added for the PyPSA 1.4 optimise surface (P19-P27, P34, P38). "ui" = Settings -> Solver
# -> Advanced sends it; everything is also usable through MCP submit_solve options.
register_options([
    RunOption(
        "options.rollingConfig.terminalSocPenalty", "number | null",
        "Price of one MWh of terminal-SOC shortfall. null = auto: 2 x the highest generator marginal_cost "
        "(above the replacement cost of the energy, so the last window refills when it can), floor 1.0. The penalty is a solver-side term only; reported costs are "
        "recomputed from solved values and exclude it.",
        None, unit="currency/MWh", reader="backend/pypsa/rolling.py (auto_terminal_penalty)", source="api", group="rolling",
    ),
    _o("options.solverName", "string", "linopy solver (installed only; GET /api/optimise/options lists them). Follow-on studies (merchant, bid, asset swap, ESS) always re-solve on HiGHS.", "highs", source="ui"),
    _o("options.solverOptions", "object", "Raw solver options passed verbatim, merged over the HiGHS solverThreads/solverType translation.", {}),
    _o("options.transmissionLosses", "boolean | object", "Line/link losses: true = secants, or {mode: secants, atol, rtol, max_segments} / {mode: tangents, segments}. An int is read as tangents segments.", False, source="ui"),
    _o("options.linearizedUnitCommitment", "boolean", "Relax committable binaries (LP).", False, source="ui"),
    _o("options.committableBigM", "number", "Big-M for committable + extendable units.", None, unit="MW", source="ui"),
    _o("options.cycleBasisMethod", "string", "Cycle basis for Kirchhoff voltage law.", "bfs-refined", allowed=["bfs-refined", "paton"], source="ui"),
    _o("options.meshedThresholds", "number[]", "PyPSA meshed_thresholds.", None),
    _o("options.computeInfeasibilities", "boolean", "On an infeasible solve append the solver IIS to the error (Gurobi/Xpress); other solvers fall back to Ragnarok's diagnosis.", False, source="ui"),
    _o("options.modelKwargs", "object", "linopy.Model kwargs (solver_dir, chunk).", {}),
    _o("options.logToConsole", "boolean", "Forward the solver log to the console.", None),
    _o("options.riskPreference", "object", "CVaR in stochastic mode: {alpha: 0<a<1, omega: 0..1} (n.set_risk_preference). 400 without stochasticConfig.", None, reader=_OO + ", " + _RES),
    _o("options.iterativeExpansion", "object", "Iterative transmission expansion: {enabled, msqThreshold=0.05, minIterations=1, maxIterations=10, lineUnitSize, lineThreshold, fractionalLastUnitSize, linkUnitSize{}, linkThreshold{}}.", None, reader="backend/pypsa/optimise_extras.py (run_iterative_expansion)"),
    _o("options.riskPreference.alpha", "number", "CVaR confidence level: the objective weighs the worst (1 - alpha) share of scenario probability. 0 < alpha < 1.", 0.95, unit="probability 0-1", reader=_OO + " (apply_risk_preference)"),
    _o("options.riskPreference.omega", "number", "Weight of the CVaR term against the expected cost: 0 = risk-neutral expected cost, 1 = pure CVaR. 0 <= omega <= 1.", 0.5, unit="weight 0-1", reader=_OO + " (apply_risk_preference)"),
    _o("options.iterativeExpansion.enabled", "boolean", "Re-solve until the extendable lines' s_nom_opt settles (line reactances are rescaled after each LP).", False, reader=_IT),
    _o("options.iterativeExpansion.msqThreshold", "number", "Stop when the mean-square change of s_nom_opt between iterations is below this.", 0.05, unit="MVA^2", reader=_IT),
    _o("options.iterativeExpansion.minIterations", "integer", "Iterations always run before the threshold is tested.", 1, unit="iterations", reader=_IT),
    _o("options.iterativeExpansion.maxIterations", "integer", "Hard cap on iterations.", 10, unit="iterations", reader=_IT),
    _o("options.iterativeExpansion.lineUnitSize", "number", "Discrete line module size: expansion is rounded to whole units of this size. Empty = continuous expansion.", None, unit="MVA", reader=_IT),
    _o("options.iterativeExpansion.lineThreshold", "number", "Share of one unit (0-1) above which a fractional line unit is rounded up (needs lineUnitSize).", None, unit="fraction of a unit 0-1", reader=_IT),
    _o("options.iterativeExpansion.fractionalLastUnitSize", "boolean", "Allow the last unit to be a fraction of lineUnitSize in the final iteration.", False, reader=_IT),
    _o("options.iterativeExpansion.linkUnitSize", "object", "Discrete link module size per link name: {linkName: MW}.", {}, unit="MW", reader=_IT),
    _o("options.iterativeExpansion.linkThreshold", "object", "Rounding threshold per link name: {linkName: fraction of a unit 0-1}.", {}, unit="fraction of a unit 0-1", reader=_IT),
    _o("options.twoStage.enabled", "boolean", "Two-stage solve: size capacities on the LP relaxation, fix them, re-solve the dispatch.", False, reader="backend/pypsa/optimise_extras.py (run_two_stage)"),
    _o("options.twoStage", "object", "{enabled}: size capacities on the LP relaxation, fix_optimal_capacities, re-solve dispatch (restores extendable flags).", None, reader="backend/pypsa/optimise_extras.py (run_two_stage)"),
    _o("options.nonLinearPowerFlowAfterOptimise", "object", "{enabled, distributeSlack, slackWeights, xTol, useSeed, skipPre}: AC power flow on a copy of the solved dispatch; result in payload.acFeasibility.", None, reader="backend/pypsa/optimise_extras.py (run_ac_feasibility)"),
    _o("options.securityConstrainedConfig.branchOutages", "string[]", "SCLOPF: secure only these passive branches ('L1', 'Transformer:T1'); empty = all. SCLOPF + pathway is allowed.", [], reader=_OO + " (parse_branch_outages)"),
    _o("options.mgaConfig.minMax", "boolean", "Run the per-carrier min/max pairs (default true).", True, reader="backend/pypsa/results/mga.py (build_mga)"),
    _o("options.mgaConfig.dimensions", "object", "MGA space: {name: {component, attribute?, carriers?}}; default one Generator p_nom dimension per extendable carrier.", None, reader="backend/pypsa/results/mga.py (_mga_dimensions)"),
    _o("options.mgaConfig.directions", "object[] | object", "MGA in a direction: [{weights: {dimension: w}}] or {random: n, seed}. Result in nearOptimal.directions.", None, reader="backend/pypsa/results/mga.py (build_mga_directions)"),
    _o("options.mgaConfig.maxParallel", "number", "Directions solved in parallel (native process pool when > 1).", 1, reader="backend/pypsa/results/mga.py (build_mga_directions)"),
    _o("options.powerFlowConfig.xTol", "number", "Newton-Raphson tolerance of n.pf().", 1e-6, reader="backend/pypsa/results/power_flow.py (pf_kwargs_from_config)"),
    _o("options.powerFlowConfig.useSeed", "boolean", "Start each snapshot from the previous solution.", False, reader="backend/pypsa/results/power_flow.py"),
    _o("options.powerFlowConfig.distributeSlack", "boolean", "Distribute the slack over all generators.", False, reader="backend/pypsa/results/power_flow.py"),
    _o("options.powerFlowConfig.slackWeights", "string", "Slack distribution weights.", "p_set", allowed=["p_set", "p_nom", "p_nom_opt"], reader="backend/pypsa/results/power_flow.py"),
    _o("options.powerFlowConfig.skipPre", "boolean", "Skip topology determination (pf and lpf).", False, reader="backend/pypsa/results/power_flow.py"),
    _o("options.contingencyConfig.snapshot", "string | number", "N-1 snapshot: ISO label or position (default the peak-demand snapshot).", "peak", reader="backend/pypsa/results/contingency.py"),
    _o("options.contingencyConfig.branchOutages", "string[]", "Test only these branch outages.", [], reader="backend/pypsa/results/contingency.py"),
    _o("options.consistencyCheck", "boolean | object", "On /api/validate: also run n.consistency_check ({strict: [...], checkDtypes}). Separate tool: MCP consistency_check / POST /api/analysis/consistency.", False, reader="backend/pypsa/network/validators.py, constraint_checks.py"),
])


def _model(session_id: str) -> dict[str, list[dict[str, Any]]]:
    model = model_store.load_full_model(session_id)
    if not model:
        raise HTTPException(status_code=400, detail="No working model in this session.")
    return model


class _SessionBody(BaseModel):
    sessionId: str = "default"
    scenario: dict[str, Any] | None = None
    options: dict[str, Any] | None = None


@router.get("/api/optimise/options")
def optimise_options() -> dict[str, Any]:
    """Installed solvers (with capability flags) and every ``n.optimize`` option key."""
    return optimise_option_catalogue()


class ExportLpRequest(_SessionBody):
    fileName: str = "model.lp"


@router.post("/api/optimise/export-lp")
def export_lp(req: ExportLpRequest) -> dict[str, Any]:
    """Build the session model and write its LP/MPS file without solving.

    The file lands in ``<data>/exports/lp/`` (``.lp`` or ``.mps``); the problem is
    exactly what ``n.optimize`` would hand the solver, including the parsed
    model-building options (transmission losses, linearised UC, ...).
    """
    from ...pypsa.network import build_network
    from ...pypsa.optimise_extras import export_lp_file

    options = dict(req.options or {})
    oo = parse_optimise_options(options)
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", req.fileName or "model.lp") or "model.lp"
    if not stem.lower().endswith((".lp", ".mps")):
        stem += ".lp"
    path = data_root() / "exports" / "lp" / stem
    model = _model(req.sessionId)
    t0 = time.perf_counter()
    try:
        network, _ = build_network(model, dict(req.scenario or {}), options)
        pathway = bool((options.get("pathwayConfig") or {}).get("enabled"))
        info = export_lp_file(network, path, oo, multi_investment_periods=pathway)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"LP export failed: {exc}") from exc
    info["seconds"] = round(time.perf_counter() - t0, 2)
    return info


@router.get("/api/optimise/export-lp/file")
def export_lp_file_download(fileName: str) -> FileResponse:
    """Stream a file previously written by ``POST /api/optimise/export-lp`` (the browser's Download)."""
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(fileName).name)
    path = data_root() / "exports" / "lp" / stem
    if not stem or not path.is_file():
        raise HTTPException(status_code=404, detail=f"No exported LP file named {stem!r}; export it first.")
    return FileResponse(path, filename=stem, media_type="application/octet-stream")


class ConsistencyRequest(_SessionBody):
    strict: list[str] | None = None
    checkDtypes: bool = False


@router.post("/api/analysis/consistency")
def consistency(req: ConsistencyRequest) -> dict[str, Any]:
    """PyPSA ``n.consistency_check`` on the session model: errors and warnings, no solve."""
    return consistency_report(
        _model(req.sessionId), req.scenario, req.options, strict=req.strict, check_dtypes=req.checkDtypes
    )


class NetworkAnalysisRequest(_SessionBody):
    include: list[str] | None = None
    cycleBasisMethod: str = "bfs-refined"
    maxBranches: int = 250


@router.post("/api/analysis/network")
def network_analysis(req: NetworkAnalysisRequest) -> dict[str, Any]:
    """Sub-networks (slack), PTDF, BODF, cycle matrix, adjacency and incidence of the topology."""
    try:
        return network_ops.network_analysis(
            _model(req.sessionId),
            scenario=req.scenario,
            options=req.options,
            include=req.include,
            cycle_basis_method=req.cycleBasisMethod,
            max_branches=req.maxBranches,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Network analysis failed: {exc}") from exc


class StatisticsRequest(BaseModel):
    runName: str
    metric: str = "energy_balance"
    groupby: list[str] | None = None
    busCarrier: list[str] | None = None
    aggregateTime: str | bool = "sum"
    atPort: bool = False
    niceNames: bool = False
    dropZero: bool = True
    components: list[str] | None = None
    carrier: list[str] | None = None
    roundDigits: int | None = None


@router.post("/api/statistics/query")
def statistics_query(req: StatisticsRequest) -> dict[str, Any]:
    """One ``n.statistics`` metric with PyPSA's own parameters, on a stored run."""
    from ...pypsa.results.statistics_query import network_from_outputs, run_statistic

    bundle = run_store.get_run(req.runName)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"Run {req.runName!r} not found.")
    result = bundle.get("result") or {}
    try:
        network = network_from_outputs(
            bundle.get("model") or {}, bundle.get("scenario") or {}, bundle.get("options") or {},
            result.get("outputs") or {},
        )
        return run_statistic(
            network,
            req.metric,
            groupby=req.groupby,
            bus_carrier=req.busCarrier,
            aggregate_time=req.aggregateTime,
            at_port=req.atPort,
            nice_names=req.niceNames,
            drop_zero=req.dropZero,
            components=req.components,
            carrier=req.carrier,
            round_digits=req.roundDigits,
        )
    except HTTPException:
        raise
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class TemporalRequest(_SessionBody):
    method: str = "resample"
    offset: str | None = None
    dropLeapDay: bool = False
    stride: int | None = None
    numSegments: int | None = None
    solver: str = "highs"
    aggregationRules: dict[str, str] | None = None


@router.post("/api/transform/temporal")
def temporal_cluster(req: TemporalRequest) -> dict[str, Any]:
    """Native temporal clustering of the session model (weights stay energy-correct)."""
    return network_ops.temporal_cluster(
        _model(req.sessionId),
        method=req.method,
        scenario=req.scenario,
        options=req.options,
        offset=req.offset,
        drop_leap_day=req.dropLeapDay,
        stride=req.stride,
        num_segments=req.numSegments,
        solver=req.solver,
        aggregation_rules=req.aggregationRules,
    )


class SliceRequest(_SessionBody):
    start: int | str | None = None
    end: int | str | None = None
    buses: list[str] | None = None


@router.post("/api/transform/slice")
def slice_network(req: SliceRequest) -> dict[str, Any]:
    """Keep a snapshot window and/or a bus subset of the session model."""
    return network_ops.slice_model(
        _model(req.sessionId), scenario=req.scenario, options=req.options,
        start=req.start, end=req.end, buses=req.buses,
    )


class MergeRequest(_SessionBody):
    otherRun: str | None = None
    otherSessionId: str | None = None
    componentsToSkip: list[str] | None = None
    withTime: bool = True


@router.post("/api/transform/merge")
def merge_network(req: MergeRequest) -> dict[str, Any]:
    """Merge a stored run's model (``otherRun``) or another session's model into this one."""
    if bool(req.otherRun) == bool(req.otherSessionId):
        raise HTTPException(status_code=400, detail="Give exactly one of otherRun or otherSessionId.")
    if req.otherRun:
        run = run_store.get_run_model(req.otherRun)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {req.otherRun!r} not found.")
        other = run.get("model") or {}
    else:
        other = _model(req.otherSessionId or "")
    return network_ops.merge_models(
        _model(req.sessionId), other, scenario=req.scenario, options=req.options,
        components_to_skip=req.componentsToSkip, with_time=req.withTime,
    )
