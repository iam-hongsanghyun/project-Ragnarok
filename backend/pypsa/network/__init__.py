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
  * Period-factor scaling of ``*_sum_min`` / ``*_sum_max`` annual caps
  * Carbon-price adder on generator marginal_cost
  * Annuitisation of capital_cost for extendable assets
  * Force-LP override of committable=True
  * Optional per-bus load shedding generators
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pypsa

from ..carbon_price import apply_carbon_price, parse_carbon_price_config
from ...app.config import load_system_defaults
from ..pathway import parse_pathway_config
from ..rolling import parse_rolling_config
from ..sampling import average_window_frames, parse_sampling_config, sample_block_indices
from ..stochastic import apply_scenarios, parse_stochastic_config
from ..pypsa_schema import (
    input_static_attributes,
    input_temporal_attributes,
)
from ..utils.annuity import annuity_factor
from ..utils.coerce import number
from .demand_response import apply_demand_response, apply_price_elastic
from .load_shedding import add_load_shedding
from .validators import validate_model  # re-export for backend.app.main
from .snapshots import (
    WEIGHTING_COLUMNS,
    imported_weightings,
    rescale_weightings,
    _snapshots_index,
    _apply_pathway_config,
    _normalize_dynamic_snapshot_index_names,
)
from .components import (
    _has_name,
    _strip_blank_columns,
    _ordered_component_sheets,
    _drop_broken_bus_refs,
    _ensure_carriers,
    _apply_ts_sheet,
    _extra_port_columns,
    _is_extra_port_attr,
    _normalize_extra_port_columns,
)
from .network_sheet import _apply_network_sheet, _peak_load_per_bus
from .serialize import ANNOTATION_COLUMNS
from .piecewise import apply_carbon_to_curves, apply_piecewise_sheets, scale_capital_curves

__all__ = ["build_network", "validate_model"]

# Any finite value with absolute magnitude beyond this threshold is treated as
# a placeholder for "no limit". Workbooks exported by upstream tooling often
# store 1e12 in p_nom_max / e_sum_min / e_sum_max / lifetime instead of the
# inf they were meant to represent, which feeds enormous RHS values into the
# LP and degrades HiGHS numerical conditioning (RHS ranges spanning 12+
# orders of magnitude trigger "excessively large row bounds" warnings and
# can push the solver into degenerate / unbounded territory). We snap those
# back to ±inf so PyPSA / linopy drop them at LP build time.
_INF_PLACEHOLDER_THRESHOLD = 1e9


def _sanitize_placeholder_bounds(network: pypsa.Network, notes: list[str]) -> None:
    """Replace 1e12-style placeholder bounds with PyPSA's natural ±inf.

    Touches ``*_nom_max`` / ``*_nom_min`` / ``*_sum_max`` / ``*_sum_min`` and
    ``lifetime`` on every component class. Pure replacement — no math — so
    rows that already used ``inf`` or sensible finite caps are left alone.
    """
    affected = 0
    for list_name in network.components.keys():
        frame = network.components[list_name].static
        if frame.empty:
            continue
        for col in list(frame.columns):
            is_upper = (
                col.endswith("_nom_max") or col.endswith("_sum_max")
                or col in ("lifetime", "v_ang_max")
            )
            is_lower = col.endswith("_sum_min")
            if not (is_upper or is_lower):
                continue
            series = pd.to_numeric(frame[col], errors="coerce")
            mask_up = is_upper and (series >= _INF_PLACEHOLDER_THRESHOLD)
            mask_lo = is_lower and (series <= -_INF_PLACEHOLDER_THRESHOLD)
            mask = (mask_up if is_upper else False) | (mask_lo if is_lower else False)
            try:
                hits = int(mask.sum())
            except Exception:
                hits = 0
            if hits == 0:
                continue
            replacement = np.inf if is_upper else -np.inf
            frame.loc[mask, col] = replacement
            affected += hits
    if affected:
        notes.append(
            f"Sanitised {affected} placeholder bound(s) (≥{_INF_PLACEHOLDER_THRESHOLD:.0e}) → ±inf "
            "to keep the LP numerically well-conditioned."
        )


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


