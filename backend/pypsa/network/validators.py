from __future__ import annotations

from typing import Any

from ...app.models import RunPayload
from ..pathway import parse_pathway_config
from ..pypsa_schema import (
    bus_reference_attributes,
    component_schema,
    component_sheets,
    input_temporal_attributes,
    output_attributes,
    required_input_static_attributes,
)
from ..rolling import parse_rolling_config
from ..utils.coerce import number, text
from ..utils.workbook import workbook_rows

TS_INDEX_KEYS = {"snapshot", "datetime", "name", "index", "timestep", "period", "timestamp", "time"}
NON_NEGATIVE_ATTRS = {
    "p_nom", "p_nom_min", "p_nom_max",
    "s_nom", "s_nom_min", "s_nom_max",
    "e_nom", "e_nom_min", "e_nom_max",
    "p_set", "q_set", "inflow",
    "capital_cost", "marginal_cost", "marginal_cost_quadratic",
    "start_up_cost", "shut_down_cost", "stand_by_cost",
    "co2_emissions",
}


def _known_input_temporal_sheets() -> set[str]:
    sheets: set[str] = set()
    for sheet in component_sheets():
        for attr in input_temporal_attributes(sheet):
            sheets.add(f"{sheet}-{attr}")
    return sheets


def _known_output_temporal_sheets() -> set[str]:
    sheets: set[str] = set()
    for sheet in component_sheets():
        component = component_schema(sheet)
        temporal = set(component.get("temporal_attributes", [])) if component else set()
        for attr in output_attributes(sheet):
            if attr in temporal:
                sheets.add(f"{sheet}-{attr}")
    return sheets


def _row_name(row: dict[str, Any]) -> str:
    return text(row.get("name"))


def _snapshot_label(row: dict[str, Any]) -> str:
    return str(
        row.get("snapshot")
        or row.get("name")
        or row.get("datetime")
        or row.get("timestep")
        or row.get("index")
        or ""
    ).strip()


def _effective_snapshot_count(snapshot_rows: list[dict[str, Any]], pathway_enabled: bool) -> tuple[int, int]:
    if pathway_enabled:
        return len(snapshot_rows), 0
    seen: set[str] = set()
    duplicates = 0
    count = 0
    for row in snapshot_rows:
      label = _snapshot_label(row)
      if not label:
        continue
      if label in seen:
        duplicates += 1
        continue
      seen.add(label)
      count += 1
    return count or (1 if snapshot_rows else 0), duplicates


def _check_required_fields(sheet: str, rows: list[dict[str, Any]], errors: list[str]) -> None:
    required = required_input_static_attributes(sheet)
    if not required:
        return
    for row in rows:
        name = _row_name(row) or "<unnamed>"
        for attr in required:
            if row.get(attr) in (None, ""):
                errors.append(f"{sheet}: row '{name}' is missing required field '{attr}'.")


def _check_duplicate_names(sheet: str, rows: list[dict[str, Any]], errors: list[str]) -> None:
    if "name" not in required_input_static_attributes(sheet):
        return
    seen: set[str] = set()
    for row in rows:
        name = _row_name(row)
        if not name:
            errors.append(f"{sheet}: found a row with empty name.")
            continue
        if name in seen:
            errors.append(f"{sheet}: duplicate component name '{name}'.")
            continue
        seen.add(name)


def _check_bus_refs(
    sheet: str,
    rows: list[dict[str, Any]],
    bus_names: set[str],
    errors: list[str],
) -> None:
    refs = bus_reference_attributes(sheet)
    if not refs:
        return
    for row in rows:
        name = _row_name(row) or "<unnamed>"
        for attr in refs:
            field = str(attr.get("attribute", ""))
            required = bool(attr.get("required"))
            value = text(row.get(field))
            if not value:
                if required:
                    errors.append(f"{sheet}: row '{name}' is missing required bus reference '{field}'.")
                continue
            if value not in bus_names:
                errors.append(f"{sheet}: row '{name}' references unknown bus '{value}' via '{field}'.")


def _check_numeric_sanity(sheet: str, rows: list[dict[str, Any]], warnings: list[str], errors: list[str]) -> None:
    for row in rows:
        name = _row_name(row) or "<unnamed>"
        for field, raw in row.items():
            if raw in (None, ""):
                continue
            value = number(raw, None)
            if value is None:
                continue
            if (field in NON_NEGATIVE_ATTRS or field.endswith("_nom")) and value < 0:
                errors.append(f"{sheet}: row '{name}' has negative '{field}' ({value}).")
            if field.endswith("_pu") and (value < 0 or value > 1):
                warnings.append(f"{sheet}: row '{name}' has '{field}'={value} outside [0, 1].")
            if field == "efficiency" and value > 5:
                warnings.append(f"{sheet}: row '{name}' has efficiency={value} — check units (ratio/COP, not %).")
            if field == "co2_emissions" and value > 5:
                warnings.append(
                    f"{sheet}: row '{name}' has co2_emissions={value} — expected tCO₂/MWh (likely needs ÷1000 if entered as kg/MWh)."
                )


