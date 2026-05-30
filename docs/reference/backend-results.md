# backend-results — Function Reference

Covers: `backend/pypsa/results/__init__.py`, `full_outputs.py`, `dispatch.py`, `emissions.py`, `expansion.py`, `market.py`, `summaries.py`.

---

## backend/pypsa/results/\_\_init\_\_.py

The top-level solve-and-extract pipeline.

### `run_pypsa(model, scenario, options=None) -> dict[str, Any]`

The complete Ragnarok PyPSA pipeline: network construction, solve with constraint application via `extra_functionality`, and result extraction.

The backend is plugin-agnostic. Plugins are a frontend concern — they contribute rows and constraints to `model`/`scenario` before the payload is sent to the backend. There are no plugin hooks inside `run_pypsa`.

Params:
- `model: dict[str, list[dict[str, Any]]]` — workbook as `{sheet: rows[]}`.
- `scenario: dict[str, Any]` — `carbonPrice` (currency/tCO2), `discountRate`, `constraints`, `constraintSpecs`, `customDsl`.
- `options: dict[str, Any] | None` — all run-control keys (see `RunPayload.options` in `backend-host.md`).

Raises HTTP 400 for mutually exclusive mode combinations:
- Stochastic + rolling horizon.
- Security-constrained (SCLOPF) + rolling horizon or stochastic.
- SCLOPF + pathway.

Pipeline stages:

1. **Build** — `build_network(model, scenario, options)` constructs a `pypsa.Network` from the JSON workbook model.
2. **Solve** — one of:
   - `network.optimize.optimize_with_rolling_horizon(...)` when `rollingConfig.enabled`.
   - `network.optimize.optimize_security_constrained(...)` when `securityConstrainedConfig.enabled`.
   - `network.optimize(...)` for all other cases (including pathway and stochastic).
   All invocations use `solver_name="highs"`, pass `extra_functionality` (which applies `scenario["constraints"]` and `scenario["constraintSpecs"]`), and forward `solverThreads` / `solverType` as `solver_options`.
3. **Status check** — any solve result other than `condition == "optimal"` raises HTTP 500 immediately.
4. **Stochastic post-processing** (when enabled) — `per_scenario_summaries` collects per-scenario KPIs; `collapse_to_representative_scenario` selects the highest-weight scenario and reshapes the network so the extraction pipeline below works without modification.
5. **Result extraction** — carrier mix, cost breakdown, dispatch/price/emissions series, nodal balance, line loading, expansion results, merit order, CO2 shadow price, and the full PyPSA-native output dataset.

### Internal helper (within `__init__.py`)

#### `extra_functionality(n, snapshots) -> None` (closure)

The callback passed to `network.optimize()`. Applies structured constraints from `scenario["constraints"]` via `apply_custom_constraints`, then applies JSON-spec constraints from `scenario["constraintSpecs"]` via `apply_constraint_specs`. When no `constraintSpecs` are present, falls back to the raw DSL text in `scenario["customDsl"]` via `apply_dsl_constraints`. Defined as a closure inside `run_pypsa` to capture `custom_constraints`, `constraint_specs`, `custom_dsl_text`, and `emissions_factors`.

#### `_coerce_solve_status(result: Any) -> tuple[str, str]`

Normalises the return value of `network.optimize()` into `(status, condition)`. The modern `optimize` path returns a 2-tuple; older SCLOPF paths may return the network or `None`. In those cases `_coerce_solve_status` returns `("ok", "optimal")` since those paths raise on failure rather than returning a non-optimal condition.

### Return value

Returns a dict with the following top-level keys:

| Key | Content |
|---|---|
| `summary` | Six KPI cards (installed capacity, peak demand, reserve position, peak price, system emissions, transmission stress). |
| `dispatchSeries` | Per-snapshot carrier-aggregated dispatch (MW). |
| `generatorDispatchSeries` | Per-snapshot per-generator dispatch (MW). |
| `systemPriceSeries` | Per-snapshot average nodal marginal price (currency/MWh). |
| `systemEmissionsSeries` | Per-snapshot emission intensity (tCO2/h). |
| `storageSeries` | Per-snapshot aggregated storage charge/discharge/state-of-charge. |
| `nodalPriceSeries` | Per-snapshot per-bus marginal prices (currency/MWh). |
| `carrierMix` | Energy mix by carrier with colour (MWh). |
| `costBreakdown` | Fuel cost, carbon cost, load-shedding cost, and (if applicable) capital cost in currency. |
| `nodalBalance` | Average generation and load per bus (MW), sorted by load descending. |
| `lineLoading` | Peak loading percentage for lines, links, and transformers. |
| `expansionResults` | Extendable asset expansion details (see `build_expansion_results`). |
| `meritOrder` | Supply stack sorted by marginal cost (see `build_merit_order`). |
| `co2Shadow` | CO2 shadow price information (see `build_co2_shadow`). |
| `appliedConstraints` | Custom and global constraints recognised by the solver (see `build_applied_constraints`). |
| `emissionsBreakdown` | Per-generator and per-carrier emission breakdown (see `build_emissions_breakdown`). |
| `narrative` | List of human-readable notes accumulated throughout the pipeline. |
| `runMeta` | `snapshotCount`, `snapshotWeight`, `modeledHours`, `storeWeight`, `planningMode`, `investmentPeriods`, and (if rolling) rolling window metadata. |
| `pathway` | Present when pathway is enabled: `enabled`, `periods`, `selectedPeriod`, `snapshotMappingMode`, `summaries`. |
| `rolling` | Present when rolling is enabled: window count, horizon, overlap, step, and per-window boundary labels. |
| `stochastic` | Present when stochastic is enabled: `representativeScenario`, per-scenario `scenarios` summaries. |
| `securityConstrained` | Present when SCLOPF is enabled: `enabled`, `branchCount`. |
| `outputs` | Full PyPSA-native output dataset from `build_full_outputs` — the `assetDetails` cache the frontend uses for per-asset drilldown and project export. |

---

## backend/pypsa/results/full_outputs.py

Schema-driven extraction of every PyPSA output attribute.

### `build_full_outputs(network: pypsa.Network) -> dict[str, Any]`

Walks every component in the schema and returns its solved output values.

Params: `network` — solved `pypsa.Network`.
Returns:
```python
{
    "static": {
        "<list_name>": {
            "<component_name>": {"<attr>": value, ...},
            ...
        },
        ...
    },
    "series": {
        "<list_name>-<attr>": [
            {"snapshot": "2024-01-01T00:00:00", "<component_name>": value, ...},
            ...
        ],
        ...
    }
}
```

Notes: only attributes with `status="output"` in the schema are extracted. `static_or_series` output attributes are recorded as series (PyPSA writes them to `_t` frames after solving). NaN values are omitted from both static and series outputs. Multi-investment results include a `period` key in each series row alongside `snapshot`.

### `_safe_scalar(value: Any) -> Any`

Converts a pandas/numpy scalar to a JSON-safe Python primitive. Returns `None` for NaN, passes through str/bool/int/float, calls `.item()` on numpy scalars. Used by `build_full_outputs` before writing any value into the output dict.

### `_component_output_attrs(sheet_name: str) -> tuple[list[str], list[str]]`

Returns `(static_output_attrs, series_output_attrs)` for a sheet by reading the schema. Attributes with `storage="static_or_series"` are treated as series (PyPSA populates `_t` frames after solving).

### `_iso_timestamp(value: Any) -> str`

Formats a timestamp as `"YYYY-MM-DDTHH:MM:SS"` using `pd.Timestamp.strftime`. Falls back to `str(value)` on parse failure.

### `_series_snapshot_row(snapshot: Any) -> dict[str, Any]`

Builds the index cell(s) for one output time-series row. Single-period snapshots produce `{"snapshot": "..."}`. Multi-investment snapshots (tuples) produce `{"period": int, "snapshot": "..."}`.

---

## backend/pypsa/results/dispatch.py

Per-snapshot dispatch and storage series builders.

### `dispatch_by_carrier(generator_dispatch_frame, generators) -> dict[str, pd.Series]`

Groups generator dispatch by carrier. For each unique carrier in `generators.carrier`, sums the clipped (floor 0.0) dispatch columns. Returns `{carrier: Series}` indexed by snapshots.
Params: `generator_dispatch_frame` — `network.generators_t.p`; `generators` — `network.generators` static frame.