def _relax_commitment(network: pypsa.Network, list_name: str) -> tuple[int, int]:
    """De-commit every committable ``list_name`` component and drop its p_min_pu floor.

    Returns ``(components de-committed, components whose positive p_min_pu — static
    or time-varying — was cleared)``.
    """
    frame = network.components[list_name].static
    if "committable" not in frame.columns:
        return 0, 0
    was_committable = frame["committable"].astype(bool)
    if not was_committable.any():
        return 0, 0
    frame["committable"] = False
    floored: set[str] = set()
    if "p_min_pu" in frame.columns:
        static_floor = was_committable & (frame["p_min_pu"].fillna(0.0) > 0.0)
        floored.update(static_floor.index[static_floor])
        frame.loc[static_floor, "p_min_pu"] = 0.0
    # A time-varying p_min_pu takes precedence over the static value.
    dyn_floor = network.components[list_name].dynamic["p_min_pu"]
    for name in dyn_floor.columns.intersection(was_committable.index[was_committable]):
        if bool((dyn_floor[name].fillna(0.0) > 0.0).any()):
            floored.add(name)
            dyn_floor[name] = 0.0
    return int(was_committable.sum()), len(floored)


def _drop_deprecated_v_ang_min(network: pypsa.Network, notes: list[str]) -> None:
    """Warn about and clear a finite ``v_ang_min`` (deprecated and ignored in PyPSA 1.4).

    PyPSA >= 1.4 enforces ``v_ang_max`` as a symmetric |angle difference| cap in
    degrees and ignores ``v_ang_min`` (emitting a DeprecationWarning). Old
    workbooks that carry a finite ``v_ang_min`` mean "lower bound"; surface that
    their meaning changed, then reset to -inf so no DeprecationWarning fires.
    """
    for list_name in ("lines", "transformers"):
        if list_name not in network.components.keys():
            continue
        frame = network.components[list_name].static
        if "v_ang_min" not in frame.columns:
            continue
        finite = np.isfinite(pd.to_numeric(frame["v_ang_min"], errors="coerce").to_numpy(dtype=float))
        if finite.any():
            frame.loc[finite, "v_ang_min"] = -np.inf
            notes.append(
                f"Warning: v_ang_min is deprecated in PyPSA 1.4 and ignored; cleared it on "
                f"{int(finite.sum())} {list_name}. Use v_ang_max (degrees, symmetric |angle difference| cap)."
            )


def _relax_maintenance(network: pypsa.Network, list_name: str) -> int:
    """Clear ``maintainable`` on ``list_name`` (it adds binary maintenance variables).

    Returns the number of components relaxed. The scheduled-outage binaries make
    the problem a MILP exactly like ``committable``, so Force-LP must drop them.
    """
    if list_name not in network.components.keys():
        return 0
    frame = network.components[list_name].static
    if "maintainable" not in frame.columns:
        return 0
    flagged = frame["maintainable"].astype(bool)
    if not flagged.any():
        return 0
    frame["maintainable"] = False
    return int(flagged.sum())


def _apply_carbon_to_piecewise(network: pypsa.Network, config: Any, notes: list[str]) -> None:
    """Fold the carbon price into generator ``marginal_cost`` curves.

    ``apply_carbon_price`` writes the adder to the scalar / time-series cost, which
    PyPSA ignores for a generator that has a curve. A single price is added to
    every segment; a price schedule cannot be expressed in a time-invariant curve.
    """
    from ..carbon_price import build_price_series
    from ..utils.emissions import per_generator_emission_factor

    if not network.components["generators"].has_piecewise("marginal_cost"):
        return
    if "co2_emissions" not in network.carriers.columns:
        return
    series = build_price_series(network, config)
    if (series <= 0).all():
        return
    if series.nunique(dropna=False) > 1:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="A carbon-price schedule that changes within the run cannot be applied to "
            "generators with a piecewise marginal_cost curve (a curve is time-invariant). "
            "Use a single carbon price, or model the fuel cost outside the curve.",
        )
    ef_carrier = network.carriers["co2_emissions"]
    if isinstance(ef_carrier.index, pd.MultiIndex) and "name" in ef_carrier.index.names:
        ef_carrier = ef_carrier.groupby(level="name").first()
    ef = per_generator_emission_factor(network, ef_carrier.to_dict())
    apply_carbon_to_curves(network, float(series.iloc[0]), ef, notes)



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

