"""Build a PyPSA Network from the in-memory workbook model.

The frontend POSTs the workbook to /api/queue as a per-sheet JSON object:
``model: {sheet_name: [row_dict, ...]}``. We turn each sheet into a pandas
DataFrame and use PyPSA's bulk `network.add()` API to import every column
the user provided. The mapping between sheet names, PyPSA component classes,
time-varying attributes and bus-reference columns is **derived from PyPSA's
own component registry** (`n.components`) so nothing is hardcoded here — when
a new PyPSA version adds attributes or component types, they Just Work.

After import we apply five small post-load transformations that depend on
Settings rather than on the workbook:
  * Snapshot windowing & downsampling
  * Annual-budgets module: yearly e_sum / CO2-cap values from RAGNAROK_AnnualBudgets -> PyPSA horizon totals
  * Carbon price recorded in ``network.meta`` (the module adds it to the objective; marginal_cost is untouched)
  * Annuitisation of capital_cost for extendable assets
  * Force-LP override of committable=True
  * Optional per-bus load shedding generators
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pypsa

from ...app.carbon_pricing import build_notes as carbon_notes, config_from_run as carbon_config_from_run, set_plan as set_carbon_plan
from ...app import annual_budgets
from ..pathway import parse_pathway_config
from ..rolling import parse_rolling_config, resolve_rolling
from ..sampling import apply_test_run_sampling, parse_sampling_config
from ..stochastic import apply_scenarios, parse_stochastic_config
from ..pypsa_schema import (
    input_static_attributes,
    input_temporal_attributes,
)
from ..utils.coerce import number
from .demand_response import apply_demand_response, apply_price_elastic
from .load_shedding import add_load_shedding
from .validators import validate_model  # re-export for backend.app.main
from . import time_units
from .legacy_window import apply_legacy_window
from .snapshots import (
    WEIGHTING_COLUMNS,
    imported_weightings,
    _snapshots_index,
    _apply_pathway_config,
    _normalize_dynamic_snapshot_index_names,
)
from .components import (
    _has_name,
    _strip_blank_columns,
    _ordered_component_sheets,
    refuse_unknown_buses,
    _ensure_carriers,
    _apply_ts_sheet,
    _extra_port_columns,
    _is_extra_port_attr,
    _normalize_extra_port_columns,
)
from .network_sheet import _apply_network_sheet, _peak_load_per_bus
from .serialize import ANNOTATION_COLUMNS
from .piecewise import apply_piecewise_sheets

__all__ = ["build_components", "build_network", "build_stored_network", "validate_model"]

_TRUE_TOKENS = frozenset({"true", "1", "yes", "y", "t", "on"})
_FALSE_TOKENS = frozenset({"false", "0", "no", "n", "f", "off"})


def _as_bool(value: Any, default: bool) -> bool:
    """Read a workbook cell as a boolean: ``"FALSE"``/``"0"``/``"no"`` are False.

    ``bool("FALSE")`` is True, so a string-typed boolean column would flip every
    flag on. Blanks and unrecognised text fall back to the attribute default.
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return default
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        return bool(value)
    token = str(value).strip().lower()
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    return default


def _coerce_numeric_columns(
    df: "pd.DataFrame", network: pypsa.Network, list_name: str
) -> "pd.DataFrame":
    """Coerce numeric / boolean columns; blanks/junk → the PyPSA default.

    A re-imported workbook can carry empty-string cells in numeric columns
    (optional fields left blank). Passed straight to ``network.add`` PyPSA tries
    ``float('')`` and raises *"could not convert string to float: ''"*. Here we
    coerce each float/int-typed column with ``to_numeric(errors='coerce')`` and
    fill the resulting NaNs with the attribute's PyPSA default — exactly what an
    *absent* column would have produced — so a blank cell can never crash a run.
    """
    defaults = network.components[list_name].defaults
    for col in list(df.columns):
        if col in defaults.index and defaults.at[col, "dtype"].kind == "b":
            df[col] = df[col].map(lambda v, d=bool(defaults.at[col, "default"]): _as_bool(v, d))
            continue
        if col not in defaults.index or defaults.at[col, "dtype"].kind not in ("f", "i"):
            continue
        coerced = pd.to_numeric(df[col], errors="coerce")
        df[col] = coerced.fillna(defaults.at[col, "default"])
    return df


