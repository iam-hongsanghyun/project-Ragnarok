"""Run-option parsing for the PyPSA 1.4 ``n.optimize`` surface (P19-P26).

Everything here is a pure translation from the JSON run options Ragnarok already
carries (``options`` of ``POST /api/queue`` / MCP ``submit_solve``) to PyPSA call
arguments, so the solve path in :func:`backend.pypsa.results.run_pypsa` stays a
thin caller and every knob is reachable from the GUI, the REST API and MCP alike.

Option keys (all optional, all top-level in ``options``):

``solverName``              linopy solver (``highs`` default); must be installed
                            (see :func:`available_solvers`), else 400.
``solverOptions``           raw ``{name: value}`` dict handed to the solver verbatim
                            (merged over the HiGHS ``solverThreads``/``solverType``
                            translation, which only applies to HiGHS).
``transmissionLosses``      ``true`` (secants) or ``{"mode": "secants", "atol", "rtol",
                            "max_segments"}`` / ``{"mode": "tangents", "segments"}``.
``linearizedUnitCommitment``  relax committable binaries (LP).
``committableBigM``         big-M for committable + extendable generators (MW).
``cycleBasisMethod``        ``bfs-refined`` (default) | ``paton``.
``meshedThresholds``        list of ints (PyPSA ``meshed_thresholds``).
``computeInfeasibilities``  on an infeasible solve, request the solver IIS
                            (Gurobi only) and append it to the failure detail.
``modelKwargs``             ``linopy.Model`` kwargs (``solver_dir``, ``chunk``).
``logToConsole``            forward the solver log to the console.
``riskPreference``          ``{"alpha": 0.95, "omega": 0.5}`` CVaR weights in stochastic
                            mode (``n.set_risk_preference``).
``iterativeExpansion``      ``{"enabled": true, "msqThreshold", "minIterations",
                            "maxIterations", "lineUnitSize", "lineThreshold",
                            "fractionalLastUnitSize", "linkUnitSize": {name: MW}}``.
``securityConstrainedConfig.branchOutages``  subset of passive branches to secure:
                            ``["L1", "Transformer:T1", {"component": "Line", "name": "L2"}]``.
``nonLinearPowerFlowAfterOptimise``  ``{"enabled": true, "distributeSlack", "slackWeights",
                            "xTol", "useSeed", "skipPre"}`` -> LOPF then AC PF.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException

from .network.piecewise import parse_piecewise_options

# Solvers Ragnarok knows how to describe. Availability is always probed from
# linopy, never assumed; the list only supplies labels + capability flags.
_SOLVER_CATALOG: dict[str, dict[str, Any]] = {
    "highs": {"label": "HiGHS", "mip": True, "iis": False, "threads_key": "threads"},
    "gurobi": {"label": "Gurobi", "mip": True, "iis": True, "threads_key": "Threads"},
    "cplex": {"label": "CPLEX", "mip": True, "iis": False, "threads_key": "threads"},
    "xpress": {"label": "FICO Xpress", "mip": True, "iis": True, "threads_key": "THREADS"},
    "copt": {"label": "COPT", "mip": True, "iis": False, "threads_key": "Threads"},
    "mosek": {"label": "MOSEK", "mip": True, "iis": False, "threads_key": "MSK_IPAR_NUM_THREADS"},
    "scip": {"label": "SCIP", "mip": True, "iis": False, "threads_key": None},
    "cbc": {"label": "CBC", "mip": True, "iis": False, "threads_key": "threads"},
    "glpk": {"label": "GLPK", "mip": True, "iis": False, "threads_key": None},
    "knitro": {"label": "Knitro", "mip": True, "iis": False, "threads_key": None},
    "cupdlpx": {"label": "cuPDLPx (GPU)", "mip": False, "iis": False, "threads_key": None},
    "cuopt": {"label": "NVIDIA cuOpt", "mip": True, "iis": False, "threads_key": None},
}
DEFAULT_SOLVER = "highs"
CYCLE_BASIS_METHODS = ("bfs-refined", "paton")


def available_solvers() -> list[str]:
    """Solver names linopy can run in this environment (``linopy.available_solvers``)."""
    try:
        import linopy

        return [str(s) for s in linopy.available_solvers]
    except Exception:  # noqa: BLE001 - capability probing must never raise
        return [DEFAULT_SOLVER]


def solver_capabilities() -> list[dict[str, Any]]:
    """One row per known or installed solver: ``{name, label, installed, default, mip, iis}``.

    ``iis`` marks solvers that can produce an irreducible infeasible subsystem,
    which is what ``computeInfeasibilities`` needs.
    """
    installed = set(available_solvers())
    names = list(_SOLVER_CATALOG) + sorted(installed - set(_SOLVER_CATALOG))
    out = []
    for name in names:
        meta = _SOLVER_CATALOG.get(name, {"label": name, "mip": True, "iis": False})
        out.append({
            "name": name,
            "label": meta["label"],
            "installed": name in installed,
            "default": name == DEFAULT_SOLVER,
            "mip": bool(meta["mip"]),
            "iis": bool(meta["iis"]),
        })
    return out


def optimise_option_catalogue() -> dict[str, Any]:
    """Machine-readable list of the option keys this module understands (for MCP/UI)."""
    return {
        "solvers": solver_capabilities(),
        "cycleBasisMethods": list(CYCLE_BASIS_METHODS),
        "transmissionLossModes": ["secants", "tangents"],
        "keys": {
            "solverName": "linopy solver name (installed solvers only; default highs)",
            "solverOptions": "raw solver options dict, passed verbatim",
            "transmissionLosses": "bool | {mode: secants|tangents, atol, rtol, max_segments, segments}",
            "linearizedUnitCommitment": "bool - relax committable binaries",
            "committableBigM": "float - big-M for committable+extendable units",
            "cycleBasisMethod": "bfs-refined | paton",
            "meshedThresholds": "list[int]",
            "computeInfeasibilities": "bool - IIS on infeasible (Gurobi/Xpress)",
            "modelKwargs": "dict - linopy.Model kwargs (solver_dir, chunk)",
            "logToConsole": "bool",
            "riskPreference": "{alpha, omega} - CVaR in stochastic mode",
            "iterativeExpansion": "{enabled, msqThreshold, minIterations, maxIterations, "
            "lineUnitSize, lineThreshold, fractionalLastUnitSize, linkUnitSize}",
            "securityConstrainedConfig.branchOutages": "list of branch names / 'Transformer:name'",
            "nonLinearPowerFlowAfterOptimise": "{enabled, distributeSlack, slackWeights, xTol, useSeed, skipPre}",
            "mgaConfig.directions": "list of {name?, weights: {carrier: weight}} for MGA in a direction",
            "mgaConfig.maxParallel": "int - parallel directions",
            "powerFlowConfig": "{enabled, linear, xTol, useSeed, distributeSlack, slackWeights, skipPre}",
            "twoStage": "{enabled} - solve, fix_optimal_capacities, re-solve dispatch",
            "piecewiseOptions": "list of {component, attribute, method: auto|lp|incremental|sos2, "
            "name?: [..], sign?} - formulation override per piecewise curve (default auto)",
        },
    }


@dataclass(frozen=True)
class OptimiseOptions:
    """Parsed ``n.optimize`` extras. ``kwargs()`` yields only non-default arguments."""

    solver_name: str = DEFAULT_SOLVER
    extra_solver_options: dict[str, Any] = field(default_factory=dict)
    transmission_losses: bool | dict[str, Any] = False
    linearized_unit_commitment: bool = False
    committable_big_m: float | None = None
    cycle_basis_method: str | None = None
    meshed_thresholds: tuple[int, ...] | None = None
    compute_infeasibilities: bool = False
    model_kwargs: dict[str, Any] = field(default_factory=dict)
    log_to_console: bool | None = None
    risk_alpha: float | None = None
    risk_omega: float | None = None
    iterative_expansion: dict[str, Any] | None = None
    branch_outages: tuple[tuple[str, str], ...] | None = None
    nonlinear_pf: dict[str, Any] | None = None
    two_stage: bool = False
    piecewise_options: tuple[dict[str, Any], ...] = ()  # P10: per-curve formulation overrides

    def io_api(self, highs_default: str = "direct") -> str | None:
        """linopy ``io_api``: in-memory ``direct`` only where it is known to work (HiGHS).

        Other solvers get ``None`` (linopy picks its LP-file path); e.g. GLPK
        rejects ``direct`` export.
        """
        return highs_default if self.solver_name == "highs" else None

    def optimize_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for ``n.optimize()`` / ``create_model`` beyond the base ones.

        Only values that differ from PyPSA's defaults are returned, so a bare
        ``options={}`` solve calls ``n.optimize`` exactly as before.
        """
        out: dict[str, Any] = {}
        if self.transmission_losses:
            out["transmission_losses"] = self.transmission_losses
        if self.linearized_unit_commitment:
            out["linearized_unit_commitment"] = True
        if self.committable_big_m is not None:
            out["committable_big_m"] = self.committable_big_m
        if self.cycle_basis_method:
            out["cycle_basis_method"] = self.cycle_basis_method
        if self.meshed_thresholds:
            out["meshed_thresholds"] = list(self.meshed_thresholds)
        if self.model_kwargs:
            out["model_kwargs"] = dict(self.model_kwargs)
        if self.log_to_console is not None:
            out["log_to_console"] = self.log_to_console
        if self.piecewise_options:
            out["piecewise_options"] = [dict(o) for o in self.piecewise_options]
            if any(o.get("method") == "sos2" for o in self.piecewise_options):
                out["reformulate_sos"] = "auto"  # HiGHS has no native SOS2
        if self.compute_infeasibilities and (_SOLVER_CATALOG.get(self.solver_name) or {}).get("iis"):
            out["compute_infeasibilities"] = True
        return out

    def solve_kwargs(self) -> dict[str, Any]:
        """The subset of :meth:`optimize_kwargs` that SCLOPF / rolling horizon accept.

        Those wrappers forward ``**kwargs`` to ``n.optimize`` (SCLOPF builds its
        own model), so the model-building knobs are passed through unchanged.
        """
        return self.optimize_kwargs()


