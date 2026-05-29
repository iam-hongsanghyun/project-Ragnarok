# backend-network — Function Reference

Covers: `backend/pypsa/network/__init__.py`, `components.py`, `network_sheet.py`, `snapshots.py`, `custom_constraints.py`, `load_shedding.py`, `validators.py`.

---

## backend/pypsa/network/\_\_init\_\_.py

Top-level entry points for network construction and pre-run validation.

### `build_network(model, scenario, options=None) -> tuple[pypsa.Network, list[str]]`

Builds a solve-ready `pypsa.Network` from the JSON workbook model.

Params:
- `model: dict[str, list[dict[str, Any]]]` — workbook as `{sheet_name: [row_dict, ...]}`.
- `scenario: dict[str, Any]` — must include `discountRate` (dimensionless); may include `carbonPrice` (currency/tCO2), `constraints`.
- `options: dict[str, Any] | None` — `snapshotStart` (int, 0-based index), `snapshotCount` (int, number of snapshots to model), `snapshotWeight` (int, hours per snapshot step), `forceLp` (bool), `enableLoadShedding` (bool), `loadSheddingCost` (currency/MWh), `currencySymbol` (str), `pathwayConfig`, `stochasticConfig`, `carbonPriceSchedule`, `enabledModules`, plus module-system keys.

Returns: `(network, notes)` where `notes` is a list of human-readable narrative strings appended to the run log.

Processing order:
1. Apply network-sheet metadata (`name`, `srid`, `crs`, `now`).
2. Build snapshot index from the `snapshots` sheet; apply pathway investment periods.
3. Bulk-add every component class in dependency-safe order (carriers, buses first) using PyPSA's `network.add()`.
4. Apply time-series sheets (`<list_name>-<attr>`).
5. Window and downsample snapshots (`snapshotStart`, `snapshotCount`, `snapshotWeight`).
6. Scale annual energy-sum caps (`*_sum_min`, `*_sum_max`) by the period factor when modelled hours < 8760 h/yr.
7. Apply carbon price (scalar or schedule) to generator marginal costs.
8. Annuitise `capital_cost` for extendable assets using `annuity_factor(discountRate, lifetime)`.
9. Override `committable=True` if `forceLp` is set.
10. Emit a sanity warning for `co2_emissions > 5` (likely entered as kg/MWh instead of tCO2/MWh).
11. Add per-bus load-shedding generators if `enableLoadShedding`.
12. Apply stochastic scenario expansion if `stochasticConfig.enabled`.

Notes: `discountRate` is required and raises HTTP 400 if absent. All other `options` keys have safe defaults.

---

## backend/pypsa/network/components.py

Component import helpers called by `build_network`.

### `_has_name(row: dict[str, Any]) -> bool`

Returns `True` if `row["name"]` is present and non-blank. Used to filter out template or header rows before DataFrame construction.

### `_strip_blank_columns(df: pd.DataFrame) -> pd.DataFrame`

Drops columns that are entirely null or contain only whitespace strings. Lets PyPSA apply its own defaults for omitted optional attributes.

### `_ordered_component_sheets(network: pypsa.Network) -> list[tuple[str, str]]`

Returns `[(sheet_name, pypsa_class_name), ...]` in dependency-safe import order. Carriers are given priority 0, buses priority 1, everything else follows PyPSA's registry order. This ensures bus references are already resolved when components that reference them are added.

### `_bus_ref_columns_for_list(network: pypsa.Network, list_name: str) -> list[str]`

Returns the bus-reference column names for a given component list (e.g. `["bus"]` for generators, `["bus0", "bus1"]` for lines). Derives these from PyPSA's defaults table by looking for attributes named `"bus"` or `"bus0"`, `"bus1"`, etc.

### `_drop_broken_bus_refs(df, cls, network, sheet, notes) -> pd.DataFrame`

Drops rows where a required bus reference (`bus`, `bus0`, `bus1`) points to a bus not present in `network.buses`. The schema determines which bus columns are required — optional bus references (e.g. on `global_constraints`) do not cause row deletion. Appends a human-readable note for each dropped row.
Params: `df` — component DataFrame; `cls` — PyPSA class name string; `network` — current network; `sheet` — sheet name for notes; `notes` — run-narrative list.
Returns: filtered DataFrame.

### `_ensure_carriers(network: pypsa.Network, carriers: pd.Series) -> None`

Auto-adds any carrier name referenced by a component that has not yet been added to the network's carriers table. Prevents PyPSA from raising on an unknown carrier reference.

### `_apply_ts_sheet(network, rows, list_name, attr) -> None`

