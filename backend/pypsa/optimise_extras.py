"""Executors for the PyPSA 1.4 optimise extras (P22, P25, P26).

Companion to :mod:`backend.pypsa.optimise_options` (which only *parses*): these
functions act on a built ``pypsa.Network``.

* :func:`run_iterative_expansion`   - ``optimize_transmission_expansion_iteratively`` (P22)
* :func:`run_ac_feasibility`        - LOPF dispatch -> non-linear PF on a copy (P25)
* :func:`run_two_stage`             - LP sizing, ``fix_optimal_capacities``, dispatch re-solve (P26)
* :func:`export_lp_file`            - ``create_model`` + ``Model.to_file`` (P26)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd
import pypsa

from .optimise_options import OptimiseOptions

_log = logging.getLogger("pypsa.solver")

# PyPSA nominal-capacity attribute per extendable component (``nominal_attrs``).
_NOM_ATTRS: dict[str, str] = {
    "generators": "p_nom",
    "links": "p_nom",
    "stores": "e_nom",
    "storage_units": "p_nom",
    "lines": "s_nom",
    "transformers": "s_nom",
    "processes": "p_nom",
}


def run_iterative_expansion(
    network: pypsa.Network, opts: OptimiseOptions, **optimize_kwargs: Any
) -> tuple[str, str, str]:
    """Run ``optimize_transmission_expansion_iteratively`` with the parsed config.

    Line reactances are re-scaled after each LP so the expanded lines carry the
    flows their new impedance implies; iteration stops when the mean-square change
    of ``s_nom_opt`` is under ``msqThreshold`` (PyPSA 1.4 also fixed a
    zero-reactance crash here).

    Returns:
        ``(status, condition, note)``.
    """
    cfg = opts.iterative_expansion or {}
    kwargs: dict[str, Any] = {
        "msq_threshold": float(cfg.get("msqThreshold", 0.05)),
        "min_iterations": int(cfg.get("minIterations", 1)),
        "max_iterations": int(cfg.get("maxIterations", 10)),
        "fractional_last_unit_size": bool(cfg.get("fractionalLastUnitSize", False)),
    }
    if cfg.get("lineUnitSize"):
        kwargs["line_unit_size"] = float(cfg["lineUnitSize"])
    if cfg.get("lineThreshold") is not None:
        kwargs["line_threshold"] = float(cfg["lineThreshold"])
    if cfg.get("linkUnitSize"):
        kwargs["link_unit_size"] = {str(k): float(v) for k, v in cfg["linkUnitSize"].items()}
    if cfg.get("linkThreshold"):
        kwargs["link_threshold"] = {str(k): float(v) for k, v in cfg["linkThreshold"].items()}
    status, condition = network.optimize.optimize_transmission_expansion_iteratively(
        **kwargs, **optimize_kwargs
    )
    iterations = getattr(network, "iteration", None)
    note = (
        "Iterative transmission expansion: "
        f"{iterations if iterations is not None else '?'} iteration(s), "
        f"msq_threshold={kwargs['msq_threshold']:g}, max_iterations={kwargs['max_iterations']}"
        + (f", line unit {kwargs['line_unit_size']:g} MVA" if "line_unit_size" in kwargs else "")
        + "."
    )
    return str(status), str(condition), note


def _detach_model(network: pypsa.Network) -> None:
    """``network.copy()`` refuses while a solver model is attached; release it."""
    try:
        if network.model is not None:
            network.model.solver_model = None
    except Exception:  # noqa: BLE001 - copy() reports if this was not enough
        pass


def run_ac_feasibility(network: pypsa.Network, cfg: dict[str, Any]) -> dict[str, Any]:
    """AC feasibility check of a solved LOPF dispatch (P25).

    Mirrors the second half of PyPSA's ``optimize_and_run_non_linear_powerflow``
    on a *copy* of the solved network, so the reported optimum is untouched:
    dispatch ``p`` becomes ``p_set``, one generator per sub-network is the slack
    (the rest PV, the first other one PQ so the Jacobian is regular) and
    ``n.pf()`` runs for every snapshot.

    Args:
        network: solved network (its solver model is detached).
        cfg: ``{distributeSlack, slackWeights, xTol, useSeed, skipPre}``.

    Returns:
        ``{converged, iterations, maxMismatch, voltageMin, voltageMax,
        peakLineLoadingPct, lossesMwh, slackShiftMwh, distributeSlack}``, or
        ``{converged: False, error}`` if PyPSA raised.
    """
    _detach_model(network)
    work = network.copy()
    try:
        for comp in work.one_port_components | {"Process", "Link"}:
            c = work.c[comp]
            if not c.dynamic["p"].empty:
                c.dynamic["p_set"] = c.dynamic["p"].copy()
        gens = work.c.generators.static
        gens["control"] = "PV"
        for sub in work.c.sub_networks.static.obj:
            gens.loc[sub.slack_generator, "control"] = "Slack"
        for sub in work.c.sub_networks.static.obj:
            members = sub.c.generators.static.index
            others = members.difference([sub.slack_generator])
            if not others.empty:
                gens.loc[others[0], "control"] = "PQ"
        res = work.pf(
            skip_pre=bool(cfg.get("skipPre", False)),
            x_tol=float(cfg.get("xTol", 1e-6)),
            use_seed=bool(cfg.get("useSeed", False)),
            distribute_slack=bool(cfg.get("distributeSlack", False)),
            slack_weights=str(cfg.get("slackWeights", "p_set")),
        )
    except Exception as exc:  # noqa: BLE001 - report, do not fail the run
        _log.warning("AC feasibility check failed: %s", exc)
        return {"converged": False, "error": str(exc)}

    weights = work.snapshot_weightings["generators"].reindex(work.snapshots).fillna(1.0)
    converged = bool(res.converged.to_numpy().all()) if getattr(res, "converged", None) is not None else True
    vmag = work.buses_t.v_mag_pu
    loss = pd.Series(0.0, index=work.snapshots)
    peak = 0.0
    for comp, t in (("lines", work.lines_t), ("transformers", work.transformers_t)):
        if not t.p0.empty:
            loss = loss + (t.p0 + t.p1).sum(axis=1)
            s_nom = getattr(work, comp)["s_nom"].clip(lower=1.0)
            peak = max(peak, float((t.p0.abs() / s_nom).max().max() * 100.0))
    gen_lopf = network.generators_t.p.mul(weights, axis=0).sum().sum() if not network.generators_t.p.empty else 0.0
    gen_pf = work.generators_t.p.mul(weights, axis=0).sum().sum() if not work.generators_t.p.empty else 0.0
    return {
        "converged": converged,
        "iterations": int(res.n_iter.to_numpy().max()) if getattr(res, "n_iter", None) is not None else 0,
        "maxMismatch": float(res.error.to_numpy().max()) if getattr(res, "error", None) is not None else 0.0,
        "voltageMin": round(float(vmag.min().min()), 4) if not vmag.empty else None,
        "voltageMax": round(float(vmag.max().max()), 4) if not vmag.empty else None,
        "peakLineLoadingPct": round(peak, 1),
        "lossesMwh": round(float((loss * weights).sum()), 3),
        "slackShiftMwh": round(float(gen_pf - gen_lopf), 3),
        "distributeSlack": bool(cfg.get("distributeSlack", False)),
    }


def _capacity_state(network: pypsa.Network) -> dict[tuple[str, str], pd.DataFrame]:
    state: dict[tuple[str, str], pd.DataFrame] = {}
    for comp, attr in _NOM_ATTRS.items():
        df = getattr(network, comp, None)
        if df is None or df.empty or f"{attr}_extendable" not in df.columns:
            continue
        state[(comp, attr)] = df[[attr, f"{attr}_extendable"]].copy()
    return state


def run_two_stage(
    network: pypsa.Network,
    opts: OptimiseOptions,
    *,
    stage_kwargs: dict[str, Any],
) -> tuple[str, str, str]:
    """Two-stage solve: size capacities on the LP relaxation, then dispatch (P26).

    Stage 1 solves with ``linearized_unit_commitment=True`` (capacity sizing
    without binaries); ``fix_optimal_capacities`` pins ``*_nom = *_nom_opt``;
    stage 2 re-solves dispatch (with the user's own unit-commitment setting, so a
    committable fleet is dispatched as a MILP on fixed capacities) and refreshes
    the duals. Extendable flags and the original nominal values are restored
    afterwards so expansion reporting (``*_nom_opt`` vs ``*_nom``) stays correct.

    Returns:
        ``(status, condition, note)`` of the *second* stage.
    """
    before = _capacity_state(network)
    stage1 = dict(stage_kwargs)
    stage1["linearized_unit_commitment"] = True
    status, condition = network.optimize(**stage1)
    if str(status) != "ok":
        return str(status), str(condition), "Two-stage: stage 1 (capacity sizing) did not solve."
    network.optimize.fix_optimal_capacities()
    status, condition = network.optimize(**stage_kwargs)
    # Restore flags/nominal values; *_nom_opt keeps the stage-1 sizes.
    for (comp, attr), frame in before.items():
        df = getattr(network, comp)
        df[attr] = frame[attr]
        df[f"{attr}_extendable"] = frame[f"{attr}_extendable"]
    n_fixed = int(sum(int(f[f"{a}_extendable"].sum()) for (_, a), f in before.items()))
    note = (
        f"Two-stage solve: stage 1 sized {n_fixed} extendable asset(s) on the LP relaxation, "
        "stage 2 re-solved dispatch with capacities fixed (fix_optimal_capacities)."
    )
    return str(status), str(condition), note


def export_lp_file(
    network: pypsa.Network,
    path: Path,
    opts: OptimiseOptions,
    *,
    multi_investment_periods: bool = False,
) -> dict[str, Any]:
    """Write the LP of ``network`` to ``path`` (``.lp`` / ``.mps``) without solving.

    Uses the split API (``create_model`` then ``Model.to_file``) so the file is
    exactly the problem ``n.optimize`` would hand to the solver, including the
    parsed model-building options (losses, linearised UC, ...).

    Returns:
        ``{path, bytes, variables, constraints, nonzeros?}``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    kwargs = opts.optimize_kwargs()
    kwargs.pop("log_to_console", None)  # not a create_model argument
    m = network.optimize.create_model(
        multi_investment_periods=multi_investment_periods,
        include_objective_constant=False,
        **kwargs,
    )
    from ..app import carbon_pricing

    carbon_pricing.extra_functionality(network, network.snapshots)  # the module's objective term is part of the problem
    m.to_file(path, io_api="lp" if path.suffix.lower() == ".lp" else None)
    return {
        "path": str(path),
        "bytes": int(path.stat().st_size),
        "variables": int(m.nvars),
        "constraints": int(m.ncons),
    }


__all__ = [
    "export_lp_file",
    "run_ac_feasibility",
    "run_iterative_expansion",
    "run_two_stage",
]
