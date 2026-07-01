from __future__ import annotations

import functools
import logging
import math
import time
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException

from ..constants import carrier_color
from ..network import build_network
from ..pathway import parse_pathway_config
from ..rolling import parse_rolling_config
from ..sampling import parse_sampling_config, sample_block_indices
from ..stochastic import (
    collapse_to_representative_scenario,
    parse_stochastic_config,
    per_scenario_summaries,
)
from ..utils.emissions import per_generator_emission_factor
from ..utils.series import weighted_sum
from ..network.custom_constraints import apply_custom_constraints
from ..network.constraint_dsl import apply_constraint_specs, apply_dsl_constraints
from .dispatch import (
    build_curtailment_series,
    build_dispatch_series,
    build_price_emissions_series,
    build_storage_series,
    build_storage_soc_series,
    dispatch_by_carrier,
)
from .emissions import build_emissions_breakdown
from .statistics import build_statistics
from .mga import build_mga
from .merchant import build_merchant
from .company import build_company_breakdown
from .finance import build_company_finance
from .price_formation import build_price_formation
from .commitment import build_commitment
from .bid_strategy import build_bid_strategy
from .optimal_bid import build_optimal_bid
from .asset_swap import build_asset_swap
from .ess import build_ess_business_case
from .ppa import build_ppa
from .expansion import build_expansion_results
from .full_outputs import build_full_outputs
from .market import (
    build_applied_constraints,
    build_co2_shadow,
    build_generator_economics,
    build_merit_order,
)
from .summaries import _rolling_window_summaries, _pathway_period_summaries
from .power_flow import run_power_flow
from .contingency import run_contingency

# Solve-phase timing and notes are logged here. With the run worker no longer
# redirecting file descriptors, these INFO lines stream to the launching
# terminal alongside HiGHS' own verbose output.
_log = logging.getLogger("pypsa.solver")


def _coerce_solve_status(result: Any) -> tuple[str, str]:
    """Normalize PyPSA optimise() return into (status, condition).

    PyPSA's modern optimise path returns a 2-tuple ``(status, condition)`` where
    condition is 'optimal' on success. Older / SCLOPF paths sometimes return
    the network or None; treat those as 'ok'/'optimal' since they would have
    raised on failure.
    """
    if isinstance(result, tuple) and len(result) >= 2:
        status = str(result[0]) if result[0] is not None else "unknown"
        condition = str(result[1]) if result[1] is not None else "unknown"
        return status, condition
    return "ok", "optimal"


def _solve_rejected(status: str, condition: str, *, strict: bool) -> bool:
    """Whether a finished solve must be rejected, per the acceptance setting.

    ``condition='optimal'`` always passes. In **strict** mode nothing else
    does — the user wants vertex-optimal solutions with exact duals only.
    In **lenient** mode (the default) a solve also passes when linopy accepted
    and parsed the solution (status ok/warning) and the condition is not a
    definite failure: interior-point methods (IPM/HiPO/PDLP) often finish
    without crossover, so HiGHS emits no 'optimal' termination string and the
    condition reads 'unknown' even though the solution is valid.
    """
    if condition == "optimal":
        return False
    if strict:
        return True
    if condition in ("infeasible", "unbounded", "infeasible_or_unbounded"):
        return True
    return status.lower() not in ("ok", "warning")


# HiGHS LP methods the user may pin. Anything else (incl. "auto"/"choose"/
# "highs"/"") leaves the method unset so HiGHS chooses — identical to a bare
# ``n.optimize(solver_name="highs")`` and the fast default.
_HIGHS_METHODS = ("simplex", "ipm", "pdlp")


@functools.lru_cache(maxsize=1)
def _highs_has_hipo() -> bool:
    """Whether the installed HiGHS was compiled with the HiPO solver.

    HiPO (a factorisation-based interior-point solver, HiGHS ≥ 1.12, built with
    ``-DHIPO=ON``) is excellent on large energy-system LPs but ships only in
    special builds — the stock pip/conda ``highspy`` rejects ``solver="hipo"``
    with ``kError``. We probe once so HiPO stays an *opt-in capability*: a
    machine that has it can pick it; every machine that doesn't falls back and
    is unaffected.
    """
    try:
        import highspy

        h = highspy.Highs()
        h.setOptionValue("output_flag", False)
        return h.setOptionValue("solver", "hipo") == highspy.HighsStatus.kOk
    except Exception:
        return False

# How linopy hands the built problem to HiGHS. linopy's default ("lp") writes
# the whole problem to an LP *text file* and HiGHS parses it back — the
# "Writing time" stage plus a load step whose cost explodes super-linearly with
# problem size (a full-year network never reaches presolve: HiGHS prints its
# banner, then spends minutes parsing the multi-million-row LP file / thrashing
# memory before "LP ... has N rows" ever appears). "direct" passes the model
# in-memory via highspy (a hard HiGHS/PyPSA dependency, always present here),
# skipping both the file write and the parse. Same solution, dramatically less
# overhead on large models — this is the I/O cost, not the optimisation.
_SOLVER_IO_API = "direct"


def _build_solver_options(options: dict[str, Any]) -> dict[str, Any]:
    """Translate run options into HiGHS ``solver_options``.

    ``solverThreads`` > 0 pins the thread count (0 = all cores → unset).
    ``solverType`` pins a HiGHS LP method only when it's an explicit method;
    the default ``"auto"`` omits ``solver`` so HiGHS picks the fastest path.
    """
    out: dict[str, Any] = {}
    threads = options.get("solverThreads", 0)
    if isinstance(threads, (int, float)) and int(threads) > 0:
        out["threads"] = int(threads)
    solver_type = str(options.get("solverType", "auto")).lower()
    if solver_type == "hipo":
        # Use HiPO where the build has it; otherwise fall back to IPM (the next
        # interior-point method) so a machine without HiPO never errors.
        out["solver"] = "hipo" if _highs_has_hipo() else "ipm"
    elif solver_type in _HIGHS_METHODS:
        out["solver"] = solver_type
    # Objective auto-scaling. Energy-system LPs often carry a wide cost range
    # (e.g. marginal costs spanning 1e2–1e6), which HiGHS itself flags
    # ("excessively large costs … consider setting user_objective_scale to -1")
    # and which slows BOTH dual simplex and PDLP. ``user_objective_scale = -1``
    # lets HiGHS pick a power-of-10 objective scale: it is results-neutral (the
    # reported objective is unscaled) and a no-op when the objective is already
    # well-scaled. Driven by the "Auto-scale objective" solver toggle. Absent
    # key ⇒ off, so a bare ``options={}`` solve stays identical to a plain
    # ``n.optimize(solver_name="highs")``; the UI sends it on by default.
    if bool(options.get("objectiveAutoScale", False)):
        out["user_objective_scale"] = -1
    return out


