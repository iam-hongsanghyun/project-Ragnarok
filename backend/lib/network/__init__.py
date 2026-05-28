"""Build a PyPSA Network from the in-memory workbook model.

The frontend POSTs the workbook to /api/run as a per-sheet JSON object:
``model: {sheet_name: [row_dict, ...]}``. We turn each sheet into a pandas
DataFrame and use PyPSA's bulk `network.add()` API to import every column
the user provided. The mapping between sheet names, PyPSA component classes,
time-varying attributes and bus-reference columns is **derived from PyPSA's
own component registry** (`n.components`) so nothing is hardcoded here — when
a new PyPSA version adds attributes or component types, they Just Work.

After import we apply five small post-load transformations that depend on
Settings rather than on the workbook:
  * Snapshot windowing & downsampling
  * Period-factor scaling of ``*_sum_min`` / ``*_sum_max`` annual caps
  * Carbon-price adder on generator marginal_cost
  * Annuitisation of capital_cost for extendable assets
  * Force-LP override of committable=True
  * Optional per-bus load shedding generators
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import pypsa

from ..config import load_system_defaults
from ..pathway import PathwayConfig, parse_pathway_config
from ..stochastic import apply_scenarios, parse_stochastic_config
from ..pypsa_schema import (
    input_static_attributes,
    input_temporal_attributes,
)
from ..utils.annuity import annuity_factor
from ..utils.coerce import number
from .load_shedding import add_load_shedding
from .validators import validate_model  # re-export for backend.main
from .snapshots import (
    _snapshots_index,
    _apply_pathway_config,
    _normalize_dynamic_snapshot_index_names,
)
from .components import (
    _has_name,
    _strip_blank_columns,
    _ordered_component_sheets,
    _bus_ref_columns_for_list,
    _drop_broken_bus_refs,
    _ensure_carriers,
    _apply_ts_sheet,
)
from .network_sheet import _apply_network_sheet, _override_network_crs, _peak_load_per_bus

__all__ = ["build_network", "validate_model"]


def build_network(
    model: dict[str, list[dict[str, Any]]],
    scenario: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> tuple[pypsa.Network, list[str]]:
    """Build a solved-ready PyPSA Network from the JSON workbook model.

    Args:
        model:      ``{sheet_name: [row_dict, ...]}`` — the GUI workbook.
        scenario:   ``{carbonPrice, discountRate, constraints, ...}``
        options:    ``{snapshotStart, snapshotCount, snapshotWeight, forceLp,
                    enableLoadShedding, loadSheddingCost, currencySymbol, …}``

    Returns:
        ``(network, notes)``
    """
    notes: list[str] = []
    options = options or {}
    pathway = parse_pathway_config(options.get("pathwayConfig"))

    if "discountRate" not in scenario:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="discountRate is required (set it in Settings).",
        )
    discount_rate = number(scenario.get("discountRate"))
    carbon_price = number(scenario.get("carbonPrice"), 0.0)
    currency = str(options.get("currencySymbol", "$"))

    network = pypsa.Network()

    _apply_network_sheet(network, model, notes)

    # ── Snapshots ─────────────────────────────────────────────────────────────
    # Snapshot dates arrive already normalized to ISO by the frontend (which
    # interprets the user's input Date format), so parse them as-is here.
    snaps_idx = _snapshots_index(model, pathway)
    if len(snaps_idx) > 0:
        network.set_snapshots(snaps_idx)
    _apply_pathway_config(network, pathway, notes)

    # ── Bulk-add every component class PyPSA knows about ──────────────────────
    # Iterate the official component registry — order is dependency-safe
    # (buses before everything that references them, carriers before buses).
    # `network` and `snapshots` are handled explicitly; every other schema-
    # defined sheet should flow through the generic component path.
    ordered = _ordered_component_sheets(network)
    for sheet_name, cls in ordered:
        rows = [r for r in (model.get(sheet_name) or []) if _has_name(r)]
        if not rows:
            continue
        df = pd.DataFrame(rows).set_index("name")
        df = _strip_blank_columns(df)
        allowed_static = input_static_attributes(sheet_name)
        if allowed_static:
            keep = [col for col in df.columns if col in allowed_static or col == "name"]
            df = df.loc[:, keep]
        # Note: zero columns is fine — we still add the components using all
        # PyPSA defaults. Skip only if there are no rows at all.
        if len(df.index) == 0:
            continue
        df = _drop_broken_bus_refs(df, cls, network, sheet_name, notes)
        if len(df.index) == 0:
            continue
        if "carrier" in df.columns and cls != "Carrier":
            _ensure_carriers(network, df["carrier"])
        kwargs = {col: df[col].tolist() for col in df.columns}
        network.add(cls, df.index.tolist(), **kwargs)

    # Generic per-component row count (schema-driven — every populated
    # component class shows up automatically, including new ones PyPSA adds).
    counts = [
        f"{len(network.components[list_name].static)} {list_name}"
        for list_name in network.components.keys()
        if len(network.components[list_name].static) > 0
    ]
    notes.append(
        f"Imported model: {', '.join(counts)}; {len(network.snapshots)} snapshots."
    )

    # ── Time-series sheets ────────────────────────────────────────────────────
    # PyPSA's per-component `defaults` table marks every time-varying attribute
    # (`varying=True`). Sheet name convention is `<list_name>-<attr>`.
    for sheet_name, rows in model.items():
        if not rows or "-" not in sheet_name:
            continue
        list_name, _, attr = sheet_name.partition("-")
        if list_name not in network.components.keys():
            continue
        allowed_temporal = input_temporal_attributes(list_name)
        if allowed_temporal and attr not in allowed_temporal:
            continue
        comp = network.components[list_name]
        if attr not in comp.defaults.index:
            continue
        if not bool(comp.defaults.at[attr, "varying"]):
            continue
        _apply_ts_sheet(network, rows, list_name, attr)
    _normalize_dynamic_snapshot_index_names(network)

    # ── Snapshot windowing & downsampling ─────────────────────────────────────
    start = max(0, int(number(options.get("snapshotStart"), 0)))
    count = max(1, int(number(options.get("snapshotCount"), len(network.snapshots) or 1)))
    step = max(1, int(number(options.get("snapshotWeight"), 1)))
    full = network.snapshots
    if len(full) > 0:
        if pathway.enabled:
            windowed = full
            if step > 1:
                if isinstance(full, pd.MultiIndex):
                    period_levels = list(full.get_level_values("period").unique())
                    pieces = []
                    for period in period_levels:
                        period_index = full[full.get_level_values("period") == period]
                        pieces.append(period_index[::step])
                    if pieces:
                        windowed = pieces[0]
                        for piece in pieces[1:]:
                            windowed = windowed.append(piece)
                else:
                    windowed = full[::step]
            stop = len(full)
            start = 0
        else:
            stop = min(len(full), start + count)
            windowed = full[start:stop]
            if step > 1:
                windowed = windowed[::step]
        if len(windowed) == 0:
            windowed = full[:1]
        network.set_snapshots(windowed)
        for col in ("objective", "stores", "generators"):
            network.snapshot_weightings[col] = float(step)
        notes.append(
            f"Modelled {len(windowed)} snapshots at {step}h resolution "
            f"(rows {start} → {stop} of {len(full)})."
        )
        _normalize_dynamic_snapshot_index_names(network)

    # ── Period-factor scaling of annual energy caps ───────────────────────────
    sim_cfg = load_system_defaults().get("simulation", {})
    hours_in_year = float(sim_cfg.get("hours_in_year", 8760.0))
    if pathway.enabled and isinstance(network.snapshots, pd.MultiIndex):
        period_sizes = network.snapshot_weightings["objective"].groupby(level="period").sum()
        period_factor = min(float(period_sizes.min()) / hours_in_year, 1.0) if len(period_sizes) > 0 else 1.0
    else:
        modelled_hours = float(len(network.snapshots)) * float(step)
        period_factor = min(1.0, modelled_hours / hours_in_year) if modelled_hours > 0 else 1.0
    if period_factor < 1.0:
        for frame in (network.generators, network.storage_units, network.stores):
            for col in list(frame.columns):
                if col.endswith("_sum_min") or col.endswith("_sum_max"):
                    frame[col] = frame[col] * period_factor
        notes.append(f"Scaled annual energy-sum caps by period factor {period_factor:.3f}.")

    # ── Carbon-price adder on generator marginal cost ─────────────────────────
    if carbon_price > 0 and "co2_emissions" in network.carriers.columns:
        ef = network.carriers["co2_emissions"]
        gen_ef = network.generators["carrier"].map(ef).fillna(0.0)
        emitting = gen_ef[gen_ef > 0]
        if not emitting.empty:
            network.generators["marginal_cost"] = (
                network.generators["marginal_cost"].fillna(0.0)
                + carbon_price * gen_ef
            )
            # PyPSA's optimiser prefers a generator's time-varying marginal_cost
            # column over the static value, so the adder must also be applied
            # there or it is silently ignored for generators with a time series.
            # (No double-count: a generator uses either its _t column or the
            # static value, never both.)
            mc_t = network.generators_t.marginal_cost
            for gen in mc_t.columns.intersection(emitting.index):
                mc_t[gen] = mc_t[gen].fillna(0.0) + carbon_price * float(emitting[gen])
            notes.append(
                f"Applied carbon price {carbon_price:.2f} {currency}/t to "
                f"{len(emitting)} emitting generator(s)."
            )

    # ── Annuitise CAPEX for extendable assets ─────────────────────────────────
    # The extendable flag column name varies by component (p_nom_extendable,
    # s_nom_extendable, e_nom_extendable). Find it via PyPSA's defaults.
    for list_name in ("generators", "storage_units", "stores", "lines", "links"):
        comp = network.components[list_name]
        frame = comp.static
        ext_cols = [c for c in frame.columns if c.endswith("_nom_extendable")]
        if not ext_cols or "capital_cost" not in frame.columns:
            continue
        ext = frame[ext_cols[0]].astype(bool)
        if not ext.any():
            continue
        if "lifetime" in frame.columns:
            lifetimes = frame.loc[ext, "lifetime"].replace(0, pd.NA).fillna(20.0)
        else:
            lifetimes = pd.Series(20.0, index=frame.index[ext])
        afs = lifetimes.apply(lambda L: annuity_factor(discount_rate, float(L)))
        frame.loc[ext, "capital_cost"] = frame.loc[ext, "capital_cost"].fillna(0.0) * afs
        notes.append(
            f"Annualised CAPEX for {int(ext.sum())} extendable {comp.name}(s) "
            f"at discount rate {discount_rate:.3f}."
        )

    # ── Force-LP override (ignore committable=True flags) ─────────────────────
    if bool(options.get("forceLp", False)) and "committable" in network.generators.columns:
        n_committable = int(network.generators["committable"].astype(bool).sum())
        if n_committable > 0:
            network.generators["committable"] = False
            notes.append(
                f"Force-LP enabled: overrode committable=True on {n_committable} generator(s)."
            )

    # ── Carbon-price emission factor sanity warning ───────────────────────────
    if "co2_emissions" in network.carriers.columns:
        suspect = network.carriers[network.carriers["co2_emissions"] > 5.0]
        for carrier_name in suspect.index:
            val = float(suspect.at[carrier_name, "co2_emissions"])
            notes.append(
                f"Warning: carrier '{carrier_name}' has co2_emissions={val} "
                f"(expected tCO₂/MWh, real fuels ≤ ~1). If this is kg/MWh, divide by 1000."
            )

    # ── Per-bus load shedding (optional VOLL backstop) ────────────────────────
    load_totals = _peak_load_per_bus(network)
    enable_load_shedding = bool(options.get("enableLoadShedding", False))
    load_shedding_cost = options.get("loadSheddingCost")
    add_load_shedding(
        network,
        load_totals,
        notes,
        enable_load_shedding=enable_load_shedding,
        load_shedding_cost=load_shedding_cost,
        currency=currency,
    )

    # ── Stochastic scenarios (must run after every deterministic setup is in
    # place so the scenario dimension can broadcast over the final values) ──
    stochastic = parse_stochastic_config(options.get("stochasticConfig"))
    if stochastic.enabled:
        apply_scenarios(network, stochastic)
        notes.append(
            "Enabled stochastic mode with "
            + ", ".join(
                f"{s.name} (w={s.weight:.2f}, load×{s.load_multiplier:.2f})"
                for s in stochastic.scenarios
            )
            + "."
        )

    final_counts = ", ".join(
        f"{len(network.components[list_name].static)} {list_name}"
        for list_name in network.components.keys()
        if len(network.components[list_name].static) > 0
    )
    _normalize_dynamic_snapshot_index_names(network)
    notes.append(f"Prepared PyPSA case with {final_counts}.")
    return network, notes