def _carry_plant_ids(network: pypsa.Network, model: dict[str, Any]) -> None:
    """Copy the :data:`ANNOTATION_COLUMNS` of the workbook rows onto the network's static frames.

    The builder keeps only schema attributes, so without this a PyPSA file exported from the workbook would
    lose which components form one plant. Rows with no value stay blank. Not an LP input.
    """
    for list_name in network.components.keys():
        rows = model.get(list_name)
        if not isinstance(rows, list) or not rows:
            continue
        frame = network.components[list_name].static
        if frame.empty or isinstance(frame.index, pd.MultiIndex):
            continue
        for col in ANNOTATION_COLUMNS:
            tags = {str(r.get("name")): str(r.get(col)) for r in rows
                    if isinstance(r, dict) and r.get(col) not in (None, "") and r.get("name") not in (None, "")}
            if tags:
                frame[col] = [tags.get(str(i), "") for i in frame.index]

def _load_model(
    model: dict[str, list[dict[str, Any]]],
    pathway: Any,
    notes: list[str],
    *,
    stochastic_enabled: bool = False,
) -> tuple[pypsa.Network, dict[str, pd.Index], pd.DataFrame | None]:
    """Hand the workbook to PyPSA 1:1: the network sheet, snapshots, every component and time series.

    No run-time conversion happens here: values go in exactly as the workbook holds them.
    Placeholder bounds (1e9+ standing for "no limit") and a deprecated ``v_ang_min`` go to PyPSA as written
    (PyPSA warns about ``v_ang_min``); the visible clean-up is ``forge_helpers.clean_placeholder_bounds``.

    Returns:
        ``(network, uncovered_by_sheet, authored_weights)``.
    """
    network = pypsa.Network()

    _apply_network_sheet(network, model, notes)

    # ── Snapshots ─────────────────────────────────────────────────────────────
    # Snapshot dates arrive already normalized to ISO by the frontend (which
    # interprets the user's input Date format), so parse them as-is here.
    snaps_idx = _snapshots_index(model, pathway, notes)
    if len(snaps_idx) > 0:
        network.set_snapshots(snaps_idx)
    _apply_pathway_config(network, pathway, notes)
    # RB9: weightings authored on the snapshots sheet (PyPSA snapshots.csv
    # `objective`/`stores`/`generators`) are kept, not overwritten by a 1 h
    # stride further down.
    authored_weights = imported_weightings(model, network.snapshots)
    if authored_weights is not None:
        for col in WEIGHTING_COLUMNS:
            if col in authored_weights.columns:
                network.snapshot_weightings[col] = authored_weights[col].to_numpy()
        notes.append(
            "Kept snapshot weightings from the snapshots sheet "
            f"(sum {float(network.snapshot_weightings['objective'].sum()):g} h)."
        )

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
            # Multi-port Link columns (bus2+/efficiency2+) are not in the
            # static schema — PyPSA registers them dynamically — but they are
            # real model inputs; keep them alongside the schema columns.
            extra_ports = _extra_port_columns(sheet_name, df.columns)
            keep = [
                col for col in df.columns
                if col in allowed_static or col == "name" or col in extra_ports
            ]
            df = df.loc[:, keep]
        df = _normalize_extra_port_columns(df, sheet_name)
        # Note: zero columns is fine — we still add the components using all
        # PyPSA defaults. Skip only if there are no rows at all.
        if len(df.index) == 0:
            continue
        if "carrier" in df.columns and cls != "Carrier":
            _ensure_carriers(network, df["carrier"], notes)
        df = _coerce_numeric_columns(df, network, sheet_name)
        kwargs = {col: df[col].tolist() for col in df.columns}
        network.add(cls, df.index.tolist(), **kwargs)

    refuse_unknown_buses(network)  # PyPSA's own check, strict: no silent row drops

    # PyPSA >= 1.3 piecewise-linear curves (`<list>-<attr>-pw` sheets), attached
    # once every component exists.
    apply_piecewise_sheets(network, model, notes, stochastic=stochastic_enabled)

    _carry_plant_ids(network, model)

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
    uncovered_by_sheet: dict[str, pd.Index] = {}
    for sheet_name, rows in model.items():
        if not rows or "-" not in sheet_name:
            continue
        list_name, _, attr = sheet_name.partition("-")
        if list_name not in network.components.keys():
            continue
        allowed_temporal = input_temporal_attributes(list_name)
        if (
            allowed_temporal
            and attr not in allowed_temporal
            and not _is_extra_port_attr(list_name, attr)
        ):
            # Multi-port attrs (efficiency2+) aren't in the static schema but
            # ARE varying once PyPSA registers the port; the defaults check
            # below still gates on the port actually existing on the network.
            continue
        comp = network.components[list_name]
        if attr not in comp.defaults.index:
            continue
        if not bool(comp.defaults.at[attr, "varying"]):
            continue
        gaps = _apply_ts_sheet(network, rows, list_name, attr, notes)
        if len(gaps) > 0:
            uncovered_by_sheet[sheet_name] = gaps
    _normalize_dynamic_snapshot_index_names(network)

    return network, uncovered_by_sheet, authored_weights