def _as_bool(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() in ("1", "true", "yes", "on"))


def _parse_losses(raw: Any) -> bool | dict[str, Any]:
    if raw in (None, False, 0, "", "off", "none"):
        return False
    if raw is True or _as_bool(raw):
        return True
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        # PyPSA deprecates the bare int; translate it to the equivalent tangents dict.
        return {"mode": "tangents", "segments": int(raw)}
    if isinstance(raw, dict):
        mode = str(raw.get("mode", "secants")).lower()
        if mode not in ("secants", "tangents"):
            raise HTTPException(
                status_code=400,
                detail=f"transmissionLosses.mode must be 'secants' or 'tangents', got {mode!r}.",
            )
        out: dict[str, Any] = {"mode": mode}
        if mode == "tangents":
            seg = raw.get("segments")
            if seg is None or int(seg) < 1:
                raise HTTPException(
                    status_code=400, detail="transmissionLosses tangents mode needs segments >= 1."
                )
            out["segments"] = int(seg)
        else:
            for key in ("atol", "rtol"):
                if raw.get(key) is not None:
                    out[key] = float(raw[key])
            if raw.get("max_segments", raw.get("maxSegments")) is not None:
                out["max_segments"] = int(raw.get("max_segments", raw.get("maxSegments")))
        return out
    raise HTTPException(status_code=400, detail="transmissionLosses must be a bool or a config object.")


