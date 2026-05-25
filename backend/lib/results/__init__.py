from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException

from ..constants import carrier_color
from ..network import build_network
from ..pathway import parse_pathway_config
from ..rolling import parse_rolling_config
from ..utils.series import weighted_sum
from ..network.custom_constraints import apply_custom_constraints
from ..module_host import execute_plugins_at_stage, get_module_metadata
from .dispatch import (
    build_dispatch_series,
    build_price_emissions_series,
    build_storage_series,
    dispatch_by_carrier,
)
from .emissions import build_emissions_breakdown
from .expansion import build_expansion_results
from .full_outputs import build_full_outputs
from .market import build_co2_shadow, build_merit_order


def _snapshot_label(snapshot: Any) -> str:
    if isinstance(snapshot, tuple) and len(snapshot) == 2:
        period, timestep = snapshot
        return f"{int(period)}|{pd.Timestamp(timestep).isoformat() if not isinstance(timestep, str) else timestep}"
    try:
        return pd.Timestamp(snapshot).isoformat()
    except Exception:
        return str(snapshot)


def _rolling_window_summaries(
    snapshots: pd.Index,
    horizon: int,
    overlap: int,
) -> list[dict[str, Any]]:
    step = max(1, horizon - overlap)
    windows: list[dict[str, Any]] = []
    starts = list(range(0, len(snapshots), step))
    for index, start in enumerate(starts):
        end = min(len(snapshots), start + horizon)
        accepted_end = end if index == len(starts) - 1 else min(len(snapshots), start + step)
        solved = snapshots[start:end]
        accepted = snapshots[start:accepted_end]
        periods: list[int] = []
        if isinstance(snapshots, pd.MultiIndex):
            periods = sorted({int(p) for p in solved.get_level_values("period").unique()})
        windows.append({
            "index": index + 1,
            "solvedStart": _snapshot_label(solved[0]),
            "solvedEnd": _snapshot_label(solved[-1]),
            "acceptedStart": _snapshot_label(accepted[0]),
            "acceptedEnd": _snapshot_label(accepted[-1]),
            "solvedCount": int(len(solved)),
            "acceptedCount": int(len(accepted)),
            "periods": periods,
        })
    return windows


def _pathway_period_summaries(
    network: pypsa.Network,
    dispatch_frame: pd.DataFrame,
    load_dispatch: pd.Series,
    price_series: pd.Series,
    emissions_factors: dict[str, float],
) -> list[dict[str, Any]]:
    if not isinstance(network.snapshots, pd.MultiIndex):
        return []
    summaries: list[dict[str, Any]] = []
    dispatch_only = dispatch_frame.clip(lower=0.0)
    for period in network.snapshots.get_level_values("period").unique():
        period_index = network.snapshots[network.snapshots.get_level_values("period") == period]
        weight = network.snapshot_weightings["objective"].reindex(period_index).fillna(1.0)
        dispatch_period = dispatch_only.loc[period_index]
        total_dispatch = float((dispatch_period.sum(axis=1) * weight).sum())
        total_emissions = 0.0
        for name in dispatch_period.columns:
            if name not in network.generators.index:
                continue
            carrier = str(network.generators.at[name, "carrier"])
            total_emissions += float((dispatch_period[name] * emissions_factors.get(carrier, 0.0) * weight).sum())
        summaries.append({
            "period": int(period),
            "snapshotCount": int(len(period_index)),
            "modeledHours": float(weight.sum()),
            "totalDispatch": total_dispatch,
            "totalEmissions": total_emissions,
            "averagePrice": float(price_series.loc[period_index].mean()) if len(period_index) else 0.0,
            "peakLoad": float(load_dispatch.loc[period_index].max()) if len(period_index) else 0.0,
            "objectiveWeight": float(network.investment_period_weightings.at[int(period), "objective"]),
            "yearsWeight": float(network.investment_period_weightings.at[int(period), "years"]),
        })
    return summaries