Assigns one time-series sheet to `network.<list_name>_t.<attr>`.
Params: `rows` — list of row dicts from the workbook; `list_name` — PyPSA component list name; `attr` — time-varying attribute name.
Steps: builds a DataFrame, detects the snapshot label column (`snapshot`, `datetime`, `name`, `index`, `timestep`), coerces numeric columns, aligns to `network.snapshots` (handling both single-period `DatetimeIndex` and pathway `MultiIndex`), deduplicates timestamps for single-period runs, and merges into the existing `_t` frame via `pd.concat`.

---

## backend/pypsa/network/network_sheet.py

Applies the `network` workbook sheet and provides bus-load utilities.

### `_apply_network_sheet(network, model, notes) -> None`

Reads the first non-empty row from `model["network"]` and applies each field according to the `network_import_policy.json` schema.
Supported fields: `name` (string), `srid` (integer EPSG code applied via `CRS.from_epsg`), `crs` (any string accepted by `CRS.from_user_input`), `now` (set directly on `network.now`).
Params: `network` — `pypsa.Network` to mutate; `model` — workbook dict; `notes` — narrative list.

### `_override_network_crs(network: pypsa.Network, crs: CRS) -> None`

Sets the CRS on `network.c.shapes.static` and `network._crs`. Used by `_apply_network_sheet` for both `srid` and `crs` fields.

### `_peak_load_per_bus(network: pypsa.Network) -> dict[str, float]`

Computes the peak demand (MW) at each bus across all snapshots. Prefers the time-series `loads_t.p_set` maximum; falls back to the static `loads.p_set` column. Returns `{bus_name: peak_mw}`. Used by `add_load_shedding` to size the VOLL generator.

---

## backend/pypsa/network/snapshots.py

Snapshot index construction and pathway period assignment.

### `_snapshots_index(model, pathway) -> pd.Index`

Builds the snapshot index from the `snapshots` workbook sheet.
Params: `model` — workbook dict; `pathway` — `PathwayConfig`.
Returns: a `DatetimeIndex` (single-period) or a `MultiIndex` with levels `["period", "timestep"]` (pathway mode with `explicit_period_column` mapping). Returns an empty `pd.Index` if no snapshot rows are present.
Notes: input date strings are expected to already be ISO-8601 (the frontend normalises them before sending). Single-period runs deduplicate repeated timestamp labels so pathway workbooks can share the same `snapshots` sheet.

### `_apply_pathway_config(network, pathway, notes) -> None`

Calls `network.set_investment_periods(periods)` and sets `investment_period_weightings` rows from the `PathwayConfig`. Appends a narrative note listing the configured periods. No-op when `pathway.enabled` is False or `pathway.periods` is empty.

### `_normalize_dynamic_snapshot_index_names(network: pypsa.Network) -> None`

Iterates every component's dynamic frames and sets `df.index.name = "snapshot"`. Ensures a consistent index name after any operation that may reset it (snapshot windowing, stochastic expansion, etc.).

---

## backend/pypsa/network/custom_constraints.py

Linopy-level custom constraints applied inside `extra_functionality`.

### `apply_custom_constraints(n, constraints, emissions_factors, notes) -> None`

Applies all enabled custom constraints to the linopy model. Called from the `extra_functionality` callback passed to `network.optimize()`, so `n.model` is available.

Params:
- `n: pypsa.Network` — the network being solved.
- `constraints: list[dict[str, Any]]` — list of constraint dicts from `scenario["constraints"]`. Each dict has `enabled` (bool), `metric` (str), `value` (float), `carrier` (str), `label` (str).
- `emissions_factors: dict[str, float]` — carrier name to tCO2/MWh_e.
- `notes: list[str]` — narrative collector.

Supported metrics:

| `metric` | Constraint |
|---|---|
| `co2_cap` | CO2 emission intensity cap (kg CO2e/MWh). Value is converted to tCO2/MWh. Constraint: total_emissions <= value_tco2 * total_dispatch. |
| `max_load_shed` | Total load shedding <= value (MWh) over the modelled period. |
| `carrier_max_gen` | Total generation from `carrier` <= value (MWh). |
| `carrier_min_gen` | Total generation from `carrier` >= value (MWh). |
| `carrier_max_share` | Carrier dispatch fraction <= value/100 of total non-shedding dispatch. |
| `carrier_min_share` | Carrier dispatch fraction >= value/100 of total non-shedding dispatch. |
| `carrier_max_cf` | Carrier capacity factor <= value/100. Handles extendable capacity via `Generator-p_nom` linopy variable. |
| `carrier_min_cf` | Carrier capacity factor >= value/100. |