def build_network(
    model: dict[str, list[dict[str, Any]]],
    scenario: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> tuple[pypsa.Network, list[str]]:
    """Build a solved-ready PyPSA Network from the JSON workbook model.

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

    # `discountRate` is consumed by exactly one thing: CAPEX annuitisation below.
    # So it is REQUIRED THERE, when there is CAPEX to annuitise, and not here —
    # a dispatch run cannot be affected by it, and demanding it anyway teaches
    # callers to supply a placeholder that then looks like a study input.
    raw_rate = scenario.get("discountRate")
    discount_rate = None if raw_rate is None or raw_rate == "" else number(raw_rate)
    if discount_rate is not None and not (0.0 <= discount_rate < 1.0):
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=(
                f"discountRate must be a fraction with 0 <= r < 1 (e.g. 0.05 for 5 %), "
                f"got {discount_rate:g}. A percentage typed as a whole number (5) would "
                "annuitise capital cost at 500 %."
            ),
        )
    carbon_price = number(scenario.get("carbonPrice"), 0.0)
    currency = str(options.get("currencySymbol", "$"))

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
        df = _drop_broken_bus_refs(df, cls, network, sheet_name, notes)
        if len(df.index) == 0:
            continue
        if "carrier" in df.columns and cls != "Carrier":
            _ensure_carriers(network, df["carrier"])
        df = _coerce_numeric_columns(df, network, sheet_name)
        kwargs = {col: df[col].tolist() for col in df.columns}
        network.add(cls, df.index.tolist(), **kwargs)

    # PyPSA >= 1.3 piecewise-linear curves (`<list>-<attr>-pw` sheets), attached
    # once every component exists; capital curves are annuitised further down.
    apply_piecewise_sheets(network, model, notes, stochastic=stochastic.enabled)

    _sanitize_placeholder_bounds(network, notes)
    _drop_deprecated_v_ang_min(network, notes)

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

    # ── Snapshot windowing & downsampling ─────────────────────────────────────
    start = max(0, int(number(options.get("snapshotStart"), 0)))
    # snapshotCount wins when present. Absent, fall back to snapshotEnd —
    # clients naturally describe the window as [start, end) and the Ragnarok
    # frontend sends both; a payload carrying only snapshotEnd used to be
    # silently solved over ALL snapshots. Absent both, model everything.
    raw_count = options.get("snapshotCount")
    if raw_count in (None, "") and options.get("snapshotEnd") not in (None, ""):
        raw_count = number(options.get("snapshotEnd"), 0) - start
    count = max(1, int(number(raw_count, len(network.snapshots) or 1)))
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
            if sampling.enabled and sampling.mode == "average":
                B = min(max(1, sampling.block_size), max(1, stop - start))
                averaged_periods = average_window_frames(network, start, stop, B)
                windowed = full[start:start + B]
                if step > 1:
                    windowed = windowed[::step]
            elif sampling.enabled:
                idx, sampled_blocks = sample_block_indices(start, stop, sampling, step)
                windowed = full[idx]
            else:
                windowed = full[start:stop]
                if step > 1:
                    windowed = windowed[::step]
        if len(windowed) == 0:
            windowed = full[:1]
        full_weights = network.snapshot_weightings.copy()
        network.set_snapshots(windowed)
        # Weighting. Contiguous runs: every column = stride hours (unchanged).
        # Sampled runs: objective/generators carry W/M so totals, costs and
        # constraint budgets integrate to the FULL window the sample
        # represents; stores keeps the physical stride so the storage SOC
        # recursion stays an hours-true integration inside each block.
        #   w = W / M   (window rows / modelled snapshots; == step when not sampling)
        sampling_active = sampling.enabled and not pathway.enabled
        if sampling_active:
            represented = float(stop - start)
        else:
            represented = float(len(windowed) * step)
        weight = represented / max(1, len(windowed))
        if authored_weights is not None:
            rescaled = rescale_weightings(
                full_weights, full, windowed, start, stop, step, sampling_active
            )
            for col in WEIGHTING_COLUMNS:
                network.snapshot_weightings[col] = rescaled[col].to_numpy()
        else:
            for col in ("objective", "generators"):
                network.snapshot_weightings[col] = weight
            network.snapshot_weightings["stores"] = float(step)
        if sampling_active and sampling.mode == "average":
            notes.append(
                f"Averaged {averaged_periods} period(s) into one {sampling.block_size}-row profile: "
                f"{len(windowed)} snapshots modelled of {stop - start} window rows "
                f"(weight ×{weight:.2f}). Totals represent the full window; "
                "peaks and variability are smoothed by the averaging."
            )
        elif sampling_active:
            notes.append(
                f"Sampled {sampled_blocks} block(s) of up to {sampling.block_size} rows: "
                f"{len(windowed)} snapshots modelled of {stop - start} window rows "
                f"(weight ×{weight:.2f}, {step}h resolution in-block). "
                "Totals are scaled to represent the full window."
            )
        else:
            notes.append(
                f"Modelled {len(windowed)} snapshots at {step}h resolution "
                f"(rows {start} → {stop} of {len(full)})."
            )
        _normalize_dynamic_snapshot_index_names(network)

    # A time-series sheet that skips snapshots the run actually models leaves NaN
    # there, which PyPSA/linopy reads as "no bound" (an unbounded generator).
    # Rows outside the modelled window are irrelevant, so check only now.
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

    # ── Period-factor scaling of annual energy caps ───────────────────────────
    sim_cfg = load_system_defaults().get("simulation", {})
    hours_in_year = float(sim_cfg.get("hours_in_year", 8760.0))
    if pathway.enabled and isinstance(network.snapshots, pd.MultiIndex):
        period_sizes = network.snapshot_weightings["objective"].groupby(level="period").sum()
        period_factor = min(float(period_sizes.min()) / hours_in_year, 1.0) if len(period_sizes) > 0 else 1.0
    else:
        # Sum of objective weights == len * step for contiguous runs (identical
        # to the old len*step form) and == represented window rows for sampled
        # runs, so annual e_sum caps scale by what the run REPRESENTS.
        modelled_hours = float(network.snapshot_weightings["objective"].sum())
        period_factor = min(1.0, modelled_hours / hours_in_year) if modelled_hours > 0 else 1.0
    if period_factor < 1.0:
        for frame in (network.generators, network.storage_units, network.stores):
            for col in list(frame.columns):
                if col.endswith("_sum_min") or col.endswith("_sum_max"):
                    frame[col] = frame[col] * period_factor
        notes.append(f"Scaled annual energy-sum caps by period factor {period_factor:.3f}.")

    # ── Carbon-price adder on generator marginal cost ─────────────────────────
    # A single scalar still works (the legacy path); when the user provides a
    # year→price schedule, the adder becomes per-snapshot. See
    # `backend/pypsa/carbon_price.py` for the year-resolution rule.
    carbon_config = parse_carbon_price_config(
        carbon_price,
        options.get("carbonPriceSchedule"),
    )
    apply_carbon_price(network, carbon_config, notes, currency)
    _apply_carbon_to_piecewise(network, carbon_config, notes)

    # ── Annuitise CAPEX for extendable assets ─────────────────────────────────
    # The extendable flag column name varies by component (p_nom_extendable,
    # s_nom_extendable, e_nom_extendable). Find it via PyPSA's defaults.
    #
    # A workbook `capital_cost` is an OVERNIGHT cost; the network carries the
    # annuitised one. So a caller that builds a network only to serialise it
    # BACK to a workbook (`network_to_model` — the Forge reduce/cluster
    # transform) must opt out: otherwise the reduced workbook stores an
    # already-annuitised cost, the next run annuitises it a second time, and
    # extendable CAPEX collapses to ~AF² of its real value (≈0.6% at r=5%,
    # 20 y), which makes capacity expansion effectively free.
    fallback_lifetime = float(sim_cfg.get("fallback_lifetime_years", 20.0))
    annuitisable: tuple[str, ...] = (
        () if bool(options.get("skipCapexAnnuitisation", False))
        else ("generators", "storage_units", "stores", "lines", "links", "processes")
    )
    # RS1: the LP compares capital cost against operating cost over the modelled
    # window, so the ANNUAL annuity must be pro-rated to that window or a 168 h
    # run builds nothing that an 8760 h run builds. Single-period only: pathway
    # runs weight periods through investment_period_weightings instead. The
    # factor is published in network.meta so reporting does not pro-rate twice.
    modelled_hours_total = float(network.snapshot_weightings["objective"].sum())
    capex_window_scale = 1.0
    window_scaled = 0
    if annuitisable and not pathway.enabled and modelled_hours_total > 0:
        capex_window_scale = modelled_hours_total / hours_in_year
    for list_name in annuitisable:
        comp = network.components[list_name]
        frame = comp.static
        ext_cols = [c for c in frame.columns if c.endswith("_nom_extendable")]
        if not ext_cols or "capital_cost" not in frame.columns:
            continue
        ext = frame[ext_cols[0]].astype(bool)
        if not ext.any():
            continue
        # P15: a finite PyPSA-native `overnight_cost` takes precedence over
        # `capital_cost` and PyPSA annuitises it itself (discount_rate, lifetime,
        # window pro-rating and fom_cost). Those rows must NOT be annuitised or
        # window-scaled a second time here; they only need a discount rate.
        if "overnight_cost" in frame.columns:
            native = ext & pd.to_numeric(frame["overnight_cost"], errors="coerce").notna()
            if native.any():
                if "discount_rate" in frame.columns:
                    dr_col = pd.to_numeric(frame["discount_rate"], errors="coerce")
                    missing = native & dr_col.isna()
                    if missing.any():
                        if discount_rate is None:
                            from fastapi import HTTPException
                            raise HTTPException(
                                status_code=400,
                                detail=(
                                    f"discountRate is required for THIS run: {int(missing.sum())} extendable "
                                    f"{comp.name}(s) carry overnight_cost but no discount_rate. Put "
                                    "scenario={\"discountRate\": 0.05} (or a per-asset discount_rate)."
                                ),
                            )
                        frame.loc[missing, "discount_rate"] = float(discount_rate)
                notes.append(
                    f"{int(native.sum())} extendable {comp.name}(s) use PyPSA-native overnight_cost "
                    "(annuitised by PyPSA with discount_rate/lifetime, plus fom_cost); capital_cost ignored."
                )
                ext = ext & ~native
                if not ext.any():
                    continue
        # 0 × AF is 0 at every rate, so free extendable capacity needs no rate.
        costs = pd.to_numeric(frame.loc[ext, "capital_cost"], errors="coerce").fillna(0.0)
        if not bool(costs.abs().gt(0).any()) and not comp.has_piecewise("capital_cost"):
            continue
        if discount_rate is None:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail=(
                    f"discountRate is required for THIS run: {int(ext.sum())} "
                    f"extendable {comp.name}(s) carry a capital cost, and the "
                    "discount rate is what turns that overnight cost into the "
                    "annual one the objective compares against fuel. It belongs in "
                    "`scenario`, not `options` — e.g. "
                    "scenario={\"discountRate\": 0.05}. (In the GUI: Settings -> "
                    "Discount rate.) No default is applied on purpose: a low rate "
                    "makes new capacity look cheap and a high one makes it look "
                    "expensive, so how much gets built depends on this number. "
                    "A run with no expandable capacity needs no rate at all."
                ),
            )
        if "lifetime" in frame.columns:
            # PyPSA DEFAULTS lifetime to +inf, which has no finite annuity factor
            # (annuity_factor(rate, inf) → NaN). Without this guard the extendable
            # asset's capital_cost annuitises to NaN → 0 in the objective, so it
            # builds for FREE up to its max. Treat inf / NaN / ≤0 as the system-default
            # fallback lifetime (noted) so CAPEX is actually priced.
            lifetimes = pd.to_numeric(frame.loc[ext, "lifetime"], errors="coerce")
            usable = (lifetimes > 0) & (lifetimes < float("inf"))
            if not bool(usable.all()):
                notes.append(
                    f"{int((~usable).sum())} extendable {comp.name}(s) have no finite lifetime — "
                    f"annuitised over the system default of {fallback_lifetime:g} years "
                    "(simulation.fallback_lifetime_years)."
                )
            lifetimes = lifetimes.where(usable, fallback_lifetime)
        else:
            lifetimes = pd.Series(fallback_lifetime, index=frame.index[ext])
            notes.append(
                f"{int(ext.sum())} extendable {comp.name}(s) carry no lifetime column — "
                f"annuitised over the system default of {fallback_lifetime:g} years."
            )
        afs = lifetimes.apply(lambda L: annuity_factor(discount_rate, float(L)))
        frame.loc[ext, "capital_cost"] = frame.loc[ext, "capital_cost"].fillna(0.0) * afs
        scale_capital_curves(network, list_name, afs)  # piecewise capital curves: same annuity
        notes.append(
            f"Annualised CAPEX for {int(ext.sum())} extendable {comp.name}(s) "
            f"at discount rate {discount_rate:.3f}."
        )
        if capex_window_scale != 1.0:
            frame.loc[ext, "capital_cost"] = frame.loc[ext, "capital_cost"] * capex_window_scale
            scale_capital_curves(
                network, list_name, pd.Series(capex_window_scale, index=frame.index[ext])
            )
            window_scaled += int(ext.sum())
    if window_scaled:
        network.meta["ragnarok_capex_window_scale"] = float(capex_window_scale)
        notes.append(
            f"Scaled annualised CAPEX of {window_scaled} extendable asset(s) to the modelled "
            f"window (x{capex_window_scale:.4g} = {modelled_hours_total:g} h / "
            f"{hours_in_year:g} h) so expansion trades against the energy it serves."
        )

    # ── Force-LP override (ignore committable=True flags) ─────────────────────
    # Generators and Links share the commitment machinery (status / start-up
    # variables → MIP), so both are relaxed. `p_min_pu` means "minimum output
    # WHILE RUNNING" only for a committable unit; on a plain LP component it is
    # an unconditional floor in every snapshot, so leaving it behind would not
    # relax the MILP — it would replace it with a TIGHTER problem the unit can
    # never switch off. Static AND time-varying floors are therefore cleared.
    if bool(options.get("forceLp", False)):
        for list_name, label in (
            ("generators", "generator"), ("links", "link"), ("processes", "process"),
        ):
            n_committable, n_floor = _relax_commitment(network, list_name)
            if n_floor:
                notes.append(
                    f"Force-LP: also cleared p_min_pu on {n_floor} de-committed {label}(s) — "
                    "without commitment it is an always-on floor, not a minimum-when-running."
                )
            if n_committable:
                notes.append(
                    f"Force-LP enabled: overrode committable=True on {n_committable} {label}(s)."
                )
        for list_name, label in (
            ("generators", "generator"), ("links", "link"), ("processes", "process"),
        ):
            n_maint = _relax_maintenance(network, list_name)
            if n_maint:
                notes.append(
                    f"Force-LP enabled: overrode maintainable=True on {n_maint} {label}(s) "
                    "(scheduled-maintenance binaries removed)."
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