def _require_discount_rate_for_overnight(network: pypsa.Network) -> None:
    """Refuse a run whose ``overnight_cost`` rows lack a ``discount_rate``.

    PyPSA annuitises ``overnight_cost`` with the row's own ``discount_rate`` and refuses to
    guess one (``check_cost_consistency``). Ragnarok does not fill it in at run time either:
    the column has to be in the workbook (Forge -> Fill discount rate).
    """
    from fastapi import HTTPException

    for comp in network.components.values():
        frame = comp.static
        if frame.empty or "overnight_cost" not in frame.columns or "discount_rate" not in frame.columns:
            continue
        overnight = pd.to_numeric(frame["overnight_cost"], errors="coerce").notna()
        missing = overnight & pd.to_numeric(frame["discount_rate"], errors="coerce").isna()
        if bool(missing.any()):
            names = ", ".join(map(str, frame.index[missing][:5])) + ("..." if int(missing.sum()) > 5 else "")
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{int(missing.sum())} {comp.name} row(s) carry an overnight_cost but no discount_rate "
                    f"({names}). PyPSA annuitises overnight_cost with the row's own discount_rate and does "
                    "not guess one. Write it into the workbook: Forge -> Fill discount rate "
                    "(or set a discount_rate per asset)."
                ),
            )


def build_components(
    model: dict[str, list[dict[str, Any]]],
    options: dict[str, Any] | None = None,
) -> tuple[pypsa.Network, list[str]]:
    """The workbook as a PyPSA network, 1:1 and nothing else.

    Use this for every build whose network is serialised BACK to a workbook (Forge
    transforms, netcdf / hdf5 export). :func:`build_network` is the run builder: it
    also windows the snapshots, records the carbon price for the carbon-pricing module
    (an objective term, not a cost conversion), runs the annual-budgets module, adds load shedding and demand response, and relaxes commitment - each
    correct for a solve and each wrong in a workbook the user keeps. None of that happens here, and no cost is
    ever converted (``capital_cost`` / ``overnight_cost`` / ``fom_cost`` pass through).

    Only ``options["pathwayConfig"]`` is read: it decides whether the snapshots carry
    investment periods. The whole time axis is built.

    Returns:
        ``(network, notes)``.
    """
    notes: list[str] = []
    pathway = parse_pathway_config((options or {}).get("pathwayConfig"))
    network, uncovered_by_sheet, _weights = _load_model(model, pathway, notes)
    _raise_on_uncovered_snapshots(network, uncovered_by_sheet)
    return network, notes


def _raise_on_uncovered_snapshots(network: pypsa.Network, uncovered_by_sheet: dict[str, pd.Index]) -> None:
    """A time-series sheet that skips snapshots the build uses would read NaN there (an unbounded bound)."""
    for sheet_name, gaps in uncovered_by_sheet.items():
        missing = gaps.intersection(network.snapshots)
        if len(missing) > 0:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Time-series sheet '{sheet_name}' has no row for {len(missing)} of the "
                    f"{len(network.snapshots)} modelled snapshot(s) (first: {missing[0]}). "
                    "A missing value would drop that bound in the LP, so the run is refused — "
                    "add the missing rows, or remove the sheet to use the static value."
                ),
            )


