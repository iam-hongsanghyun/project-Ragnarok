"""
ragnarok-dashboard-importer — build engine (vendored by plugin.py)
==================================================================
The Ragnarok backend runs NO plugin code during the solve, so everything this
plugin wants to affect at solve time must travel **as data** in the model it
returns. Entry points (dispatched by plugin.py; host contract in
backend/app/plugins.py):

* **transform(model, scenario, options)** — builds a complete PyPSA network
  from the GUI settings (+ optional uploaded dashboard / model workbooks),
  converts it to a Ragnarok workbook model dict, and returns it; the host
  replaces the session model with the return value. No solver runs here.

  - CF capacity-factor limits are emitted as DSL lines in a
    ``RAGNAROK_CustomDSL`` sheet (see ``_custom_dsl_from_cf``); Ragnarok's
    core DSL compiler applies them at solve time.
  - The carbon price is folded into generator marginal costs at build time
    (see ``_apply_carbon_price_marginal_cost``) — objective-equivalent to the
    retired in-solve hook, and visible in marginal-cost-derived outputs.

* **payload builders** (``capacity_payload``, ``replacement_plan_payload``,
  ``generator_filter_values_payload``, …) — answer the plugin's ``options`` /
  ``analyze`` / action hooks.

Typical workflow
----------------
1. Configure settings in the plugin Input tab (upload the model workbook once).
2. Click "Build & load into Ragnarok" — the session model is replaced.
3. Topbar Run solves it; the CF DSL and carbon-adjusted costs are already in
   the model.
"""

from __future__ import annotations

import base64
import logging
import math
import re
import sys
import tempfile
import threading
from datetime import date, datetime
import importlib
import importlib.util
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

PLUGIN_ROOT = Path(__file__).resolve().parent

MODEL_SHEETS = [
    "network",
    "snapshots",
    "carriers",
    "buses",
    "generators",
    "loads",
    "links",
    "lines",
    "stores",
    "storage_units",
    "transformers",
    "shunt_impedances",
    "global_constraints",
    "shapes",
    "processes",
    "generators-p_max_pu",
    "generators-p_min_pu",
    "loads-p_set",
    "storage_units-inflow",
    "links-p_max_pu",
]