### `build_dispatch_series(network, by_carrier, load_dispatch, generator_dispatch_frame) -> tuple[list[dict], list[dict]]`

Builds two per-snapshot dispatch series for the frontend.
Returns: `(dispatch_series, generator_dispatch_series)`.
- `dispatch_series`: one row per snapshot with `{label, timestamp, period, values: {carrier: MW}, total: MW}`. Values below 1e-6 MW are omitted.
- `generator_dispatch_series`: same shape but `values` is keyed by generator name instead of carrier.

### `build_price_emissions_series(network, by_carrier, price_series, emissions_factors=None) -> tuple[list[dict], list[dict]]`

Builds per-snapshot system price and emission intensity series.
Returns: `(system_price, system_emissions)`.
- `system_price`: `[{label, timestamp, period, value: currency/MWh}]`.
- `system_emissions`: `[{label, timestamp, period, value: tCO2/h}]` — hourly emissions computed as sum of (carrier dispatch * emission factor) over all non-shedding generators.
Params: `emissions_factors` defaults to `network.carriers["co2_emissions"].to_dict()` when not provided.

### `build_storage_series(network: pypsa.Network) -> list[dict]`

Builds the aggregated storage series across all storage units.
Returns: `[{label, timestamp, period, charge: MW, discharge: MW, state: MWh}]`. Charge is the absolute value of the negative power (charging) part; discharge is the positive part. State of charge is summed directly across all units. Returns zero-filled rows if no storage units are present.

### Internal helpers

#### `_snapshot_parts(snapshot) -> tuple[int | None, object]`
Splits a snapshot into `(period, timestep)` for MultiIndex snapshots, or `(None, snapshot)` for single-period.

#### `_snapshot_label(snapshot) -> tuple[str, str, int | None]`
Returns `(hh:mm_label, iso_timestamp, period_or_None)` for a snapshot.

---

## backend/pypsa/results/emissions.py

Per-generator and per-carrier emission breakdowns.

### `build_emissions_breakdown(network, emissions_factors) -> dict[str, list[dict[str, Any]]]`

Computes emission totals and intensities from a solved network.

Params:
- `network: pypsa.Network` — solved network.
- `emissions_factors: dict[str, float]` — `{carrier: tCO2/MWh_e}`. Load-shedding generators (name prefix `load_shedding_`) are excluded.

Returns:
```python
{
    "byGenerator": [
        {
            "name": str,
            "carrier": str,
            "bus": str,
            "energy_mwh": float,       # weighted dispatch (MWh) over modelled period
            "emissions_tco2": float,   # tCO2e over modelled period
            "intensity_kg_mwh": float  # kg CO2e/MWh (constant per carrier)
        },
        ...  # sorted by emissions_tco2 descending
    ],
    "byCarrier": [
        {
            "carrier": str,
            "energy_mwh": float,
            "emissions_tco2": float,
            "intensity_kg_mwh": float  # average weighted by actual dispatch
        },
        ...  # sorted by energy_mwh descending
    ]
}
```

Returns `{"byGenerator": [], "byCarrier": []}` when `generators_t.p` is empty.

---

## backend/pypsa/results/expansion.py

Capacity expansion result extraction.

### `build_expansion_results(network: pypsa.Network) -> list[dict[str, Any]]`

Returns a list of result dicts for all extendable assets across Generators, StorageUnits, Stores, Links, and Lines.

Each dict contains:
- `name` — component name.
- `component` — `"Generator"`, `"StorageUnit"`, `"Store"`, `"Link"`, or `"Line"`.
- `carrier` — carrier string.
- `bus` — bus name (`bus0` for Lines/Links).
- `p_nom_mw` — workbook installed/fixed capacity (MW; MWh for Stores; MVA for Lines).
- `p_nom_opt_mw` — optimised capacity from PyPSA (`p_nom_opt` or `e_nom_opt`).
- `delta_mw` — `p_nom_opt - p_nom` (positive = new build).
- `capital_cost` — annualised capital cost (currency/MW/yr from the network; annuitisation was applied in `build_network`).
- `capex_annual` — `capital_cost * p_nom_opt` (total annual CAPEX, currency).
- `unit` — `"MWh"` for Stores, `"MVA"` for Lines, absent otherwise.

### `_safe_number(value: Any, fallback: float = 0.0) -> float`