def run_pypsa(
    model: dict[str, list[dict[str, Any]]],
    scenario: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the network from the JSON workbook model, optimise, return results."""
    options = options or {}
    enabled_modules: list[str] = list(options.get("enabledModules") or [])
    pathway = parse_pathway_config(options.get("pathwayConfig"))
    rolling = parse_rolling_config(options.get("rollingConfig"))

    # ── pre-build ─────────────────────────────────────────────────────────────
    pre_outputs = execute_plugins_at_stage(
        "pre-build", enabled_modules, model=model, scenario=scenario, options=options
    )
    # Any plugin that returns a dict replaces the model (last writer wins)
    for result in pre_outputs.values():
        if isinstance(result, dict) and not result.get("error"):
            model = result

    network, notes = build_network(model, scenario, options)

    # ── post-build ────────────────────────────────────────────────────────────
    execute_plugins_at_stage(
        "post-build", enabled_modules, network=network, scenario=scenario, options=options
    )

    snapshot_count = len(network.snapshots)
    snapshot_weight = float(network.snapshot_weightings["objective"].iloc[0]) if snapshot_count else 1.0
    emissions_factors: dict[str, float] = (
        network.carriers["co2_emissions"].to_dict()
        if "co2_emissions" in network.carriers.columns
        else {}
    )

    custom_constraints: list[dict] = scenario.get("constraints") or []

    def extra_functionality(n, snapshots):
        apply_custom_constraints(n, custom_constraints, emissions_factors, notes)
        # ── in-solve ──────────────────────────────────────────────────────────
        execute_plugins_at_stage(
            "in-solve", enabled_modules,
            network=n, model=model, scenario=scenario, options=options,
        )


    # Currency symbol for formatted output strings
    currency = str(options.get("currencySymbol", "$"))

    # Read solver performance options from run payload
    solver_options: dict = {}
    threads = options.get("solverThreads", 0)
    if isinstance(threads, (int, float)) and int(threads) > 0:
        solver_options["threads"] = int(threads)
    solver_type = str(options.get("solverType", "simplex")).lower()
    if solver_type in ("ipm", "simplex"):
        solver_options["solver"] = solver_type

    rolling_windows: list[dict[str, Any]] = []
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
            )
        else:
            network.optimize(
                multi_investment_periods=pathway.enabled,
                solver_name="highs",
                solver_options=solver_options if solver_options else {},
                extra_functionality=extra_functionality,
            )
        solver_note = "HiGHS"
        if solver_options.get("threads"):
            solver_note += f" ({solver_options['threads']} threads)"
        if solver_options.get("solver"):
            solver_note += f", {solver_options['solver'].upper()}"
        if rolling.enabled:
            notes.append(
                "PyPSA rolling horizon solved with "
                f"{solver_note}: horizon {rolling.horizon_snapshots}, overlap {rolling.overlap_snapshots}, "
                f"{len(rolling_windows)} window(s)."
            )
        else:
            notes.append(f"PyPSA optimize() solved with {solver_note}.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PyPSA optimization failed: {exc}") from exc

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

    emission_totals: dict[str, float] = defaultdict(float)
    carrier_energy: dict[str, float] = defaultdict(float)
    for carrier, series in by_carrier.items():
        positive = series.clip(lower=0.0)
        carrier_energy[carrier] += weighted_sum(positive, generator_weights)
        emission_totals[carrier] += weighted_sum(positive * emissions_factors.get(carrier, 0.0), generator_weights)

    carrier_mix = [
        {"label": c, "value": v, "color": carrier_color(network, c)}
        for c, v in sorted(carrier_energy.items(), key=lambda x: x[1], reverse=True)
        if v > 0.0
    ]

    # Cost breakdown
    fuel_cost = 0.0
    carbon_cost = 0.0
    shed_cost = 0.0
    for name in network.generators.index:
        if name not in generator_dispatch_frame.columns:
            continue
        mc = float(network.generators.at[name, "marginal_cost"])
        dispatch_mwh = weighted_sum(generator_dispatch_frame[name].clip(lower=0.0), generator_weights)
        carrier = network.generators.at[name, "carrier"]
        ef = emissions_factors.get(carrier, 0.0)
        carbon_c = float(scenario.get("carbonPrice", 0.0))
        carbon_component = dispatch_mwh * ef * carbon_c
        fuel_component = dispatch_mwh * max(0.0, mc - ef * carbon_c)
        if name.startswith("load_shedding_"):
            shed_cost += dispatch_mwh * mc
        else:
            fuel_cost += fuel_component
            carbon_cost += carbon_component

    # Expansion CAPEX (annualised)
    expansion_results = build_expansion_results(network)
    total_capex_annual = sum(r["capex_annual"] for r in expansion_results)

    # Market analysis — merit order + CO₂ shadow price (pure post-processing)
    merit_order = build_merit_order(network)
    co2_shadow = build_co2_shadow(network, float(scenario.get("carbonPrice", 0.0)), currency)
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

    # ── post-solve ────────────────────────────────────────────────────────────
    raw_plugin_outputs = execute_plugins_at_stage(
        "post-solve", enabled_modules,
        network=network, results={}, scenario=scenario, options=options,
    )
    # Enrich each plugin result with its display metadata (name, ui hints from
    # module.json) so the frontend can render generically without hardcoding.
    plugin_analytics: dict[str, Any] = {}
    for module_id, data in raw_plugin_outputs.items():
        meta = get_module_metadata(module_id)
        plugin_analytics[module_id] = {
            "name": meta.get("name", module_id),
            "ui":   meta.get("ui", {}),
            "data": data if isinstance(data, dict) else {"result": data},
        }

    return {
        "pluginAnalytics": plugin_analytics,
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
        # Full PyPSA-native output dataset (every output attribute, every
        # component, every snapshot). The frontend turns this into per-asset
        # detail records (`assetDetails`) locally and uses the same cache for
        # Export-Project, so the backend stays a stateless solver.
        "outputs": build_full_outputs(network),
    }