def _check_carrier_refs(sheet: str, rows: list[dict[str, Any]], carrier_names: set[str], warnings: list[str]) -> None:
    if not carrier_names:
        return
    for row in rows:
        if "carrier" not in row:
            continue
        name = _row_name(row) or "<unnamed>"
        carrier = text(row.get("carrier"))
        if carrier and carrier not in carrier_names:
            warnings.append(f"{sheet}: row '{name}' references undefined carrier '{carrier}'.")


def _check_output_columns(sheet: str, rows: list[dict[str, Any]], notes: list[str]) -> None:
    output_cols = output_attributes(sheet)
    if not output_cols:
        return
    present = sorted({col for row in rows for col in row.keys() if col in output_cols})
    if present:
        notes.append(
            f"{sheet}: output-only columns will be ignored on run ({', '.join(present[:6])}{' …' if len(present) > 6 else ''})."
        )


def _check_ts_sheets(
    model: dict[str, list[dict[str, Any]]],
    snapshot_count: int,
    pathway_enabled: bool,
    notes: list[str],
    warnings: list[str],
    errors: list[str],
) -> None:
    known_input_ts = _known_input_temporal_sheets()
    known_output_ts = _known_output_temporal_sheets()
    static_names = {
        sheet: {_row_name(row) for row in workbook_rows(model, sheet) if _row_name(row)}
        for sheet in component_sheets()
    }
    for sheet, rows in model.items():
        if not rows or "-" not in sheet:
            continue
        if sheet in known_output_ts:
            notes.append(f"{sheet}: output-only time-series sheet will be ignored on run.")
            continue
        if sheet not in known_input_ts:
            continue
        list_name, _, attr = sheet.partition("-")
        label_candidates = [key for key in rows[0].keys() if key.lower() in TS_INDEX_KEYS]
        if not label_candidates:
            errors.append(f"{sheet}: time-series sheet is missing a snapshot label column.")
            continue
        if snapshot_count > 0 and len(rows) != snapshot_count:
            warnings.append(f"{sheet}: row count {len(rows)} differs from snapshot count {snapshot_count}.")
        seen_labels: set[str] = set()
        duplicates = 0
        for row in rows:
            label = _snapshot_label(row)
            if not label:
                continue
            if not pathway_enabled and label in seen_labels:
                duplicates += 1
                continue
            seen_labels.add(label)
        if duplicates:
            notes.append(f"{sheet}: found {duplicates} duplicated snapshot label(s); single-period runs dedupe them by first occurrence.")
        component_names = static_names.get(list_name, set())
        cols = [key for key in rows[0].keys() if key.lower() not in TS_INDEX_KEYS]
        if not cols:
            warnings.append(f"{sheet}: time-series sheet has no component columns.")
            continue
        for col in cols:
            if col not in component_names:
                errors.append(f"{sheet}: time-series column '{col}' does not exist in sheet '{list_name}'.")
        for row in rows:
            for col in cols:
                raw = row.get(col)
                if raw in (None, ""):
                    continue
                value = number(raw, None)
                if value is None:
                    continue
                if attr.endswith("_pu") and (value < 0 or value > 1):
                    warnings.append(f"{sheet}: column '{col}' has values outside [0, 1].")
                    break
                if attr in {"p_set", "inflow"} and value < 0:
                    warnings.append(f"{sheet}: column '{col}' has negative values.")
                    break


