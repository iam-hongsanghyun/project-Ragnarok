"""Derive full analytics from PRE-COMPUTED outputs (an imported result).

An external Excel result carries the solved frames — ``generators-p``,
``buses-marginal_price``, ``p_nom_opt``, storage SoC, … — but **no derived
analytics**: it never went through a solve, so the summary / carrier mix /
dispatch series that the Result view renders were never built.

This module rebuilds the PyPSA network from the model + the *original run
options* (which reproduce the exact snapshot grid — verified: identical count
and timestamps), **injects** the stored outputs into the network's result
frames, then runs the SAME per-chart extraction helpers a real solve uses
(``dispatch.py`` / ``market.py`` / ``emissions.py`` / ``expansion.py``). The
numbers therefore match what a re-solve would report — without re-solving the
(expensive) model.

Source of truth for the orchestration is :func:`pypsa.results.run_pypsa`; this
mirrors its post-solve section. Keep the two in sync when changing analytics
(the test ``test_import_history`` pins the key aggregates).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd

from ..carbon_price import build_price_series, parse_carbon_price_config
from ..constants import carrier_color
from ..network import build_network
from ..utils.series import weighted_sum
from .dispatch import (
    build_curtailment_series,
    curtailment_mwh_by_generator,
    metric_definitions,
    system_average_price,
    build_dispatch_series,
    build_price_emissions_series,
    build_storage_series,
    build_storage_soc_series,
    electricity_bus_scope,
    electricity_dispatch_by_carrier,
    system_price_series,
)
from .emissions import build_emissions_breakdown, emission_totals_by_carrier
from .expansion import build_expansion_results
from .market import (
    build_applied_constraints,
    build_co2_shadow,
    build_generator_economics,
    build_merit_order,
    installed_capacity_series,
)

# Fallback discount rate when an imported file omits the setting (build_network
# requires it). Matches the app's default; only annualises extendable-asset
# capex, which a solved import has none of. The file's own value always wins.
_DEFAULT_DISCOUNT_RATE = 0.05


def _series_to_frame(
    rows: list[dict[str, Any]] | None, snapshots: pd.Index, columns: list[str]
) -> pd.DataFrame:
    """Turn a stored output series (list of ``{snapshot, <name>: value, …}``
    rows) into a snapshot-indexed numeric frame aligned to ``snapshots``.

    Alignment is by timestamp; if the stored timestamps don't parse to the
    network grid but the row count matches exactly, fall back to positional
    assignment (both sides are written in snapshot order). Columns are reindexed
    to the component index so a frame missing a component is zero-filled and an
    extra column is dropped.

    Multi-period (pathway) rows carry a ``period`` column; with a
    ``(period, timestep)`` ``snapshots`` MultiIndex they are aligned on both
    levels, because the same timestep repeats in every investment period.
    """
    if not rows:
        return _named(pd.DataFrame(0.0, index=snapshots, columns=columns), snapshots)
    df = pd.DataFrame(rows)
    period_col = df["period"] if "period" in df.columns else None
    for meta_col in ("timestamp", "period"):
        if meta_col in df.columns:
            df = df.drop(columns=[meta_col])
    if "snapshot" in df.columns:
        df = df.set_index("snapshot")
    df = df.apply(pd.to_numeric, errors="coerce")
    aligned = df.copy()
    aligned.index = pd.to_datetime(df.index, errors="coerce")
    if isinstance(snapshots, pd.MultiIndex) and period_col is not None:
        # Multi-period (pathway) rows: the same timestep repeats in every
        # investment period, so the timestamp alone is not a key - align on
        # (period, timestamp), the index the network was built with.
        aligned.index = pd.MultiIndex.from_arrays(
            [pd.to_numeric(period_col, errors="coerce").to_numpy(), aligned.index],
            names=list(snapshots.names),
        )
    reindexed = aligned.reindex(snapshots)
    # Timestamp alignment found nothing but the lengths match → positional.
    if reindexed.notna().to_numpy().sum() == 0 and len(df) == len(snapshots):
        df.index = snapshots
        reindexed = df
    return _named(reindexed.reindex(columns=columns, fill_value=0.0).fillna(0.0), snapshots)


def _named(frame: pd.DataFrame, snapshots: pd.Index) -> pd.DataFrame:
    """Name the axes as PyPSA does (``snapshot`` x ``name``).

    ``n.statistics`` over a ``NetworkCollection`` groups on the ``name`` level of
    the per-component frames; an unnamed column axis makes the grouping fail
    (P39), though the same statistic on one network tolerates it.
    """
    frame.columns.name = "name"
    if not isinstance(frame.index, pd.MultiIndex):
        frame.index.name = snapshots.name or "snapshot"
    return frame


def _inject_outputs(network: Any, outputs: dict[str, Any]) -> None:
    """Write the stored output frames onto the rebuilt (unsolved) network so the
    extraction helpers read them as if they came from a fresh solve."""
    series = (outputs or {}).get("series") or {}
    static = (outputs or {}).get("static") or {}
    snaps = network.snapshots

    def put_dynamic(comp_t: str, attr: str, sheet: str, index: pd.Index) -> None:
        rows = series.get(sheet)
        if rows and len(index):
            getattr(network, comp_t)[attr] = _series_to_frame(rows, snaps, list(index))

    put_dynamic("generators_t", "p", "generators-p", network.generators.index)
    put_dynamic("buses_t", "marginal_price", "buses-marginal_price", network.buses.index)
    put_dynamic("storage_units_t", "p", "storage_units-p", network.storage_units.index)
    put_dynamic("storage_units_t", "state_of_charge", "storage_units-state_of_charge", network.storage_units.index)
    put_dynamic("stores_t", "p", "stores-p", network.stores.index)
    put_dynamic("stores_t", "e", "stores-e", network.stores.index)
    put_dynamic("lines_t", "p0", "lines-p0", network.lines.index)
    put_dynamic("links_t", "p0", "links-p0", network.links.index)
    put_dynamic("transformers_t", "p0", "transformers-p0", network.transformers.index)

    # Solved capacities (p_nom_opt / s_nom_opt) live in the static outputs.
    for comp, opt_attr in (
        ("generators", "p_nom_opt"),
        ("storage_units", "p_nom_opt"),
        ("stores", "e_nom_opt"),
        ("links", "p_nom_opt"),
        ("lines", "s_nom_opt"),
        ("transformers", "s_nom_opt"),
    ):
        sheet_static = static.get(comp) or {}
        df = getattr(network, comp)
        if not sheet_static or not len(df):
            continue
        values = {
            name: vals.get(opt_attr)
            for name, vals in sheet_static.items()
            if isinstance(vals, dict) and vals.get(opt_attr) not in (None, "")
        }
        if values:
            col = pd.to_numeric(pd.Series(values), errors="coerce").reindex(df.index)
            df[opt_attr] = col.fillna(df[opt_attr]) if opt_attr in df.columns else col


def derive_imported_result(
    model: dict[str, list[dict[str, Any]]],
    scenario: dict[str, Any],
    options: dict[str, Any],
    outputs: dict[str, Any],
) -> dict[str, Any]:
    """Derive the analytics fields the Result view renders, from stored outputs.

    Mirrors the post-solve extraction of :func:`run_pypsa` (intermediates +
    per-chart helpers) against a network whose result frames are the imported
    outputs. Returns only the derived analytics — the caller merges them into
    the bundle's ``result`` (which already holds ``outputs`` itself).
    """
    from fastapi import HTTPException

    # `build_network` needs a discountRate only where extendable capacity carries a
    # capital cost to annuitise, and an already-solved import normally has fixed
    # capacities — so no rate is invented up front. Where the imported model DOES
    # still carry extendable assets and the file omits one (Ragnarok's own files
    # carry it in their settings sheet), fall back rather than refuse an otherwise
    # complete result — but SAY SO in the narrative, because the rate then shapes a
    # reported capital cost and an invented number must not pass as the file's own.
    scenario = dict(scenario or {})
    rate_defaulted = False
    try:
        network, _build_notes = build_network(model, scenario, options or {})
    except HTTPException as exc:
        if "discountRate" not in str(exc.detail):
            raise
        scenario["discountRate"] = _DEFAULT_DISCOUNT_RATE
        rate_defaulted = True
        network, _build_notes = build_network(model, scenario, options or {})
    _inject_outputs(network, outputs or {})

    currency = str((options or {}).get("currencySymbol", "$"))
    snapshot_count = len(network.snapshots)
    snapshot_weight = (
        float(network.snapshot_weightings["objective"].iloc[0]) if snapshot_count else 1.0
    )

    if "co2_emissions" in network.carriers.columns:
        ef = network.carriers["co2_emissions"]
        if isinstance(ef.index, pd.MultiIndex) and "name" in ef.index.names:
            ef = ef.groupby(level="name").first()
        emissions_factors: dict[str, float] = ef.to_dict()
    else:
        emissions_factors = {}

    # ── Intermediates (mirror run_pypsa) ────────────────────────────────────
    generator_dispatch_frame = network.generators_t.p.copy()
    by_carrier = electricity_dispatch_by_carrier(network, generator_dispatch_frame)
    # Resolve static + time-varying load into a dense frame. run_pypsa reads
    # network.loads_t.p_set directly because the solve has already densified it;
    # this path never solved, so a STATIC p_set would leave that frame empty —
    # get_switchable_as_dense broadcasts the scalar correctly without solving.
    load_dense = (
        network.get_switchable_as_dense("Load", "p_set")
        if len(network.loads)
        else pd.DataFrame(index=network.snapshots)
    )
    load_dispatch = load_dense.sum(axis=1)
    # Load-weighted system price (see dispatch.system_price_series).
    price_series = system_price_series(network, electricity_bus_scope(network), load_dense)
    generator_weights = network.snapshot_weightings["generators"].reindex(network.snapshots).fillna(1.0)

    # Installed capacity uses the solved p_nom_opt (== p_nom for non-extendable
    # units); the injected load_shedding_ backstop is excluded. Mirrors the
    # solve path in results/__init__.py.
    _gen_installed = installed_capacity_series(network.generators)
    _real_gen = ~network.generators.index.str.startswith("load_shedding_")
    generator_capacity = float(_gen_installed[_real_gen].sum())
    storage_capacity = float(installed_capacity_series(network.storage_units).sum())
    total_load = float(load_dispatch.max()) if len(load_dispatch) else 0.0
    reserve_requirement = total_load

    shed_carriers = set(
        network.generators.loc[
            network.generators.index.str.startswith("load_shedding_"), "carrier"
        ].unique()
    )
    emission_totals: dict[str, float] = defaultdict(float)
    carrier_energy: dict[str, float] = defaultdict(float)
    for carrier, s in by_carrier.items():
        if carrier in shed_carriers:
            continue
        carrier_energy[carrier] += weighted_sum(s.clip(lower=0.0), generator_weights)
    # Emissions on PyPSA's primary_energy basis (RB10), see emissions.py.
    emission_totals.update(emission_totals_by_carrier(network, emissions_factors))

    carrier_mix = [
        {"label": c, "value": v, "color": carrier_color(network, c)}
        for c, v in sorted(carrier_energy.items(), key=lambda x: x[1], reverse=True)
        if v > 0.0
    ]

    # Per-generator dispatched energy (+ curtailment for renewables), mirroring
    # run_pypsa's "Dispatch by unit" aggregate.
    # P28: PyPSA's n.statistics.curtailment (variable-availability generators).
    curtailment_by_gen = curtailment_mwh_by_generator(network)
    generator_carriers = network.generators["carrier"].to_dict()
    generator_energy: list[dict[str, Any]] = []
    for gen in generator_dispatch_frame.columns:
        if str(gen).startswith("load_shedding_"):
            continue
        energy = weighted_sum(generator_dispatch_frame[gen].clip(lower=0.0), generator_weights)
        if energy <= 0.0:
            continue
        curtailment_mwh: float | None = curtailment_by_gen.get(str(gen))
        carrier = str(generator_carriers.get(gen, ""))
        generator_energy.append(
            {"name": str(gen), "value": float(energy), "carrier": carrier,
             "color": carrier_color(network, carrier), "curtailmentMwh": curtailment_mwh}
        )
    generator_energy.sort(key=lambda row: row["value"], reverse=True)

    # ── Series + market analysis (reuse the solve-path helpers) ─────────────
    dispatch_s, gen_dispatch_s = build_dispatch_series(
        network, by_carrier, load_dispatch, generator_dispatch_frame
    )
    curtailment_s = build_curtailment_series(network, generator_dispatch_frame)
    price_s, emissions_s = build_price_emissions_series(
        network, price_series, emissions_factors
    )
    storage_s = build_storage_series(network)
    storage_soc_s = build_storage_soc_series(network)
    expansion_results = build_expansion_results(network)
    merit_order = build_merit_order(network)
    # Schedule-aware carbon price, mirroring the solve path: a stored
    # ``carbonPrice: null`` coerces to 0.0 and a ``carbonPriceSchedule``
    # supersedes the scalar, so the shadow price matches what was solved.
    carbon_cfg = parse_carbon_price_config(
        (scenario or {}).get("carbonPrice") or 0.0,
        (options or {}).get("carbonPriceSchedule"),
    )
    carbon_price_series = build_price_series(network, carbon_cfg)
    carbon_price = float(carbon_price_series.mean()) if len(carbon_price_series) else 0.0
    co2_shadow = build_co2_shadow(network, carbon_price, currency)
    applied_constraints = build_applied_constraints(network)
    generator_economics = build_generator_economics(network, currency)
    emissions_breakdown = build_emissions_breakdown(network, emissions_factors)

    # Nodal balance + line loading (mirror run_pypsa).
    nodal_balance = []
    for bus in network.buses.index:
        bus_loads = list(network.loads.index[network.loads.bus == bus])
        load_val = (
            float(load_dense.reindex(columns=bus_loads, fill_value=0.0).sum(axis=1).mean())
            if bus_loads else 0.0
        )
        gen_names = list(network.generators.index[network.generators.bus == bus])
        gen_val = (
            float(generator_dispatch_frame.reindex(columns=gen_names, fill_value=0.0).sum(axis=1).mean())
            if gen_names else 0.0
        )
        nodal_balance.append({"label": bus, "load": load_val, "generation": gen_val})
    nodal_balance.sort(key=lambda x: x["load"], reverse=True)

    # Loading is against the SOLVED rating (p_nom_opt / s_nom_opt) when the
    # stored outputs carry one > 0, falling back to the input nameplate —
    # mirrors the solve path in results/__init__.py.
    def _rating(static_df: pd.DataFrame, name: str, nominal_attr: str) -> float:
        opt_attr = f"{nominal_attr}_opt"
        if opt_attr in static_df.columns:
            opt = pd.to_numeric(static_df.at[name, opt_attr], errors="coerce")
            if pd.notna(opt) and float(opt) > 0.0:
                return float(opt)
        return float(static_df.at[name, nominal_attr])

    line_loading = []
    for link in (network.links.index if not network.links_t.p0.empty else []):
        peak = float((network.links_t.p0[link].abs() / max(_rating(network.links, link, "p_nom"), 1.0) * 100.0).max())
        line_loading.append({"label": link, "value": peak})
    for line in (network.lines.index if not network.lines_t.p0.empty else []):
        peak = float((network.lines_t.p0[line].abs() / max(_rating(network.lines, line, "s_nom"), 1.0) * 100.0).max())
        line_loading.append({"label": line, "value": peak})
    for transformer in (network.transformers.index if not network.transformers_t.p0.empty else []):
        peak = float((network.transformers_t.p0[transformer].abs() / max(_rating(network.transformers, transformer, "s_nom"), 1.0) * 100.0).max())
        line_loading.append({"label": transformer, "value": peak})

    total_emissions = sum(emission_totals.values()) / 1000.0
    _avg_stat = system_average_price(network, electricity_bus_scope(network))
    average_price = (
        _avg_stat if _avg_stat is not None
        else (float(price_series.mean()) if len(price_series) else 0.0)
    )
    peak_price = float(price_series.max()) if len(price_series) else 0.0
    peak_net_load = round(float(load_dispatch.max())) if len(load_dispatch) else 0

    summary = [
        {"label": "Generator capacity", "value": f"{round(generator_capacity):,} MW",
         "detail": f"{len(network.generators)} generators (installed nameplate)"},
        {"label": "Storage capacity", "value": f"{round(storage_capacity):,} MW",
         "detail": f"{len(network.storage_units)} storage units (installed nameplate)"},
        {"label": "Peak demand", "value": f"{round(total_load):,} MW", "detail": "from workbook load profile"},
        {"label": "Generator reserve", "value": f"{round(generator_capacity - reserve_requirement):,} MW",
         "detail": "generator capacity vs peak demand"},
        {"label": "Storage reserve", "value": f"{round(storage_capacity - reserve_requirement):,} MW",
         "detail": "storage capacity vs peak demand"},
        {"label": "Peak price", "value": f"{round(peak_price):,} {currency}/MWh", "detail": f"{peak_net_load:,} MW peak load"},
        {"label": "System emissions", "value": f"{round(total_emissions):,} ktCO2e",
         "detail": (
             f"Carbon price {float(carbon_price_series.min()):.0f}–{float(carbon_price_series.max()):.0f} {currency}/t (schedule)"
             if len(carbon_price_series) and carbon_price_series.nunique(dropna=False) > 1
             else f"Carbon price {carbon_price:.0f} {currency}/t"
         )},
        {"label": "Transmission stress",
         "value": f"{round(sum(x['value'] for x in line_loading) / len(line_loading) if line_loading else 0):,}%",
         "detail": f"{sum(1 for x in line_loading if x['value'] > 80.0)} corridors above 80%"},
    ]

    notes = [
        "Imported result — analytics derived from the stored solved outputs, not a fresh solve.",
        f"Derived over {snapshot_count} snapshots at {snapshot_weight:g}h weight; "
        f"average price {average_price:.1f} {currency}/MWh, peak {peak_price:.1f} {currency}/MWh.",
    ]
    if rate_defaulted:
        notes.append(
            f"The imported file carried no discount rate, so {_DEFAULT_DISCOUNT_RATE:.0%} was "
            "assumed to annuitise the capital cost of its extendable assets. Any capital "
            "figure below depends on that assumption, not on the file."
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
        "carrierMix": carrier_mix,
        "generatorEnergy": generator_energy,
        "nodalBalance": nodal_balance,
        "lineLoading": line_loading,
        "expansionResults": expansion_results,
        "meritOrder": merit_order,
        "co2Shadow": co2_shadow,
        "appliedConstraints": applied_constraints,
        "generatorEconomics": generator_economics,
        "emissionsBreakdown": emissions_breakdown,
        "narrative": notes,
        "metricDefinitions": metric_definitions(currency),
        "runMeta": {
            "averageSystemPrice": float(average_price),
            "snapshotCount": snapshot_count,
            "snapshotWeight": snapshot_weight,
            "modeledHours": snapshot_count * snapshot_weight,
            "componentCounts": {
                "buses": len(network.buses),
                "generators": len(network.generators),
                "loads": len(network.loads),
                "lines": len(network.lines),
                "links": len(network.links),
                "storage_units": len(network.storage_units),
                "transformers": len(network.transformers),
                "stores": len(network.stores),
            },
        },
    }