Each constraint failure is caught per-constraint and recorded as a note; the solve continues with the remaining constraints.

---

## backend/pypsa/network/load_shedding.py

Per-bus VOLL generator injection.

### `add_load_shedding(network, load_totals, notes, enable_load_shedding=False, load_shedding_cost=None, currency="$") -> None`

Adds a high-cost `"Generator"` at each bus to represent the value of lost load (VOLL). When `enable_load_shedding` is False this is a no-op and a note is appended warning that supply shortfalls will surface as solver infeasibility.

Params:
- `network: pypsa.Network` — must have buses already added.
- `load_totals: dict[str, float]` — peak MW per bus from `_peak_load_per_bus`.
- `notes: list[str]` — narrative collector.
- `enable_load_shedding: bool` — Settings toggle; must be True for generators to be added.
- `load_shedding_cost: float | None` — VOLL in currency/MWh. Falls back to `system_defaults.json` `load_shedding.marginal_cost` when None.
- `currency: str` — symbol for the narrative note.

Generator sizing: `p_nom` is set to `max(peak_time_series_total, static_load_total, 1.0)` MW, uncapped, so the solver can always absorb the full demand shortfall. Generator names use the prefix `load_shedding_<bus>` so `run_pypsa` and `emissions.py` can identify and exclude them from energy mix and emission totals.

---

## backend/pypsa/network/validators.py

Pre-run model validation without building a network.

### `validate_model(payload: RunPayload) -> dict[str, Any]`

Validates the JSON workbook model against the PyPSA schema. Returns a validation result dict that the frontend displays before the user clicks Run.

Returns:
```python
{
    "valid": bool,
    "errors": list[str],       # blocking issues
    "warnings": list[str],     # non-blocking concerns
    "notes": list[str],        # informational
    "snapshotCount": int,
    "networkSummary": {sheet: row_count, ...}
}
```

Checks performed:
- Unrecognised sheet names (warning).
- Output-only sheets present in workbook (note).
- Snapshot count and duplicate label detection.
- Pathway mode: at least one period, periods unique and increasing, snapshot `period` column completeness, snapshot periods match configured periods (when using `explicit_period_column` mapping).
- Rolling horizon: positive `horizonSnapshots`, non-negative `overlapSnapshots`, overlap < horizon.
- At least one bus, one load, one generator.
- Loads with zero or missing `p_set` and no time-series data.
- Per-component: duplicate names, required fields, bus references, numeric sanity (negative `p_nom`, `*_pu` outside [0,1], efficiency > 5, `co2_emissions` > 5), carrier references, output-column presence.
- Time-series sheets: missing snapshot label column, row count vs snapshot count mismatch, component column existence, value range checks.

### Internal validation helpers

#### `_known_input_temporal_sheets() -> set[str]`
Returns all `<list_name>-<attr>` sheet names for attributes marked as input time-series in the schema.

#### `_known_output_temporal_sheets() -> set[str]`
Returns all `<list_name>-<attr>` sheet names for attributes marked as output time-series.

#### `_row_name(row: dict[str, Any]) -> str`
Returns `row["name"]` coerced to string via `text()`, or `""`.

#### `_snapshot_label(row: dict[str, Any]) -> str`
Returns the first non-empty value among `snapshot`, `name`, `datetime`, `timestep`, `index` keys.

#### `_effective_snapshot_count(snapshot_rows, pathway_enabled) -> tuple[int, int]`
Returns `(unique_count, duplicate_count)`. For pathway mode returns the raw row count. For single-period mode deduplicates by label.

#### `_check_required_fields(sheet, rows, errors) -> None`
Appends errors for any row missing a field listed in `required_input_static_attributes(sheet)`.

#### `_check_duplicate_names(sheet, rows, errors) -> None`
Appends errors for duplicate or missing `name` values in a component sheet.

#### `_check_bus_refs(sheet, rows, bus_names, errors) -> None`
Appends errors for missing required bus references and unknown bus names.

#### `_check_numeric_sanity(sheet, rows, warnings, errors) -> None`
Checks non-negative attributes, `*_pu` range [0,1], `efficiency` unit sanity, and `co2_emissions` unit sanity.

#### `_check_carrier_refs(sheet, rows, carrier_names, warnings) -> None`
Warns when a component references a carrier not defined in the `carriers` sheet.

#### `_check_output_columns(sheet, rows, notes) -> None`
Notes when output-only column names appear in input rows (they will be ignored at solve time).

#### `_check_ts_sheets(model, snapshot_count, pathway_enabled, notes, warnings, errors) -> None`
Validates all time-series sheets: snapshot label column presence, row count alignment, component column existence, and value range checks.