def run_pypsa(
    model: dict[str, list[dict[str, Any]]],
    scenario: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the network from the JSON workbook model, optimise, return results."""
    options = options or {}
    pathway = parse_pathway_config(options.get("pathwayConfig"))
    rolling = parse_rolling_config(options.get("rollingConfig"))
    stochastic = parse_stochastic_config(options.get("stochasticConfig"))
    sampling = parse_sampling_config(options.get("samplingConfig"))
    sclopf_cfg = options.get("securityConstrainedConfig") or {}
    sclopf_enabled = bool(sclopf_cfg.get("enabled", False))
    powerflow_cfg = options.get("powerFlowConfig") or {}
    pf_enabled = bool(powerflow_cfg.get("enabled", False))
    pf_linear = bool(powerflow_cfg.get("linear", False))
    contingency_cfg = options.get("contingencyConfig") or {}
    contingency_enabled = bool(contingency_cfg.get("enabled", False))
    mga_cfg = options.get("mgaConfig") or {}
    mga_enabled = bool(mga_cfg.get("enabled", False))
    merchant_cfg = options.get("merchantConfig") or {}
    merchant_enabled = bool(merchant_cfg.get("enabled", False))
    bid_cfg = options.get("bidStrategyConfig") or {}
    bid_enabled = bool(bid_cfg.get("enabled", False))
    bid_mode = str(bid_cfg.get("mode", "fixed") or "fixed")
    swap_cfg = options.get("assetSwapConfig") or {}
    swap_enabled = bool(swap_cfg.get("enabled", False))
    ess_cfg = options.get("essConfig") or {}
    ess_enabled = bool(ess_cfg.get("enabled", False))
    ppa_cfg = options.get("ppaConfig") or {}
    ppa_enabled = bool(ppa_cfg.get("enabled", False))
    # The owner/company column (F1 + B1) is a shared, top-level concern. Fall
    # back to the legacy merchantConfig.ownerColumn for scenarios saved before
    # it was promoted out of the merchant config.
    owner_column = str(
        options.get("ownerColumn") or merchant_cfg.get("ownerColumn") or "owner"
    )
    if stochastic.enabled and rolling.enabled:
        raise HTTPException(
            status_code=400,
            detail="Stochastic mode and rolling horizon cannot be combined.",
        )
    if sampling.enabled and pathway.enabled:
        raise HTTPException(
            status_code=400,
            detail="Sampled snapshot blocks cannot be combined with multi-investment pathway mode.",
        )
    if sampling.enabled and rolling.enabled:
        raise HTTPException(
            status_code=400,
            detail="Sampled snapshot blocks cannot be combined with rolling horizon.",
        )
    if sclopf_enabled and (rolling.enabled or stochastic.enabled):
        raise HTTPException(
            status_code=400,
            detail="Security-constrained (SCLOPF) cannot be combined with rolling horizon or stochastic mode.",
        )
    if sclopf_enabled and pathway.enabled:
        raise HTTPException(
            status_code=400,
            detail="Security-constrained (SCLOPF) cannot be combined with multi-investment pathway mode.",
        )
    if pf_enabled and (
        rolling.enabled or stochastic.enabled or sclopf_enabled or pathway.enabled or sampling.enabled
    ):
        raise HTTPException(
            status_code=400,
            detail="Power-flow study mode cannot be combined with rolling horizon, stochastic, "
            "security-constrained, multi-investment pathway, or sampled-block modes.",
        )
    if contingency_enabled and (
        rolling.enabled or stochastic.enabled or sclopf_enabled or pathway.enabled
        or sampling.enabled or pf_enabled
    ):
        raise HTTPException(
            status_code=400,
            detail="N-1 contingency analysis cannot be combined with rolling horizon, stochastic, "
            "security-constrained, multi-investment pathway, sampled-block, or power-flow modes.",
        )
    # MGA layers on top of a full optimise (it needs the optimum to set the cost
    # budget), so it is incompatible with the modes that change *how* the LP is
    # solved or that skip the LP entirely. It may combine with multi-investment
    # pathway runs (optimize_mga takes multi_investment_periods).
    if mga_enabled and (
        rolling.enabled or stochastic.enabled or sclopf_enabled
        or sampling.enabled or pf_enabled or contingency_enabled
    ):
        raise HTTPException(
            status_code=400,
            detail="MGA near-optimal exploration cannot be combined with rolling horizon, stochastic, "
            "security-constrained, sampled-block, power-flow, or contingency modes.",
        )
    # Merchant mode needs the stage-1 optimum's LMPs, so it layers on the normal
    # optimise like MGA and is incompatible with the modes that skip or reshape
    # that solve. (Pathway is allowed; a series price source bypasses the LMP.)
    if merchant_enabled and (
        rolling.enabled or stochastic.enabled or sclopf_enabled
        or sampling.enabled or pf_enabled or contingency_enabled
    ):
        raise HTTPException(
            status_code=400,
            detail="Merchant (price-taker) analysis cannot be combined with rolling horizon, stochastic, "
            "security-constrained, sampled-block, power-flow, or contingency modes.",
        )
    # Bid-strategy re-clears the full market with modified offers, so like
    # merchant it needs the plain optimise path.
    if bid_enabled and (
        rolling.enabled or stochastic.enabled or sclopf_enabled
        or sampling.enabled or pf_enabled or contingency_enabled
    ):
        raise HTTPException(
            status_code=400,
            detail="Bid-strategy simulation cannot be combined with rolling horizon, stochastic, "
            "security-constrained, sampled-block, power-flow, or contingency modes.",
        )
    # Asset-swap re-solves the whole system with a carrier swapped, so it needs
    # the plain optimise path (a cost/emissions LP solution to diff against).
    if swap_enabled and (
        rolling.enabled or stochastic.enabled or sclopf_enabled
        or sampling.enabled or pf_enabled or contingency_enabled
    ):
        raise HTTPException(
            status_code=400,
            detail="Asset-swap what-if cannot be combined with rolling horizon, stochastic, "
            "security-constrained, sampled-block, power-flow, or contingency modes.",
        )
    # ESS business case prices arbitrage against the base LMP, so it needs the
    # plain optimise path (marginal prices to arbitrage against).
    if ess_enabled and (
        rolling.enabled or stochastic.enabled or sclopf_enabled
        or sampling.enabled or pf_enabled or contingency_enabled
    ):
        raise HTTPException(
            status_code=400,
            detail="ESS business case cannot be combined with rolling horizon, stochastic, "
            "security-constrained, sampled-block, power-flow, or contingency modes.",
        )

    # The Ragnarok backend is plugin-agnostic: it only ever receives a model,
    # scenario and options and solves them. Plugins live entirely on the
    # frontend side (they contribute rows/constraints to the model before it is
    # sent here), so there is no plugin hook in this pipeline.
    _t_build = time.perf_counter()
    network, notes = build_network(model, scenario, options)
    _log.info(
        "network built in %.2fs — %d snapshots, %d buses, %d generators",
        time.perf_counter() - _t_build,
        len(network.snapshots),
        len(network.buses),
        len(network.generators),
    )

    snapshot_count = len(network.snapshots)
    snapshot_weight = float(network.snapshot_weightings["objective"].iloc[0]) if snapshot_count else 1.0

    # Power-flow study mode (pf/lpf) solves network physics, not an LP — none of
    # the cost/price/economics extraction below applies, so delegate to the
    # focused power-flow path and return its payload directly.
    if pf_enabled:
        return run_power_flow(
            network,
            linear=pf_linear,
            currency=str(options.get("currencySymbol", "$")),
            snapshot_count=snapshot_count,
            snapshot_weight=snapshot_weight,
            notes=notes,
        )
    if contingency_enabled:
        return run_contingency(
            network,
            currency=str(options.get("currencySymbol", "$")),
            snapshot_count=snapshot_count,
            snapshot_weight=snapshot_weight,
            notes=notes,
        )

    # CO₂ emission factors are a static carrier property, shared across
    # scenarios. Strip any scenario level from the MultiIndex so emission
    # totals key by carrier name only.
    if "co2_emissions" in network.carriers.columns:
        _carriers_ef = network.carriers["co2_emissions"]
        if isinstance(_carriers_ef.index, pd.MultiIndex) and "name" in _carriers_ef.index.names:
            _carriers_ef = _carriers_ef.groupby(level="name").first()
        emissions_factors: dict[str, float] = _carriers_ef.to_dict()
    else:
        emissions_factors = {}

    custom_constraints: list[dict] = scenario.get("constraints") or []
    # Advanced constraints arrive as a structured JSON spec from the frontend
    # (constraintSpecs). Older payloads may still send the raw DSL text; accept
    # both, preferring the JSON spec.
    constraint_specs: list[dict] = scenario.get("constraintSpecs") or []
    custom_dsl_text: str = str(scenario.get("customDsl") or "")

    def extra_functionality(n, snapshots):
        # `snapshots` is the window being optimised — for rolling horizon it is a
        # single window, not the full run. Pass it through so weights/hours and
        # apportioned budgets are scoped to that window (a no-op single-shot).
        apply_custom_constraints(n, custom_constraints, emissions_factors, notes, snapshots)
        if constraint_specs:
            apply_constraint_specs(n, constraint_specs, emissions_factors, notes, snapshots)
        elif custom_dsl_text:
            apply_dsl_constraints(n, custom_dsl_text, emissions_factors, notes, snapshots)


    # Currency symbol for formatted output strings
    currency = str(options.get("currencySymbol", "$"))

    # Read solver performance options from run payload. HiGHS is always the
    # solver (solver_name="highs"); solverType picks the method within HiGHS and
    # the default "auto" leaves it to HiGHS (the fast path, == a bare optimize).
    solver_options = _build_solver_options(options)

    rolling_windows: list[dict[str, Any]] = []
    solve_status: str = "unknown"
    solve_condition: str = "unknown"
    _t_solve = time.perf_counter()
    try:
        if rolling.enabled:
            # Rolling horizon carries storage state between windows via
            # `state_of_charge_initial` (set from the previous window's end).
            # Cyclic SOC (soc_end == soc_start within each window) is INCOMPATIBLE:
            # it ignores the carried state and forces every window — especially the
            # shorter trailing one — to net-zero storage, which is frequently
            # infeasible. PyPSA then silently leaves that window's results at zero,
            # truncating the run. Force non-cyclic so carried state provides
            # continuity across the full horizon.
            if not network.storage_units.empty:
                network.storage_units["cyclic_state_of_charge"] = False
                if "cyclic_state_of_charge_per_period" in network.storage_units.columns:
                    network.storage_units["cyclic_state_of_charge_per_period"] = False
            if not network.stores.empty:
                if "e_cyclic" in network.stores.columns:
                    network.stores["e_cyclic"] = False
                if "e_cyclic_per_period" in network.stores.columns:
                    network.stores["e_cyclic_per_period"] = False
            rolling_windows = _rolling_window_summaries(
                network.snapshots,
                rolling.horizon_snapshots,
                rolling.overlap_snapshots,
            )
            network.optimize.optimize_with_rolling_horizon(
                horizon=rolling.horizon_snapshots,
                overlap=rolling.overlap_snapshots,
                multi_investment_periods=pathway.enabled,
                solver_name="highs",
                solver_options=solver_options if solver_options else {},
                extra_functionality=extra_functionality,
                io_api=_SOLVER_IO_API,
                include_objective_constant=False,  # see note on the single-period call
            )
            # PyPSA's rolling-horizon helper does not return a status; it
            # only logs a warning on bad windows. Treat the run as optimal
            # only if no window violated its bounds in an obvious way.
            solve_status, solve_condition = "ok", "optimal"
        elif sclopf_enabled:
            # SCLOPF: every dispatch decision must remain feasible under the
            # outage of any single passive branch. PyPSA enforces this by
            # adding N-1 line-loading constraints for each branch in
            # `branch_outages` (default: all passive branches in the
            # network).
            result = network.optimize.optimize_security_constrained(
                solver_name="highs",
                solver_options=solver_options if solver_options else {},
                extra_functionality=extra_functionality,
                io_api=_SOLVER_IO_API,
            )
            solve_status, solve_condition = _coerce_solve_status(result)
        else:
            result = network.optimize(
                multi_investment_periods=pathway.enabled,
                solver_name="highs",
                solver_options=solver_options if solver_options else {},
                extra_functionality=extra_functionality,
                io_api=_SOLVER_IO_API,
                # Keep the objective constant out of the LP. It is a fixed
                # offset that does not affect the optimal dispatch/capacities,
                # and this app never reads n.objective (costs are recomputed
                # from solved values), so it changes no reported number — it
                # only improves LP conditioning. Pinned to False to match the
                # PyPSA v2.0 default ahead of time. Not user-configurable: it
                # is a numerical detail, not a modelling choice.
                include_objective_constant=False,
            )
            solve_status, solve_condition = _coerce_solve_status(result)
        _log.info(
            "solve finished in %.2fs — status=%s condition=%s",
            time.perf_counter() - _t_solve,
            solve_status,
            solve_condition,
        )
        # Gate the result per the user's "Solution acceptance" solver setting
        # (see _solve_rejected): Strict demands condition='optimal'; Lenient
        # (default) also accepts linopy-validated solves whose condition is
        # merely 'unknown' (typical for interior-point runs without crossover).
        strict = str(options.get("solveAcceptance", "lenient")).lower() == "strict"
        if _solve_rejected(solve_status, solve_condition, strict=strict):
            strict_hint = (
                " Solution acceptance is set to Strict; this solve was accepted "
                "by the solver toolchain and Lenient mode would keep it — "
                "see Settings → Solver."
                if strict and solve_status.lower() in ("ok", "warning")
                and solve_condition not in ("infeasible", "unbounded", "infeasible_or_unbounded")
                else ""
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Solver did not return a usable solution "
                    f"(status='{solve_status}', condition='{solve_condition}'). "
                    "The model is likely infeasible or ill-conditioned: check for "
                    "placeholder 1e12 / inf values in p_nom_max, e_sum_min, "
                    "e_sum_max, lifetime, or for conflicting constraints (CO₂ cap, "
                    "capacity factor caps) against the available capacity."
                    + strict_hint
                ),
            )
        if solve_condition != "optimal":
            notes.append(
                f"Solver finished with condition='{solve_condition}' but linopy "
                f"accepted the solution (status='{solve_status}'). This is normal "
                "for interior-point methods (IPM/HiPO) that skip crossover; the "
                "result is usable. Switch Solver to 'simplex' or set Solution "
                "acceptance to 'Strict' if you need vertex-optimal solutions "
                "with exact shadow prices."
            )
        # HiPO requested on a build that lacks it → we ran IPM; say so.
        if str(options.get("solverType", "auto")).lower() == "hipo" and not _highs_has_hipo():
            notes.append(
                "HiPO was selected but this HiGHS build doesn't include it — "
                "solved with IPM instead. To enable HiPO, install a HiGHS built "
                "with -DHIPO=ON (and METIS + BLAS)."
            )
        solver_note = "HiGHS"
        if solver_options.get("solver"):
            solver_note += f", {solver_options['solver'].upper()}"
        else:
            solver_note += " (auto method)"
        if solver_options.get("threads"):
            solver_note += f" ({solver_options['threads']} threads)"
        if rolling.enabled:
            notes.append(
                "PyPSA rolling horizon solved with "
                f"{solver_note}: horizon {rolling.horizon_snapshots}, overlap {rolling.overlap_snapshots}, "
                f"{len(rolling_windows)} window(s)."
            )
        elif sclopf_enabled:
            n_passive = (
                len(network.lines) + len(network.transformers)
                if "transformers" in network.components.keys()
                else len(network.lines)
            )
            notes.append(
                f"PyPSA SCLOPF solved with {solver_note}: "
                f"N-1 security against {n_passive} passive branch(es)."
            )
        else:
            notes.append(f"PyPSA optimize() solved with {solver_note}.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PyPSA optimization failed: {exc}") from exc

    # ── Stochastic post-processing ──────────────────────────────────────────
    # After the stochastic solve, every static / dynamic frame is indexed by
    # (scenario, name). Summarise per-scenario totals for the new GUI card,
    # then collapse to the highest-weighted scenario so the existing
    # deterministic result-extraction pipeline keeps working unchanged.
    stochastic_result: dict[str, Any] | None = None
    if stochastic.enabled:
        scenario_summaries = per_scenario_summaries(
            network, stochastic, emissions_factors, currency
        )
        representative_scenario = collapse_to_representative_scenario(network, stochastic)
        stochastic_result = {
            "enabled": True,
            "representativeScenario": representative_scenario,
            "scenarios": scenario_summaries,
        }
        notes.append(
            f"Showing scenario \"{representative_scenario}\" for detailed analytics; "
            "expected values across all scenarios are available in the Stochastic scenarios card."
        )

    # One copy (decouples from the network); both frames below are read-only,
    # so dispatch_frame can alias it when there are no storage units.
    generator_dispatch_frame = network.generators_t.p.copy()
    if hasattr(network, "storage_units_t") and not network.storage_units_t.p.empty:
        dispatch_frame = pd.concat([generator_dispatch_frame, network.storage_units_t.p], axis=1)
    else:
        dispatch_frame = generator_dispatch_frame

    by_carrier = dispatch_by_carrier(generator_dispatch_frame, network.generators)
    load_dispatch = network.loads_t.p_set.sum(axis=1)
    price_series = (
        network.buses_t.marginal_price.mean(axis=1)
        if not network.buses_t.marginal_price.empty
        else pd.Series(0.0, index=network.snapshots)
    )
    shed_cols = [n for n in network.generators.index if n.startswith("load_shedding_")]
    load_shed = dispatch_frame.reindex(columns=shed_cols, fill_value=0.0).sum(axis=1)
    generator_weights = network.snapshot_weightings["generators"].reindex(network.snapshots).fillna(1.0)
    store_weights = network.snapshot_weightings["stores"].reindex(network.snapshots).fillna(1.0)

    # Capacity & energy metrics. Generator vs storage capacity are reported as
    # separate KPIs (installed nameplate p_nom); the combined total still drives
    # the reserve position.
    generator_capacity = float(network.generators.p_nom.sum())
    storage_capacity = float(network.storage_units.p_nom.sum())
    total_capacity = generator_capacity + storage_capacity
    total_load = float(load_dispatch.max())
    reserve_requirement = total_load  # installed capacity vs peak demand

    # Carriers used only by the injected load-shedding backstop are not real
    # generation: exclude them from energy mix and emission totals so shed
    # (unserved) load is never counted as supply or as emissions. emissions.py
    # makes the same exclusion by the ``load_shedding_`` name prefix.
    shed_carriers = set(
        network.generators.loc[
            network.generators.index.str.startswith("load_shedding_"), "carrier"
        ].unique()
    )

    emission_totals: dict[str, float] = defaultdict(float)
    carrier_energy: dict[str, float] = defaultdict(float)
    for carrier, series in by_carrier.items():
        if carrier in shed_carriers:
            continue
        carrier_energy[carrier] += weighted_sum(series.clip(lower=0.0), generator_weights)
    # Emissions on the thermal basis: dispatch × co2_emissions / η (M3), summed
    # per generator then grouped by carrier — η varies by unit, not by carrier,
    # so it can't be applied to the carrier-summed dispatch.
    eff_ef = per_generator_emission_factor(network, emissions_factors)
    for name in generator_dispatch_frame.columns:
        if str(name).startswith("load_shedding_"):
            continue
        factor = float(eff_ef.get(name, 0.0))
        if not factor:
            continue
        carrier = str(network.generators.at[name, "carrier"])
        if carrier in shed_carriers:
            continue
        emission_totals[carrier] += weighted_sum(
            generator_dispatch_frame[name].clip(lower=0.0) * factor, generator_weights
        )

    carrier_mix = [
        {"label": c, "value": v, "color": carrier_color(network, c)}
        for c, v in sorted(carrier_energy.items(), key=lambda x: x[1], reverse=True)
        if v > 0.0
    ]

    # Per-generator dispatched energy (MWh, snapshot-weighted). This is the small
    # aggregate the "Dispatch by unit" donut renders, so the heavy per-snapshot
    # generator series never has to reach the browser — it stays server-side and
    # is fetched windowed only when a time-series chart is opened.
    generator_carriers = network.generators["carrier"].to_dict()
    # Generators with time-varying p_max_pu (renewables) are the only ones for
    # which curtailment is meaningful; thermal units at static p_max_pu=1 are
    # not "curtailed" when running at partial load.
    # p_nom_opt where solved (>0), else input p_nom — p_nom_opt exists with a
    # 0.0 default for non-extendable generators on some pypsa versions.
    _p_nom_in = network.generators["p_nom"].fillna(0.0)
    if "p_nom_opt" in network.generators.columns:
        _p_nom_opt = network.generators["p_nom_opt"].fillna(0.0)
        p_nom_opt_s = _p_nom_opt.where(_p_nom_opt > 0, _p_nom_in)
    else:
        p_nom_opt_s = _p_nom_in
    tv_p_max_pu_cols = set(network.generators_t.p_max_pu.columns)
    generator_energy = []
    for gen in generator_dispatch_frame.columns:
        if str(gen).startswith("load_shedding_"):
            continue
        energy = weighted_sum(generator_dispatch_frame[gen].clip(lower=0.0), generator_weights)
        if energy > 0.0:
            carrier = str(generator_carriers.get(gen, ""))
            curtailment_mwh: float | None = None
            if gen in tv_p_max_pu_cols:
                p_nom_opt = float(p_nom_opt_s.get(gen, 0.0))
                avail_s = (network.generators_t.p_max_pu[gen] * p_nom_opt).clip(lower=0.0)
                curtailment_mwh = float(
                    weighted_sum(
                        (avail_s - generator_dispatch_frame[gen].clip(lower=0.0)).clip(lower=0.0),
                        generator_weights,
                    )
                )
            generator_energy.append(
                {
                    "name": str(gen),
                    "value": float(energy),
                    "carrier": carrier,
                    "color": carrier_color(network, carrier),
                    "curtailmentMwh": curtailment_mwh,
                }
            )
    generator_energy.sort(key=lambda row: row["value"], reverse=True)

    # Cost breakdown. Use the effective per-snapshot marginal cost
    # (``get_switchable_as_dense`` resolves static vs time-varying inputs) so
    # the fuel/carbon split is correct even when a generator's marginal_cost is
    # supplied as a time series. The carbon adder (carbon_price * emission
    # factor) was folded into marginal_cost by build_network, so we back it out
    # per snapshot to report the fuel component separately.
    fuel_cost = 0.0
    carbon_cost = 0.0
    shed_cost = 0.0
    carbon_c = float(scenario.get("carbonPrice", 0.0))
    mc_dense = network.get_switchable_as_dense("Generator", "marginal_cost")
    for name in network.generators.index:
        if name not in generator_dispatch_frame.columns:
            continue
        # ef is the per-generator electrical-basis factor (co2 / η) — the SAME
        # quantity carbon_price folded into marginal_cost, so backing it out here
        # recovers the fuel component exactly (M3).
        ef = float(eff_ef.get(name, 0.0))
        dispatch_pos = generator_dispatch_frame[name].clip(lower=0.0)
        mc_s = mc_dense[name]
        if name.startswith("load_shedding_"):
            shed_cost += weighted_sum(dispatch_pos * mc_s, generator_weights)
        else:
            carbon_cost += weighted_sum(dispatch_pos * ef * carbon_c, generator_weights)
            fuel_cost += weighted_sum(dispatch_pos * (mc_s - ef * carbon_c).clip(lower=0.0), generator_weights)

    # Expansion CAPEX (annualised)
    expansion_results = build_expansion_results(network)
    total_capex_annual = sum(r["capex_annual"] for r in expansion_results)

    # Market analysis — merit order + CO₂ shadow price (pure post-processing)
    merit_order = build_merit_order(network)
    co2_shadow = build_co2_shadow(network, float(scenario.get("carbonPrice", 0.0)), currency)
    applied_constraints = build_applied_constraints(network)
    generator_economics = build_generator_economics(network, currency)
    statistics = build_statistics(network)
    emissions_breakdown = build_emissions_breakdown(network, emissions_factors)

    cost_breakdown = [
        {"label": "Fuel cost", "value": round(fuel_cost)},
        {"label": "Carbon cost", "value": round(carbon_cost)},
        {"label": "Load shedding", "value": round(shed_cost)},
    ]
    if total_capex_annual > 0:
        cost_breakdown.append({"label": "Capital cost", "value": round(total_capex_annual)})

    # Per-bus LMP (nodal marginal prices) — one value series per snapshot.
    # Vectorised: the naive per-(snapshot, bus) `mp.at[...]` scalar lookup is
    # O(snapshots × buses) — ~1.7M label lookups for a 1-year, multi-bus run.
    # Round once and `tolist()` the whole array (C-level) instead.
    nodal_price_series: list[dict] = []
    if not network.buses_t.marginal_price.empty:
        mp = network.buses_t.marginal_price.round(2)
        bus_cols = [str(b) for b in mp.columns]
        for ts, vals in zip(mp.index, mp.to_numpy().tolist()):
            nodal_price_series.append({
                "label": str(ts),
                "timestamp": str(ts),
                "values": dict(zip(bus_cols, vals)),
            })

    # Series
    dispatch_s, gen_dispatch_s = build_dispatch_series(network, by_carrier, load_dispatch, generator_dispatch_frame)
    curtailment_s = build_curtailment_series(network, generator_dispatch_frame)
    price_s, emissions_s = build_price_emissions_series(network, by_carrier, price_series, emissions_factors)
    storage_s = build_storage_series(network)
    storage_soc_s = build_storage_soc_series(network)
    pathway_summaries = _pathway_period_summaries(
        network,
        generator_dispatch_frame,
        load_dispatch,
        price_series,
        emissions_factors,
    )

    # Nodal balance
    nodal_balance = []
    for bus in network.buses.index:
        bus_loads = network.loads.index[network.loads.bus == bus]
        load_val = float(network.loads_t.p_set.loc[:, bus_loads].sum(axis=1).mean()) if len(bus_loads) else 0.0
        gen_names = list(network.generators.index[network.generators.bus == bus])
        gen_val = float(dispatch_frame.reindex(columns=gen_names, fill_value=0.0).sum(axis=1).mean()) if gen_names else 0.0
        nodal_balance.append({"label": bus, "load": load_val, "generation": gen_val})
    nodal_balance = sorted(nodal_balance, key=lambda x: x["load"], reverse=True)

    # Line loading
    line_loading = []
    for line in network.lines.index if not network.lines_t.p0.empty else []:
        peak = float((network.lines_t.p0[line].abs() / max(float(network.lines.at[line, "s_nom"]), 1.0) * 100.0).max())
        line_loading.append({"label": line, "value": peak})
    for link in network.links.index if not network.links_t.p0.empty else []:
        peak = float((network.links_t.p0[link].abs() / max(float(network.links.at[link, "p_nom"]), 1.0) * 100.0).max())
        line_loading.append({"label": link, "value": peak})
    for transformer in network.transformers.index:
        if not network.transformers_t.p0.empty:
            peak = float((network.transformers_t.p0[transformer].abs() / max(float(network.transformers.at[transformer, "s_nom"]), 1.0) * 100.0).max())
            line_loading.append({"label": transformer, "value": peak})

    total_emissions = sum(emission_totals.values()) / 1000.0
    average_price = float(price_series.mean())
    peak_net_load = round(float(load_dispatch.max()))

    summary = [
        {"label": "Generator capacity", "value": f"{round(generator_capacity):,} MW", "detail": f"{len(network.generators)} generators (installed nameplate)"},
        {"label": "Storage capacity", "value": f"{round(storage_capacity):,} MW", "detail": f"{len(network.storage_units)} storage units (installed nameplate)"},
        {"label": "Peak demand", "value": f"{round(total_load):,} MW", "detail": "from workbook load profile"},
        {"label": "Generator reserve", "value": f"{round(generator_capacity - reserve_requirement):,} MW", "detail": "generator capacity vs peak demand"},
        {"label": "Storage reserve", "value": f"{round(storage_capacity - reserve_requirement):,} MW", "detail": "storage capacity vs peak demand"},
        {"label": "Peak price", "value": f"{round(float(price_series.max())):,} {currency}/MWh", "detail": f"{peak_net_load:,} MW peak load"},
        {"label": "System emissions", "value": f"{round(total_emissions):,} ktCO2e", "detail": f"Carbon price {float(scenario.get('carbonPrice', 0.0)):.0f} {currency}/t"},
        {"label": "Transmission stress", "value": f"{round(np.mean([x['value'] for x in line_loading]) if line_loading else 0):,}%", "detail": f"{sum(1 for x in line_loading if x['value'] > 80.0)} corridors above 80%"},
    ]

    # Unit-commitment status note
    committable_gens = [g for g in network.generators.index if network.generators.at[g, "committable"]] \
        if "committable" in network.generators.columns else []
    if committable_gens:
        notes.append(
            f"MIP unit commitment enabled for {len(committable_gens)} generator(s): {', '.join(committable_gens[:5])}"
            + (" …" if len(committable_gens) > 5 else "") + "."
        )
        if sampling.enabled and sampling.mode != "average":
            # An averaged profile is one contiguous block — no seams to warn about.
            notes.append(
                "Unit commitment with sampled blocks: start-up and min up/down behaviour "
                "at block boundaries is approximate (blocks are stitched as if consecutive)."
            )

    notes.extend([
        f"Backend PyPSA run solved {len(network.snapshots)} hourly snapshots with {len(network.generators)} generators and {len(network.loads)} loads.",
        f"Average price settled at {average_price:.1f} {currency}/MWh and peaked at {float(price_series.max()):.1f} {currency}/MWh.",
        f"Load shedding totalled {float(weighted_sum(load_shed, generator_weights)):.2f} MWh across the day.",
    ])

    # Sampled-blocks test run meta: snapshot_weight = W/M carries the
    # full-window scaling, so W (represented window rows) is recoverable.
    sampling_meta = None
    if sampling.enabled:
        represented_rows = int(round(snapshot_count * snapshot_weight))
        store_w = float(store_weights.iloc[0]) if len(store_weights) else 1.0
        if sampling.mode == "average":
            # blockCount = periods folded into the average profile.
            block_count = max(1, math.ceil(represented_rows / max(1, sampling.block_size)))
        else:
            block_count = sample_block_indices(0, represented_rows, sampling)[1]
        sampling_meta = {
            "enabled": True,
            "mode": sampling.mode,
            "blockSize": sampling.block_size,
            "blockCount": block_count,
            "gapSnapshots": sampling.gap_snapshots,
            "sampledSnapshots": snapshot_count,
            "representedSnapshots": represented_rows,
            "scale": snapshot_weight / store_w if store_w > 0 else snapshot_weight,
        }

    # MGA near-optimal exploration runs last: it copies the solved network and
    # detaches the solver model, so it must follow every read of the optimum's
    # solution dataframes above. It never mutates the base network's solution.
    near_optimal = (
        build_mga(
            network,
            slack=float(mga_cfg.get("slack", 0.05) or 0.05),
            carriers=mga_cfg.get("carriers") or None,
            currency=currency,
            solver_options=solver_options if solver_options else {},
            io_api=_SOLVER_IO_API,
            multi_investment_periods=pathway.enabled,
        )
        if mga_enabled
        else None
    )

    # Merchant / price-taker analysis — like MGA, runs last on a copy of the
    # solved optimum (it reads stage-1 LMPs and detaches the solver model).
    merchant = (
        build_merchant(
            network,
            model,
            owner=str(merchant_cfg.get("owner", "") or ""),
            owner_column=owner_column,
            price_source=str(merchant_cfg.get("priceSource", "lmp") or "lmp"),
            flat_price=float(merchant_cfg.get("flatPrice", 0.0) or 0.0),
            price_series=merchant_cfg.get("priceSeries") or None,
            currency=currency,
            solver_options=solver_options if solver_options else {},
            io_api=_SOLVER_IO_API,
        )
        if merchant_enabled
        else None
    )

    # Bid-strategy simulator (Tier 2) — raise one owner's offers by a markup,
    # re-clear the market, and compare profit to the price-taker baseline.
    bid_strategy = (
        build_bid_strategy(
            network,
            model,
            owner=str(bid_cfg.get("owner", "") or ""),
            owner_column=owner_column,
            markup_type=str(bid_cfg.get("markupType", "percent") or "percent"),
            markup=float(bid_cfg.get("markup", 0.0) or 0.0),
            currency=currency,
            solver_options=solver_options if solver_options else {},
            io_api=_SOLVER_IO_API,
        )
        if bid_enabled and bid_mode != "optimal"
        else None
    )
    # Optimal-bid finder (Tier 3a) — sweep the markup for the profit-max bid.
    optimal_bid = (
        build_optimal_bid(
            network,
            model,
            owner=str(bid_cfg.get("owner", "") or ""),
            owner_column=owner_column,
            markup_type=str(bid_cfg.get("markupType", "percent") or "percent"),
            max_markup=float(bid_cfg.get("maxMarkup", 2.0) or 2.0),
            steps=int(bid_cfg.get("steps", 8) or 8),
            currency=currency,
            solver_options=solver_options if solver_options else {},
            io_api=_SOLVER_IO_API,
        )
        if bid_enabled and bid_mode == "optimal"
        else None
    )

    # Asset-swap / repowering what-if (DW2) — retire a carrier, add a
    # replacement 1:1, re-solve, and report the before-vs-after delta.
    asset_swap = (
        build_asset_swap(
            network,
            model,
            scenario,
            options,
            build_network,
            remove_filters=swap_cfg.get("removeFilters") or None,
            remove_carrier=str(swap_cfg.get("removeCarrier", "") or ""),
            add_carrier=str(swap_cfg.get("addCarrier", "") or ""),
            add_capital_cost=float(swap_cfg.get("addCapitalCost", 0.0) or 0.0),
            add_marginal_cost=float(swap_cfg.get("addMarginalCost", 0.0) or 0.0),
            replace_ratio=float(swap_cfg.get("replaceRatio", 1.0) or 1.0),
            add_storage_mw=float(swap_cfg.get("addStorageMW", 0.0) or 0.0),
            add_storage_hours=float(swap_cfg.get("addStorageHours", 4.0) or 4.0),
            add_storage_capex_per_mw=float(swap_cfg.get("addStorageCapexPerMW", 0.0) or 0.0),
            currency=currency,
            emissions_factors=emissions_factors,
            solver_options=solver_options if solver_options else {},
            io_api=_SOLVER_IO_API,
        )
        if swap_enabled
        else None
    )

    # ESS business-case builder (DW3) — size sweep of a price-taker battery.
    ess_business_case = (
        build_ess_business_case(
            network,
            bus=str(ess_cfg.get("bus", "") or ""),
            max_hours=float(ess_cfg.get("maxHours", 4.0) or 4.0),
            capital_cost_per_mw=float(ess_cfg.get("capitalCostPerMW", 0.0) or 0.0),
            min_size_mw=float(ess_cfg.get("minSizeMW", 0.0) or 0.0),
            max_size_mw=float(ess_cfg.get("maxSizeMW", 0.0) or 0.0),
            steps=int(ess_cfg.get("steps", 6) or 6),
            round_trip_efficiency=float(ess_cfg.get("roundTripEfficiency", 0.9) or 0.9),
            discount_rate=float(scenario.get("discountRate", 0.0) or 0.0),
            currency=currency,
            solver_options=solver_options if solver_options else {},
            io_api=_SOLVER_IO_API,
        )
        if ess_enabled
        else None
    )

    # Company / owner dimension (F1) — per-company KPIs whenever assets carry an
    # owner tag. Independent of merchant mode; reads only solved dataframes.
    company_breakdown = build_company_breakdown(
        network, model,
        owner_column=owner_column, currency=currency, emissions_factors=emissions_factors,
    )
    # Price-formation view (Tier 0) — price vs residual demand & the marginal
    # (price-setting) carrier each snapshot. Best-effort; None on non-LP runs.
    price_formation = build_price_formation(network, currency=currency)
    # Unit-commitment view (Tier 1) — starts, start-up costs, on/off patterns.
    commitment = build_commitment(network, currency=currency)
    # PPA contract valuation (PP1) — value a fixed-price PPA against the LMP.
    ppa = (
        build_ppa(
            network, model,
            owner=str(ppa_cfg.get("owner", "") or ""),
            owner_column=owner_column,
            volume_type=str(ppa_cfg.get("volumeType", "generation") or "generation"),
            flat_mw=float(ppa_cfg.get("flatMW", 0.0) or 0.0),
            strike_price=float(ppa_cfg.get("strikePrice", 0.0) or 0.0),
            currency=currency,
        )
        if ppa_enabled
        else None
    )
    # Company-level financial model (F2) — NPV / IRR / payback / DSCR per owner.
    company_finance = build_company_finance(
        network, model,
        owner_column=owner_column,
        discount_rate=float(scenario.get("discountRate", 0.0) or 0.0),
        currency=currency,
        debt=options.get("financeConfig") or None,
    )

    return {
        "summary": summary,
        "dispatchSeries": dispatch_s,
        "curtailmentSeries": curtailment_s,
        "generatorDispatchSeries": gen_dispatch_s,
        "systemPriceSeries": price_s,
        "systemEmissionsSeries": emissions_s,
        "storageSeries": storage_s,
        "storageSocSeries": storage_soc_s,
        "nodalPriceSeries": nodal_price_series,
        "carrierMix": carrier_mix,
        "generatorEnergy": generator_energy,
        "costBreakdown": cost_breakdown,
        "nodalBalance": nodal_balance,
        "lineLoading": line_loading,
        "expansionResults": expansion_results,
        "meritOrder": merit_order,
        "co2Shadow": co2_shadow,
        "appliedConstraints": applied_constraints,
        "generatorEconomics": generator_economics,
        "statistics": statistics,
        "nearOptimal": near_optimal,
        "merchant": merchant,
        "companies": company_breakdown,
        "companyFinance": company_finance,
        "priceFormation": price_formation,
        "commitment": commitment,
        "ppa": ppa,
        "bidStrategy": bid_strategy,
        "optimalBid": optimal_bid,
        "assetSwap": asset_swap,
        "essBusinessCase": ess_business_case,
        "emissionsBreakdown": emissions_breakdown,
        "narrative": notes,
        "runMeta": {
            "snapshotCount": snapshot_count,
            "snapshotWeight": snapshot_weight,
            "modeledHours": snapshot_count * snapshot_weight,
            "storeWeight": float(store_weights.iloc[0]) if len(store_weights) else snapshot_weight,
            "planningMode": pathway.planning_mode,
            "investmentPeriods": [row.period for row in pathway.periods],
            "rolling": {
                "enabled": rolling.enabled,
                "horizonSnapshots": rolling.horizon_snapshots,
                "overlapSnapshots": rolling.overlap_snapshots,
                "stepSnapshots": rolling.step_snapshots,
                "windowCount": len(rolling_windows),
            } if rolling.enabled else None,
            "sampling": sampling_meta,
        },
        "pathway": {
            "enabled": pathway.enabled,
            "periods": [row.period for row in pathway.periods],
            "selectedPeriod": pathway.selected_period or (pathway.periods[0].period if pathway.periods else None),
            "snapshotMappingMode": pathway.snapshot_mapping_mode,
            "summaries": pathway_summaries,
        } if pathway.enabled else None,
        "rolling": {
            "enabled": rolling.enabled,
            "horizonSnapshots": rolling.horizon_snapshots,
            "overlapSnapshots": rolling.overlap_snapshots,
            "stepSnapshots": rolling.step_snapshots,
            "windowCount": len(rolling_windows),
            "windows": rolling_windows,
        } if rolling.enabled else None,
        "stochastic": stochastic_result,
        "securityConstrained": (
            {
                "enabled": True,
                "branchCount": (
                    len(network.lines)
                    + (len(network.transformers) if "transformers" in network.components.keys() else 0)
                ),
            }
            if sclopf_enabled
            else None
        ),
        # Full PyPSA-native output dataset (every output attribute, every
        # component, every snapshot). The frontend turns this into per-asset
        # detail records (`assetDetails`) locally and uses the same cache for
        # Export-Project, so the backend stays a stateless solver.
        "outputs": build_full_outputs(network),
    }
