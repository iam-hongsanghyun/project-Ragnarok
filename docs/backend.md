# Backend Reference

This document is the single reference for the Ragnarok backend implementation.
It covers module structure, the HTTP API, the solve pipeline, network
construction, result extraction, planning modes, constraints, utilities, and
configuration.

**Scope boundary.** This document describes what the code does — module by
module, function by function — for analysts and contributors working on or
integrating with the backend. It does not cover end-user steps (see
`docs/guides/USER_MANUAL.md`) or system-level architectural decisions (see
`docs/architecture/ARCHITECTURE.md`). Frontend internals are in
`docs/reference/frontend-*.md`.

---

## Table of Contents

1. [Overview and directory layout](#1-overview-and-directory-layout)
2. [HTTP API](#2-http-api)
   - 2.1 [Request/response models](#21-requestresponse-models)
   - 2.2 [Endpoints](#22-endpoints)
   - 2.3 [Job lifecycle](#23-job-lifecycle)
3. [Backend registry and adapter](#3-backend-registry-and-adapter)
4. [Solve pipeline](#4-solve-pipeline)
5. [Network construction](#5-network-construction)
   - 5.1 [build_network — processing order](#51-build_network--processing-order)
   - 5.2 [components.py](#52-componentspy)
   - 5.3 [network_sheet.py](#53-network_sheetpy)
   - 5.4 [snapshots.py](#54-snapshotspy)
   - 5.5 [load_shedding.py](#55-load_sheddingpy)
   - 5.6 [validators.py](#56-validatorspy)
6. [Result extraction](#6-result-extraction)
   - 6.1 [run_pypsa return value](#61-run_pypsa-return-value)
   - 6.2 [dispatch.py](#62-dispatchpy)
   - 6.3 [emissions.py](#63-emissionspy)
   - 6.4 [expansion.py](#64-expansionpy)
   - 6.5 [market.py](#65-marketpy)
   - 6.6 [summaries.py](#66-summariespy)
   - 6.7 [full_outputs.py](#67-full_outputspy)
7. [Planning modes](#7-planning-modes)
   - 7.1 [Pathway (multi-investment)](#71-pathway-multi-investment)
   - 7.2 [Rolling horizon](#72-rolling-horizon)
   - 7.3 [Stochastic](#73-stochastic)
   - 7.4 [Security-constrained (SCLOPF)](#74-security-constrained-sclopf)
   - 7.5 [Carbon price](#75-carbon-price)
8. [Constraints](#8-constraints)
   - 8.1 [apply_custom_constraints — structured metrics](#81-apply_custom_constraints--structured-metrics)
   - 8.2 [apply_constraint_specs — JSON spec wire format](#82-apply_constraint_specs--json-spec-wire-format)
   - 8.3 [apply_dsl_constraints — free-text DSL](#83-apply_dsl_constraints--free-text-dsl)
   - 8.4 [DSL grammar reference](#84-dsl-grammar-reference)
9. [Utilities](#9-utilities)
10. [Configuration](#10-configuration)

---

## 1. Overview and directory layout

The backend is a FastAPI application that receives a JSON workbook from the
frontend, builds a `pypsa.Network`, solves it with HiGHS via linopy, and
returns a structured result dict. The backend is **plugin-agnostic**: plugins
are a frontend concern. They contribute rows and constraints to `model` and
`scenario` before the payload is sent here. There are no plugin hooks inside
the backend pipeline.

```
backend/
  app/
    main.py              FastAPI app, job store, all HTTP endpoints
    config.py            Loads backend/config/system_defaults.json
    models.py            RunPayload Pydantic model
    backends/
      base.py            Backend Protocol + BackendError
      registry.py        register_backend / get_backend / available_backends
  pypsa/
    adapter.py           PypsaBackend — wraps run_pypsa behind the Backend protocol
    pathway.py           PathwayConfig, parse_pathway_config
    rolling.py           RollingHorizonConfig, parse_rolling_config
    stochastic.py        StochasticConfig, apply_scenarios, collapse_to_representative_scenario
    carbon_price.py      CarbonPriceConfig, apply_carbon_price
    constants.py         Carrier/generator colour utilities
    pypsa_schema.py      Schema accessors (reads pypsa_schema.json, network_import_policy.json)
    network/
      __init__.py        build_network, re-exports validate_model
      components.py      Bulk-add helpers (_ordered_component_sheets, _apply_ts_sheet, …)
      network_sheet.py   _apply_network_sheet, _peak_load_per_bus
      snapshots.py       _snapshots_index, _apply_pathway_config
      custom_constraints.py  apply_custom_constraints, build_model_context, ModelContext
      constraint_dsl.py  DSL parser/compiler, apply_dsl_constraints, apply_constraint_specs
      load_shedding.py   add_load_shedding
      validators.py      validate_model
    results/
      __init__.py        run_pypsa — the complete solve-and-extract pipeline
      dispatch.py        dispatch_by_carrier, build_dispatch_series, build_storage_series
      emissions.py       build_emissions_breakdown
      expansion.py       build_expansion_results
      full_outputs.py    build_full_outputs
      market.py          build_merit_order, build_co2_shadow, build_applied_constraints
      summaries.py       _rolling_window_summaries, _pathway_period_summaries
    utils/
      annuity.py         annuity_factor
      coerce.py          number, text
      series.py          safe_series, weighted_sum
      workbook.py        workbook_rows
  config/
    system_defaults.json  Simulation limits, VOLL defaults, demand/availability profiles
```

---

## 2. HTTP API

### 2.1 Request/response models

**`RunPayload`** (`backend/app/models.py`) — the body for every solve, validate,
and export/import endpoint.

| Field | Type | Description |
|---|---|---|
| `model` | `dict[str, list[dict[str, Any]]]` | Workbook as `{sheet_name: [row_dict, ...]}` |
| `scenario` | `dict[str, Any]` | `carbonPrice`, `discountRate`, `constraints`, `constraintSpecs`, `customDsl`, etc. |
| `options` | `dict[str, Any] \| None` | Run-control metadata (see table below) |

Key `options` fields:

| Key | Type | Default | Description |
|---|---|---|---|
| `backend` | `str` | `"pypsa"` | Backend name from the registry |
| `snapshotStart` | `int` | `0` | 0-based index of the first snapshot to model |
| `snapshotCount` | `int` | all | Number of snapshots to use |
| `snapshotWeight` | `int` | `1` | Hours per snapshot (downsampling step) |
| `forceLp` | `bool` | `false` | Override all `committable=True` generators to LP |
| `enableLoadShedding` | `bool` | `false` | Add per-bus VOLL backstop generators |
| `loadSheddingCost` | `float` | system_defaults | VOLL marginal cost (currency/MWh) |
| `currencySymbol` | `str` | `"$"` | Symbol for cost strings in results |
| `solverThreads` | `int` | `0` (auto) | HiGHS thread count |
| `solverType` | `str` | `"simplex"` | `"simplex"` or `"ipm"` |
| `pathwayConfig` | `dict` | disabled | Multi-investment planning config |
| `rollingConfig` | `dict` | disabled | Rolling-horizon config |
| `stochasticConfig` | `dict` | disabled | Two-stage stochastic config |
| `securityConstrainedConfig` | `dict` | disabled | SCLOPF config |
| `carbonPriceSchedule` | `list[dict]` | `None` | Year-price schedule overriding scalar |

### 2.2 Endpoints

All endpoints are defined in `backend/app/main.py`.

#### Liveness and configuration

| Method | Path | Description | Returns |
|---|---|---|---|
| `GET` | `/api/health` | Liveness probe | `{"status": "ok"}` |
| `GET` | `/api/config` | Snapshot limits from `system_defaults.json` | `{"maxSnapshots", "defaultSnapshotCount", "defaultSnapshotWeight"}` |
| `GET` | `/api/backends` | All registered backends and their capabilities | `{"backends": [...], "default": "pypsa"}` |

#### Validation

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/api/validate` | `RunPayload` | `{valid, errors, warnings, notes, snapshotCount, networkSummary}` |

No network is built; no solve occurs.

#### Async solve job

| Method | Path | Body / Params | Returns |
|---|---|---|---|
| `POST` | `/api/run` | `RunPayload` | `{"jobId": uuid, "status": "running"}` |
| `GET` | `/api/run/{job_id}` | — | `{"jobId", "status"}` while running; `{"jobId", "status": "done", "result": {...}}` when complete |
| `DELETE` | `/api/run/{job_id}` | — | `{"jobId", "status": "cancelled"}` |

`POST /api/run` returns HTTP 400 immediately for an unknown backend name.
`GET /api/run/{job_id}` returns HTTP 500 on error, HTTP 499 on cancellation,
HTTP 404 when the job ID is not found (already delivered or never existed).

#### Binary format converters (no solve)

| Method | Path | Body / Upload | Returns |
|---|---|---|---|
| `POST` | `/api/export/netcdf` | `RunPayload` | `application/x-netcdf` bytes (`ragnarok_network.nc`) |
| `POST` | `/api/export/hdf5` | `RunPayload` | `application/x-hdf5` bytes (`ragnarok_network.h5`) |
| `POST` | `/api/import/netcdf` | `UploadFile` (.nc) | `{"model": {sheet: rows[]}}` |
| `POST` | `/api/import/hdf5` | `UploadFile` (.h5) | `{"model": {sheet: rows[]}}` |

Export endpoints build the network without solving. Import endpoints use
PyPSA's native `import_from_netcdf` / `import_from_hdf5` and convert the
result back to the workbook JSON shape via `_network_to_model_json`.

### 2.3 Job lifecycle

`POST /api/run` spawns a child process using Python's `multiprocessing`
`"spawn"` context. The worker function `_solve_worker` (module-level, so it can
be pickled) calls `backend.run()` and puts `("ok", result)` or `("err", msg)`
onto a `multiprocessing.Queue`.

An asyncio background task (`_collect_job`) polls the queue every 0.5 s and
transitions `_Job.status` to `"done"` or `"error"` on receipt. If the process
exits without posting a result, the job transitions to `"cancelled"`.

Completed jobs (`"done"`, `"error"`, `"cancelled"`) are removed from the
in-process `_jobs` dict either when polled by the client or at the next `POST
/api/run` call (stale-job pruning). The job store is in-process memory; there
is no persistence across server restarts.

---

## 3. Backend registry and adapter

`backend/app/backends/registry.py` maps `options["backend"]` strings to
adapter instances.

| Function | Description |
|---|---|
| `register_backend(backend)` | Registers `backend` under `backend.name.lower()`. Last writer wins. |
| `get_backend(name=None)` | Returns the backend for `name`, defaulting to `"pypsa"`. Raises `BackendError` if `name` is given but not registered. |
| `available_backends()` | Returns `[b.capabilities() for b in _BACKENDS.values()]`. |

`PypsaBackend` (in `backend/pypsa/adapter.py`) is the only registered adapter.
It satisfies the `Backend` protocol defined in `backend/app/backends/base.py`:
`name`, `label`, `capabilities()`, and `run()`.

`PypsaBackend.capabilities()` returns:

```python
{
    "name": "pypsa",
    "label": "PyPSA",
    "solver": "HiGHS",
    "studyModes": ["optimize"],
    "features": {
        "singlePeriod": True,
        "pathway": True,
        "rollingHorizon": True,
        "stochastic": True,
        "securityConstrained": True,
        "customConstraints": True,
        "globalConstraints": True,
        "carbonPrice": True,
        "loadShedding": True,
        "unitCommitment": True,
    },
}
```

`PypsaBackend.run(model, scenario, options)` is a thin forwarding call to
`run_pypsa(model, scenario, options or {})`. All solve logic lives in
`backend/pypsa/results/__init__.py`.

To add a future backend, implement the `Backend` protocol and call
`register_backend(MyBackend())` at import time. No other file needs to change.

---

## 4. Solve pipeline

`run_pypsa(model, scenario, options)` in `backend/pypsa/results/__init__.py`
is the complete pipeline.

**Mutually exclusive mode combinations** raise HTTP 400:
- Stochastic + rolling horizon.
- Security-constrained (SCLOPF) + rolling horizon or stochastic.
- SCLOPF + pathway.

**Stage 1 — Parse mode configs.**
`parse_pathway_config`, `parse_rolling_config`, `parse_stochastic_config` are
called unconditionally; their results gate the branching in stages 2 and 3.

**Stage 2 — Build network.**
`build_network(model, scenario, options)` constructs the `pypsa.Network`. See
[Section 5](#5-network-construction).

**Stage 3 — Solve.**
One of three paths:

- Rolling horizon: `network.optimize.optimize_with_rolling_horizon(horizon, overlap, ...)`.
- SCLOPF: `network.optimize.optimize_security_constrained(...)`.
- All other cases (single-period, pathway, stochastic):
  `network.optimize(multi_investment_periods=pathway.enabled, ...)`.

All paths pass `solver_name="highs"`, `extra_functionality`, and
`solver_options` (derived from `solverThreads` and `solverType`).

**`extra_functionality(n, snapshots)`** is a closure defined inside
`run_pypsa`. It is called by PyPSA/linopy after the LP model is assembled but
before it is solved. It applies constraints in this order:

1. `apply_custom_constraints(n, scenario["constraints"], ...)` — structured UI metrics.
2. `apply_constraint_specs(n, scenario["constraintSpecs"], ...)` if `constraintSpecs` is non-empty.
3. `apply_dsl_constraints(n, scenario["customDsl"], ...)` as a fallback if no `constraintSpecs` but `customDsl` is present.

**Stage 4 — Status check.**
Any `condition != "optimal"` raises HTTP 500 with a diagnostic message naming
likely causes (placeholder `1e12` bounds, conflicting constraints).

**Stage 5 — Stochastic post-processing** (when enabled).
`per_scenario_summaries` collects per-scenario KPIs from the multi-indexed
solved network; `collapse_to_representative_scenario` selects the
highest-weight scenario and reshapes all static and dynamic frames to a plain
`name` index so the extraction pipeline below operates without modification.

**Stage 6 — Result extraction.**
Carrier mix, cost breakdown, dispatch/price/emissions series, nodal balance,
line loading, expansion, merit order, CO2 shadow price, applied constraints,
emissions breakdown, and the full PyPSA-native output dataset. See
[Section 6](#6-result-extraction).

---

## 5. Network construction

### 5.1 `build_network` — processing order

`build_network(model, scenario, options)` in `backend/pypsa/network/__init__.py`
returns `(network, notes)`.

`notes` is a `list[str]` of human-readable narrative strings accumulated
throughout construction. The caller (`run_pypsa`) passes them through to the
final `"narrative"` key of the result dict.

Processing order:

1. Parse `pathwayConfig` from `options`.
2. Validate that `discountRate` is present in `scenario` — raises HTTP 400 if absent.
3. Apply the `network` workbook sheet (name, SRID, CRS, `now`).
4. Build the snapshot index from the `snapshots` sheet; apply pathway investment periods.
5. Bulk-add every component class in dependency-safe order (carriers and buses first) using PyPSA's `network.add()`. Only `input_static_attributes` columns are kept; others are dropped before `add()`.
6. Run `_sanitize_placeholder_bounds` — replaces values >= 1e9 in `*_nom_max`, `*_sum_max`, `*_sum_min`, and `lifetime` columns with `±inf` to prevent HiGHS numerical conditioning issues.
7. Apply time-series sheets (`<list_name>-<attr>`), aligning each to `network.snapshots`.
8. Window and downsample snapshots (`snapshotStart`, `snapshotCount`, `snapshotWeight`). For pathway mode, windowing ignores `snapshotStart`/`snapshotCount` and only applies the step (downsampling).
9. Scale annual energy-sum caps (`*_sum_min`, `*_sum_max`) by the period factor when modelled hours < 8760.
10. Apply carbon price (scalar or schedule) to generator marginal costs.
11. Annuitise `capital_cost` for extendable assets using `annuity_factor(discountRate, lifetime)`. Default lifetime is 20 years when not specified.
12. Override `committable=False` on all generators if `forceLp` is set.
13. Emit a warning note for any carrier with `co2_emissions > 5` (likely entered as kg/MWh instead of tCO2/MWh).
14. Add per-bus load-shedding generators if `enableLoadShedding`.
15. Apply stochastic scenario expansion (`apply_scenarios`) if `stochasticConfig.enabled`.

### 5.2 `components.py`

Helper functions called by `build_network` during bulk component import.

| Function | Description |
|---|---|
| `_has_name(row)` | Returns True if `row["name"]` is present and non-blank. Used to filter template rows. |
| `_strip_blank_columns(df)` | Drops entirely null or whitespace-only columns so PyPSA applies its own defaults. |
| `_ordered_component_sheets(network)` | Returns `[(sheet_name, pypsa_class_name), ...]` in dependency-safe order. Carriers = priority 0, buses = priority 1, everything else follows PyPSA's registry order. |
| `_bus_ref_columns_for_list(network, list_name)` | Returns bus-reference column names for a component list (e.g. `["bus"]` for generators, `["bus0", "bus1"]` for lines). |
| `_drop_broken_bus_refs(df, cls, network, sheet, notes)` | Drops rows with required bus references pointing to unknown buses. Optional bus references are not checked. |
| `_ensure_carriers(network, carriers)` | Auto-adds any carrier name referenced by a component but not yet in `network.carriers`. |
| `_apply_ts_sheet(network, rows, list_name, attr)` | Assigns one time-series workbook sheet to `network.<list_name>_t.<attr>`. Detects the snapshot label column, coerces numerics, aligns to `network.snapshots`, deduplicates for single-period runs, and merges via `pd.concat`. |

### 5.3 `network_sheet.py`

| Function | Description |
|---|---|
| `_apply_network_sheet(network, model, notes)` | Reads the first non-empty row from `model["network"]` and applies fields according to `network_import_policy.json`. Supported: `name`, `srid` (EPSG integer), `crs` (any pyproj string), `now`. |
| `_override_network_crs(network, crs)` | Sets CRS on `network.c.shapes.static` and `network._crs`. |
| `_peak_load_per_bus(network)` | Returns `{bus_name: peak_mw}`. Prefers time-series `loads_t.p_set` maximum; falls back to static `loads.p_set`. Used to size VOLL generators. |

### 5.4 `snapshots.py`

| Function | Description |
|---|---|
| `_snapshots_index(model, pathway)` | Builds snapshot index from the `snapshots` workbook sheet. Returns `DatetimeIndex` (single-period) or `MultiIndex` with levels `["period", "timestep"]` (pathway). Returns empty `pd.Index` when no rows are present. |
| `_apply_pathway_config(network, pathway, notes)` | Calls `network.set_investment_periods(periods)` and sets `investment_period_weightings`. No-op when `pathway.enabled` is False. |
| `_normalize_dynamic_snapshot_index_names(network)` | Sets `df.index.name = "snapshot"` on every component's dynamic frames. Called after any operation that may reset the index name. |

### 5.5 `load_shedding.py`

**`add_load_shedding(network, load_totals, notes, enable_load_shedding, load_shedding_cost, currency)`**

Adds a high-cost generator at each bus (value-of-lost-load, VOLL). When
`enable_load_shedding` is False this is a no-op and a note is appended
warning that supply shortfalls will surface as solver infeasibility.

`p_nom` is set to `max(peak_time_series_total, static_load_total, 1.0)` MW so
the solver can always absorb the full demand shortfall. Generator names use the
prefix `load_shedding_<bus>` so `run_pypsa`, `emissions.py`, and `market.py`
can exclude them from energy mix, emission totals, and merit order.

The fallback `marginal_cost` is `system_defaults.json` → `load_shedding.marginal_cost`
(2000 currency/MWh by default).

### 5.6 `validators.py`

**`validate_model(payload: RunPayload) -> dict`**

Runs pre-build validation without constructing a network. Called by `POST /api/validate`.

Returns:

```python
{
    "valid": bool,
    "errors": list[str],      # blocking issues
    "warnings": list[str],    # non-blocking concerns
    "notes": list[str],       # informational
    "snapshotCount": int,
    "networkSummary": {sheet: row_count, ...}
}
```

Checks performed (non-exhaustive):

- Unrecognised or output-only sheet names.
- Snapshot count, duplicate labels.
- Pathway: at least one period, periods unique and ascending, snapshot `period` column completeness.
- Rolling horizon: positive `horizonSnapshots`, non-negative `overlapSnapshots`, overlap < horizon.
- At least one bus, one load, one generator.
- Loads with zero / missing `p_set` and no time-series data.
- Per-component: duplicate names, required fields, bus references, numeric sanity (negative `p_nom`, `*_pu` outside [0, 1], `efficiency > 5`, `co2_emissions > 5`), carrier references, output-column presence.
- Time-series sheets: snapshot label column, row count vs snapshot count, component column existence, value range.

---

## 6. Result extraction

### 6.1 `run_pypsa` return value

`run_pypsa` returns a single dict with the following top-level keys.

| Key | Type | Description |
|---|---|---|
| `summary` | `list[dict]` | Six KPI cards: installed capacity, peak demand, reserve position, peak price, system emissions (ktCO2e), transmission stress (average line loading %). |
| `dispatchSeries` | `list[dict]` | Per-snapshot carrier-aggregated dispatch (MW). Each row: `{label, timestamp, period, values: {carrier: MW}, total: MW}`. Values below 1e-6 MW are omitted. |
| `generatorDispatchSeries` | `list[dict]` | Same shape but `values` is keyed by generator name. |
| `systemPriceSeries` | `list[dict]` | Per-snapshot average nodal marginal price (currency/MWh). Each row: `{label, timestamp, period, value}`. |
| `systemEmissionsSeries` | `list[dict]` | Per-snapshot emission intensity (tCO2/h). |
| `storageSeries` | `list[dict]` | Per-snapshot aggregated storage: `{label, timestamp, period, charge: MW, discharge: MW, state: MWh}`. |
| `nodalPriceSeries` | `list[dict]` | Per-snapshot per-bus marginal prices: `{label, timestamp, values: {bus: currency/MWh}}`. |
| `carrierMix` | `list[dict]` | Energy by carrier: `{label, value: MWh, color}`, sorted descending. |
| `costBreakdown` | `list[dict]` | Fuel cost, carbon cost, load-shedding cost, and (when expansion occurred) capital cost in currency. |
| `nodalBalance` | `list[dict]` | Average generation and load per bus (MW), sorted by load descending. |
| `lineLoading` | `list[dict]` | Peak loading percentage for lines, links, and transformers: `{label, value: %}`. |
| `expansionResults` | `list[dict]` | Extendable asset expansion details. See [Section 6.4](#64-expansionpy). |
| `meritOrder` | `list[dict]` | Supply stack sorted by marginal cost ascending. See [Section 6.5](#65-marketpy). |
| `co2Shadow` | `dict` | CO2 shadow price information. See [Section 6.5](#65-marketpy). |
| `appliedConstraints` | `list[dict]` | Custom and global constraints active during the solve. |
| `emissionsBreakdown` | `dict` | Per-generator and per-carrier emission totals. See [Section 6.3](#63-emissionspy). |
| `narrative` | `list[str]` | Human-readable notes accumulated throughout build and extraction. |
| `runMeta` | `dict` | `snapshotCount`, `snapshotWeight`, `modeledHours`, `storeWeight`, `planningMode`, `investmentPeriods`; nested `rolling` dict when rolling is enabled. |
| `pathway` | `dict \| None` | `enabled`, `periods`, `selectedPeriod`, `snapshotMappingMode`, `summaries`. Present only when pathway is enabled. |
| `rolling` | `dict \| None` | `enabled`, `horizonSnapshots`, `overlapSnapshots`, `stepSnapshots`, `windowCount`, `windows`. Present only when rolling is enabled. |
| `stochastic` | `dict \| None` | `enabled`, `representativeScenario`, `scenarios`. Present only when stochastic is enabled. |
| `securityConstrained` | `dict \| None` | `enabled`, `branchCount`. Present only when SCLOPF is enabled. |
| `outputs` | `dict` | Full PyPSA-native output dataset: `{static: {...}, series: {...}}`. See [Section 6.7](#67-full_outputspy). |

**Cost breakdown accounting.** The carbon adder was folded into `marginal_cost`
by `build_network`. `run_pypsa` backs it out per snapshot:
`fuel_cost += dispatch * (mc - ef * carbon_price).clip(lower=0)`.
`carbon_cost += dispatch * ef * carbon_price`. Load-shedding cost is tracked
separately by the `load_shedding_` name prefix.

**Line loading.** `lineLoading` covers `network.lines`, `network.links`, and
`network.transformers`. It is only populated for components with non-empty
`_t.p0` frames.

### 6.2 `dispatch.py`

| Function | Returns | Description |
|---|---|---|
| `dispatch_by_carrier(generator_dispatch_frame, generators)` | `dict[str, pd.Series]` | Groups generator dispatch by carrier. Clips at 0 (no negative generation in the mix). |
| `build_dispatch_series(network, by_carrier, load_dispatch, generator_dispatch_frame)` | `(dispatch_series, generator_dispatch_series)` | Builds two per-snapshot dispatch series. |
| `build_price_emissions_series(network, by_carrier, price_series, emissions_factors)` | `(system_price, system_emissions)` | System price from `buses_t.marginal_price.mean(axis=1)`; emissions as Σ(carrier dispatch × emission factor) over non-shedding generators. |
| `build_storage_series(network)` | `list[dict]` | Aggregated storage charge/discharge/state-of-charge. Returns zero-filled rows when no storage units are present. |

### 6.3 `emissions.py`

**`build_emissions_breakdown(network, emissions_factors) -> dict`**

Generators with names starting `load_shedding_` are excluded.

```python
{
    "byGenerator": [
        {
            "name": str,
            "carrier": str,
            "bus": str,
            "energy_mwh": float,       # weighted dispatch over modelled period
            "emissions_tco2": float,
            "intensity_kg_mwh": float  # constant per carrier
        }, ...  # sorted by emissions_tco2 descending
    ],
    "byCarrier": [
        {
            "carrier": str,
            "energy_mwh": float,
            "emissions_tco2": float,
            "intensity_kg_mwh": float  # weighted average by actual dispatch
        }, ...  # sorted by energy_mwh descending
    ]
}
```

Returns `{"byGenerator": [], "byCarrier": []}` when `generators_t.p` is empty.

### 6.4 `expansion.py`

**`build_expansion_results(network) -> list[dict]`**

Returns extendable assets across Generators, StorageUnits, Stores, Links, and
Lines. Each dict:

| Key | Description |
|---|---|
| `name` | Component name |
| `component` | `"Generator"`, `"StorageUnit"`, `"Store"`, `"Link"`, or `"Line"` |
| `carrier` | Carrier string |
| `bus` | Bus name (`bus0` for Lines/Links) |
| `p_nom_mw` | Workbook installed/fixed capacity (MW; MWh for Stores; MVA for Lines) |
| `p_nom_opt_mw` | Optimised capacity from PyPSA (`p_nom_opt` or `e_nom_opt`) |
| `delta_mw` | `p_nom_opt - p_nom` (positive = new build) |
| `capital_cost` | Annualised capital cost (currency/MW/yr; already annuitised by `build_network`) |
| `capex_annual` | `capital_cost * p_nom_opt` |
| `unit` | `"MWh"` for Stores, `"MVA"` for Lines; absent otherwise |

### 6.5 `market.py`

**`build_merit_order(network) -> list[dict]`**

Returns the supply stack sorted by `marginal_cost` ascending. Excludes
`load_shedding_*` and `system_bess` generators. For extendable generators uses
`p_nom_opt` as block width. Generators with zero or negative capacity are
omitted.

Each dict: `name`, `carrier`, `bus`, `marginal_cost` (rounded to 2 dp),
`p_nom` (MW), `cumulative_mw` (left edge on the supply curve), `color` (hex).

**`build_co2_shadow(network, carbon_price, currency) -> dict`**

Checks two sources in priority order:
1. PyPSA `GlobalConstraints` — matched by `carrier_attribute == "co2_emissions"` or index name containing `"co2"`.
2. Custom linopy constraints — matched by name pattern `cc_<i>_co2_cap`.

Returns:

```python
{
    "found": bool,
    "constraint_name": str | None,
    "shadow_price": float,       # currency/tCO2 (absolute dual value)
    "explicit_price": float,     # scenario carbonPrice
    "cap_value": float | None,   # RHS of the constraint
    "cap_unit": str,             # "ktCO2e" (global) or "kg CO2e/MWh" (custom)
    "status": "binding" | "slack" | "none",
    "note": str
}
```

**`build_applied_constraints(network) -> list[dict]`**

Returns custom and global constraints registered on the solved network.

### 6.6 `summaries.py`

| Function | Returns | Description |
|---|---|---|
| `_rolling_window_summaries(snapshots, horizon, overlap)` | `list[dict]` | Boundary metadata for each rolling-horizon window: `index`, `solvedStart/End`, `acceptedStart/End`, `solvedCount`, `acceptedCount`, `periods`. |
| `_pathway_period_summaries(network, dispatch_frame, load_dispatch, price_series, emissions_factors)` | `list[dict]` | Per-investment-period KPIs: `period`, `snapshotCount`, `modeledHours`, `totalDispatch`, `totalEmissions`, `averagePrice`, `peakLoad`, `objectiveWeight`, `yearsWeight`. Returns `[]` when the snapshot index is not a `MultiIndex`. |

### 6.7 `full_outputs.py`

**`build_full_outputs(network) -> dict`**

Walks every component in the schema and extracts all output attributes.

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

Only attributes with `status="output"` in `pypsa_schema.json` are extracted.
`static_or_series` output attributes are recorded as series. NaN values are
omitted. Multi-investment results include a `period` key alongside `snapshot`
in each series row.

The frontend uses `outputs` as the `assetDetails` cache for per-asset drilldown
and export-project. The backend is stateless — it does not cache between runs.

---

## 7. Planning modes

### 7.1 Pathway (multi-investment)

**Module:** `backend/pypsa/pathway.py`

**Data classes:**

`PathwayPeriod` — `period: int`, `objective_weight: float`, `years_weight: float`.

`PathwayConfig` — `enabled: bool`, `planning_mode: str` (`"pathway"` or
`"single_period"`), `snapshot_mapping_mode: str` (default
`"explicit_period_column"`), `periods: list[PathwayPeriod]` (sorted
ascending), `selected_period: int | None`.

**`parse_pathway_config(raw) -> PathwayConfig`**

Activated when `raw["enabled"]` is truthy or `raw["planningMode"] == "pathway"`.
Items in `raw["periods"]` with unparseable `period` values are silently skipped.
Returns a disabled config with no periods when `raw` is `None` or empty.

When pathway is enabled:
- `_snapshots_index` builds a `MultiIndex` with levels `["period", "timestep"]` using the `period` column in the `snapshots` sheet.
- `_apply_pathway_config` calls `network.set_investment_periods(periods)` and sets `investment_period_weightings`.
- `network.optimize` receives `multi_investment_periods=True`.
- Snapshot windowing ignores `snapshotStart`/`snapshotCount` (pathway workbooks include all periods).

### 7.2 Rolling horizon

**Module:** `backend/pypsa/rolling.py`

**`RollingHorizonConfig`** — `enabled`, `horizon_snapshots` (default 168,
clamped >= 1), `overlap_snapshots` (default 24, clamped >= 0), `step_snapshots`
(derived as `max(1, horizon - overlap)`; not read from payload),
`preserve_terminal_state` (default True), `selected_window`.

**`parse_rolling_config(raw) -> RollingHorizonConfig`**

`step_snapshots` is always derived, never read from the payload.

When rolling is enabled, `run_pypsa` calls
`network.optimize.optimize_with_rolling_horizon(horizon, overlap, ...)`.
PyPSA's rolling-horizon helper does not return a status tuple; the run is
treated as optimal unless an exception is raised. Rolling cannot be combined
with stochastic or SCLOPF.

### 7.3 Stochastic

**Module:** `backend/pypsa/stochastic.py`

**Data classes (all frozen):**

`ScenarioOverride` — `sheet`, `attribute`, `scope_type` (`"all"` | `"name"` |
`"carrier"`), `scope_value`, `operation` (`"multiply"` | `"set"`), `value`.

`StochasticScenario` — `name`, `weight` (normalised to sum=1), `overrides`.

`StochasticConfig` — `enabled`, `scenarios`.

**`parse_stochastic_config(raw) -> StochasticConfig`**

Activated when `raw["enabled"]` is truthy and at least two valid scenarios are
present (a single scenario is a deterministic solve). Weights are normalised to
sum to 1.0. Scenarios with empty names or non-positive weights are skipped.

**`apply_scenarios(network, config)`**

Calls `network.set_scenarios({name: weight})` to expand all static and dynamic
frames to a `(scenario, name)` MultiIndex, then applies per-scenario overrides
via `_apply_advanced_override`. Must run after all deterministic setup so the
scenario dimension broadcasts over final values.

**`per_scenario_summaries(network, config, emissions_factors, currency_symbol)`**

Slices the solved multi-indexed network per scenario and computes:
`totalEnergyMwh`, `totalEmissionsTco2`, `totalOperatingCost` (and formatted
variant), `loadShedEnergyMwh`, `name`, `weight`, `overrideCount`.

**`collapse_to_representative_scenario(network, config) -> str`**

Selects the highest-weight scenario, reduces all static frames from
`(scenario, name)` MultiIndex to `name`, and slices all dynamic frame column
MultiIndexes to the representative scenario. Returns the representative
scenario name.

Stochastic cannot be combined with rolling horizon or SCLOPF.

### 7.4 Security-constrained (SCLOPF)

Enabled via `options["securityConstrainedConfig"]["enabled"] = true`.

`run_pypsa` calls `network.optimize.optimize_security_constrained(...)`. This
enforces N-1 security for all passive branches (lines and transformers). PyPSA
adds line-loading constraints for every possible single-branch outage.

SCLOPF cannot be combined with rolling horizon, stochastic, or pathway.

The `securityConstrained` key in the result dict reports `enabled: true` and
`branchCount` (lines + transformers).

### 7.5 Carbon price

**Module:** `backend/pypsa/carbon_price.py`

**`CarbonPriceConfig`** — `scalar: float`, `schedule: tuple[CarbonPriceScheduleEntry, ...]`,
property `is_scheduled: bool` (True when schedule is non-empty).

**`CarbonPriceScheduleEntry`** — `year: int`, `price: float` (currency/tCO2).

**`parse_carbon_price_config(scalar, raw_schedule) -> CarbonPriceConfig`**

`raw_schedule` is `options["carbonPriceSchedule"]` — a list of `{year, price}`
dicts. Duplicate years are resolved last-write-wins. Items with non-numeric or
non-positive years are skipped.

**`build_price_series(network, config) -> pd.Series`**

Per-snapshot carbon price indexed by `network.snapshots`. Constant series when
`not config.is_scheduled`. For scheduled prices, each snapshot's year is
resolved via `_snapshot_years` (uses the `period` level for pathway
MultiIndexes) and the most-recent schedule entry with year <= snapshot year is
applied.

**`apply_carbon_price(network, config, notes, currency_symbol)`**

Adds the carbon adder to every generator whose carrier has `co2_emissions > 0`.

- **Constant path:** adds `price * emission_factor` to the static
  `marginal_cost` column and to any existing `generators_t.marginal_cost`
  time-varying frame.
- **Varying path** (schedule with multiple distinct values): writes all
  generators onto `generators_t.marginal_cost` with a per-snapshot adder
  series, overriding the static column during the solve.

---

## 8. Constraints

All constraint code runs inside the `extra_functionality` closure in
`run_pypsa`, after the linopy model is assembled and before the solve. The
`ModelContext` dataclass (built once per solve by `build_model_context`) holds
the shared linopy variables and weights that both the structured and DSL paths
use.

**`ModelContext`** fields:

| Field | Description |
|---|---|
| `network` | The `pypsa.Network` being solved |
| `gen_p` | `n.model["Generator-p"]` — the dispatch variable |
| `dim` | Generator dimension name in the linopy variable |
| `weights` | `n.snapshot_weightings["generators"]` |
| `supply_gens` | Generator names without the `load_shedding_` prefix |
| `shed_gens` | Generator names with the `load_shedding_` prefix |
| `modeled_hours` | `float(weights.sum())` |
| `cap_var` | `n.model["Generator-p_nom"]` if extendable generators are present, else `None` |
| `cap_dim` | Dimension name of `cap_var`, or `None` |
| `emissions_factors` | `{carrier: tCO2/MWh}` |

### 8.1 `apply_custom_constraints` — structured metrics

Reads `scenario["constraints"]` — a list of dicts, each with `enabled`,
`metric`, `value`, `carrier`, `label`. Only dicts with `enabled: true` are
processed. Each constraint failure is caught and recorded as a note; the solve
continues.

Constraint names in the linopy model follow the pattern `cc_<i>_<metric>`.

Supported metrics:

| `metric` | Constraint | Notes |
|---|---|---|
| `co2_cap` | Σ(ef·dispatch) <= value·Σ(dispatch) | `value` in tCO2/MWh. Sums over all non-shedding generators. |
| `max_load_shed` | Σ(load-shedding dispatch) <= value | `value` in MWh. Requires `enableLoadShedding`. |
| `carrier_max_gen` | Σ(carrier dispatch) <= value | `value` in MWh. |
| `carrier_min_gen` | Σ(carrier dispatch) >= value | `value` in MWh. |
| `carrier_max_share` | Σ(carrier) - (value/100)·Σ(all supply) <= 0 | `value` in %. |
| `carrier_min_share` | Σ(carrier) - (value/100)·Σ(all supply) >= 0 | `value` in %. |
| `carrier_max_cf` | Σ(carrier dispatch) <= (value/100)·capacity·hours | Handles extendable capacity via `Generator-p_nom` linopy variable. |
| `carrier_min_cf` | Σ(carrier dispatch) >= (value/100)·capacity·hours | Same capacity handling as max. |

### 8.2 `apply_constraint_specs` — JSON spec wire format

Reads `scenario["constraintSpecs"]` — the canonical wire format the frontend
sends. Overrides the DSL path when non-empty.

Each spec dict:

```python
{
    "id": str,       # used as the constraint name in the narrative
    "sense": "<="|">="|"==",
    "lhs": [{"coef": float, "kind": str, "carrier": str|None}, ...],
    "rhs": [{"coef": float, "kind": str, "carrier": str|None}, ...]
}
```

Valid `kind` values: `gen`, `cap`, `cf`, `emissions`, `load_shed`, `const`.

Constraint names in the linopy model: `spec_<i>` (1-based).

Bad specs are skipped with a note; the solve continues.

### 8.3 `apply_dsl_constraints` — free-text DSL

Fallback when `constraintSpecs` is empty but `scenario["customDsl"]` is
non-empty. Parses the text line by line; `#` starts a comment; blank lines are
ignored. Bad lines are skipped with a note.

Constraint names in the linopy model: `dsl_<line_number>` (1-based).

### 8.4 DSL grammar reference

```
line    := linexpr ("<=" | ">=" | "==") linexpr
linexpr := term (("+" | "-") term)*
term    := [NUMBER "*"] atom
atom    := ("gen" | "cap" | "emissions") ["(" CARRIER ")"]
         | "cf" "(" CARRIER ")"
         | "load_shed"
         | NUMBER
```

Atom semantics:

| Atom | Unit | Description |
|---|---|---|
| `gen` | MWh | Weighted total dispatch over all non-shedding generators |
| `gen(C)` | MWh | Weighted dispatch for carrier `C` only |
| `cap` | MW | Sum of installed/optimised capacity, all supply generators |
| `cap(C)` | MW | Capacity for carrier `C` (uses linopy variable for extendable) |
| `emissions` | tCO2 | Σ(ef·dispatch) over all emitting generators |
| `emissions(C)` | tCO2 | Same, restricted to carrier `C` |
| `load_shed` | MWh | Total load-shedding dispatch |
| `cf(C)` | fraction | Capacity factor shorthand; rewrites to `gen(C) <op> k·cap(C)·hours` |
| `NUMBER` | — | Numeric literal (scientific notation supported) |

Carrier names are bare `[A-Za-z0-9_]+` tokens or `"quoted strings"` for names
containing spaces. The `cf(C)` atom is only valid as `cf(C) <op> NUMBER` or
`NUMBER <op> cf(C)`.

**Examples:**

```
# Renewable share >= 50 %
gen(Wind) + gen(Solar) >= 0.5 * gen

# CO2 intensity cap 0.1 tCO2/MWh
emissions <= 0.1 * gen

# Capacity factor of solar <= 40 %
cf(Solar) <= 0.4
```

---

## 9. Utilities

### `backend/pypsa/utils/coerce.py`

| Function | Signature | Description |
|---|---|---|
| `number` | `(value, default=0.0) -> float` | Safe float coercion. Returns `default` for `None`, `""`, NaN, Inf. `True` → 1.0, `False` → 0.0. |
| `text` | `(value, default="") -> str` | Safe string coercion. Returns `default` for `None` or blank after strip. |

### `backend/pypsa/utils/workbook.py`

| Function | Signature | Description |
|---|---|---|
| `workbook_rows` | `(model, sheet) -> list[dict]` | Returns `model[sheet]` or `[]` if absent. Never returns `None`. |

### `backend/pypsa/utils/series.py`

| Function | Signature | Description |
|---|---|---|
| `safe_series` | `(frame, name) -> pd.Series` | Returns `frame[name]` or a zero-filled Series with the same index if the column is absent. |
| `weighted_sum` | `(series, weights) -> float` | Computes `(series * aligned_weights).sum()`. Reindexes weights to `series.index` with fill=1.0 to handle post-collapse index mismatches. Used for all MWh energy integrals. |

### `backend/pypsa/utils/annuity.py`

**`annuity_factor(discount_rate, lifetime_years) -> float`**

Capital recovery factor (CRF):

```
CRF = r * (1 + r)^n / ((1 + r)^n - 1)
```

where `r = discount_rate` and `n = lifetime_years`.

Special cases: `lifetime_years <= 0` returns `1.0`; `discount_rate <= 0`
returns `1.0 / lifetime_years` (straight-line, no time-value-of-money).

### `backend/pypsa/constants.py`

| Function | Signature | Description |
|---|---|---|
| `default_carrier_color` | `(carrier) -> str` | Deterministic hex colour from a 30-colour palette by hashing the normalised carrier name. |
| `carrier_color` | `(network, carrier) -> str` | Prefers `network.carriers["color"]` when present and non-blank, falls back to `default_carrier_color`. |
| `generator_color` | `(network, generator) -> str` | Prefers explicit `network.generators["color"]`, then delegates to `carrier_color`. |

### `backend/pypsa/pypsa_schema.py`

Schema accessors that read `frontend/Ragnarok_default/src/config/pypsa_schema.json`
and `network_import_policy.json`. All functions use `lru_cache(maxsize=1)`.
The schema is shared between frontend and backend; new PyPSA attributes added
to the schema are automatically handled by the backend without code changes.

| Function | Returns | Description |
|---|---|---|
| `load_pypsa_schema()` | `dict` | Full schema dict |
| `load_network_import_policy()` | `dict` | Network import policy dict |
| `component_schema(sheet_name)` | `dict \| None` | Schema for one component sheet |
| `component_sheets()` | `list[str]` | All schema-defined component sheet names |
| `non_component_sheets()` | `set[str]` | Sheet names like `"snapshots"` and `"network"` that are not component tables |
| `network_runtime_import_fields()` | `list[dict]` | Fields with `enabled_for_runtime_import: true` |
| `input_static_attributes(sheet_name)` | `set[str]` | Attributes with `status="input"` and `storage` in `{"static", "static_or_series"}` |
| `input_temporal_attributes(sheet_name)` | `set[str]` | Attributes with `status="input"` and `storage` in `{"series", "static_or_series"}` |
| `output_attributes(sheet_name)` | `set[str]` | Output-only attribute names |
| `required_input_static_attributes(sheet_name)` | `set[str]` | Required input static attributes (`required: true`, not series-only) |
| `bus_reference_attributes(sheet_name)` | `list[dict]` | Input static columns named `bus`, `bus0`, `bus1`, etc., with `required` flag |

---

## 10. Configuration

### `backend/config/system_defaults.json`

Read and cached by `load_system_defaults()` in `backend/app/config.py`
(`lru_cache(maxsize=None)`). Loaded once per process.

| Section | Key | Default | Description |
|---|---|---|---|
| `simulation` | `max_snapshots` | 8760 | Upper limit enforced by the frontend |
| `simulation` | `default_snapshot_count` | 24 | Default when not specified |
| `simulation` | `default_snapshot_weight` | 1.0 | Default hours per snapshot |
| `simulation` | `hours_in_year` | 8760.0 | Used for period-factor scaling of annual caps |
| `load_shedding` | `marginal_cost` | 2000.0 | Fallback VOLL cost (currency/MWh) |
| `load_shedding` | `p_nom_floor` | 1000 | Minimum VOLL generator size (MW) |
| `load_shedding` | `carrier` | `"LoadShedding"` | Carrier assigned to VOLL generators |

`GET /api/config` exposes `maxSnapshots`, `defaultSnapshotCount`, and
`defaultSnapshotWeight` from the `simulation` section to the frontend.

### FastAPI app settings

The FastAPI app (`backend/app/main.py`) adds a CORS middleware with
`allow_origins=["*"]`. In production, scope this to the specific frontend
origin.

The app is launched by `uvicorn` (see `docs/architecture/PROCESSES.md`).
`GET /api/run/{job_id}` polling noise is suppressed at the `uvicorn.access`
INFO level and re-emitted at DEBUG via `_SuppressPollLogs`.
