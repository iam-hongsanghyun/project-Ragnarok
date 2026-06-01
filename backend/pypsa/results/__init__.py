from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException

# Solve-phase timing and notes are logged here. With the run worker no longer
# redirecting file descriptors, these INFO lines stream to the launching
# terminal alongside HiGHS' own verbose output.
_log = logging.getLogger("pypsa.solver")

from ..constants import carrier_color
from ..network import build_network
from ..pathway import parse_pathway_config
from ..rolling import parse_rolling_config
from ..stochastic import (
    collapse_to_representative_scenario,
    parse_stochastic_config,
    per_scenario_summaries,
)
from ..utils.series import weighted_sum
from ..network.custom_constraints import apply_custom_constraints
from ..network.constraint_dsl import apply_constraint_specs, apply_dsl_constraints
from .dispatch import (
    build_dispatch_series,
    build_price_emissions_series,
    build_storage_series,
    dispatch_by_carrier,
)
from .emissions import build_emissions_breakdown
from .expansion import build_expansion_results
from .full_outputs import build_full_outputs
from .market import build_applied_constraints, build_co2_shadow, build_merit_order
from .summaries import _snapshot_label, _rolling_window_summaries, _pathway_period_summaries


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


# HiGHS LP methods the user may pin. Anything else (incl. "auto"/"choose"/
# "highs"/"") leaves the method unset so HiGHS chooses — identical to a bare
# ``n.optimize(solver_name="highs")`` and the fast default.
_HIGHS_METHODS = ("simplex", "ipm", "pdlp")

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
    if solver_type in _HIGHS_METHODS:
        out["solver"] = solver_type
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
    sclopf_cfg = options.get("securityConstrainedConfig") or {}
    sclopf_enabled = bool(sclopf_cfg.get("enabled", False))
    if stochastic.enabled and rolling.enabled:
        raise HTTPException(
            status_code=400,
            detail="Stochastic mode and rolling horizon cannot be combined.",
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
        apply_custom_constraints(n, custom_constraints, emissions_factors, notes)
        if constraint_specs:
            apply_constraint_specs(n, constraint_specs, emissions_factors, notes)
        elif custom_dsl_text:
            apply_dsl_constraints(n, custom_dsl_text, emissions_factors, notes)


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
            )
            solve_status, solve_condition = _coerce_solve_status(result)
        _log.info(
            "solve finished in %.2fs — status=%s condition=%s",
            time.perf_counter() - _t_solve,
            solve_status,
            solve_condition,
        )
        # Solver may return without raising but still report a non-optimal
        # condition (e.g. HiGHS "Dual simplex ratio test failed" leaves
        # condition='unknown' while linopy parses a garbage primal). Treat
        # anything other than ('ok', 'optimal') as a failed run.
        if solve_condition != "optimal":
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Solver did not return an optimal solution "
                    f"(status='{solve_status}', condition='{solve_condition}'). "
                    "The model is likely ill-conditioned: check for placeholder "
                    "1e12 / inf values in p_nom_max, e_sum_min, e_sum_max, "
                    "lifetime, or for conflicting constraints (CO₂ cap, "
                    "capacity factor caps) against the available capacity."
                ),
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

    generator_dispatch_frame = network.generators_t.p.copy()
    dispatch_frame = generator_dispatch_frame.copy()
    if hasattr(network, "storage_units_t") and not network.storage_units_t.p.empty:
        dispatch_frame = pd.concat([dispatch_frame, network.storage_units_t.p], axis=1)

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

    # Capacity & energy metrics
    total_capacity = float(network.generators.p_nom.sum() + network.storage_units.p_nom.sum())
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
        positive = series.clip(lower=0.0)
        carrier_energy[carrier] += weighted_sum(positive, generator_weights)
        emission_totals[carrier] += weighted_sum(positive * emissions_factors.get(carrier, 0.0), generator_weights)

    carrier_mix = [
        {"label": c, "value": v, "color": carrier_color(network, c)}
        for c, v in sorted(carrier_energy.items(), key=lambda x: x[1], reverse=True)
        if v > 0.0
    ]

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
        carrier = network.generators.at[name, "carrier"]
        ef = emissions_factors.get(carrier, 0.0)
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
    emissions_breakdown = build_emissions_breakdown(network, emissions_factors)

    cost_breakdown = [
        {"label": "Fuel cost", "value": round(fuel_cost)},
        {"label": "Carbon cost", "value": round(carbon_cost)},
        {"label": "Load shedding", "value": round(shed_cost)},
    ]
    if total_capex_annual > 0:
        cost_breakdown.append({"label": "Capital cost", "value": round(total_capex_annual)})

    # Per-bus LMP (nodal marginal prices) — one value series per bus
    nodal_price_series: list[dict] = []
    if not network.buses_t.marginal_price.empty:
        mp = network.buses_t.marginal_price
        for ts in network.snapshots:
            nodal_price_series.append({
                "label": str(ts),
                "timestamp": str(ts),
                "values": {bus: round(float(mp.at[ts, bus]), 2) for bus in mp.columns},
            })

    # Series
    dispatch_s, gen_dispatch_s = build_dispatch_series(network, by_carrier, load_dispatch, generator_dispatch_frame)
    price_s, emissions_s = build_price_emissions_series(network, by_carrier, price_series, emissions_factors)
    storage_s = build_storage_series(network)
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
        {"label": "Installed capacity", "value": f"{round(total_capacity):,} MW", "detail": f"{len(network.generators)} generators + {len(network.storage_units)} storage units"},
        {"label": "Peak demand", "value": f"{round(total_load):,} MW", "detail": "from workbook load profile"},
        {"label": "Reserve position", "value": f"{round(total_capacity - reserve_requirement):,} MW", "detail": "installed capacity vs peak demand"},
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

    notes.extend([
        f"Backend PyPSA run solved {len(network.snapshots)} hourly snapshots with {len(network.generators)} generators and {len(network.loads)} loads.",
        f"Average price settled at {average_price:.1f} {currency}/MWh and peaked at {float(price_series.max()):.1f} {currency}/MWh.",
        f"Load shedding totalled {float(load_shed.sum()):.2f} MWh across the day.",
    ])

    return {
        "summary": summary,
        "dispatchSeries": dispatch_s,
        "generatorDispatchSeries": gen_dispatch_s,
        "systemPriceSeries": price_s,
        "systemEmissionsSeries": emissions_s,
        "storageSeries": storage_s,
        "nodalPriceSeries": nodal_price_series,
        "carrierMix": carrier_mix,
        "costBreakdown": cost_breakdown,
        "nodalBalance": nodal_balance,
        "lineLoading": line_loading,
        "expansionResults": expansion_results,
        "meritOrder": merit_order,
        "co2Shadow": co2_shadow,
        "appliedConstraints": applied_constraints,
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