Safely converts a value to float, returning `fallback` on TypeError, ValueError, or NaN.

---

## backend/pypsa/results/market.py

Merit order and CO2 shadow price post-processing.

### `build_merit_order(network: pypsa.Network) -> list[dict[str, Any]]`

Returns the supply stack (merit order) sorted by marginal cost ascending.

Excludes generators with names starting `"load_shedding_"` or `"system_bess"`. For extendable generators, uses `p_nom_opt` as the block width; otherwise uses `p_nom`. Generators with zero or negative capacity are omitted.

Each dict:
- `name`, `carrier`, `bus`
- `marginal_cost` — currency/MWh (rounded to 2 dp).
- `p_nom` — installed/optimised capacity (MW).
- `cumulative_mw` — left edge of this block on the supply curve x-axis.
- `color` — hex colour resolved via `generator_color`.

### `build_co2_shadow(network, carbon_price, currency="$") -> dict[str, Any]`

Returns CO2 shadow price information from the solved network. Checks two sources in priority order:

1. PyPSA `GlobalConstraints` from the `global_constraints` workbook sheet — matched by `carrier_attribute == "co2_emissions"` or index name containing `"co2"`.
2. Custom linopy constraints added by `apply_custom_constraints` — matched by name pattern `cc_<i>_co2_cap`.

Params: `network` — solved network; `carbon_price` — explicit scenario carbon price (currency/tCO2); `currency` — symbol for narrative strings.

Returns:
```python
{
    "found": bool,
    "constraint_name": str | None,
    "shadow_price": float,        # currency/tCO2 (absolute dual value)
    "explicit_price": float,      # scenario carbon price
    "cap_value": float | None,    # RHS of the constraint
    "cap_unit": str,              # "ktCO2e" (global) or "kg CO2e/MWh" (custom)
    "status": "binding" | "slack" | "none",
    "note": str                   # human-readable explanation
}
```

### `build_applied_constraints(network: pypsa.Network) -> list[dict[str, Any]]`

Returns a list of custom and global constraints that were registered on the solved network. Used by the frontend's Applied Constraints card to display which constraints were active during the solve.

### `_linopy_dual(network: pypsa.Network, cname: str) -> float`

Extracts the dual variable of a linopy constraint by name from `network.model.constraints[cname].dual`. Returns 0.0 on any failure (constraint not present, NaN dual). Used by `build_co2_shadow` for custom constraints that are not written to `network.global_constraints`.

---

## backend/pypsa/results/summaries.py

Rolling-horizon window and pathway-period summary helpers.

### `_snapshot_label(snapshot: Any) -> str`

Formats a snapshot as an ISO string for window boundary labels. Multi-investment tuples are formatted as `"<period>|<iso_timestep>"`. Falls back to `str(snapshot)` on parse failure.

### `_rolling_window_summaries(snapshots, horizon, overlap) -> list[dict[str, Any]]`

Computes the boundary metadata for each rolling-horizon solve window.
Params: `snapshots` — full snapshot index; `horizon` (int) — window size in snapshots; `overlap` (int) — overlap in snapshots.
Returns: list of dicts, one per window:
- `index` — 1-based window number.
- `solvedStart`, `solvedEnd` — boundary labels of the full solved window.
- `acceptedStart`, `acceptedEnd` — boundary labels of the non-overlapping accepted slice (all snapshots for the final window).
- `solvedCount`, `acceptedCount` — snapshot counts.
- `periods` — sorted unique investment period values present in the window (empty list for single-period).

### `_pathway_period_summaries(network, dispatch_frame, load_dispatch, price_series, emissions_factors) -> list[dict[str, Any]]`

Computes per-investment-period summary statistics. Returns `[]` when the snapshot index is not a `MultiIndex`.

For each period returns:
- `period` — investment year (int).
- `snapshotCount` — number of snapshots in this period.
- `modeledHours` — sum of snapshot objective weights (h).
- `totalDispatch` — weighted total generation (MWh).
- `totalEmissions` — weighted total emissions (tCO2e).
- `averagePrice` — average system marginal price over the period (currency/MWh).
- `peakLoad` — peak demand in this period (MW).
- `objectiveWeight` — from `network.investment_period_weightings`.
- `yearsWeight` — from `network.investment_period_weightings`.