def validate_model(payload: RunPayload) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    model = payload.model
    options = payload.options or {}
    pathway = parse_pathway_config(options.get("pathwayConfig"))
    rolling = parse_rolling_config(options.get("rollingConfig"))

    known_static = set(component_sheets())
    known_input_ts = _known_input_temporal_sheets()
    known_output_ts = _known_output_temporal_sheets()

    populated_static = [sheet for sheet in known_static if workbook_rows(model, sheet)]
    if populated_static:
        notes.append("PyPSA defaults will be used for omitted optional input attributes.")

    for sheet, rows in model.items():
        if not rows:
            continue
        if sheet.startswith("RAGNAROK_"):
            continue
        if sheet in known_output_ts:
            notes.append(f"{sheet}: output-only sheet present in workbook and ignored for validation/run.")
            continue
        if sheet not in known_static and sheet not in known_input_ts:
            warnings.append(f"{sheet}: unrecognized sheet will be ignored.")

    snapshot_rows = workbook_rows(model, "snapshots")
    raw_snapshot_count = len(snapshot_rows)
    effective_snapshot_count, deduped_snapshots = _effective_snapshot_count(snapshot_rows, pathway.enabled)
    if raw_snapshot_count == 1:
        label = _snapshot_label(snapshot_rows[0]).lower() if snapshot_rows else ""
        if label in ("now", ""):
            warnings.append(
                "Snapshot series contains a single 'now' entry — static single-period model. The simulation will run as one dispatch period."
            )
    if deduped_snapshots:
        notes.append(f"Snapshots: deduped {deduped_snapshots} repeated label(s) for single-period interpretation.")

    if pathway.enabled:
        if not pathway.periods:
            errors.append("Pathway mode requires at least one investment period.")
        configured_periods = [row.period for row in pathway.periods]
        if configured_periods != sorted(set(configured_periods)):
            errors.append("Investment periods must be unique increasing integers.")
        snapshot_periods: list[int] = []
        missing_period_rows = 0
        for row in snapshot_rows:
            period_value = row.get("period")
            if period_value in (None, ""):
                missing_period_rows += 1
                continue
            try:
                snapshot_periods.append(int(number(period_value)))
            except Exception:
                errors.append(f"Invalid snapshot period value: {period_value}")
                break
        if pathway.snapshot_mapping_mode == "explicit_period_column":
            if missing_period_rows > 0:
                errors.append("Pathway mode with explicit period mapping requires every snapshots row to have a period value.")
            if snapshot_periods:
                observed = sorted(set(snapshot_periods))
                if observed != configured_periods:
                    errors.append("Snapshot periods must match the configured investment periods exactly.")
        elif raw_snapshot_count == 0:
            errors.append("Pathway mode requires at least one snapshot row.")
        notes.append(
            "Pathway effective horizon: "
            + ", ".join(str(row.period) for row in pathway.periods)
            + f" across {raw_snapshot_count} snapshot row(s)."
        )

    if rolling.enabled:
        if effective_snapshot_count <= 0:
            errors.append("Rolling horizon requires at least one snapshot.")
        if rolling.horizon_snapshots <= 0:
            errors.append("Rolling horizon size must be a positive integer.")
        if rolling.overlap_snapshots < 0:
            errors.append("Rolling overlap must be zero or greater.")
        if rolling.overlap_snapshots >= rolling.horizon_snapshots:
            errors.append("Rolling overlap must be smaller than the horizon size.")
        notes.append(
            f"Rolling effective horizon: {effective_snapshot_count} snapshots, horizon {rolling.horizon_snapshots}, overlap {rolling.overlap_snapshots}, step {rolling.step_snapshots}."
        )

    buses = workbook_rows(model, "buses")
    if not buses:
        errors.append("No buses defined. At least one bus is required.")
    bus_names: set[str] = {_row_name(row) for row in buses if _row_name(row)}
    carrier_names: set[str] = {_row_name(row) for row in workbook_rows(model, "carriers") if _row_name(row)}

    loads = workbook_rows(model, "loads")
    generators = workbook_rows(model, "generators")
    if not loads:
        errors.append("No loads defined. The model cannot be optimised without demand.")
    if not generators:
        errors.append("No generators defined. The model cannot be optimised without supply.")

    loads_ts_rows = model.get("loads-p_set") or []
    ts_load_names: set[str] = set()
    if loads_ts_rows and loads_ts_rows[0]:
        ts_load_names = {k for k in loads_ts_rows[0].keys() if k.lower() not in TS_INDEX_KEYS}
    for row in loads:
        name = _row_name(row)
        if not name:
            warnings.append("loads: found a row with empty name — it will be skipped.")
            continue
        if name not in ts_load_names:
            p_set = number(row.get("p_set"), None)
            if p_set is None or p_set <= 0:
                errors.append(f"Load '{name}' has zero or missing p_set with no time-series data — it contributes no demand.")

    for sheet in known_static:
        rows = workbook_rows(model, sheet)
        if not rows or sheet in {"snapshots", "network"}:
            continue
        _check_duplicate_names(sheet, rows, errors)
        _check_required_fields(sheet, rows, errors)
        _check_bus_refs(sheet, rows, bus_names, errors)
        _check_numeric_sanity(sheet, rows, warnings, errors)
        _check_carrier_refs(sheet, rows, carrier_names, warnings)
        _check_output_columns(sheet, rows, notes)

    _check_ts_sheets(model, raw_snapshot_count, pathway.enabled, notes, warnings, errors)

    network_summary = {
        sheet: len(workbook_rows(model, sheet))
        for sheet in known_static
        if len(workbook_rows(model, sheet)) > 0
    }
    network_summary["snapshots"] = raw_snapshot_count

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "notes": notes,
        "snapshotCount": raw_snapshot_count,
        "networkSummary": network_summary,
    }
