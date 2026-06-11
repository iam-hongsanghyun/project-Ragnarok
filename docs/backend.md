# Backend Reference

This document is the single reference for the Ragnarok backend implementation.
It covers module structure, the HTTP API, the solve pipeline, network
construction, result extraction, planning modes, constraints, utilities,
configuration, the server-side session subsystem, the run store (History),
project export/import, the external-data importers, and the boot-config
endpoint.

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
11. [Session subsystem (server-side working model)](#11-session-subsystem-server-side-working-model)
    - 11.1 [model_store.py — storage facade](#111-model_storepy--storage-facade)
    - 11.2 [sqlite_store.py — SQLite session store](#112-sqlite_storepy--sqlite-session-store)
    - 11.3 [session_store.py — legacy JSON+Parquet store](#113-session_storepy--legacy-jsonparquet-store)
    - 11.4 [timeseries.py — windowing and downsampling](#114-timeseriespy--windowing-and-downsampling)
    - 11.5 [routers/session.py — /api/session/*](#115-routerssessionpy--apisession)
12. [Run store (History)](#12-run-store-history)
    - 12.1 [run_store.py](#121-run_storepy)
    - 12.2 [Run and export endpoints](#122-run-and-export-endpoints)
13. [Project workbook](#13-project-workbook)
14. [External-data importers — /api/import/*](#14-external-data-importers--apiimport)
15. [Boot config — /api/config](#15-boot-config--apiconfig)

---

## 1. Overview and directory layout

The backend is a FastAPI application that receives a JSON workbook from the
frontend (or holds it in a server-side session), builds a `pypsa.Network`,
solves it with HiGHS via linopy, and returns a structured result dict.

Two plugin kinds exist, with different relationships to the backend:

* **Frontend plugins** run in the browser; they contribute rows and constraints
  to `model` and `scenario` *before* the payload is sent here. The **solve
  pipeline** has no plugin hooks — no plugin code executes at any solve stage.
* **Backend plugins** (`app/plugins.py` + `app/routers/plugins.py`) are
  3rd-party Python packages installed at runtime into `backend/data/plugins/`
  and run **in the backend process** via `/api/plugins/*`, writing into the
  server-side session. See [docs/plugin.md §16](plugin.md#16-backend-server-side-plugins)
  for the contract and isolation rules.

```
backend/
  app/
    main.py              FastAPI app, job store, solve/validate/export endpoints
    config.py            Loads backend/config/system_defaults.json
    config_provider.py   Config lookups for the /api/config surface
    models.py            RunPayload Pydantic model
    model_store.py       Session-storage facade (sqlite default, legacy json/parquet)
    sqlite_store.py      SQLite session store (one project.db per session)
    session_store.py     Legacy JSON+Parquet session store
    run_store.py         Persisted solved-run results
    plugins.py           Backend-plugin framework: discovery, registry, hook runners
    timeseries.py        Shared time-series windowing/downsampling for the thin-client API
    project_workbook.py  Lossless project-workbook (.xlsx) read/write for sessions
    log_capture.py       In-process log capture (Analytics → Log tab)
    startup_status.py    Startup progress reporting (GET /api/status)
    routers/
      session.py         /api/session/* — server-side working model (source of truth)
      plugins.py         /api/plugins/* — backend-plugin lifecycle + hooks
      importers.py       /api/import/* — external-data importer subsystem (Data view)
      config.py          /api/config — the boot bundle the frontend fetches at startup
    importers/           importer implementations used by routers/importers.py
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
| `model` | `dict[str, list[dict[str, Any]]] \| None` | Workbook as `{sheet_name: [row_dict, ...]}`. Optional when `sessionId` is given. |
| `scenario` | `dict[str, Any]` | `carbonPrice`, `discountRate`, `constraints`, `constraintSpecs`, `customDsl`, etc. |
| `options` | `dict[str, Any] \| None` | Run-control metadata (see table below) |
| `sessionId` | `str \| None` | Server-side session to load the model from when `model` is absent |

A thin client submits only `{sessionId, scenario, options}` — the working model
lives server-side (see [Section 11](#11-session-subsystem-server-side-working-model)).
`_resolve_payload_model` (in `main.py`) snapshots the session model into the
payload at submit time, so a later session edit never mutates an
already-submitted or queued run. A payload with neither `model` nor `sessionId`,
or a `sessionId` with no loaded model, gets HTTP 400.

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

Solve, validate, and export/import endpoints are defined in
`backend/app/main.py`. Session (`/api/session/*`), backend-plugin
(`/api/plugins/*`), external-data importer (`/api/import/*`), and boot-config
(`/api/config`) endpoints live in `backend/app/routers/` — each router module's
docstring carries its endpoint table, mirrored in this document: session
endpoints in [Section 11.5](#115-routerssessionpy--apisession), stored-run and
export endpoints in [Section 12.2](#122-run-and-export-endpoints), importer
endpoints in [Section 14](#14-external-data-importers--apiimport), and the
config bundle in [Section 15](#15-boot-config--apiconfig). Backend-plugin
routes are documented in [docs/plugin.md §16.5](plugin.md#165-endpoints).

#### Liveness and configuration

| Method | Path | Description | Returns |
|---|---|---|---|
| `GET` | `/api/health` | Liveness probe | `{"status": "ok"}` |
| `GET` | `/api/config` | Full shared-config bundle (schema, capabilities, simulation defaults — see [Section 15](#15-boot-config--apiconfig)) | `ConfigBundle` JSON |
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
and export-project. The solve pipeline itself keeps no state between runs; the
completed bundle is persisted by the run store (`app/run_store.py`) for
History / "View result".

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
| `session` | `max_chart_points_default` | 800 | Default `maxPoints` for series windows ([Section 11](#11-session-subsystem-server-side-working-model)) |
| `session` | `chart_window_hours_default` | 168 | Default chart window span (hours) |
| `session` | `sheet_page_default` | 200 | Default page size for sheet reads |
| `session` | `undo_depth` | 25 | Frontend edit undo-stack depth |

The `simulation` keys reach the frontend as `simulation_defaults`
(`maxSnapshots`, `defaultSnapshotCount`, `defaultSnapshotWeight`) inside the
`GET /api/config` bundle (see [Section 15](#15-boot-config--apiconfig)).

### FastAPI app settings

The FastAPI app (`backend/app/main.py`) adds a CORS middleware with
`allow_origins=["*"]`. In production, scope this to the specific frontend
origin.

The app is launched by `uvicorn` (see `docs/architecture/PROCESSES.md`).
`GET /api/run/{job_id}` polling noise is suppressed at the `uvicorn.access`
INFO level and re-emitted at DEBUG via `_SuppressPollLogs`.

---

## 11. Session subsystem (server-side working model)

The backend holds the working model; the frontend is a thin terminal. A model
is imported once (`POST /api/session/model`) and thereafter the browser fetches
only what it shows — a page of static rows or a windowed, downsampled
time-series slice. The solve path consumes the session model server-side
(`_resolve_payload_model`), so no giant payload travels from the browser.

A session is keyed by `session_id` (default `"default"`; the app is single-user
on one machine today). Every store function takes `session_id` so a remote,
multi-session deployment is a configuration change, not a rewrite. Every public
reader is defensive: a missing or cleared session returns `None` rather than
raising.

### 11.1 `model_store.py` — storage facade

All app code (routers, run/queue, plugins) imports `model_store`, never a
concrete store. The engine is selected once at import time from the
`RAGNAROK_STORE` environment variable:

| Value | Engine |
|---|---|
| `sqlite` (**default**, and any value other than `legacy`) | `sqlite_store` — one `project.db` per session |
| `legacy` | `session_store` — JSON + Parquet files (escape hatch while SQLite beds in) |

The public API (signatures and JSON shapes) is identical in both engines, so
the `/api/session/*` contract is unchanged either way:

| Function | Description |
|---|---|
| `save_model(session_id, model, *, filename, scenario_name)` | Persist a full model, replacing any current one. Returns the meta. Raises `ValueError` on an unsafe session id. |
| `merge_static_model(session_id, model)` | Overwrite STATIC sheets only; series untouched. Returns refreshed meta or `None`. |
| `get_meta(session_id)` | Session meta or `None`. |
| `get_sheet_page(session_id, sheet, offset, limit)` | One page of rows (static or series). |
| `get_series_window(session_id, sheet, *, start, end, columns, max_points, agg)` | Windowed + downsampled series slice. |
| `load_full_model(session_id, *, static_only)` | Reconstruct `{sheet: rows}`; `static_only=True` skips series sheets. |
| `save_controls(session_id, controls)` / `get_controls(session_id)` | Model-bound run controls (carbon, window, constraints). Rolling-horizon config is intentionally never persisted — it resets on reload/import per the product rule; callers strip it. |
| `patch_sheet(session_id, sheet, ops)` | Apply edit ops; returns updated `{name, kind, total, columns}`. |
| `clear(session_id)` | Delete the session from disk; returns whether anything existed. |
| `has_model(session_id)` | `get_meta(...) is not None`. |
| `is_series_sheet(name, rows=None)` | True for `<component>-<attribute>` sheet names. `snapshots` is the time axis, classified static. |
| `distinct_values(session_id, sheet, column)` | Sorted distinct non-empty string values. Uses the engine's native query when available (SQLite `SELECT DISTINCT`); the facade computes it from sheet rows on the legacy store. |

**Session meta shape** (returned by `save_model` / `get_meta`; the only thing
the frontend keeps in memory):

```python
{
    "sessionId": str,
    "filename": str,
    "scenarioName": str,
    "savedAt": str,                 # UTC ISO timestamp
    "sheets": [{"name", "kind": "static"|"series", "rowCount", "columns"}, ...],
    "snapshotCount": int,
    "snapshotStart": str | None,    # first/last snapshot label
    "snapshotEnd": str | None,
    "scenarioYear": int | None,     # parsed from the first snapshot label
    "componentCounts": {sheet: row_count, ...}   # known PyPSA component sheets
}
```

### 11.2 `sqlite_store.py` — SQLite session store

One `backend/data/session/<session_id>/project.db` per session — zero
scattered files. Rows are stored one-per-row as JSON in
`sheet_<i>(__row INTEGER PRIMARY KEY, d TEXT)` tables (series sheets too: one
row per snapshot). This sidesteps SQLite's 2000-column limit and the quoting
that literal asset-name columns would require. A `_kv` table holds the JSON
values `meta`, `tables` (sheet name → table name), and `controls`.

Engine-specific behaviour:

- **Connections** — `_connect` opens the db per operation and always closes it
  (open handles break delete/replace on Windows). `PRAGMA journal_mode=WAL` and
  `PRAGMA busy_timeout=5000` let concurrent FastAPI worker threads (e.g. an
  importer plugin storing the model while the UI persists controls) wait
  instead of failing with "database is locked".
- **Reads are queries, not loads** — `get_sheet_page` and `get_series_window`
  use `LIMIT ? OFFSET ?`; `distinct_values` uses
  `SELECT DISTINCT json_extract(d, '$.<column>')` for `[A-Za-z0-9_]+` column
  names and falls back to a Python row scan for odd names.
- **`patch_sheet`** reads the sheet's rows, applies the ops
  (`session_store._apply_ops`), and rewrites the table — correct for
  set/addRow/deleteRows alike.
- **Legacy migration** — `_ensure_migrated` runs on first read: when
  `project.db` is absent but legacy JSON/Parquet files exist, the full legacy
  model is loaded, written into a fresh db, and only then are the legacy
  artifacts deleted (a crash mid-migration leaves them intact for a retry).
- **`clear`** removes the whole session directory.

Shared helpers (id/sheet guards, sheet classification, snapshot parsing, op
application, config defaults) are imported from `session_store` so the two
engines stay in lock-step.

### 11.3 `session_store.py` — legacy JSON+Parquet store

The original file-per-sheet store, kept for one release behind
`RAGNAROK_STORE=legacy`. Layout per session under
`backend/data/session/<session_id>/`:

```
meta.json                 # sheet inventory, snapshot range, component counts
static/<sheet>.json       # component sheets (buses, generators, …) + snapshots
series/<sheet>.parquet    # time-series sheets (generators-p_max_pu, loads-p_set, …)
controls.json             # run controls bound to the model (no rolling-horizon)
```

Time-series sheets are wide and tall (assets × 8760), so they live in Parquet —
columnar, readable one column-subset and one row-window at a time
(`get_series_window` does true column pushdown at the Parquet read). Static
sheets are small and edited cell-by-cell, so they live in JSON.

Helpers also used by the SQLite engine:

| Function | Description |
|---|---|
| `_is_safe_id(session_id)` / `_is_safe_sheet(name)` | Path-traversal guards (`session_id` and sheet names become filesystem names). |
| `is_series_sheet(name, rows=None)` | `<component>-<attribute>` naming convention; `snapshots` is static. |
| `_snapshot_labels(model)` / `_scenario_year_from_labels(labels)` | Snapshot labels from the `snapshots` sheet; year parsed from the first label. |
| `_apply_ops(rows, ops)` | Pure application of `set` / `addRow` / `deleteRows` ops to a row list. |
| `default_max_points()` / `default_window_hours()` / `default_page_size()` | Defaults from `system_defaults.json` → `session` (800 / 168 / 200). |

### 11.4 `timeseries.py` — windowing and downsampling

Shared maths for the thin-client API: both the session store and the run store
serve time-series the same way — the client asks for a row window `[start, end)`
and a maximum number of points, and the server slices and reduces so the
browser only receives what it draws.

| Function | Description |
|---|---|
| `series_index_col(columns)` | The time-axis column, first match in priority order `snapshot`, `name`, `datetime`, `period`; falls back to the first column. |
| `df_to_records(df)` | DataFrame → JSON-safe row dicts (NaN/NaT → `None`). |
| `downsample(df, max_points, agg, index_col)` | Splits the N rows into `min(N, max_points)` contiguous buckets (`numpy.array_split`); each bucket yields one row labelled by its first index value. `agg` is `mean`, `max`, `min` (numeric reduction; non-numeric cells coerce to NaN) or `point` (first row verbatim — decimation). |
| `slice_and_reduce(df, *, start, end, max_points, agg, index_col)` | Window then downsample. Returns `{indexCol, total, window: {start, end}, returned, agg, columns, rows}`. Invalid `agg` falls back to `"mean"`. |

### 11.5 `routers/session.py` — `/api/session/*`

| Method | Path | Body / Params | Returns |
|---|---|---|---|
| `POST` | `/api/session/model` | `SessionModelPayload` `{model, filename, scenarioName, sessionId}` | meta (ingest a full model, replacing any current one; 400 on unsafe id) |
| `POST` | `/api/session/model/static` | `SessionModelPayload` | meta (merge static sheets, keep series; 400 when no session exists) |
| `GET` | `/api/session/meta` | `?session_id` | meta, or `{}` when nothing is loaded |
| `GET` | `/api/session/model/full` | `?session_id&staticOnly` | `{"model": {sheet: rows} \| null}` — `staticOnly=true` omits series (editor rehydration on boot) |
| `GET` | `/api/session/sheet/{name}` | `?offset&limit` | one page `{name, kind, total, offset, limit, columns, rows}` (404 if absent) |
| `GET` | `/api/session/sheet/{name}/distinct` | `?column` | `{sheet, column, values}` (404 if absent) |
| `GET` | `/api/session/series/{name}` | `?start&end&columns&maxPoints&agg` | windowed slice (404 if absent / not a series). `columns` is comma-separated. |
| `PATCH` | `/api/session/sheet/{name}` | `SheetPatch` `{ops, sessionId}` | updated `{name, kind, total, columns}` (404 if absent) |
| `POST` | `/api/session/clear` | `?session_id` | `{"cleared": bool}` |

`SheetPatch.ops` are applied in order:

```python
{"op": "set",        "row": <int>, "column": <str>, "value": <any>}
{"op": "addRow",     "values": {<col>: <val>, ...}, "index"?: <int>}  # append if no index
{"op": "deleteRows", "rows": [<int>, ...]}
```

Backend plugins write into the same session via their own router (see
[docs/plugin.md §16](plugin.md#16-backend-server-side-plugins)).

---

## 12. Run store (History)

### 12.1 `run_store.py`

Every successful solve is persisted automatically: the solve worker hands the
finished bundle (`{model, scenario, options, result}`) to `store_run`, which
writes ONE SQLite file `backend/data/runs/<name>.db`. The run name is
`<label>_<UTC timestamp>` (e.g. `north-sea-2030_2026-06-09T14-30-00`); the
label comes from `options["runLabel"]`, the scenario label, or the model
filename stem. Sanitisation is a **denylist** (path separators, traversal,
control characters), so non-Latin scenario names (한글, 日本語, …) survive into
the run name. Generic default filenames (`ragnarok_case.xlsx` etc.) contribute
no label.

**DB layout** (written by `_build_run_db`): the `_kv` table holds `meta` (the
History sidecar), `head` (bundle minus model/result), `result_light` (result
with output series replaced by a `seriesSheets` name list), `analytics` (the
light analytics bundle), and two name→table maps; `m_<i>` tables hold the
input-model snapshot (a run must stay reproducible after the live session is
edited) and `o_<i>` tables hold each output time-series, one JSON row per
sheet row / snapshot. The bundle JSON and the Excel workbook are DERIVED on
demand at export and never stored. Runs saved by older versions (JSON bundle +
meta sidecar + Parquet series) migrate into their `.db` on first access
(build-before-delete, like the session migration).

The **light analytics** bundle drops the input model, the per-component output
series, and the heavy per-snapshot `generatorDispatchSeries`, and adds
`modelStatic` (topology for the network map) and `generatorEnergy` (a compact
per-generator energy aggregate for the "Dispatch by unit" donut, summed from
the dispatch series for older runs that predate the server-side field).

Every public function is defensive — a storage failure is logged and never
propagates into the solve.

| Function | Description |
|---|---|
| `store_run(model, scenario, options, result)` | Persist a finished run; returns the meta or `None` on failure (never raises into the solve). |
| `build_run_meta(name, bundle, size_bytes)` | The lightweight meta sidecar: label, snapshot window, component counts, KPIs, carrier mix, pathway/rolling summaries, History-card fields (`scenarioYear`, `resolutionHours`, `windowCount`, `totalDemandMwh`, `tags`). |
| `list_runs()` | Every run's meta, newest first. Unreadable dbs are skipped with a warning; un-migrated legacy `*.meta.json` runs are included. |
| `get_run(name)` | Reassemble the FULL bundle (model snapshot + all output series). Heavy — export/rerun path only. |
| `get_run_for_export(name, *, include_meta, include_model, include_result)` | Load only the bundle pieces the xlsx builder needs for the selected parts (metadata-only export skips the heavy series deserialize). |
| `get_run_analytics(name)` | The light analytics bundle — one small `_kv` read, what "View Result" loads first. Falls back to deriving from the full bundle if the key is corrupt. |
| `run_series_window(name, sheet, *, start, end, columns, max_points, agg)` | Windowed + downsampled slice of an output series (`LIMIT/OFFSET` SQL read). |
| `run_model_sheet_page(name, sheet, offset, limit)` | One page of the stored INPUT model sheet (re-edit / import-project). |
| `delete_run(name)` | Delete the db, legacy artefacts, and WAL sidecars. |
| `run_exists(name)` | Cheap existence check (no bundle load). |
| `run_to_xlsx(name, *, include_meta, include_model, include_result)` | Build the export workbook on demand via `project_workbook.bundle_to_workbook`. |
| `run_to_package(name)` | A Ragnarok Project `.zip` of three derived files: `<name>.json` (lossless bundle), `<name>.meta.json`, `<name>.xlsx`. |

### 12.2 Run and export endpoints

These live in `backend/app/main.py` (not a router).

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/runs` | All stored runs' lightweight metas, newest first |
| `GET` | `/api/runs/{name}` | Full stored bundle (heavy; prefer `/analytics` + `/series`). 404 if missing. |
| `GET` | `/api/runs/{name}/analytics` | Light analytics bundle — what "View Result" loads first |
| `GET` | `/api/runs/{name}/series/{sheet}` | Windowed + downsampled output series (`start`, `end`, `columns`, `maxPoints`, `agg`) |
| `GET` | `/api/runs/{name}/model/sheet/{sheet}` | One page of the stored input model sheet (`offset`, `limit`) |
| `DELETE` | `/api/runs/{name}` | `{"deleted": bool}` |
| `GET` | `/api/runs/{name}/xlsx` | Synchronous workbook download; `?parts=` comma-separated subset of `metadata,model,result` (default all) |
| `GET` | `/api/runs/{name}/package` | Synchronous project `.zip` download |
| `POST` | `/api/exports` | Start a background export build. Body `{name, kind: 'xlsx'\|'package', parts?}`. Returns `{jobId, ...}`. |
| `GET` | `/api/exports/{job_id}` | Poll export status (`pending` / `running` / `ready` / `error`) |
| `GET` | `/api/exports/{job_id}/download` | Stream the finished file, then delete artefact + job |
| `POST` | `/api/export/project` | Package an *unsaved* live model: body `{model, result}` → project `.zip` (stored runs use `/api/runs/{name}/package`) |
| `POST` | `/api/import/project` | Upload a project `.zip` or bare `.xlsx`; parsed to a bundle and stored via `store_run` — the import becomes a History entry. Returns `{meta, name}`. |

Async exports exist because a full-year workbook build is CPU-bound (minutes):
`POST /api/exports` runs the build off-thread, the client polls, and a TTL
sweeper reaps artefacts never collected (30 min). Project import also runs
off-thread so a large upload doesn't block the event loop (including the boot
screen's `/api/status` poll).

---

## 13. Project workbook

**Module:** `backend/app/project_workbook.py` — lossless, round-trippable
project xlsx read/write. It produces the **exact layout** the frontend's
`buildProjectWorkbook` / `parseProjectWorkbook` use, so server- and
client-written workbooks are interchangeable. The input/output column
classification comes from the shared PyPSA schema (`pypsa_schema`), so the two
implementations cannot drift apart.

**Workbook layout:**

- One sheet per model component (`generators`, `buses`, …); solved *static*
  outputs (`p_nom_opt`, …) merged in as extra columns. The importer splits
  them back out by the schema's input/output classification.
- Input time-series and config sheets copied verbatim; output series sheets
  named `<list>-<attr>` (no `OUT_` prefix — stays inside Excel's 31-char sheet
  name limit).
- `RAGNAROK_*` metadata sheets (`ResultMeta`, `Constraints`, `RunState`,
  `Settings`, `PluginAnalytics`, …). Long JSON payloads are chunked across rows
  at 30 000 chars (Excel caps a cell at 32 767).
- A human-readable `RAGNAROK_Summary` landing sheet (KPIs, window, constraints,
  settings) is written last and moved to the front. Display-only — skipped on
  re-import.
- Styling (bold headers, frozen panes, column widths, number formats) is
  display-only; cell values are never changed, so re-import is byte-identical
  in meaning. Per-cell number formats are skipped on sheets above 80 000 cells.

| Function | Description |
|---|---|
| `bundle_to_workbook(bundle, *, include_bundle=False, include_meta=True, include_model=True, include_result=True)` | Bundle → xlsx bytes. The three `include_*` flags mirror the Export dialog's Metadata/Model/Result checkboxes. `include_bundle=True` additionally embeds the complete bundle as chunked JSON (`RAGNAROK_Bundle`) so a *standalone* xlsx round-trips losslessly. |
| `workbook_to_bundle(data, filename)` | xlsx bytes → `{model, scenario, options, result}`. Fast path: read the embedded `RAGNAROK_Bundle` JSON verbatim. Fallback: reconstruct from the readable sheets, splitting output-static columns into `result.outputs.static` and `<list>-<attr>` sheets into `result.outputs.series`. Derived analytics are *not* reconstructed — the frontend recomputes them from `outputs`. |
| `bundle_to_package(bundle, base_name, meta=None)` | Project `.zip`: `<stem>.json` (canonical bundle), `<stem>.meta.json` (when provided), `<stem>.xlsx`. |
| `package_to_bundle(data, filename)` | `.zip` → bundle, verbatim from its JSON member (never the `.meta.json` sidecar); falls back to parsing an embedded `.xlsx`. |
| `import_bundle_from_upload(data, filename)` | Dispatch by extension: `.zip` → package, `.xlsx`/`.xls` → workbook, unknown → try package then workbook. (Detection must be by extension — an xlsx is itself a zip.) |
| `project_basename(filename)` | `<stem>_project` from a model filename, stripping data extensions. |

---

## 14. External-data importers — `/api/import/*`

**Module:** `backend/app/routers/importers.py`; importer implementations live
in `backend/app/importers/`. The Data view's three-pane shell routes through
these endpoints: the browser sends only a filter blob (plus any
bring-your-own-key secrets); fetch and convert run on the backend.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/import/databases` | Flat registry contents (one entry per dataset) |
| `GET` | `/api/import/sources` | Datasets grouped by source for the Country → Database → Datasets tree, each with its `common_filters`; plus `serverSecrets` (the secret *names* the server provides) |
| `GET` | `/api/import/countries` | Country index for the map search box (warms the boundaries cache on first call) |
| `GET` | `/api/import/boundaries/countries.geojson` | Country polygons for the Data-view map (`Cache-Control: max-age=86400`) |
| `POST` | `/api/import/run` | One-trip fetch of one or more datasets → one combined PyPSA-aligned fragment + one preview |
| `GET` | `/api/import/secrets` | `{stored, env}` — secret NAMES only; values never leave the server |
| `PUT` | `/api/import/secrets/{name}` | Record an API key server-side; an empty value deletes it. Write-only. |
| `DELETE` | `/api/import/secrets/{name}` | Remove a server-recorded key |

(`POST /api/import/netcdf` / `/api/import/hdf5` share the prefix but are the
binary format converters in `main.py` — see [Section 2.2](#22-endpoints).)

**`POST /run`** body: `{dataset_ids, country_iso, filters, convert_options?,
secrets?}` (`database_id` is the back-compat single-dataset form). The
requested datasets are expanded with their declared `depends_on` and fetched
dependency-first with the same shared filters; their fragments are folded
together (`combine_fragments`) into one result
`{source_id, dataset_ids, country_iso, preview, fragment}`. The frontend holds
the fragment in React state until the user clicks Add to workbook — no second
network call. Error mapping: unknown dataset → 404, dataset marked unavailable
→ 503, missing required API key (`PermissionError`) → 400, any other fetch
failure → 502.

**Secrets** are layered (values never leave the server): environment variables
`RAGNAROK_SECRET_<NAME>` provide the importer secret `<name>` (lowercased);
keys typed into Settings → API keys are stored in
`backend/data/secrets.json` (gitignored, chmod 0600) and win over env; a key
sent in a request body (BYOK) overrides both for that one request only.

---

## 15. Boot config — `/api/config`

**Module:** `backend/app/routers/config.py`, an isolated wrapper around
`backend/app/config_provider.py`. The bundle is dynamic — the PyPSA schema and
standard types are computed live from the installed package, capabilities come
from the live backend registry — and memoised for the life of the process.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/config` | Full `ConfigBundle` (~110 kB JSON, gzip ~25 kB). The frontend caches it in `localStorage` keyed by `build_id`. |
| `GET` | `/api/config/build-id` | `{build_id, backend_version}` — cheap freshness probe |
| `POST` | `/api/config/reload` | Drop the cache; the next request rebuilds. Dev affordance for upgrading PyPSA without a restart. Re-points `/api/status` at the new `build_id`. |

`ConfigBundle` payloads:

| Key | Description |
|---|---|
| `schema` | PyPSA component schema, built live (`pypsa_schema_builder.build_pypsa_schema`) |
| `standard_types` | PyPSA line + transformer catalogues, built live |
| `network_import_policy` | Curated rule table, read from disk |
| `capabilities` | Solver-backend capability list from the backend registry |
| `simulation_defaults` | `{maxSnapshots, defaultSnapshotCount, defaultSnapshotWeight}` from `system_defaults.json` → `simulation` |
| `build_id` / `backend_version` | The frontend's cache key |