TS_SHEET_ATTRS = {
    "generators-p_max_pu": ("generators", "p_max_pu"),
    "generators-p_min_pu": ("generators", "p_min_pu"),
    "loads-p_set": ("loads", "p_set"),
    "storage_units-inflow": ("storage_units", "inflow"),
    "links-p_max_pu": ("links", "p_max_pu"),
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def transform(
    model: dict[str, list[dict[str, Any]]],
    scenario: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Build a Ragnarok workbook model from GUI settings and table edits.

    The returned model completely replaces the current Ragnarok workbook —
    no rows from the existing workbook are carried over.
    """
    del model, scenario  # existing workbook is intentionally discarded

    module_config = options.get("moduleConfig", {})
    dashboard_path = _resolve_dashboard_path(module_config)
    base_dir = dashboard_path.parent if dashboard_path is not None else Path.cwd()
    export_path = _resolve_export_path(module_config, base_dir)

    logger.info(
        "[dashboard-importer] mode=%s",
        "xlsx+gui" if dashboard_path is not None else "gui-only",
    )

    network = _build_dashboard_network(dashboard_path, module_config)
    imported_model = _network_to_model(network)

    # Emit CF constraints INTO the workbook so they reach the Ragnarok frontend
    # (Advanced Constraints DSL) and are applied on Run via constraintSpecs.
    # Ragnarok runs no plugin code during the solve, so constraints must travel
    # inside the model. (The carbon price can't be expressed as DSL — it is an
    # objective cost, not a bound — so it is folded into marginal costs during
    # the build; see _apply_carbon_price_marginal_cost.)
    custom_dsl = _custom_dsl_from_cf(network, module_config)
    if custom_dsl:
        imported_model["RAGNAROK_CustomDSL"] = [{"text": custom_dsl}]
        logger.info("[dashboard-importer] emitted CF constraints to RAGNAROK_CustomDSL")

    if export_path is not None:
        _write_model_workbook(imported_model, export_path)
        logger.info("[dashboard-importer] wrote debug workbook to %s", export_path)

    logger.info(
        "[dashboard-importer] replacing workbook — %d buses, %d generators, %d loads, %d snapshots",
        len(imported_model["buses"]),
        len(imported_model["generators"]),
        len(imported_model["loads"]),
        len(imported_model["snapshots"]),
    )
    return imported_model


# ---------------------------------------------------------------------------
# Carbon price → marginal-cost adder (build-time)
# ---------------------------------------------------------------------------


def _apply_carbon_price_marginal_cost(network: Any, dashboard: Any) -> None:
    """Fold the carbon cost into generator marginal costs at build time.

    Replaces the retired in-solve ``apply_constraints`` objective term —
    Ragnarok runs no plugin code during the solve, so the carbon cost must
    live in the model itself.

    Algorithm:
        $$ mc_g \\mathrel{+}= I_c \\cdot P \\cdot X / 1000
           \\quad \\forall g \\in \\text{carrier } c $$
        ASCII: mc_g += intensity_c[kg CO2/MWh] * price[cp-currency/tCO2]
                       * fx[model-currency per cp-currency] / 1000

    where ``I_c`` is the carrier's emission intensity for the target year
    (kg CO₂/MWh), ``P`` the carbon price for the chosen scenario and target
    year (per tCO₂, in whatever currency the carbon-price curves are quoted
    in), and ``X`` the ``currency_exchange`` setting (model-currency units per
    one unit of that carbon-price currency — no currency is hardcoded here);
    /1000 converts kg→t. The objective contribution Σ p·adder is exactly the
    retired hook's carbon term, and the cost is now visible in
    marginal-cost-derived outputs (e.g. merit order).

    Must run AFTER ``apply_marginal_cost_multipliers`` (the per-carrier
    multiplier scales fuel cost only — never the carbon adder, matching the
    original design where the objective term bypassed multipliers) and BEFORE
    region aggregation (a uniform per-carrier additive adder commutes with the
    capacity-weighted carrier merge). Static ``marginal_cost`` only — this
    pipeline never emits time-varying marginal costs, and the retired hook
    ignored them too.

    Args:
        network: The built, not-yet-aggregated ``pypsa.Network``.
        dashboard: The ``dashboard_lib`` Dashboard carrying ``settings``
            (``carbonprice``, ``currency_exchange``), ``carbon_price_usd``
            (price per tCO₂ for the target year, in the carbon-price currency
            — the field name is historical) and ``emission_intensity``
            (carrier → kg CO₂/MWh for the target year).
    """
    settings = dashboard.settings
    if not getattr(settings, "carbonprice", False):
        return

    price_usd = float(dashboard.carbon_price_usd or 0.0)
    emission_intensity = dashboard.emission_intensity
    if price_usd <= 0:
        logger.warning(
            "[dashboard-importer] Carbon price: scenario %r / year %d → %.1f per tCO₂ — skipping",
            getattr(settings, "carbonprice_scenario", ""),
            settings.target_year,
            price_usd,
        )
        return
    if emission_intensity is None or emission_intensity.empty:
        logger.warning(
            "[dashboard-importer] Carbon price: emission intensities are empty — skipping"
        )
        return

    fx = float(getattr(settings, "currency_exchange", 1.0) or 1.0)
    applied = False
    for carrier, kg_per_mwh in emission_intensity.items():
        if float(kg_per_mwh) == 0:
            continue
        gens = network.generators.index[
            network.generators["carrier"] == str(carrier).strip()
        ]
        if len(gens) == 0:
            continue
        adder = float(kg_per_mwh) * price_usd * fx / 1000.0
        base = pd.to_numeric(
            network.generators.loc[gens, "marginal_cost"], errors="coerce"
        ).fillna(0.0)
        network.generators.loc[gens, "marginal_cost"] = base + adder
        applied = True
        logger.info(
            "[dashboard-importer] carbon %s: %.0f kg CO₂/MWh × %.1f per tCO₂ × %.2f fx = +%.0f per MWh marginal cost",
            carrier,
            kg_per_mwh,
            price_usd,
            fx,
            adder,
        )

    if not applied:
        logger.warning(
            "[dashboard-importer] Carbon price: no matching generators found"
        )


# ---------------------------------------------------------------------------
# Core build pipeline
# ---------------------------------------------------------------------------


def _build_dashboard_network(
    dashboard_path: Path | None,
    module_config: dict[str, Any],
) -> Any:
    """Build a PyPSA network from GUI config, table edits, and optional xlsx."""
    settings_mod = _lib("settings")
    loader_mod = _lib("loader")
    topology_mod = _lib("topology")
    region_mod = _lib("region")
    carrier_mod = _lib("carrier")
    scaling_mod = _lib("scaling")
    snapshots_mod = _lib("snapshots")
    merge_cc_mod = _lib("merge_cc")
    p_max_pu_mod = _lib("p_max_pu")
    demand_redist_mod = _lib("demand_redistribution")
    gen_replace_mod = _lib("generator_replacement")
    ess_mod = _lib("ess")
    marginal_cost_mod = _lib("marginal_cost")

    if dashboard_path is not None:
        xlsx_dashboard = settings_mod.read_dashboard(dashboard_path)
        settings = xlsx_dashboard.settings
        _apply_config_to_settings(settings, module_config)
    else:
        xlsx_dashboard = None
        settings = _settings_from_config(settings_mod, module_config)

    settings.model = str(
        _resolve_model_workbook(module_config, dashboard_path, settings.model)
    )

    dashboard = _build_dashboard(settings_mod, settings, module_config, xlsx_dashboard)
    # Full-model solar/wind additions by build year (incl. years after the target
    # year) for the close-year follow split of existing plants — read from the raw
    # generators sheet, since the built network is filtered to the target year.
    raw_gens = _read_generators_sheet(settings.model)
    dashboard.renewable_additions_by_year = _additions_by_year(raw_gens)
    # The full raw fleet lets replacement reach plants that retire before the
    # target year (retire-and-replace: their renewables are dated at close year).
    dashboard.raw_generators = raw_gens

    network = loader_mod.build_network_for_year(settings.model, settings.target_year)
    loader_mod.select_base_year_temporal(network, settings.base_year)
    merge_cc_mod.merge_cc_generators(network, dashboard)
    topology_mod.apply_topology(network, settings)
    # Scale to the target annual energy first, then redistribute demand between
    # bus/region groups — both must happen BEFORE region aggregation so the
    # redistributor can select groups at any resolution, and before snapshot
    # slicing so an annual MWh is the sum over the full year.  Moving scale_load
    # ahead of aggregation is output-neutral: a uniform scale commutes with the
    # sum performed by aggregation.
    scaling_mod.scale_load(network, settings.target_load_twh, settings.base_year)
    demand_redist_mod.redistribute_demand(network, dashboard)
    # Replace selected new plants with solar/wind while generators are still
    # individual and carry their province — before p_max_pu so the new units
    # inherit the province's renewable profile via apply_standard_p_max_pu.
    replaced_by_bus = gen_replace_mod.replace_generators(network, dashboard)
    # Add an ESS StorageUnit at each replacement bus (sized from the replaced
    # capacity), while buses are still individual — so it rides onto its region
    # bus through aggregation's bus-remap like every other component.
    ess_mod.add_storage_at_replaced_buses(network, dashboard, replaced_by_bus)
    # Scale generator marginal cost per carrier (uniform factor commutes with the
    # capacity-weighted carrier merge, so order vs aggregation is immaterial).
    marginal_cost_mod.apply_marginal_cost_multipliers(network, dashboard)
    # Fold the carbon price into marginal costs AFTER the multipliers (the
    # multiplier scales fuel cost only, never the carbon adder) and BEFORE
    # aggregation (a per-carrier additive adder commutes with the merge).
    _apply_carbon_price_marginal_cost(network, dashboard)
    region_mod.aggregate_by_region(network, dashboard)
    p_max_pu_mod.apply_standard_p_max_pu(network, settings.model)
    carrier_mod.aggregate_by_carrier(network, dashboard)
    # Apply transmission losses last: split lossless bidirectional links into
    # forward + reverse one-directional lossy links (energy-consistent).
    topology_mod.apply_link_losses(network, settings.link_loss)
    snapshots_mod.slice_snapshots(
        network, settings.snapshot_start, settings.snapshot_length
    )
    topology_mod.drop_components_with_missing_buses(network)
    return network


def _resolve_model_for_analytics(module_config: dict[str, Any]) -> tuple[str, int, int]:
    """Resolve (model_path, base_year, target_year) from the GUI config."""
    settings_mod = _lib("settings")

    dashboard_path = _resolve_dashboard_path(module_config)
    if dashboard_path is not None:
        settings = settings_mod.read_dashboard(dashboard_path).settings
        _apply_config_to_settings(settings, module_config)
    else:
        settings = _settings_from_config(settings_mod, module_config)

    model_path = str(
        _resolve_model_workbook(module_config, dashboard_path, settings.model)
    )
    return model_path, int(settings.base_year), int(settings.target_year)


def _active_in_year(df: "pd.DataFrame", target_year: int) -> "pd.Series":
    """Boolean mask of rows active in *target_year*: ``build ≤ year < close``.

    Mirrors :func:`dashboard_lib.loader.filter_components_by_year` on a raw
    sheet: a missing ``build_year`` is pre-existing (always built), a missing
    ``close_year`` never closes. A sheet without ``build_year`` is all-active.
    """
    if "build_year" in df.columns:
        build = pd.to_numeric(df["build_year"], errors="coerce")
        active = build.isna() | (build <= target_year)
    else:
        active = pd.Series(True, index=df.index)
    if "close_year" in df.columns:
        close = pd.to_numeric(df["close_year"], errors="coerce")
        active = active & (close.isna() | (close > target_year))
    return active


def capacity_payload(module_config: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Capacity by carrier × year for the configured model — no build/solve.

    Resolves the model workbook from *module_config* exactly as the build
    pipeline does, then returns :func:`_capacity_by_carrier_year`.  Used by the
    ``/capacity`` endpoint so the Output tab can show the fleet straight from
    the input, before anything is run.

    Args:
        module_config: The plugin GUI config (``moduleConfig``).

    Returns:
        Capacity-by-year rows, or ``None`` when no model is configured.
    """
    model_path, base_year, _ = _resolve_model_for_analytics(module_config)
    # When replacement is on, reflect it: retire each replaced plant at its
    # online year and add the solar/wind it becomes, so the chart shows the
    # transition rather than the untouched input fleet.
    if _as_bool(module_config, "replace_generators", False):
        df = _read_generators_sheet(model_path)
        if df is None:
            return None
        plan = replacement_plan_payload(module_config)
        if plan:
            df = _apply_replacement_to_fleet(df, plan)
        return _capacity_rows_from_fleet(df, base_year)
    return _capacity_by_carrier_year(model_path, base_year)


def _apply_replacement_to_fleet(
    df: "pd.DataFrame",
    plan: list[dict[str, Any]],
) -> "pd.DataFrame":
    """Return a copy of the generators fleet with the replacement plan applied.

    Each replaced plant is retired at its ``online_year`` (its ``close_year`` is
    pulled back to that year) and the solar/wind capacity it becomes is appended
    as new rows built in that year. Used by the Output capacity chart so it
    reflects the built model. The original ``df`` is not mutated.
    """
    if "name" not in df.columns:
        return df
    out = df.copy()
    for col in ("build_year", "close_year"):
        if col not in out.columns:
            out[col] = pd.NA
    names = out["name"].astype(str).str.strip()
    new_rows: list[dict[str, Any]] = []
    for row in plan:
        g = str(row.get("generator", "")).strip()
        ry = row.get("online_year")
        if not g or ry is None:
            continue
        mask = names == g
        if mask.any():
            # Retire the original plant at the replacement year (no later than it
            # already closes) so its carrier's capacity drops as it is replaced.
            existing = pd.to_numeric(out.loc[mask, "close_year"], errors="coerce")
            out.loc[mask, "close_year"] = existing.where(existing < ry, ry).fillna(ry)
        for carrier, mw in (
            ("solar", row.get("solar_mw")),
            ("wind", row.get("wind_mw")),
        ):
            if not mw or float(mw) <= 0:
                continue
            new_rows.append(
                {
                    "name": f"{g}_repl_{carrier}",
                    "carrier": carrier,
                    "p_nom": float(mw),
                    "build_year": ry,
                    "close_year": pd.NA,
                }
            )
    if new_rows:
        out = pd.concat([out, pd.DataFrame(new_rows)], ignore_index=True)
    return out


def _apply_attr_filter(
    df: "pd.DataFrame", module_config: dict[str, Any]
) -> "pd.DataFrame":
    """Filter 3 (optional): keep only rows where ``column == value``.

    ``replace_filter_column`` / ``replace_filter_value`` come from the GUI's
    column + value dropdowns (any generators-sheet column, any of its unique
    values). A blank pair, or a column not in the sheet, is a no-op.
    """
    col = _as_str(module_config, "replace_filter_column", "").strip()
    val = _as_str(module_config, "replace_filter_value", "").strip()
    if not col or not val or col not in df.columns:
        return df
    # String-equal OR numeric-equal, so a flag column stored as ``1.0`` still
    # matches a typed/selected ``"1"`` (mirrors generator_replacement._attr_match).
    match = df[col].astype(str).str.strip() == val
    try:
        match = match | (pd.to_numeric(df[col], errors="coerce") == float(val))
    except ValueError:
        pass
    return df[match]


def generator_filter_values_payload(
    module_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Every (column, unique value) of the generators sheet for the filter dropdowns.

    Powers the replacement attribute filter: the column dropdown reads the
    distinct ``column`` values, and the value dropdown reads ``value`` filtered
    to the chosen column. Per-column uniques are capped to keep the payload
    small; high-cardinality columns (e.g. ``name``) are simply truncated.
    """
    model_path, _, _ = _resolve_model_for_analytics(module_config)
    df = _read_generators_sheet(model_path)
    if df is None:
        return []
    rows: list[dict[str, Any]] = []
    cap = 300  # max unique values surfaced per column
    for col in df.columns:
        vals = df[col].dropna().astype(str).str.strip()
        uniques = sorted({v for v in vals if v and v.lower() != "nan"})
        for v in uniques[:cap]:
            rows.append({"column": str(col), "value": v})
    return rows


def generators_payload(module_config: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Generators active in the target year ``[{name, build_year, …}]``.

    Powers the replacement dropdown's ``source: 'server'`` options. The list is
    filtered to the **target year** (``build_year ≤ target < close_year``) — the
    same set the build operates on — so the dropdown shows exactly the plants
    that are replaceable. The carrier multi-select narrows it further client-side.

    Args:
        module_config: The plugin GUI config (``moduleConfig``).

    Returns:
        One dict per active generator with ``name`` and ``build_year`` (or
        ``None``), or ``None`` when no model is configured / readable.
    """
    model_path, _, target_year = _resolve_model_for_analytics(module_config)
    df = _read_generators_sheet(model_path)
    if df is None or "name" not in df.columns:
        return None
    df = df[_active_in_year(df, target_year)]  # Filter 1: active in target year
    # Filter 2 (replacement only): build_year ≥ replacement base year — skipped
    # entirely when "Include existing plants" is on (the whole fleet is replaceable).
    threshold = (
        0
        if _as_bool(module_config, "replace_include_existing", False)
        else _as_int(module_config, "replace_build_year", 0)
    )
    if threshold > 0 and "build_year" in df.columns:
        df = df[pd.to_numeric(df["build_year"], errors="coerce") >= threshold]
    df = _apply_attr_filter(df, module_config)  # Filter 3: column == value (optional)
    # fillna("") so a blank/NaN cell becomes "" (str.strip can re-introduce NaN).
    names = df["name"].astype(str).str.strip().fillna("")
    build = (
        pd.to_numeric(df["build_year"], errors="coerce")
        if "build_year" in df.columns
        else pd.Series(index=df.index, dtype="float64")
    )
    pnom = (
        pd.to_numeric(df["p_nom"], errors="coerce")
        if "p_nom" in df.columns
        else pd.Series(index=df.index, dtype="float64")
    )
    carrier = (
        df["carrier"].astype(str).str.strip().fillna("")
        if "carrier" in df.columns
        else pd.Series("", index=df.index)
    )
    rows: list[dict[str, Any]] = []
    for name, b, p, c in zip(names, build, pnom, carrier, strict=False):
        if not name or name.lower() == "nan":
            continue
        by_int = int(b) if pd.notna(b) else None
        p_val = round(float(p), 1) if pd.notna(p) else None
        # "detail" is what the dropdown shows after the name, e.g. "2030 · 300 MW".
        parts = []
        if by_int is not None:
            parts.append(str(by_int))
        if p_val is not None:
            parts.append(f"{p_val:g} MW")
        rows.append(
            {
                "name": name,
                "build_year": by_int,
                "p_nom": p_val,
                "carrier": "" if c.lower() == "nan" else c,
                "detail": " · ".join(parts),
            }
        )
    return rows


def replacement_plan_payload(module_config: dict[str, Any]) -> list[dict[str, Any]]:
    """Per selected plant: total / solar / wind MW under the current split.

    Mirrors the build's split: fixed ``replace_solar_pct`` /
    ``replace_wind_pct`` are direct percentages of the original capacity when
    not following; ``replace_follow`` uses the solar:wind ratio of capacity
    added in a reference year (the build year for new builds, the close year for
    existing plants — see :mod:`dashboard_lib.generator_replacement`) and ignores
    fixed shares. Returns ``[]`` when nothing is selected / no model.

    Args:
        module_config: The plugin GUI config (``moduleConfig``).
    """
    rules = module_config.get("generator_replacements")
    sel_rows = (
        [
            r
            for r in rules
            if isinstance(r, dict) and str(r.get("generator", "")).strip()
        ]
        if isinstance(rules, list)
        else []
    )
    bulk_on = _as_bool(module_config, "replace_all_carriers", False)
    # Carrier matching is case/whitespace-insensitive — a model spelling its
    # carriers "Solar"/"Wind" must still match the lowercase GUI checkboxes.
    carriers_sel = {
        c.strip().lower() for c in _as_str_list(module_config, "replace_carriers")
    }
    if not sel_rows and not (bulk_on and carriers_sel):
        return []

    model_path, base_year, target_year = _resolve_model_for_analytics(module_config)
    df = _read_generators_sheet(model_path)
    if df is None or "name" not in df.columns:
        return []
    # Full-model additions (all build years, incl. years after the target year)
    # for the close-year split of existing plants — taken before the target filter.
    full_additions = _additions_by_year(df)
    # Annual additions (for the build-year follow ratio) come from the fleet
    # active in the target year — computed before replacement filters so the
    # solar:wind ratio is not affected by carrier/filter dropdown choices.
    additions_df = df[_active_in_year(df, target_year)].copy()

    # Retire-and-replace fleet: every plant built by the target year — INCLUDING
    # those that already retire before it (close ≤ target). The target-year
    # network dropped them, but their capacity still becomes renewables (dated at
    # the plant's close/forced year). Mirrors generator_replacement.replace_generators.
    if "build_year" in df.columns:
        _built = pd.to_numeric(df["build_year"], errors="coerce")
        df = df[_built.isna() | (_built <= target_year)]

    # Filter 2: build_year ≥ replacement base year — skipped entirely when
    # "Include existing plants" is on (the whole fleet is replaceable).
    threshold = (
        0
        if _as_bool(module_config, "replace_include_existing", False)
        else _as_int(module_config, "replace_build_year", 0)
    )
    if threshold > 0 and "build_year" in df.columns:
        df = df[pd.to_numeric(df["build_year"], errors="coerce") >= threshold]
    df = _apply_attr_filter(df, module_config)  # Filter 3: column == value (optional)

    names = df["name"].astype(str).str.strip().fillna("")
    build = (
        pd.to_numeric(df["build_year"], errors="coerce")
        if "build_year" in df.columns
        else pd.Series(index=df.index, dtype="float64")
    )
    pnom = (
        pd.to_numeric(df["p_nom"], errors="coerce").fillna(0.0)
        if "p_nom" in df.columns
        else pd.Series(0.0, index=df.index)
    )
    carrier = (
        df["carrier"].astype(str).str.strip().fillna("")
        if "carrier" in df.columns
        else pd.Series("", index=df.index)
    )

    follow = _as_bool(module_config, "replace_follow", False)
    solar_pct = _as_float(module_config, "replace_solar_pct", 50.0)
    wind_pct = _as_float(module_config, "replace_wind_pct", 50.0)
    solar_pct = max(solar_pct, 0.0)
    wind_pct = max(wind_pct, 0.0)

    # Follow-mode reference: each plant's build year by default; the close year
    # (capped) for every plant when "Include existing plants" is on. Mirrors the
    # build's generator_replacement split exactly. Cap is 0/blank → target year.
    active_additions = _additions_by_year(additions_df)
    follow_close_year = follow and _as_bool(
        module_config, "replace_include_existing", False
    )
    # Forced-retirement cap: renewables come online at min(close, cap); a plant
    # with no close year retires at the cap (0/blank → target year).
    cap = _as_int(module_config, "replace_max_close_year", 0) or int(target_year)

    def _repl_year(by: int | None, close: int | None) -> int:
        """Year the replacement comes online (mirrors generator_replacement)."""
        ry = close if close is not None else cap
        ry = min(ry, cap)
        if by is not None:
            ry = max(ry, by)
        return min(ry, int(target_year))

    def _computed_split(
        total: float, by: int | None, close: int | None
    ) -> tuple[float, float]:
        if follow:
            if follow_close_year:  # replacement (close/forced) year
                solar_add, wind_add = _latest_nonzero(
                    full_additions, _repl_year(by, close)
                )
            else:  # build year
                ref = by if by is not None else int(base_year)
                solar_add, wind_add = _latest_nonzero(active_additions, ref)
            total_add = solar_add + wind_add
            if total_add > 0:
                return total * solar_add / total_add, total * wind_add / total_add
            return total * 0.5, total * 0.5
        return total * solar_pct / 100.0, total * wind_pct / 100.0

    # name → (p_nom, build_year, carrier, close_year), first occurrence wins.
    close = (
        pd.to_numeric(df["close_year"], errors="coerce")
        if "close_year" in df.columns
        else pd.Series(index=df.index, dtype="float64")
    )
    info: dict[str, tuple[float, int | None, str, int | None]] = {}
    for nm, b, p, c, cl in zip(names, build, pnom, carrier, close, strict=False):
        if not nm or nm.lower() == "nan" or nm in info:
            continue
        info[nm] = (
            float(p),
            int(b) if pd.notna(b) else None,
            c,
            int(cl) if pd.notna(cl) else None,
        )

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Explicit table picks. A row carrying a FROZEN solar_mw/wind_mw split (set by
    # "Fill table from carriers" at add-time) is shown verbatim — regardless of
    # the current settings or even the base-year filter — so earlier batches keep
    # their numbers. Rows without a frozen split compute live from the settings.
    for r in sel_rows:
        g = str(r.get("generator", "")).strip()
        if g in seen:
            continue
        fz = _frozen_split(r)
        if fz is not None:
            seen.add(g)
            solar, wind = fz
            by = info[g][1] if g in info else None
            close_y = info[g][3] if g in info else None
            rows.append(
                {
                    "generator": g,
                    "build_year": by,
                    "online_year": _repl_year(by, close_y),
                    "total_mw": round(solar + wind, 1),
                    "solar_mw": round(solar, 1),
                    "wind_mw": round(wind, 1),
                }
            )
            continue
        if g not in info:
            continue
        seen.add(g)
        total, by, _, close_y = info[g]
        solar, wind = _computed_split(total, by, close_y)
        rows.append(
            {
                "generator": g,
                "build_year": by,
                "online_year": _repl_year(by, close_y),
                "total_mw": round(total, 1),
                "solar_mw": round(solar, 1),
                "wind_mw": round(wind, 1),
            }
        )

    # Bulk: every plant of the selected carriers passing both filters above
    # (computed split). The sheet is already filtered, so no extra check here.
    if bulk_on and carriers_sel:
        for nm, (total, by, c, close_y) in info.items():
            if nm in seen or c.strip().lower() not in carriers_sel or total <= 0:
                continue
            seen.add(nm)
            solar, wind = _computed_split(total, by, close_y)
            rows.append(
                {
                    "generator": nm,
                    "build_year": by,
                    "online_year": _repl_year(by, close_y),
                    "total_mw": round(total, 1),
                    "solar_mw": round(solar, 1),
                    "wind_mw": round(wind, 1),
                }
            )

    return rows


def ess_plan_payload(module_config: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-bus ESS sizing preview — mirrors the build's ``add_storage_at_replaced_buses``.

    Maps each replaced plant to its bus, sums the replaced capacity per bus, and
    applies the chosen sizing rule (proportional % of that capacity, or a fixed
    MW). Returns ``[]`` when ESS is off, nothing is replaced, or the model has no
    generators/bus columns.
    """
    if not _as_bool(module_config, "add_ess", False):
        return []
    plan = replacement_plan_payload(module_config)
    if not plan:
        return []
    model_path, _base_year, _target_year = _resolve_model_for_analytics(module_config)
    gdf = _read_generators_sheet(model_path)
    if gdf is None or "name" not in gdf.columns or "bus" not in gdf.columns:
        return []
    name_to_bus = {
        str(n).strip(): str(b).strip() for n, b in zip(gdf["name"], gdf["bus"])
    }
    replaced_by_bus: dict[str, float] = {}
    for r in plan:
        bus = name_to_bus.get(str(r.get("generator", "")).strip(), "")
        if not bus:
            continue
        replaced_by_bus[bus] = replaced_by_bus.get(bus, 0.0) + float(
            r.get("total_mw") or 0.0
        )

    mode = _as_str(module_config, "ess_sizing_mode", "proportional").strip().lower()
    fixed_mw = _as_float(module_config, "ess_fixed_mw", 100.0)
    proportion = _as_float(module_config, "ess_proportion_pct", 30.0) / 100.0
    # Expansion bounds (resolved to MW per bus) for the preview.
    expandable = _as_bool(module_config, "ess_expandable", False)
    exp_mode = (
        _as_str(module_config, "ess_expansion_mode", "proportional").strip().lower()
    )
    min_in = _as_float(module_config, "ess_p_nom_min", 0.0)
    max_in = _as_float(module_config, "ess_p_nom_max", 0.0)

    def _bound(value: float, cap: float) -> float:
        return cap * value / 100.0 if exp_mode == "proportional" else value

    rows: list[dict[str, Any]] = []
    for bus, cap in sorted(replaced_by_bus.items(), key=lambda kv: -kv[1]):
        ess = fixed_mw if mode == "fixed" else cap * proportion
        row = {
            "bus": bus,
            "replaced_mw": round(cap, 1),
            "ess_mw": round(max(ess, 0.0), 1),
        }
        if expandable:
            row["min_mw"] = round(max(_bound(min_in, cap), 0.0), 1)
            row["max_mw"] = round(_bound(max_in, cap), 1) if max_in > 0 else None
        rows.append(row)
    return rows


def _read_generators_sheet(model_path: str) -> "pd.DataFrame | None":
    """Read the model workbook's ``generators`` sheet (raw, unfiltered).

    Returns the DataFrame with stripped column names, or ``None`` when the path
    is empty / the sheet is missing / the read fails (best-effort).
    """
    if not model_path:
        return None
    try:
        xl = None
        for engine in ("calamine", "openpyxl"):
            try:
                xl = pd.ExcelFile(model_path, engine=engine)
                break
            except Exception:  # noqa: BLE001 - try the next engine
                continue
        if xl is None or "generators" not in xl.sheet_names:
            return None
        df = xl.parse("generators")
    except Exception:  # noqa: BLE001 - best-effort; never break the caller
        return None
    if df.empty:
        return None
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _additions_by_year(df: "pd.DataFrame | None") -> dict[int, tuple[float, float]]:
    """``{build_year: (solar_mw, wind_mw)}`` from a raw generators DataFrame.

    Sums solar/wind ``p_nom`` per build year across **all** rows (no target-year
    filtering), so the result carries additions in years after the target year —
    needed for the close-year follow-mode split of existing plants. Mirrors
    :func:`dashboard_lib.generator_replacement._year_additions_by_year`, which
    runs on the (target-filtered) network.
    """
    if (
        df is None
        or df.empty
        or "build_year" not in df.columns
        or "carrier" not in df.columns
    ):
        return {}
    by = pd.to_numeric(df["build_year"], errors="coerce")
    carrier = df["carrier"].astype(str).str.strip().str.lower()
    pnom = (
        pd.to_numeric(df["p_nom"], errors="coerce").fillna(0.0)
        if "p_nom" in df.columns
        else pd.Series(0.0, index=df.index)
    )
    rows = pd.DataFrame({"year": by, "carrier": carrier, "p_nom": pnom})
    rows = rows[rows["year"].notna() & rows["carrier"].isin(("solar", "wind"))]
    if rows.empty:
        return {}
    grouped = rows.groupby(["year", "carrier"])["p_nom"].sum()
    out: dict[int, tuple[float, float]] = {}
    for year_value in rows["year"].dropna().unique():
        out[int(year_value)] = (
            float(grouped.get((year_value, "solar"), 0.0)),
            float(grouped.get((year_value, "wind"), 0.0)),
        )
    return out


def _frozen_split(row: Any) -> tuple[float, float] | None:
    """Return ``(solar_mw, wind_mw)`` frozen on a table row, or ``None`` if absent.

    "Fill table from carriers" stores the split it computed at add-time in the
    row's ``solar_mw`` / ``wind_mw`` keys. Both present + numeric → frozen (shown
    and built verbatim); otherwise the split is computed live.
    """
    if not isinstance(row, dict):
        return None
    solar, wind = row.get("solar_mw"), row.get("wind_mw")
    if solar is None or wind is None or solar == "" or wind == "":
        return None
    try:
        return float(solar), float(wind)
    except (TypeError, ValueError):
        return None


def _latest_nonzero(
    additions: dict[int, tuple[float, float]], year: int
) -> tuple[float, float]:
    """Additions for *year*, else the latest earlier year with nonzero additions."""
    solar_add, wind_add = additions.get(year, (0.0, 0.0))
    if solar_add + wind_add > 0:
        return solar_add, wind_add
    for candidate in sorted((y for y in additions if y <= year), reverse=True):
        solar_add, wind_add = additions[candidate]
        if solar_add + wind_add > 0:
            return solar_add, wind_add
    return 0.0, 0.0


def _read_model_sheet(model_path: str, sheet: str) -> "pd.DataFrame | None":
    """Read one sheet of the model workbook (stripped column names); best-effort."""
    if not model_path:
        return None
    try:
        xl = None
        for engine in ("calamine", "openpyxl"):
            try:
                xl = pd.ExcelFile(model_path, engine=engine)
                break
            except Exception:  # noqa: BLE001
                continue
        if xl is None or sheet not in xl.sheet_names:
            return None
        df = xl.parse(sheet)
    except Exception:  # noqa: BLE001 - best-effort; never break the caller
        return None
    if df.empty:
        return None
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _canon(x: object) -> str:
    """Trim and drop a float-coercion ``.0`` so bus/load names compare as strings."""
    s = str(x).strip()
    m = re.match(r"^(-?\d+)\.0+$", s)
    return m.group(1) if m else s


def _is_blank(s: str) -> bool:
    """True for an empty / 'nan' / 'none' label (so it never reaches a dropdown)."""
    return not s or s.strip().lower() in ("nan", "none")


def _energy_label(mwh: float) -> str:
    """Human label for an annual energy: GWh, or TWh once it reaches 1 TWh."""
    if mwh >= 1e6:
        return f"{mwh / 1e6:,.1f} TWh"
    return f"{mwh / 1e3:,.0f} GWh"


def demand_values_payload(module_config: dict[str, Any]) -> list[dict[str, Any]]:
    """Per (resolution, value) annual demand for the demand-move dropdowns.

    Reads the configured model's ``loads`` + ``loads-p_set`` over the **full
    year** (never snapshot-sliced — that only happens when sending to Ragnarok)
    and the ``buses`` provinces, scales to the target annual energy exactly as
    the build does (additional post-base-year demand held fixed), then
    aggregates per bus and per region resolution.

    Returns rows ``{resolution, value, annual_mwh, annual_label}`` — the value
    dropdowns read this (so the user picks from the real fleet) and show
    ``annual_label`` beside each value (so they know how much demand sits there).
    """
    model_path, base_year, _target_year = _resolve_model_for_analytics(module_config)
    pset = _read_model_sheet(model_path, "loads-p_set")
    loads = _read_model_sheet(model_path, "loads")
    buses = _read_model_sheet(model_path, "buses")
    if pset is None or pset.empty or loads is None or "name" not in loads.columns:
        return []

    # Per-load annual energy over the full year (first 'snapshot' column aside).
    value_cols = [c for c in pset.columns if str(c).strip().lower() != "snapshot"]
    annual: dict[str, float] = {
        _canon(c): float(pd.to_numeric(pset[c], errors="coerce").fillna(0.0).sum())
        for c in value_cols
    }

    # load → bus, and optional build_year on loads / buses (for additional demand).
    bus_of_load: dict[str, str] = {}
    load_by: dict[str, float] = {}
    has_load_by = "build_year" in loads.columns
    for _, r in loads.iterrows():
        nm = _canon(r["name"])
        bus_of_load[nm] = _canon(r.get("bus")) if "bus" in loads.columns else ""
        if has_load_by:
            v = pd.to_numeric(r["build_year"], errors="coerce")
            if pd.notna(v):
                load_by[nm] = float(v)
    bus_by: dict[str, float] = {}
    if buses is not None and "name" in buses.columns and "build_year" in buses.columns:
        for _, r in buses.iterrows():
            v = pd.to_numeric(r["build_year"], errors="coerce")
            if pd.notna(v):
                bus_by[_canon(r["name"])] = float(v)

    def _is_additional(load: str) -> bool:
        by = load_by.get(load)
        if by is not None and by > base_year:
            return True
        bby = bus_by.get(bus_of_load.get(load, ""))
        return bby is not None and bby > base_year

    # Scale to the target annual energy, holding additional demand fixed (mirrors
    # dashboard_lib.scaling.scale_load). Full-year totals, no snapshot slicing.
    target_twh = _as_float(module_config, "target_load_twh", 0.0)
    total_raw = sum(annual.values())
    scaled = dict(annual)
    if target_twh > 0 and total_raw > 0:
        add_mwh = sum(e for ld, e in annual.items() if _is_additional(ld))
        dist_mwh = total_raw - add_mwh
        dist_target = target_twh * 1e6 - add_mwh
        if dist_mwh > 0 and dist_target > 0:
            factor = dist_target / dist_mwh
            scaled = {
                ld: (e if _is_additional(ld) else e * factor)
                for ld, e in annual.items()
            }

    # Aggregate to buses.
    bus_annual: dict[str, float] = {}
    for ld, e in scaled.items():
        bus = bus_of_load.get(ld, "")
        if bus:
            bus_annual[bus] = bus_annual.get(bus, 0.0) + e

    # bus → province (buses 'Province'/'province').
    prov_of_bus: dict[str, str] = {}
    prov_col = next(
        (
            c
            for c in ("Province", "province")
            if buses is not None and c in buses.columns
        ),
        None,
    )
    if buses is not None and "name" in buses.columns and prov_col:
        for _, r in buses.iterrows():
            prov_of_bus[_canon(r["name"])] = str(r.get(prov_col, "")).strip()

    # Region labels MUST match what redistribute_demand resolves, so reuse the
    # SAME region helper (_build_province_to_region) per resolution. A province
    # not in the mapping falls back to itself, exactly as _build_bus_to_region.
    region_mod = _lib("region")
    pm = _table_to_df(module_config.get("province_mapping"))

    rows: list[dict[str, Any]] = []
    for bus, e in sorted(bus_annual.items()):
        if _is_blank(bus):
            continue
        rows.append(
            {
                "resolution": "bus",
                "value": bus,
                "annual_mwh": round(e, 1),
                "annual_label": _energy_label(e),
            }
        )
    for res in ("province", "group1", "group2", "group3", "singlenode"):
        prov_to_region, _ = region_mod._build_province_to_region(pm, res)
        agg: dict[str, float] = {}
        for bus, e in bus_annual.items():
            prov = prov_of_bus.get(bus, "")
            if _is_blank(prov):
                continue
            region = str(
                prov_to_region.get(prov, prov)
            ).strip()  # mirror _build_bus_to_region fallback
            if _is_blank(region):
                continue
            agg[region] = agg.get(region, 0.0) + e
        for region, e in sorted(agg.items()):
            rows.append(
                {
                    "resolution": res,
                    "value": region,
                    "annual_mwh": round(e, 1),
                    "annual_label": _energy_label(e),
                }
            )
    return rows


def _capacity_by_carrier_year(
    model_path: str,
    base_year: int,
) -> list[dict[str, Any]] | None:
    """Installed capacity (MW) by carrier for each year, from the raw fleet.

    Reads the model workbook's ``generators`` sheet (every build/close year, not
    just the target year) and, for each year ``Y`` in the data's range, sums
    ``p_nom`` by carrier over generators active in ``Y``::

        active(Y) = (build_year is NaN OR build_year <= Y)
                    AND (close_year is NaN OR Y < close_year)

    A missing ``build_year`` means "built before the start" (always built); a
    missing ``close_year`` means "never closes".  Returns one row per year
    ``{"year": Y, <carrier>: MW, ..., "total": MW}`` (carriers as columns), or
    ``None`` when the sheet is unavailable.

    The series starts at the fleet's earliest ``build_year`` (not the GUI base
    year) so the chart shows the cumulative build-up history; with
    ``base_year == target_year`` it would otherwise collapse to a single year.

    Args:
        model_path: Path to the model workbook.
        base_year:  Always included in the series; also anchors the guard
            against absurd close years.
    """
    df = _read_generators_sheet(model_path)
    if df is None or "carrier" not in df.columns or "p_nom" not in df.columns:
        return None
    return _capacity_rows_from_fleet(df, base_year)


def _capacity_rows_from_fleet(
    df: "pd.DataFrame",
    base_year: int,
) -> list[dict[str, Any]] | None:
    """Per-year installed capacity by carrier from a (possibly replacement-adjusted)
    generators DataFrame. See :func:`_capacity_by_carrier_year` for the semantics."""
    if "carrier" not in df.columns or "p_nom" not in df.columns:
        return None

    nan_col = pd.Series(index=df.index, dtype="float64")  # all-NaN fallback
    build = (
        pd.to_numeric(df["build_year"], errors="coerce")
        if "build_year" in df.columns
        else nan_col
    )
    close = (
        pd.to_numeric(df["close_year"], errors="coerce")
        if "close_year" in df.columns
        else nan_col
    )
    p_nom = pd.to_numeric(df["p_nom"], errors="coerce").fillna(0.0)
    carrier = df["carrier"].astype(str).str.strip()

    start = int(base_year)
    if build.notna().any():
        start = min(start, int(build.dropna().min()))
    end = int(base_year)
    if close.notna().any():
        end = max(end, int(close.dropna().max()))
    if build.notna().any():
        end = max(end, int(build.dropna().max()))
    end = min(end, int(base_year) + 80)  # guard against absurd close years (e.g. 9999)
    start = max(start, end - 120)  # bound the span against absurd build years (e.g. 0)

    carriers = sorted(c for c in carrier.dropna().unique() if c and c.lower() != "nan")
    rows: list[dict[str, Any]] = []
    for year in range(start, end + 1):
        active = (build.isna() | (build <= year)) & (close.isna() | (year < close))
        grp = p_nom[active].groupby(carrier[active]).sum()
        row: dict[str, Any] = {"year": year}
        for c in carriers:
            row[c] = round(float(grp.get(c, 0.0)), 3)
        row["total"] = round(float(p_nom[active].sum()), 3)
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Settings construction
# ---------------------------------------------------------------------------


def _settings_from_config(settings_mod: Any, cfg: dict[str, Any]) -> Any:
    """Build a Settings dataclass entirely from GUI module_config values."""
    return settings_mod.Settings(
        model="",
        base_year=_as_int(cfg, "base_year", 2024),
        target_year=_as_int(cfg, "target_year", 2030),
        target_load_twh=_as_float(cfg, "target_load_twh", 0.0),
        snapshot_start=_as_str(cfg, "snapshot_start", "01/01/2024 00:00"),
        snapshot_length=_as_int(cfg, "snapshot_length", 8760),
        grid_mode=_as_str(cfg, "grid_mode", "as-is"),
        single_bus=_as_str(cfg, "single_bus", "KR"),
        link_loss=_as_float(cfg, "link_loss", 0.03),
        aggregate_by_region=_as_bool(cfg, "aggregate_by_region", False),
        region_column=_as_str(cfg, "region_column", "province"),
        aggregate_by_carrier=_as_bool(cfg, "aggregate_by_carrier", False),
        demand_redistribution=_as_bool(cfg, "demand_redistribution", False),
        replace_generators=_as_bool(cfg, "replace_generators", False),
        replace_build_year=_as_int(cfg, "replace_build_year", 0),
        replace_include_existing=_as_bool(cfg, "replace_include_existing", False),
        replace_follow=_as_bool(cfg, "replace_follow", False),
        replace_max_close_year=_as_int(cfg, "replace_max_close_year", 0),
        replace_solar_pct=_as_float(cfg, "replace_solar_pct", 50.0),
        replace_wind_pct=_as_float(cfg, "replace_wind_pct", 50.0),
        replace_all_carriers=_as_bool(cfg, "replace_all_carriers", False),
        replace_carriers=_as_str_list(cfg, "replace_carriers"),
        replace_filter_column=_as_str(cfg, "replace_filter_column", ""),
        replace_filter_value=_as_str(cfg, "replace_filter_value", ""),
        add_ess=_as_bool(cfg, "add_ess", False),
        ess_carrier=_as_str(cfg, "ess_carrier", "ESS"),
        ess_hours=_as_float(cfg, "ess_hours", 4.0),
        ess_efficiency=_as_float(cfg, "ess_efficiency", 0.9),
        ess_sizing_mode=_as_str(cfg, "ess_sizing_mode", "proportional"),
        ess_proportion_pct=_as_float(cfg, "ess_proportion_pct", 30.0),
        ess_fixed_mw=_as_float(cfg, "ess_fixed_mw", 100.0),
        ess_capital_cost=_as_float(cfg, "ess_capital_cost", 0.0),
        ess_lifetime=_as_float(cfg, "ess_lifetime", 15.0),
        ess_expandable=_as_bool(cfg, "ess_expandable", False),
        ess_expansion_mode=_as_str(cfg, "ess_expansion_mode", "proportional"),
        ess_p_nom_min=_as_float(cfg, "ess_p_nom_min", 0.0),
        ess_p_nom_max=_as_float(cfg, "ess_p_nom_max", 0.0),
        marginal_cost_multiplier=_as_bool(cfg, "marginal_cost_multiplier", False),
        plot_map=_as_bool(cfg, "plot_map", True),
        cc_rule=_as_bool(cfg, "cc_rule", True),
        carbonprice=_as_bool(cfg, "carbonprice", False),
        carbonprice_scenario=_as_str(cfg, "carbonprice_scenario", ""),
        currency_exchange=_as_float(cfg, "currency_exchange", 1350.0),
        constraints=_as_bool(cfg, "constraints", False),
        constraints_attribute=_as_str(cfg, "constraints_attribute", "max_cf, min_cf"),
    )


def _apply_config_to_settings(settings: Any, cfg: dict[str, Any]) -> None:
    """Overlay GUI values onto an xlsx-derived Settings dataclass."""
    _override_str(settings, cfg, "grid_mode")
    _override_str(settings, cfg, "single_bus")
    _override_str(settings, cfg, "region_column")
    _override_str(settings, cfg, "carbonprice_scenario")
    _override_str(settings, cfg, "constraints_attribute")
    _override_str(settings, cfg, "snapshot_start")
    _override_int(settings, cfg, "base_year")
    _override_int(settings, cfg, "target_year")
    _override_int(settings, cfg, "snapshot_length")
    _override_float(settings, cfg, "target_load_twh")
    _override_float(settings, cfg, "link_loss")
    _override_float(settings, cfg, "currency_exchange")
    _override_bool(settings, cfg, "aggregate_by_region")
    _override_bool(settings, cfg, "aggregate_by_carrier")
    _override_bool(settings, cfg, "demand_redistribution")
    _override_bool(settings, cfg, "replace_generators")
    _override_int(settings, cfg, "replace_build_year")
    _override_bool(settings, cfg, "replace_include_existing")
    _override_bool(settings, cfg, "replace_follow")
    _override_int(settings, cfg, "replace_max_close_year")
    _override_float(settings, cfg, "replace_solar_pct")
    _override_float(settings, cfg, "replace_wind_pct")
    _override_str(settings, cfg, "replace_filter_column")
    _override_str(settings, cfg, "replace_filter_value")
    _override_bool(settings, cfg, "add_ess")
    _override_str(settings, cfg, "ess_carrier")
    _override_float(settings, cfg, "ess_hours")
    _override_float(settings, cfg, "ess_efficiency")
    _override_str(settings, cfg, "ess_sizing_mode")
    _override_float(settings, cfg, "ess_proportion_pct")
    _override_float(settings, cfg, "ess_fixed_mw")
    _override_float(settings, cfg, "ess_capital_cost")
    _override_float(settings, cfg, "ess_lifetime")
    _override_bool(settings, cfg, "ess_expandable")
    _override_str(settings, cfg, "ess_expansion_mode")
    _override_float(settings, cfg, "ess_p_nom_min")
    _override_float(settings, cfg, "ess_p_nom_max")
    _override_bool(settings, cfg, "marginal_cost_multiplier")
    _override_bool(settings, cfg, "replace_all_carriers")
    if "replace_carriers" in cfg:
        settings.replace_carriers = _as_str_list(cfg, "replace_carriers")
    _override_bool(settings, cfg, "plot_map")
    _override_bool(settings, cfg, "cc_rule")
    _override_bool(settings, cfg, "carbonprice")
    _override_bool(settings, cfg, "constraints")


def _as_str(cfg: dict[str, Any], key: str, default: str) -> str:
    raw = str(cfg.get(key, default) or "").strip()
    return raw or default


def _as_int(cfg: dict[str, Any], key: str, default: int) -> int:
    raw = str(cfg.get(key, "") or "").strip()
    return int(raw) if raw else default


def _raw(cfg: dict[str, Any], key: str) -> str:
    """Stripped string for *key*, or '' only when genuinely absent/blank.

    Critically, a numeric ``0`` must NOT collapse to ''. The old
    ``str(cfg.get(key, "") or "")`` did exactly that — ``0`` is falsy, so a
    user-entered ``0`` reverted to the field's default (e.g. ESS 0 MW → 100 MW).
    Only ``None`` / missing / whitespace counts as unset here.
    """
    val = cfg.get(key)
    if val is None:
        return ""
    return str(val).strip()


def _as_float(cfg: dict[str, Any], key: str, default: float) -> float:
    raw = _raw(cfg, key)
    return float(raw) if raw else default


def _as_bool(cfg: dict[str, Any], key: str, default: bool) -> bool:
    val = cfg.get(key)
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "yes")


def _as_str_list(cfg: dict[str, Any], key: str) -> tuple[str, ...]:
    """Parse a multi-select value (list[str], or a comma string) into a tuple."""
    val = cfg.get(key)
    if isinstance(val, (list, tuple)):
        items = [str(v).strip() for v in val]
    elif val is None or val == "":
        items = []
    else:
        items = [s.strip() for s in str(val).split(",")]
    return tuple(s for s in items if s)


def _override_str(s: Any, cfg: dict[str, Any], field: str) -> None:
    raw = _raw(cfg, field)
    if raw:
        setattr(s, field, raw)


def _override_int(s: Any, cfg: dict[str, Any], field: str) -> None:
    raw = _raw(cfg, field)
    if raw:
        setattr(s, field, int(raw))


def _override_float(s: Any, cfg: dict[str, Any], field: str) -> None:
    raw = _raw(cfg, field)
    if raw:
        setattr(s, field, float(raw))


def _override_bool(s: Any, cfg: dict[str, Any], field: str) -> None:
    val = cfg.get(field)
    if val is None:
        return
    if isinstance(val, bool):
        setattr(s, field, val)
        return
    raw = str(val).strip().lower()
    if raw in ("true", "1", "yes"):
        setattr(s, field, True)
    elif raw in ("false", "0", "no"):
        setattr(s, field, False)


# ---------------------------------------------------------------------------
# Dashboard (tabular data) construction
# ---------------------------------------------------------------------------


def _build_dashboard(
    settings_mod: Any,
    settings: Any,
    cfg: dict[str, Any],
    xlsx_dashboard: Any | None,
) -> Any:
    """Build a Dashboard merging GUI table edits with optional xlsx fallback."""

    def _gui(field: str, xlsx_attr: str) -> pd.DataFrame | None:
        """Resolve a tabular field: non-empty GUI rows win; else xlsx fallback."""
        df = _table_to_df(cfg.get(field))
        if df is not None and not df.empty:
            return df
        if xlsx_dashboard is not None:
            xlsx_val = getattr(xlsx_dashboard, xlsx_attr, None)
            if isinstance(xlsx_val, pd.DataFrame) and not xlsx_val.empty:
                return xlsx_val
        return None

    cc_rules = _gui("cc_rules", "cc_rules")
    province_mapping = _gui("province_mapping", "province_mapping")
    region_rules = _normalise_region_rules(_gui("region_rules", "region_rules"))
    carrier_rules = _gui("carrier_rules", "carrier_rules")
    carrier_rules_t = _gui("carrier_rules_t", "carrier_rules_t")
    # GUI-only (no xlsx fallback): demand redistribution moves — one row per
    # move with its own from/to resolution + value (see demand_redistribution).
    demand_redist_rules = _table_to_df(cfg.get("demand_redist_moves"))
    # GUI-only (no xlsx fallback): generator replacements (plant → solar/wind).
    generator_replacements = _table_to_df(cfg.get("generator_replacements"))
    # GUI-only (no xlsx fallback): per-carrier marginal-cost multipliers.
    marginal_cost_rules = _table_to_df(cfg.get("marginal_cost_multipliers"))

    cf_df = _gui("constraints_rows", "cf_constraints")
    cf_constraints = _filter_constraints(cf_df, settings.target_year)

    ei_df = _table_to_df(cfg.get("emission_intensity_rows"))
    if ei_df is not None and not ei_df.empty:
        emission_intensity = _emission_intensity_series(ei_df, settings.target_year)
    elif xlsx_dashboard is not None:
        emission_intensity = xlsx_dashboard.emission_intensity
    else:
        emission_intensity = pd.Series(dtype=float)

    cp_df = _table_to_df(cfg.get("carbonprice_curves"))
    if cp_df is not None and not cp_df.empty:
        carbon_price_usd = _lookup_carbon_price_long(
            cp_df, settings.carbonprice_scenario, settings.target_year
        )
    elif xlsx_dashboard is not None:
        carbon_price_usd = xlsx_dashboard.carbon_price_usd
    else:
        carbon_price_usd = 0.0

    return settings_mod.Dashboard(
        settings=settings,
        cc_rules=cc_rules,
        cf_constraints=cf_constraints,
        carbon_price_usd=carbon_price_usd,
        emission_intensity=emission_intensity,
        province_mapping=province_mapping,
        carrier_rules=carrier_rules,
        carrier_rules_t=carrier_rules_t,
        region_rules=region_rules,
        demand_redist_rules=demand_redist_rules,
        generator_replacements=generator_replacements,
        marginal_cost_rules=marginal_cost_rules,
    )


def _table_to_df(rows: Any) -> pd.DataFrame | None:
    """Convert an SDK ``table`` field value (``list[dict]``) into a DataFrame."""
    if not isinstance(rows, list) or not rows:
        return None
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        norm = {str(k).strip(): v for k, v in row.items()}
        # Drop rows where every value is blank
        if any(_cell_nonempty(v) for v in norm.values()):
            cleaned.append(norm)
    if not cleaned:
        return None
    return pd.DataFrame(cleaned)


def _cell_nonempty(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, float) and math.isnan(v):
        return False
    return str(v).strip() != ""


def _normalise_region_rules(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Loader.py lowercases these columns at parse time — match that here."""
    if df is None or df.empty:
        return df
    out = df.copy()
    out.columns = out.columns.str.strip().str.lower()
    for col in ("component", "attribute", "rule"):
        if col in out.columns:
            out[col] = out[col].astype(str).str.strip().str.lower()
    return out


def _filter_constraints(df: pd.DataFrame | None, target_year: int) -> pd.DataFrame:
    empty = pd.DataFrame(columns=["carrier", "attribute", "value"])
    if df is None or df.empty:
        return empty
    df = df.copy()
    df.columns = df.columns.str.strip()
    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce")
        df = df[df["year"] == target_year]
    if not {"carrier", "attribute", "value"}.issubset(df.columns):
        return empty
    df = df.dropna(subset=["carrier", "attribute", "value"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    return df[["carrier", "attribute", "value"]].reset_index(drop=True)


def _custom_dsl_from_cf(network: Any, cfg: dict[str, Any]) -> str:
    """Render the CF capacity-factor config as Ragnarok custom-DSL lines.

    The frontend reads ``RAGNAROK_CustomDSL`` into the Advanced Constraints box
    and compiles it to ``constraintSpecs`` on Run. ``cf("C") <= v`` means the
    capacity factor of carrier C is at most v (``max_cf``); ``>=`` is ``min_cf``
    — matching the backend's ``cf(C) <op> n  ⇒  gen(C) <op> n·cap(C)·hours``.
    Only carriers that actually have generators are emitted.
    """
    if not _as_bool(cfg, "constraints", False):
        return ""
    target_year = _as_int(cfg, "target_year", 2030)
    cf_df = _filter_constraints(_table_to_df(cfg.get("constraints_rows")), target_year)
    if cf_df is None or cf_df.empty:
        return ""

    active = {
        a.strip()
        for a in _as_str(cfg, "constraints_attribute", "max_cf,min_cf").split(",")
        if a.strip()
    }
    op = {"max_cf": "<=", "min_cf": ">="}
    carriers_with_gens = set(
        network.generators["carrier"].dropna().astype(str).unique()
    )

    lines: list[str] = []
    for _, row in cf_df.iterrows():
        carrier = str(row["carrier"]).strip()
        attribute = str(row["attribute"]).strip()
        if attribute not in active or attribute not in op or not carrier:
            continue
        if carrier not in carriers_with_gens:
            logger.warning(
                "[dashboard-importer] CF DSL skip: carrier %r has no generators",
                carrier,
            )
            continue
        lines.append(f'cf("{carrier}") {op[attribute]} {float(row["value"]):g}')

    if not lines:
        return ""
    header = f"# Dashboard Importer — CF constraints (target year {target_year})"
    return "\n".join([header, *lines]) + "\n"


def _emission_intensity_series(df: pd.DataFrame, target_year: int) -> pd.Series:
    df = df.copy()
    df.columns = df.columns.str.strip()
    if not {"year", "carrier", "value"}.issubset(df.columns):
        return pd.Series(dtype=float)
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df[df["year"] == target_year].dropna(subset=["carrier", "value"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    return pd.Series(
        df["value"].values,
        index=df["carrier"].astype(str).str.strip(),
        name="intensity_kg_MWh",
        dtype=float,
    )


def _lookup_carbon_price_long(
    df: pd.DataFrame, scenario: str, target_year: int
) -> float:
    """Long-format lookup: rows are (scenario, year, value)."""
    if df is None or df.empty:
        return 0.0
    df = df.copy()
    df.columns = df.columns.str.strip()
    if not {"scenario", "year", "value"}.issubset(df.columns):
        return 0.0
    scenario = str(scenario or "").strip()
    if not scenario:
        return 0.0
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    match = df[
        (df["scenario"].astype(str).str.strip() == scenario)
        & (df["year"] == target_year)
    ]
    if match.empty:
        return 0.0
    val = match.iloc[0]["value"]
    return float(val) if pd.notna(val) else 0.0


# ---------------------------------------------------------------------------
# File-value helpers
# ---------------------------------------------------------------------------


def _is_file_value(v: Any) -> bool:
    """Detect a Ragnarok PluginFileValue dict ``{name, content, mime}``."""
    return isinstance(v, dict) and "name" in v and "content" in v and "mime" in v


def _decode_binary_file_value(file_val: dict[str, Any]) -> bytes:
    """Decode a ``binary: true`` file upload into raw bytes.

    The SDK delivers ``content`` as a data URL: ``data:<mime>;base64,<payload>``.
    Defensive fallback handles a bare base64 string or text content.
    """
    content = file_val.get("content", "") or ""
    if isinstance(content, bytes):
        return content
    if content.startswith("data:"):
        comma = content.find(",")
        if comma > 0:
            header, payload = content[5:comma], content[comma + 1 :]
            if "base64" in header.lower():
                return base64.b64decode(payload)
            return payload.encode("utf-8", errors="replace")
    # Bare string — try base64 first, fall back to Latin-1 byte-preserving.
    try:
        return base64.b64decode(content, validate=True)
    except Exception:
        try:
            return content.encode("latin-1")
        except UnicodeEncodeError:
            return content.encode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _resolve_dashboard_path(cfg: dict[str, Any]) -> Path | None:
    raw = str(cfg.get("dashboard_path", "") or "").strip()
    if not raw:
        return None
    path = _resolve_path(raw)
    if not path.exists():
        raise ValueError(f"dashboard_path does not exist: {path}")
    return path


def _resolve_export_path(cfg: dict[str, Any], base: Path) -> Path | None:
    raw = str(cfg.get("export_path", "") or "").strip()
    if not raw:
        return None
    return _resolve_path(raw, base=base)


# Uploaded model_file bytes are materialised to a CONTENT-ADDRESSED path so that
# repeated calls (the GUI fills filter dropdowns by re-POSTing the whole config,
# including the base64 model, on every interaction) reuse ONE file instead of
# leaking a fresh NamedTemporaryFile each time. Without this the temp dir filled
# with thousands of identical xlsx copies → "No space left on device". Stale
# entries are reaped on each call so the cache dir is self-bounding.
_MODEL_CACHE_DIR = Path(tempfile.gettempdir()) / "ragnarok_dashboard_models"
_MODEL_CACHE_TTL_SECONDS = 3600  # reap files untouched for > 1 h


def _reap_model_cache(now: float) -> None:
    try:
        for stale in _MODEL_CACHE_DIR.glob("model_*"):
            try:
                if now - stale.stat().st_mtime > _MODEL_CACHE_TTL_SECONDS:
                    stale.unlink()
            except OSError:
                pass
    except OSError:
        pass


def _materialize_uploaded_model(data: bytes, suffix: str) -> Path:
    """Write the uploaded model bytes to ``<tmp>/ragnarok_dashboard_models/
    model_<sha256[:16]><suffix>``, reusing the file if it already exists."""
    import hashlib
    import os
    import time

    _MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    _reap_model_cache(now)
    digest = hashlib.sha256(data).hexdigest()[:16]
    target = _MODEL_CACHE_DIR / f"model_{digest}{suffix}"
    if target.exists() and target.stat().st_size == len(data):
        os.utime(target, None)  # touch so reuse keeps it past the TTL
        return target
    # Atomic write: a unique temp in the same dir, then rename onto the target.
    fd, tmp_name = tempfile.mkstemp(
        dir=str(_MODEL_CACHE_DIR), prefix="part_", suffix=suffix
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
    logger.info(
        "[dashboard-importer] cached uploaded model_file (%d bytes) -> %s",
        len(data),
        target.name,
    )
    return target


def _resolve_model_workbook(
    cfg: dict[str, Any],
    dashboard_path: Path | None,
    xlsx_model: str,
) -> Path:
    """Resolve the PyPSA model workbook path.

    Priority:
    1. GUI ``model_path`` text input
    2. GUI ``model_file`` upload (binary base64 → temp file)
    3. ``dashboard.xlsx`` embedded ``model`` field
    """
    gui_path = str(cfg.get("model_path", "") or "").strip()
    if gui_path:
        resolved = _resolve_path(gui_path)
        if not resolved.exists():
            raise ValueError(f"model_path does not exist: {resolved}")
        return resolved

    file_val = cfg.get("model_file")
    if _is_file_value(file_val) and file_val.get("content"):
        data = _decode_binary_file_value(file_val)
        suffix = Path(str(file_val.get("name", "model.xlsx"))).suffix or ".xlsx"
        return _materialize_uploaded_model(data, suffix)

    if dashboard_path is not None and xlsx_model:
        candidate = Path(str(xlsx_model).strip()).expanduser()
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else (dashboard_path.parent / candidate).resolve()
        )
        if not resolved.exists():
            raise ValueError(
                f"Dashboard-embedded model path does not exist: {resolved}"
            )
        return resolved

    raise ValueError(
        "No model workbook specified. Set 'Model workbook path' (model_path) "
        "to an absolute path, upload a model_file, or set dashboard_path."
    )


def _resolve_path(raw: str, base: Path | None = None) -> Path:
    text = raw.replace("${HOME}", str(Path.home()))
    text = text.replace("${PROJECT_ROOT}", str(Path.cwd()))
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (base or Path.cwd()) / path
    return path.resolve()


# Serialises the bundled-lib import block. This server is long-lived and runs
# request handlers in a threadpool (FastAPI run_in_threadpool), so two requests
# can import the bundled lib concurrently. The import machinery is not safe
# against another thread mutating sys.modules mid-import, so we hold this lock
# for the (cheap, cached-after-first) import block.
_IMPORT_LOCK = threading.Lock()

# The bundled dashboard_lib registers in sys.modules under a name derived from
# THIS plugin's install directory — never as bare "dashboard_lib", and with no
# sys.path mutation. Plugins get copy-pasted from each other, so two installed
# plugins can easily both ship a package named dashboard_lib; importing it by
# its bare name would silently hand one plugin the other's code (whichever
# imported first wins). The directory name is the install id, unique under the
# plugins dir, so every installed copy keeps its own modules.
_LIB_ALIAS = "_ragnarok_plugin_lib_" + re.sub(r"\W", "_", PLUGIN_ROOT.name)

# This module is re-executed whenever the plugin is (re)installed or the
# registry refreshes (plugin.py reloads, then _load_engine re-execs us). Drop
# any lib modules a PREVIOUS install registered under our alias so a reinstall
# with changed dashboard_lib files takes effect without a backend restart.
# In-flight holders keep their already-bound module objects; the next _lib()
# call re-imports from this install's files.
_STALE_LIBS = [
    n for n in list(sys.modules) if n == _LIB_ALIAS or n.startswith(_LIB_ALIAS + ".")
]
for _name in _STALE_LIBS:
    del sys.modules[_name]


def _lib(submodule: str) -> Any:
    """Import a bundled ``dashboard_lib`` submodule, isolated and thread-safe.

    Loads the package once under :data:`_LIB_ALIAS` and returns the requested
    submodule (``_lib("loader")`` ≙ ``dashboard_lib.loader``). Modules stay
    cached after the first call; relative imports inside the package resolve
    within the alias, so the lib never sees — or collides on — its bare name.
    """
    with _IMPORT_LOCK:
        if _LIB_ALIAS not in sys.modules:
            init = PLUGIN_ROOT / "dashboard_lib" / "__init__.py"
            spec = importlib.util.spec_from_file_location(
                _LIB_ALIAS, init, submodule_search_locations=[str(init.parent)]
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load bundled dashboard_lib from {init}")
            pkg = importlib.util.module_from_spec(spec)
            # Register before exec so the package's relative imports resolve.
            sys.modules[_LIB_ALIAS] = pkg
            try:
                spec.loader.exec_module(pkg)
            except BaseException:
                sys.modules.pop(_LIB_ALIAS, None)
                raise
        return importlib.import_module(f"{_LIB_ALIAS}.{submodule}")


# ---------------------------------------------------------------------------
# Network → Ragnarok model conversion
# ---------------------------------------------------------------------------


def _network_to_model(network: Any) -> dict[str, list[dict[str, Any]]]:
    model = _empty_model()

    snapshots = []
    for snapshot in network.snapshots:
        row = {"snapshot": _normalize_scalar(snapshot)}
        for col in ("objective", "stores", "generators"):
            if col in network.snapshot_weightings.columns:
                row[col] = _normalize_scalar(
                    network.snapshot_weightings.at[snapshot, col]
                )
        snapshots.append(row)
    model["snapshots"] = snapshots

    model["network"] = (
        [{"name": str(network.name)}] if getattr(network, "name", "") else []
    )

    for component in network.iterate_components():
        sheet_name = component.list_name
        if sheet_name in model:
            model[sheet_name] = _frame_to_rows(component.df)

    for sheet_name, (component_name, attr) in TS_SHEET_ATTRS.items():
        pnl = getattr(network, f"{component_name}_t", None)
        if pnl is None:
            continue
        df = getattr(pnl, attr, None)
        if df is None or df.empty:
            continue
        out = df.copy()
        out.index.name = out.index.name or "snapshot"
        model[sheet_name] = _frame_to_rows(out.reset_index(), preserve_index=False)

    return model


def _frame_to_rows(
    frame: pd.DataFrame, preserve_index: bool = True
) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    out = frame.copy()
    if preserve_index:
        out.index.name = out.index.name or "name"
        out = out.reset_index()
    rows = []
    for raw_row in out.to_dict(orient="records"):
        row = {str(key): _normalize_scalar(value) for key, value in raw_row.items()}
        if any(value not in (None, "") for value in row.values()):
            rows.append(row)
    return rows


def _write_model_workbook(
    model: dict[str, list[dict[str, Any]]], export_path: Path
) -> None:
    export_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(export_path, engine="openpyxl") as writer:
        for sheet in MODEL_SHEETS:
            rows = model.get(sheet) or []
            if not rows:
                continue
            pd.DataFrame(rows).to_excel(writer, sheet_name=sheet, index=False)


# Sentinel finite value used to represent +/- infinity when serialising to
# the Ragnarok workbook dict.  JSON doesn't carry IEEE infinities, so we
# substitute a value large enough to be "effectively unbounded" in any
# realistic power-system optimisation but still finite.  1e12 MW = 1 TW —
# four orders of magnitude above the largest national grid today.
_INF_SENTINEL: float = 1e12


def _normalize_scalar(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "item") and callable(value.item):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat(sep=" ")
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            if math.isnan(value):
                return None
            if math.isinf(value):
                return _INF_SENTINEL if value > 0 else -_INF_SENTINEL
        return value
    if isinstance(value, str):
        return value
    return str(value)


def _empty_model() -> dict[str, list[dict[str, Any]]]:
    return {sheet: [] for sheet in MODEL_SHEETS}