def parse_branch_outages(raw: Any) -> tuple[tuple[str, str], ...] | None:
    """Normalise a branch-outage list to ``(component, name)`` pairs.

    Accepts plain names (Lines), ``"Transformer:T1"`` and ``{"component", "name"}``.
    ``None``/empty means *every* passive branch (PyPSA's default).
    """
    if not raw:
        return None
    out: list[tuple[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            comp, name = str(item.get("component") or "Line"), str(item.get("name") or "")
        else:
            text = str(item)
            comp, _, name = text.partition(":") if ":" in text else ("Line", "", text)
        comp = comp.strip().capitalize() if comp.strip().lower() in ("line", "transformer") else comp.strip()
        if name.strip():
            out.append((comp, name.strip()))
    return tuple(dict.fromkeys(out)) or None


def parse_optimise_options(options: dict[str, Any] | None) -> OptimiseOptions:
    """Parse and validate the P19-P26 run options (see module docstring).

    Raises:
        HTTPException: 400 on an unknown / uninstalled solver, a bad cycle-basis
            method or malformed loss config.
    """
    options = options or {}
    solver = str(options.get("solverName") or DEFAULT_SOLVER).strip().lower()
    installed = available_solvers()
    if solver not in installed:
        raise HTTPException(
            status_code=400,
            detail=f"Solver {solver!r} is not installed here. Installed: {', '.join(installed)}.",
        )
    cycle = options.get("cycleBasisMethod")
    if cycle:
        cycle = str(cycle).strip().lower()
        if cycle not in CYCLE_BASIS_METHODS:
            raise HTTPException(
                status_code=400,
                detail=f"cycleBasisMethod must be one of {CYCLE_BASIS_METHODS}, got {cycle!r}.",
            )
    big_m = options.get("committableBigM")
    if big_m is not None:
        big_m = float(big_m)
        if not big_m > 0:
            raise HTTPException(status_code=400, detail="committableBigM must be > 0.")
    thresholds = options.get("meshedThresholds")
    risk = options.get("riskPreference") or {}
    alpha = omega = None
    if risk and risk.get("alpha") is not None:
        alpha = float(risk["alpha"])
        omega = float(risk.get("omega", 0.5))
        if not 0.0 < alpha < 1.0 or not 0.0 <= omega <= 1.0:
            raise HTTPException(
                status_code=400, detail="riskPreference needs 0 < alpha < 1 and 0 <= omega <= 1."
            )
    iterative = options.get("iterativeExpansion") or {}
    nlpf = options.get("nonLinearPowerFlowAfterOptimise") or {}
    sclopf = options.get("securityConstrainedConfig") or {}
    two_stage = options.get("twoStage") or {}
    return OptimiseOptions(
        solver_name=solver,
        extra_solver_options=dict(options.get("solverOptions") or {}),
        transmission_losses=_parse_losses(options.get("transmissionLosses")),
        # Force-LP IS PyPSA's linearized unit commitment: nothing in the model is cleared for it.
        linearized_unit_commitment=_as_bool(options.get("linearizedUnitCommitment")) or _as_bool(options.get("forceLp")),
        committable_big_m=big_m,
        cycle_basis_method=cycle or None,
        meshed_thresholds=tuple(int(t) for t in thresholds) if thresholds else None,
        compute_infeasibilities=_as_bool(options.get("computeInfeasibilities")),
        model_kwargs=dict(options.get("modelKwargs") or {}),
        log_to_console=None if options.get("logToConsole") is None else _as_bool(options["logToConsole"]),
        risk_alpha=alpha,
        risk_omega=omega,
        iterative_expansion=dict(iterative) if _as_bool(iterative.get("enabled")) else None,
        branch_outages=parse_branch_outages(sclopf.get("branchOutages")),
        nonlinear_pf=dict(nlpf) if _as_bool(nlpf.get("enabled")) else None,
        piecewise_options=parse_piecewise_options(options.get("piecewiseOptions")),
        two_stage=_as_bool(two_stage.get("enabled")) if isinstance(two_stage, dict) else _as_bool(two_stage),
    )


def merge_solver_options(
    base: dict[str, Any], opts: OptimiseOptions, options: dict[str, Any]
) -> dict[str, Any]:
    """Solver options for ``opts.solver_name``.

    The HiGHS translation (``threads``/``solver``/``user_objective_scale``) only
    applies to HiGHS; for any other solver just the thread count is mapped to
    that solver's own key. ``solverOptions`` always wins.
    """
    if opts.solver_name == "highs":
        merged = dict(base)
    else:
        merged = {}
        key = (_SOLVER_CATALOG.get(opts.solver_name) or {}).get("threads_key")
        threads = options.get("solverThreads", 0)
        if key and isinstance(threads, (int, float)) and int(threads) > 0:
            merged[key] = int(threads)
    merged.update(opts.extra_solver_options)
    return merged


def supported_kwargs(func: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Drop ``kwargs`` the callable does not name (it has no ``**kwargs`` sink we trust)."""
    params = inspect.signature(func).parameters
    return {k: v for k, v in kwargs.items() if k in params}


def apply_risk_preference(network: Any, opts: OptimiseOptions) -> str | None:
    """Set CVaR risk preference on a stochastic network; returns a note.

    Raises:
        HTTPException: 400 if the network has no scenarios (CVaR needs them).
    """
    if opts.risk_alpha is None:
        return None
    if not getattr(network, "has_scenarios", False):
        raise HTTPException(
            status_code=400,
            detail="riskPreference needs stochastic mode (at least two weighted scenarios).",
        )
    network.set_risk_preference(alpha=opts.risk_alpha, omega=opts.risk_omega if opts.risk_omega is not None else 0.5)
    return (
        f"CVaR risk preference applied: alpha={opts.risk_alpha:g}, omega={opts.risk_omega if opts.risk_omega is not None else 0.5:g}."
    )


def build_branch_outages(network: Any, opts: OptimiseOptions) -> Any:
    """``branch_outages`` argument for ``optimize_security_constrained`` (None = all).

    Raises:
        HTTPException: 400 when a named branch is not a passive branch of the network.
    """
    import pandas as pd

    if not opts.branch_outages:
        return None
    passive = network.passive_branches().index
    if getattr(network, "has_scenarios", False) and "scenario" in (passive.names or []):
        passive = passive.droplevel("scenario").unique()
    known = set(passive)
    missing = [f"{c}:{n}" for c, n in opts.branch_outages if (c, n) not in known]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"branchOutages names passive branches not in the network: {', '.join(missing)}.",
        )
    return pd.MultiIndex.from_tuples(list(opts.branch_outages))


def iis_text(network: Any, opts: OptimiseOptions) -> str:
    """Solver IIS report for an infeasible solve, or ``""``.

    Only solvers that support it (Gurobi, Xpress) produce one; HiGHS and others
    fall through to Ragnarok's own diagnostics (``diagnose_infeasibility``).
    """
    if not opts.compute_infeasibilities:
        return ""
    if not (_SOLVER_CATALOG.get(opts.solver_name) or {}).get("iis"):
        return ""
    try:
        return str(network.model.format_infeasibilities())
    except Exception as exc:  # noqa: BLE001 - IIS is advisory
        return f"(IIS unavailable: {exc})"
