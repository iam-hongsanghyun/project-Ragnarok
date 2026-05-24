from __future__ import annotations

from typing import Any

from ..models import RunPayload
from ..pathway import parse_pathway_config
from ..utils.coerce import number, text
from ..utils.workbook import workbook_rows


def validate_model(payload: RunPayload) -> dict[str, Any]:
    """Validate workbook structure without optimising. Returns errors, warnings, and a network summary."""
    errors: list[str] = []
    warnings: list[str] = []
    model = payload.model
    pathway = parse_pathway_config((payload.options or {}).get("pathwayConfig") if payload.options else None)

    # ── Snapshots ──────────────────────────────────────────────────────────────
    snapshot_rows = workbook_rows(model, "snapshots")
    snapshot_count = len(snapshot_rows)
    if snapshot_count == 1:
        label = str(
            snapshot_rows[0].get("name")
            or snapshot_rows[0].get("snapshot")
            or snapshot_rows[0].get("datetime")
            or ""
        ).strip().lower()
        if label in ("now", ""):
            warnings.append(
                "Snapshot series contains a single 'now' entry — static single-period model. "
                "The simulation will run as one dispatch period."
            )
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
                errors.append(
                    "Pathway mode with explicit period mapping requires every snapshots row to have a period value."
                )
            if snapshot_periods:
                observed = sorted(set(snapshot_periods))
                if observed != configured_periods:
                    errors.append(
                        "Snapshot periods must match the configured investment periods exactly."
                    )
        elif snapshot_count == 0:
            errors.append("Pathway mode requires at least one snapshot row.")

    # ── Topology ────────────────────────────────────────────────────────────────
    buses = workbook_rows(model, "buses")
    if not buses:
        errors.append("No buses defined. At least one bus is required.")
    bus_names: set[str] = {text(b.get("name")) for b in buses if text(b.get("name"))}

    # Identify loads that have time-series p_set data in the loads-p_set sheet
    loads_ts_rows = model.get("loads-p_set") or []
    ts_index_keys = {"snapshot", "datetime", "name", "index", "timestep"}
    ts_load_names: set[str] = set()
    if loads_ts_rows and loads_ts_rows[0]:
        ts_load_names = {k for k in loads_ts_rows[0].keys() if k.lower() not in ts_index_keys}

    loads = workbook_rows(model, "loads")
    if not loads:
        errors.append("No loads defined. The model cannot be optimised without demand.")
    else:
        for row in loads:
            name = text(row.get("name"))
            bus = text(row.get("bus"))
            if not name:
                warnings.append("A load row has no name — it will be skipped.")
            elif bus and bus not in bus_names:
                errors.append(f"Load '{name}' references non-existent bus '{bus}'.")
            if name and name not in ts_load_names:
                p_set = number(row.get("p_set"), None)
                if p_set is None or p_set <= 0:
                    errors.append(f"Load '{name}' has zero or missing p_set with no time-series data — it contributes no demand.")

    generators = workbook_rows(model, "generators")
    if not generators:
        errors.append("No generators defined. The model cannot be optimised without supply.")
    else:
        for row in generators:
            name = text(row.get("name"))
            bus = text(row.get("bus"))
            if not name:
                continue
            if bus and bus not in bus_names:
                errors.append(f"Generator '{name}' references non-existent bus '{bus}'.")
            p_nom = number(row.get("p_nom"), 0.0)
            if p_nom <= 0:
                warnings.append(f"Generator '{name}' has p_nom ≤ 0 — it will produce no power.")

    # ── Carrier CO₂ emission factor sanity check ────────────────────────────────
    # PyPSA convention: co2_emissions is in tCO₂/MWh. No real fuel exceeds ~1.
    # A value > 5 almost certainly means the user entered kg/MWh by mistake.
    for row in workbook_rows(model, "carriers"):
        name = text(row.get("name"))
        co2 = number(row.get("co2_emissions"), None)
        if name and co2 is not None and co2 > 5.0:
            warnings.append(
                f"Carrier '{name}' has co2_emissions={co2} — expected tCO₂/MWh "
                f"(real fuels are ≤ ~1). If this is kg/MWh, divide by 1000."
            )

    # ── Optional but common issues ──────────────────────────────────────────────
    for row in workbook_rows(model, "lines"):
        name = text(row.get("name"))
        if not name:
            continue
        for end in ("bus0", "bus1"):
            bus = text(row.get(end))
            if bus and bus not in bus_names:
                errors.append(f"Line '{name}' {end} references non-existent bus '{bus}'.")

    for row in workbook_rows(model, "links"):
        name = text(row.get("name"))
        if not name:
            continue
        for end in ("bus0", "bus1"):
            bus = text(row.get(end))
            if bus and bus not in bus_names:
                errors.append(f"Link '{name}' {end} references non-existent bus '{bus}'.")

    # Structural counts only — the full PyPSA-side validation happens at Run
    # time when `build_network()` constructs the network and `optimize()` is
    # executed against the in-memory workbook payload.
    network_summary = {
        "buses": len(buses),
        "generators": len(generators),
        "loads": len(loads),
        "lines": len(workbook_rows(model, "lines")),
        "links": len(workbook_rows(model, "links")),
        "storageUnits": len(workbook_rows(model, "storage_units")),
        "stores": len(workbook_rows(model, "stores")),
        "snapshots": snapshot_count,
    }

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "notes": [],
        "snapshotCount": snapshot_count,
        "networkSummary": network_summary,
    }