def build_stored_network(
    model: dict[str, list[dict[str, Any]]],
    scenario: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> tuple[pypsa.Network, list[str]]:
    """:func:`build_network` for a STORED run's inputs (re-derivation of analytics, no solve).

    A run solved before ``buildVersion`` was stamped holds an overnight ``capital_cost`` that the old
    builder annuitised; it is migrated in memory first (:func:`cost_basis.model_for_stored_run`) so
    PyPSA reproduces the stored numbers. A stamped run goes straight through.
    """
    from .cost_basis import build_version_of, legacy_e_sum_scale, model_for_stored_run

    current, report = model_for_stored_run(model, scenario, options)
    version = build_version_of(model, options)
    network, notes = build_network(current, scenario, options, legacy=version is None or version < 4)
    factor = legacy_e_sum_scale(network, build_version_of(model, options))
    if factor is not None:
        notes.append(f"Stored run from before build version 3: annual energy-sum caps scaled by {factor:.3f}, as it was solved.")
    if report is not None and report.changed_rows:
        notes.append(
            f"Stored run from before the PyPSA cost basis: {len(report.changed_rows)} capital cost row(s) read as "
            f"overnight_cost at the run's discount rate ({report.discount_rate:g}) - the same figures it was solved with."
        )
    return network, notes


def build_network(
    model: dict[str, list[dict[str, Any]]],
    scenario: dict[str, Any],
    options: dict[str, Any] | None = None,
    *,
    legacy: bool = False,
) -> tuple[pypsa.Network, list[str]]:
    """Build a solved-ready PyPSA Network from the JSON workbook model.

    ``legacy`` is for re-deriving a STORED run from before build version 4 only (see :mod:`.legacy_window`):
    it windows with the stride / sampled weights that run was solved with. A new run never sets it.

    Args:
        model:      ``{sheet_name: [row_dict, ...]}`` — the GUI workbook.
        scenario:   ``{carbonPrice, discountRate, constraints, ...}``.
                    ``discountRate`` is required only when the run has extendable
                    capacity carrying a capital cost — it annuitises that cost, and
                    nothing else reads it. Dispatch-only runs may omit it.
        options:    ``{snapshotStart, snapshotCount, snapshotWeight, forceLp,
                    enableLoadShedding, loadSheddingCost, currencySymbol, …}``

    Returns:
        ``(network, notes)``
    """
    notes: list[str] = []
    options = options or {}
    pathway = parse_pathway_config(options.get("pathwayConfig"))
    sampling = parse_sampling_config(options.get("samplingConfig"))
    stochastic = parse_stochastic_config(options.get("stochasticConfig"))
    rolling = parse_rolling_config(options.get("rollingConfig"))

    # RS6: the custom-constraint compilers index ``Generator-p`` by (snapshot,
    # name); under stochastic mode linopy adds a scenario level, so they would
    # crash mid-solve with a tuple-index error. Refuse up front, clearly.
    if stochastic.enabled:
        active = [
            what for what, present in (
                ("custom constraints", any(
                    isinstance(c, dict) and c.get("enabled", False)
                    for c in scenario.get("constraints") or []
                )),
                ("constraint specs", bool(scenario.get("constraintSpecs"))),
                ("DSL constraints", bool(str(scenario.get("customDsl") or "").strip())),
            ) if present
        ]
        if active:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Stochastic scenarios cannot be combined with {' / '.join(active)}: "
                    "they are not scenario-aware yet and would be built on the wrong "
                    "variable dimensions. Disable them, or turn stochastic mode off."
                ),
            )

    # `discountRate` no longer converts anything: costs go to PyPSA as the workbook holds
    # them, and each overnight_cost row carries its own discount_rate. The scenario value
    # is the project setting Forge writes INTO the workbook (Fill discount rate); it is
    # still range-checked so a percentage typed as 5 cannot be written as 500 %.
    raw_rate = scenario.get("discountRate")
    discount_rate = None if raw_rate is None or raw_rate == "" else number(raw_rate)
    if discount_rate is not None and not (0.0 <= discount_rate < 1.0):
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=(
                f"discountRate must be a fraction with 0 <= r < 1 (e.g. 0.05 for 5 %), "
                f"got {discount_rate:g}. A percentage typed as a whole number (5) would "
                "be written as a 500 % discount rate."
            ),
        )
    currency = str(options.get("currencySymbol", "$"))

    network, uncovered_by_sheet, authored_weights = _load_model(
        model, pathway, notes, stochastic_enabled=stochastic.enabled
    )

    # ── Snapshot window ────────────────────────────────────────────────────────
    # Core slices the window and keeps the workbook's weightings as they are. It never strides: resolution is a
    # visible transform (Forge -> Temporal, which writes the reduced snapshots, weightings and series). Test-run
    # sampling is a module (backend/pypsa/sampling.py) that writes sampled snapshots and weightings.
    start = max(0, int(number(options.get("snapshotStart"), 0)))
    # snapshotCount wins when present. Absent, fall back to snapshotEnd —
    # clients naturally describe the window as [start, end) and the Ragnarok
    # frontend sends both; a payload carrying only snapshotEnd used to be
    # silently solved over ALL snapshots. Absent both, model everything.
    raw_count = options.get("snapshotCount")
    if raw_count in (None, "") and options.get("snapshotEnd") not in (None, ""):
        raw_count = number(options.get("snapshotEnd"), 0) - start
    count = max(1, int(number(raw_count, len(network.snapshots) or 1)))
    stride = max(1, int(number(options.get("snapshotWeight"), 1)))
    full = network.snapshots
    if stride > 1 and not legacy:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=(
                f"snapshotWeight={stride} (a run-time stride) is no longer a run option: it point-sampled every {stride}th row. "
                f"Reduce the resolution as a visible transform instead - Forge -> Temporal (resample '{stride}h' takes block means "
                "and writes the snapshots, the weightings and the aggregated series into the workbook; "
                "POST /api/transform/temporal) - then run at snapshotWeight 1."
            ),
        )
    if len(full) > 0 and legacy:
        apply_legacy_window(network, options, pathway, sampling, authored_weights, notes)
        _normalize_dynamic_snapshot_index_names(network)
    elif len(full) > 0:
        if pathway.enabled:
            if sampling.enabled:
                notes.append("Test-run sampling ignored: a pathway run defines its horizon with investment periods.")
        else:
            stop = min(len(full), start + count)
            if sampling.enabled:
                apply_test_run_sampling(network, start, stop, sampling, notes)
            else:
                windowed = full[start:stop]
                if len(windowed) == 0:
                    windowed = full[:1]
                if len(windowed) != len(full):
                    network.set_snapshots(windowed)
                notes.append(f"Modelled {len(windowed)} snapshots (rows {start} → {stop} of {len(full)}).")
        _normalize_dynamic_snapshot_index_names(network)

    # A time-series sheet that skips snapshots the run actually models leaves NaN
    # there, which PyPSA/linopy reads as "no bound" (an unbounded generator).
    # Rows outside the modelled window are irrelevant, so check only now.
    _raise_on_uncovered_snapshots(network, uncovered_by_sheet)

    # ── Annual budgets (module): per-year e_sum / CO2-cap values -> PyPSA horizon totals ──
    # Only rows of RAGNAROK_AnnualBudgets are touched; every other e_sum / constant passes through.
    try:
        annual_budget_table = annual_budgets.apply_to_network(network, model, notes, check_spacing=not sampling.enabled, rolling=rolling.enabled, enabled=not (isinstance(options.get("annualBudgets"), dict) and options["annualBudgets"].get("enabled") is False))
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    del annual_budget_table

    # ── Time units (module): ramps and UC times in hours -> PyPSA per-snapshot values ──
    # The weights are final here (window / sampling done), so the conversion uses what the solve will use.
    try:
        time_units.apply_to_network(
            network, time_units.with_rows(model, time_units.ramp_config_rows(model, options.get("rampConfig"))), notes,
        )
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # ── Carbon price: declared, not converted ────────────────────────────────
    # The price is NOT written into marginal_cost. The network records the price it was built for
    # (network.meta) and the carbon-pricing module adds `price x emissions` to the objective in
    # `extra_functionality` (backend/app/carbon_pricing). `*_sum_min/max` pass through as PyPSA's
    # whole-horizon totals; the annual-budgets module writes them (backend/app/annual_budgets).
    carbon_config = carbon_config_from_run(scenario, options)
    set_carbon_plan(network, carbon_config)
    notes.extend(carbon_notes(network, carbon_config, currency))

    # ── Cost basis ────────────────────────────────────────────────────────────
    # Nothing is converted here. `capital_cost` is PyPSA's periodised cost per
    # modelled horizon and `overnight_cost` is annuitised by PyPSA itself
    # (annuity(discount_rate, lifetime) x nyears, plus `fom_cost`; pypsa.costs).
    # A row that carries an overnight_cost therefore has to carry its discount_rate.
    _require_discount_rate_for_overnight(network)

    # ── Force-LP ──────────────────────────────────────────────────────────────
    # Force-LP is PyPSA's `linearized_unit_commitment` (run_pypsa passes it to n.optimize): the committable
    # binaries become continuous and every UC constraint stays. Nothing is cleared here. PyPSA has no switch for
    # the `maintainable` binaries, so a maintainable unit is refused with the visible action that relaxes it.
    if bool(options.get("forceLp", False)):
        from fastapi import HTTPException

        maint = [
            f"{label} {name}"
            for list_name, label in (("generators", "generator"), ("links", "link"), ("processes", "process"))
            if list_name in network.components.keys()
            and "maintainable" in network.components[list_name].static.columns
            for name in network.components[list_name].static.index[network.components[list_name].static["maintainable"].astype(bool)]
        ]
        if maint:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Force-LP cannot relax scheduled maintenance: PyPSA has no switch for the maintainable binaries "
                    f"({', '.join(maint[:4])}{'...' if len(maint) > 4 else ''}). Run the visible workbook step "
                    "'Relax maintenance' (Forge -> Operations; POST /api/model/relax-maintenance) to write maintainable = False, "
                    "or turn Force-LP off."
                ),
            )
        notes.append(
            "Force-LP: committable binaries relaxed by PyPSA (linearized_unit_commitment); status, start-up and the "
            "minimum-load / ramp / minimum up-down-time constraints are kept as continuous relaxations."
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

    # ── Demand response (shiftable load) — rewire tagged loads into the DR
    # bus + Link + Store pattern before stochastic broadcasting ────────────────
    dr_cfg = options.get("demandResponseConfig") or {}
    if dr_cfg.get("enabled"):
        apply_demand_response(
            network,
            notes,
            enabled=True,
            loads=dr_cfg.get("loads") or None,
            shift_fraction=float(dr_cfg.get("shiftFraction", 0.2) or 0.0),
            max_shift_hours=float(dr_cfg.get("maxShiftHours", 4.0) or 0.0),
        )
    if dr_cfg.get("elasticEnabled"):
        apply_price_elastic(
            network,
            notes,
            enabled=True,
            loads=dr_cfg.get("loads") or None,
            fraction=float(dr_cfg.get("elasticFraction", 0.2) or 0.0),
            wtp_max=float(dr_cfg.get("wtpMax", 200.0) or 0.0),
        )

    # ── Stochastic scenarios (must run after every deterministic setup is in
    # place so the scenario dimension can broadcast over the final values) ──
    if stochastic.enabled:
        apply_scenarios(network, stochastic)
        notes.append(
            "Enabled stochastic mode with "
            + ", ".join(
                f"{s.name} (w={s.weight:.2f}, {len(s.overrides)} override{'s' if len(s.overrides) != 1 else ''})"
                for s in stochastic.scenarios
            )
            + "."
        )

    if rolling.enabled:
        rolling = resolve_rolling(rolling, time_units.step_hours(network)[0], notes)
        # Rows each rolling window COMMITS (horizon - overlap): custom/DSL
        # budgets are apportioned by these hours so overlapping windows do not
        # each spend a full share (see ModelContext.window_fraction).
        network.meta["ragnarok_rolling_step"] = int(rolling.step_snapshots)

    final_counts = ", ".join(
        f"{len(network.components[list_name].static)} {list_name}"
        for list_name in network.components.keys()
        if len(network.components[list_name].static) > 0
    )
    _normalize_dynamic_snapshot_index_names(network)
    notes.append(f"Prepared PyPSA case with {final_counts}.")
    return network, notes


