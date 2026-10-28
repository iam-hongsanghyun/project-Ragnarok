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
`user-manual.md`) or system-level architectural decisions (see
`architecture.md`). Frontend internals are in
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
   - 5.7 [piecewise.py — piecewise-linear curves](#57-piecewisepy--piecewise-linear-curves)
   - 5.9 [p2x — power-to-X routes, chains, RFNBO, results](#59-p2x--power-to-x-routes-chains-rfnbo-results)
   - 5.10 [plants — Build plant picker, co-firing, results by plant](#510-plants--build-plant-picker-co-firing-results-by-plant)
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
14. [External-data importers — /api/import/*](#14-external-data-importers--apiimport) (incl. [14.2 Siting screening](#142-siting-screening--apisitingscreening), [14.1 Demand database](#141-demand-database--apidemand-db-d2))
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
    tab_modules.py       Third-party TAB-MODULE store (a whole tab; see docs/module.md)
    reporting.py         Perspective-based report documents assembled from stored runs
    routers/
      session.py         /api/session/* — server-side working model (source of truth)
      plugins.py         /api/plugins/* — backend-plugin lifecycle + hooks
      tab_modules.py     /api/modules/* — tab-module install/list/enable/remove
      importers.py       /api/import/* — external-data importer subsystem (Data view)
      demand_db.py       /api/demand-db/* — self-hosted hourly demand snapshot (coverage, slice)
      config.py          /api/config — the boot bundle the frontend fetches at startup
      reports.py         /api/reports/* — report documents (policy maker, investor, …)
    importers/           importer implementations used by routers/importers.py
    backends/
      base.py            Backend Protocol + BackendError
      registry.py        register_backend / get_backend / available_backends
  pypsa/
    adapter.py           PypsaBackend — wraps run_pypsa behind the Backend protocol
    pathway.py           PathwayConfig, parse_pathway_config
    rolling.py           RollingHorizonConfig, parse_rolling_config
    stochastic.py        StochasticConfig, apply_scenarios, collapse_to_representative_scenario
    (app/carbon_pricing/  carbon-pricing module: config.py price series, term.py objective term + results; app/annual_budgets/  annual-budgets module)
    constants.py         Carrier/generator colour utilities
    pypsa_schema.py      Schema accessors (runtime schema from pypsa_schema_builder.py; network_import_policy.json)
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
      coerce.py          number, text
      series.py          safe_series, weighted_sum
      workbook.py        workbook_rows
  config/
    system_defaults.json  Simulation defaults, session paging, VOLL defaults
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

Key `options` fields. This table lists the core keys only. Every key, with its type,
default, unit and reader, is served by `GET /api/run-options` (MCP `describe_run_options`).
The PyPSA 1.4 solve options are in [§7.6](#76-other-pypsa-14-solve-options).

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
| `solverType` | `str` | `"auto"` | HiGHS LP method: `auto`, `simplex`, `ipm`, `pdlp` or `hipo` (`hipo` falls back to `ipm` where HiGHS lacks it) |
| `pathwayConfig` | `dict` | disabled | Multi-investment planning config |
| `rollingConfig` | `dict` | disabled | Rolling-horizon config |
| `stochasticConfig` | `dict` | disabled | Two-stage stochastic config |
| `securityConstrainedConfig` | `dict` | disabled | SCLOPF config |
| `solverName` | `str` | `"highs"` | linopy solver; other installed solvers are listed by `GET /api/optimise/options` |
| `piecewiseOptions` | `list[dict]` | `[]` | Formulation override per piecewise curve ([§5.7](#57-piecewisepy--piecewise-linear-curves)) |
| `riskPreference` | `dict` | disabled | CVaR for stochastic mode ([§7.3](#73-stochastic)) |
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

Solves run through the run queue: `POST /api/queue` (body `RunPayload`; returns
immediately with the queue item), `GET /api/queue` (status of every item) and
the per-item cancel / rerun / delete routes. The former direct-job API
(`POST/GET/DELETE /api/run[/{job_id}]`) was removed - nothing in the UI or MCP
called it.

#### Binary format converters (no solve)

| Method | Path | Body / Upload | Returns |
|---|---|---|---|
| `POST` | `/api/export/netcdf` | `RunPayload` | `application/x-netcdf` bytes (`ragnarok_network.nc`) |
| `POST` | `/api/export/hdf5` | `RunPayload` | `application/x-hdf5` bytes (`ragnarok_network.h5`) |
| `POST` | `/api/import/netcdf` | `UploadFile` (.nc) | `{"model": {sheet: rows[]}, "runName": str \| null}` (`runName` = the run stored from a SOLVED file, `origin="netcdf_import"`) |
| `POST` | `/api/import/hdf5` | `UploadFile` (.h5) | `{"model": {sheet: rows[]}, "runName": str \| null}` |
| `POST` | `/api/import/project/load` | `UploadFile` (.zip / .xlsx) | `{model, scenario, options, result, runName, conversation, filename}`; a file with solved results is stored as a run (`runName`, then `result` is `{}`) |
| `GET` | `/api/runs/{name}/period/{period}` | query `currency`, `fields` | `{run, period, result}`: one investment period of a pathway run from that period's slice of `n.statistics` (400 for a single-period run or an unknown period) |
| `GET` | `/api/runs/{name}/analysis/{topic}` | query `period`, `currency`; topic `duration-curve`: `source`; topic `transition-risk`: `baseYear`, `years`, `basePrice`, `escalationPct`, `strandedThreshold`, `demandGrowthPct`, `fuelGrowthPct` | Analytics-card metrics the browser no longer computes (P28): `load-analysis`, `carrier-performance`, `transition-risk`, `duration-curve`, `setpoint-duals`, `totals` (sums over result rows). `{run, topic, period, ...}`; 400 for an unknown topic. MCP `get_run_analysis` |

Export endpoints build the network without solving, from the posted `model` with
its time-series re-attached from `sessionId` (see `_model_with_session_series` —
the browser holds no series). Import endpoints use PyPSA's native
`import_from_netcdf` / `import_from_hdf5` and convert the result back to the
workbook JSON shape via `_network_to_model_json`.

### 2.3 Job lifecycle

Each queued solve spawns a child process using Python's `multiprocessing`
`"spawn"` context. The worker function `_solve_worker` (module-level, so it can
be pickled) calls `backend.run()` and puts `("ok", result)` or `("err", msg)`
onto a `multiprocessing.Queue`; the queue runner collects it and transitions the
item to `done` or `error`. The queue is in-process memory with disk-backed
payloads; see `_QueueItem` in `backend/app/main.py`.

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

**Mode combinations refused with HTTP 400** (checked at the top of `run_pypsa`):
- Stochastic + rolling horizon.
- Sampled snapshot blocks + rolling horizon, or + pathway.
- Security-constrained (SCLOPF) + rolling horizon or stochastic. SCLOPF + pathway is allowed.
- Power-flow study + rolling horizon, stochastic, SCLOPF, pathway, or sampled blocks.
- N-1 contingency + rolling horizon, stochastic, SCLOPF, pathway, sampled blocks, or power flow.

MGA has its own restrictions in the same function.

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

All paths pass `solver_name` (from `options.solverName`, default `highs`),
`extra_functionality`, and `solver_options`. For HiGHS, `solver_options` come from
`solverThreads` and `solverType`. For another solver only its thread key is mapped, and
`options.solverOptions` is merged last (`backend/pypsa/optimise_options.py`).

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
9. **Annual-budgets module** (§5.12): write `annual × Σw/8760` into the `e_sum_*` / GlobalConstraint `constant` of the rows in `RAGNAROK_AnnualBudgets`. Every other `e_sum` / `constant` passes through as PyPSA's total.
10. **Carbon price: recorded, not converted.** The price is stored in `network.meta` (`carbon_pricing.set_plan`); `marginal_cost` is untouched. The carbon-pricing module adds the term to the objective in `extra_functionality` (§7.5).
11. **Cost basis: no conversion.** `capital_cost`, `overnight_cost` and `fom_cost` pass to PyPSA unchanged (see §5.11); the builder only refuses an `overnight_cost` row that has no `discount_rate`. Then copy the `plant` annotation column (`serialize.ANNOTATION_COLUMNS`) onto the network frames so a PyPSA export keeps which components form a plant.
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

**Snapshot-axis alignment.** `snapshots` is the ONE time axis every temporal sheet is
read against: `_apply_ts_sheet` reindexes each series onto it, which DROPS rows whose
label is not on the axis and leaves the uncovered snapshots undefined. The solve reports
neither — a `loads-p_set` covering 2 of 4 snapshots returns "Optimal" with the missing
hours dispatched as ZERO demand, so the run produces a plausible wrong answer. Both
conditions are therefore **errors**, not warnings. A row-count comparison cannot catch
it, because a sheet can have exactly the right number of rows and still be for the wrong
year; labels are compared as normalised timestamps, so `2030-01-01T00:00:00` and
`2030-01-01 00:00:00` are the same snapshot. Non-datetime axes (`now`, integer steps)
fall back to the row-count check.

Checks performed (non-exhaustive):

- Unrecognised or output-only sheet names.
- Snapshot count, duplicate labels.
- Pathway: at least one period, periods unique and ascending, snapshot `period` column completeness.
- Rolling horizon: positive `horizonSnapshots`, non-negative `overlapSnapshots`, overlap < horizon.
- At least one bus, one load, one generator.
- Loads with zero / missing `p_set` and no time-series data.
- Per-component: duplicate names, required fields, bus references, numeric sanity (negative `p_nom`, `*_pu` outside [0, 1], `efficiency > 5`, `co2_emissions > 5`), carrier references, output-column presence.
- Time-series sheets: snapshot label column, row count vs snapshot count, component column existence, value range.

### 5.7 `piecewise.py` — piecewise-linear curves

PyPSA >= 1.3 lets `marginal_cost`, `capital_cost`, `efficiency` and Process `rate` be a
piecewise-linear curve (`c.piecewise[attr]`) instead of a scalar. Which curve each component
accepts, on which x axis, and whether the component may be extendable is PyPSA's own table
(`pypsa/data/piecewise.csv`); `piecewise_catalog()` reads it and the schema builder publishes it as
`piecewise_attributes` on every component.

**Sheet format.** One sheet per curve, named `<list>-<attribute>-pw` (PyPSA's own file name, so a
CSV folder is interchangeable), in long form with one row per breakpoint:

| name | breakpoint | p_pu | marginal_cost |
|---|---|---|---|
| g1 | 0 | 0 | 0 |
| g1 | 1 | 0.5 | 10 |
| g1 | 2 | 1 | 40 |

`name` is the component; the two value columns are the x attribute and the curve attribute
(`breakpoint` is informational; rows are sorted by x). A multi-port curve names its port
(`links-efficiency2-pw`, `processes-rate1-pw`).

| Sheet | x axis | y |
|---|---|---|
| `generators/links/processes-marginal_cost-pw` | `p_pu` | price per unit of x on the segment ending at the breakpoint |
| `storage_units-marginal_cost-pw` | `p_dispatch_pu` | same |
| `stores-marginal_cost-pw` | `p_pu` | same |
| `<list>-capital_cost-pw` (also lines, transformers) | `p_nom` / `e_nom` / `s_nom` (absolute) | periodised price per unit of x on the segment (per modelled horizon, as `capital_cost`) |
| `generators/links-efficiency-pw`, `processes-rate<k>-pw` | `p_pu` | efficiency (rate) at the breakpoint |

Cost of operating at `x`: `C(x) = sum_i y_i * (min(x, x_i) - x_{i-1})+` (y at the first breakpoint
is ignored). A cost curve is convex, hence an LP with tangent cuts, iff `y_1 <= y_2 <= ...`;
anything else is a MIP (binaries). Efficiency / rate curves are equalities: a MIP unless a straight
line. Per-unit curves need a fixed, finite nominal capacity (`*_extendable = false`), start at
`x = 0` and end at `x = 1`; capital curves may be on extendable assets. A scalar cost on a component
that has a curve is ignored by PyPSA.

**Build** (`network/__init__.py`): after the components exist, `apply_piecewise_sheets` parses each
`-pw` sheet (`rows_to_frame`), validates it and calls PyPSA's `_import_piecewise_from_df`; every
refusal is a 400 naming the sheet and component. Two build steps treat curves like the scalars
they replace: a `capital_cost` curve goes to PyPSA exactly as written (it must already be periodised for the horizon; PyPSA refuses a curve combined with `overnight_cost`, and the migration flags such curves for review); the carbon price is added to every segment price of an emitting
generator's `marginal_cost` curve (a price schedule that changes within the run is refused, since
a curve is time-invariant); and curves cannot be combined with stochastic scenarios (PyPSA limit).

**Run option `piecewiseOptions`** (`options.piecewiseOptions`, parsed in `parse_piecewise_options`, handed to
`n.optimize(piecewise_options=...)`): a list of `{component, attribute, method, name?, sign?}` that
overrides the formulation per curve. `method` is `auto` (default: LP for convex cost curves,
incremental binaries otherwise), `lp`, `incremental` or `sos2`. HiGHS has no SOS2, so `sos2` also
sets `reformulate_sos="auto"` and linopy rewrites it with binaries. `sign` defaults to PyPSA's own
(`>=` for cost curves, `=` for efficiency / rate).

**Round trips.** `network_to_model` emits the `-pw` sheets, so netCDF / HDF5 / CSV-folder imports keep
curves; the build's netCDF / HDF5 export carries them natively. The session store treats a `-pw`
sheet as a static table (not a snapshot series). The browser's CSV-folder zip writes and reads
PyPSA's wide layout (`name,g,g / attribute,p_pu,marginal_cost / breakpoint,,`), and also reads the
long layout; xlsx and project workbooks carry the long sheet.

**Results.** `build_piecewise_results` returns `result.piecewise`: per curve the breakpoints, its
shape (`convex` / `linear` / `nonconvex`) and the solved `marginal_cost_piecewise_opt` (realised
average cost per MWh, min / max over dispatched snapshots, operating cost) or
`capital_cost_piecewise_opt` (average annual cost per unit of optimal capacity). The raw series are
in `outputs.series["<list>-marginal_cost_piecewise_opt"]`. The generator cost breakdown, finance,
company statement and economics read the realised average (`overlay_piecewise_marginal_cost`), so
the breakdown sums to the objective.

**API / MCP.** `GET /api/piecewise/catalog`, `POST /api/piecewise/check`, `POST /api/piecewise/options/check`
(`backend/app/routers/piecewise.py`); MCP tools `describe_piecewise`, `get_piecewise_curve`,
`set_piecewise_curve`, `clear_piecewise_curve`, `check_piecewise_options`.

---

### 5.8 Maintenance and phase-shifting transformers

Both are plain PyPSA attributes. The schema-driven builder passes them through, so no
sheet kind is needed. Edit them in the Generators, Links, Processes and Transformers sheets
(or with the MCP tool `set_maintenance`).

| Attribute | Sheet | Meaning |
|---|---|---|
| `maintainable` | `generators`, `links`, `processes` | `true` lets the solver schedule maintenance for that unit |
| `maintenance_duration` | same | hours per maintenance event |
| `maintenance_events` | same | number of events per horizon |
| `maintenance_pu` | same | fraction of capacity unavailable during an event (0–1) |
| `phase_shift_min`, `phase_shift_max` | `transformers` | optimisable phase-shift range, in degrees |

Checks: `_check_maintenance_attributes` (positive duration and event count for a
maintainable unit) and `_check_phase_shift_bounds` (`phase_shift_min <= phase_shift_max`) in
`backend/pypsa/network/validators.py`. Both run in the validation pass.

Results: `generators_t.maintenance` and `maintenance_start` are extracted by
`full_outputs.py`; the analytics maintenance card reads them. `transformers-phase_shift_opt`
holds the optimised angle, shown by the phase-shifter card. Adequacy uses `maintenance_pu`
(`results/adequacy.py`). The power-flow study ignores the optimised angles and warns when a
phase-shifting transformer is present (`results/power_flow.py`).

Force-LP does not relax `maintainable`, so a model with maintenance stays a MIP.

### 5.9 `p2x` — power-to-X routes, chains, RFNBO, results

A use-case surface over the core model; no separate engine. Code: `backend/app/p2x/`
(`technologies.json` + `technologies.py`, `chains.py`, `config_store.py`, `results.py`), the router
`backend/app/routers/p2x.py` and the solve fragment `backend/pypsa/network/rfnbo.py`.

| Route | Purpose |
|---|---|
| `GET /api/p2x/technologies` | the technology data file: every parameter with value, unit, source (document, locator, year), cost year and currency, and a `verified` flag (`file`, `derived`, `literature-recalled`, `assumption`) |
| `GET /api/p2x/chain/defaults` | the default chain spec, the products and the model's anchor bus |
| `POST /api/p2x/chain` | build a chain from a spec; `apply=false` previews (fragment, component summary, warnings, row counts), `apply=true` merges the fragment into the session. `model` takes an inline model (UI mirror) for a preview |
| `GET` / `PUT /api/p2x/rfnbo/config` | the session's RFNBO matching settings, stored outside the workbook (`<RAGNAROK_DATA_DIR>/p2x/rfnbo_<session>.json`) |
| `POST /api/p2x/rfnbo/checks` | pre-solve additionality and geographic checks and what each candidate filter would drop |
| `GET /api/p2x/results/{run}` | LCOH, LCOA, LCOM, e-fuel cost, cost waterfall, electrolyser CF and full-load hours, H2 SoC, compliance table, checks, Art. 4 alternatives. Query: `period` (pathway investment period), `electricity_cost` (`nodal` or `ppa`), `chain_id` |

**Technology data.** Defaults are read from `technologies.json` (override the file with
`RAGNAROK_P2X_TECHNOLOGIES_FILE`): PyPSA/technology-data `v0.15.0` (commit `07e43575`, `outputs/costs_2030.csv` and
`inputs/data_sheets_for_renewable_fuels.xlsx`, the Danish Energy Agency renewable-fuels catalogue), 2030 values,
EUR2025 (the 100 MW electrolyser sheets are EUR2020 in the source and carry the converted value plus `rawValue`,
`rawCostYear` and `priceIndex`). Constants: H2 33.33, NH3 5.17, MeOH 5.54 kWh/kg LHV.

**Chain components.** The electrolyser, compressor and H2 discharge are `Link`s; the synthesis steps, the ASU and the CO2 capture are
PyPSA 1.4 `Process`es (`conversion_row` in `chains.py`; `spec.componentType` = `process` (default) or `link`). A synthesis
`Process` has `rate0 = -1` at `bus0` (H2, `p_nom` in MW_H2, LHV), `rate1 = 1/h` at the product bus and negative `rate2` (electricity) and
`rate3` (N2 or CO2); the Link form carries the same numbers as `efficiency` / `efficiency2` / `efficiency3`. Flows have the same sign
convention (`p_i = -rate_i p`, positive = drawn from the bus), so the two forms are the same LP: identical objective, series, sizes,
LCOH / LCOA / LCOM (`tests/test_p2x_process_parity.py`). A Process carries the same PyPSA cost columns as a Link
(`tests/test_process_capex_annuitisation.py`). The registry (`RAGNAROK_P2X`, version 2) records `componentType` and each component's
`sheet`; the results read series from `processes-pN` or `links-pN` by that field, so a chain stored with Links (version 1)
reads unchanged. Costs follow PyPSA's own split: each priced component carries `overnight_cost` (EUR per MW or MWh), `fom_cost` (EUR per MW
or MWh **per modelled horizon**: yearly fixed O&M × the workbook's horizon in years, `cost_basis.horizon_years`, written visibly and refreshed by re-applying the chain), `lifetime` and `discount_rate` (the chain's rate; the UI sets it from Settings); `capital_cost` is blank. PyPSA annualises `overnight_cost` with the row's rate and lifetime and scales it by `n.nyears`. The registry row
(`RAGNAROK_P2X`) lets the results find the components. Stack replacement is a marginal cost per MWh_el (stack cost / stack life in hours).
Chains saved before this change carry a folded `capital_cost` and are still read (the split into capex and FOM uses `f / (a + f)`).

**RFNBO run option `options.rfnboConfig`** (documented by `describe_run_options`): with `enabled`, the solve adds, for
every matching period `T`, `sum_{t in T} w_t sum_e p_el[e,t] <= sum_{t in T} w_t sum_g p_gen[g,t]`
(Delegated Regulation (EU) 2023/1184 Art. 6). Hourly is one row per snapshot; monthly one row per calendar month;
`auto` is monthly before `hourlyFrom` (2030-01-01) and hourly from it. Additionality (Art. 5(a): the generator came into
operation not earlier than 36 months before the electrolyser, tested on calendar years) and geographic correlation
(Art. 7(1)(a): same bus or same `bidding_zone` / `zone` / `country`) are checks and candidate filters
(`enforceAdditionality`, `enforceGeographic`), never LP constraints; Art. 5(b), 7(1)(b)/(c) are listed as `attest`.
Art. 4 grid alternatives (zone renewable share above 90 %, emission intensity below 18 gCO2e/MJ) are reported from the
solved run only. A run with matching on and no electrolyser or no eligible designated generator is refused (400). A run
that sets no `rfnboConfig` takes the session's stored settings at submit time (`main._resolve_payload_model`); an explicit
`rfnboConfig`, even `{"enabled": false}`, wins, and the frozen run options record what was used.

**Results.** Computed from the stored model, outputs and options (`results.py` docstring has the algorithm). The LCOH is
annualised capex plus FOM of the electrolyser, compressor and H2 store (the LP's capital charge split by `f / (a + f)`),
plus electricity (nodal price x consumption, or the designated generators' PPA cost), water and stack wear, over the H2
produced in kg. LCOA, LCOM and the e-fuel cost add the synthesis link, the hydrogen it took at the LCOH, its electricity,
its share of the N2 or CO2 supply and the product tank.

The fixed charge is read from PyPSA, not recomputed: the results rebuild the network from the stored model, scenario and options (no solve) and take
`n.components[..].capital_cost` (overnight x annuity at the row's rate x `n.nyears`; FOM is not in it) times the installed capacity, plus
`fom_cost` x capacity: PyPSA charges `fom_cost` per modelled horizon, **unscaled**, so the results report exactly that (the earlier pro-rating by window years
is gone). A period slice takes its share of the stored window.

### 5.10 `plants` — Build plant picker, co-firing, results by plant

One plant-type picker over the core model; no separate engine. Code: `backend/app/plants/` (`technologies.json` +
`technologies.py`, `thermal.py`, `catalog.py`, `registry.py`, `results.py`), the router `backend/app/routers/plants.py`, the MCP tools
`backend/mcp/tools_plants.py` and the solve fragment `backend/pypsa/network/cofiring.py`. The P2X chain is built by
`p2x/chains.py` (not duplicated).

| Route | Purpose |
|---|---|
| `GET /api/build/plant/types` | the plant types (`generator`, `bess`, `ccgt`, `ocgt`, `cofiring_simple`, `cofiring_network`, `p2x`) with their fields (key, label, kind, unit, default, `advanced`) and defaults |
| `GET /api/build/plant/technologies` | the technology data file: every parameter with value, unit, source, cost year / currency and `verified` (`file`, `derived`, `literature`, `assumption`), the fuels and the LHV constants |
| `GET /api/build/plants` | the plants of the session model (cards: type, bus, capacity, components) |
| `POST /api/build/plant` | build a plant from `{type, spec}`; `apply=false` previews, `apply=true` merges into the session. `model` = inline model (UI mirror, stateless) |
| `POST /api/build/plant/edit` | re-derive a plant from its stored spec + a patch: old rows removed, new ones merged, under the same id |
| `POST /api/build/plant/delete` | delete a plant and nothing else; a bus or carrier another row references is kept and released |
| `GET /api/build/plant/results/{run}` | results grouped by plant id. Query: `plant`, `period`, `include_series` |

**Change set.** Every write returns `change = {remove: {sheet: [names]}, release: [{sheet, name}], fragment, kept}`; the browser
applies it to the model it holds (`lib/build/plants.ts`), the session applies the same thing (`registry.apply_change`). A plant is the set
of rows whose `plant` column equals its id plus one `RAGNAROK_PLANTS` row (type, normalised spec, components, feeders, blend). The
`plant` column survives the session store (sheet columns are the union of the row keys), the workbook export / import and, because
`build_network` copies `ANNOTATION_COLUMNS` onto the PyPSA frames, `export_to_netcdf` / `csv` / `excel`; the registry is Ragnarok-only
(an imported plant is listed and deletable, not editable).

**Technology data** (`RAGNAROK_PLANTS_TECHNOLOGIES_FILE` overrides the file): PyPSA/technology-data `v0.15.0` (commit `07e43575`,
`outputs/costs_2030.csv`; `inputs/technology_data_for_el_and_dh.xlsx`, DEA sheets `05 Gas turb. CC, steam extract.` and `52 OCGT - Natural gas`,
2030 column; `inputs/technology_data_catalogue_for_energy_storage.xlsx`). CCGT: efficiency 0.58, 1108.7 EUR2025/kW, FOM 3.35 %, VOM
5.61 EUR/MWh, 25 a, minimum load 40 %, secondary regulation 15 %/min. OCGT: 0.41, 581.4 EUR/kW, 1.78 %, 6.01 EUR/MWh, 25 a, 20 %, 30 %/min,
start-up 43 EUR2015/MW (x 1.3358 = 57.4). Gas: 0.198 tCO2/MWh_th, 28.42 EUR/MWh_th. Assumptions (flagged `assumption`): CCGT start-up cost
60 EUR/MW, minimum up / down 4 h (OCGT 1 h), the H2 price (100 EUR/MWh_LHV), the H2 derate (0, off). Part-load efficiency is not modelled
(`notModelled` in the file). LHV per Nm3: H2 10.78 (derived from 119.96 MJ/kg x 0.08988 kg/Nm3), CH4 35.8 (literature, recalled).

**Formulation.** Simple co-firing generator: `mc = ((1-s) c_g + s c_h)/eta + v`, carrier `co2_emissions = (1-s) e_g` (the app divides a
generator's carrier factor by its efficiency). Turbine Link: `p_nom = P_el/eta`, `capital_cost = k_el eta`, `marginal_cost = v eta`,
`start_up_cost = u P_el`; costs are `overnight_cost = k_el eta`, `fom_cost = f k_el eta`, `lifetime`, `discount_rate` (no `capital_cost`); unit-commitment fields are written only when `committable` and the size is fixed (`p_min_pu` is a minimum load
only for a committable unit). Blend share: `vol_to_energy_share`, and per plant `(1 - s_max) h_t - s_max g_t <= 0`,
`s_min g_t - (1 - s_min) h_t <= 0` per snapshot (hourly) or summed with the snapshot weights (period), added in `extra_functionality`
beside the RFNBO hook (`cofiring_<plant>_<min|max>_<hourly|period>`).

**Run option `options.cofiringConfig`** (documented by `describe_run_options`): `{enabled, plants, minShare, maxShare, unit: energy|vol,
scope: hourly|period, perPlant}`. A run that sets none takes each plant's stored `blendMax` / `blendMin`; an explicit value, even
`{enabled: false}`, wins. A limit naming no fuel-network plant, or `minShare > maxShare`, is refused (400) before the solve.

**Results** (`plants/results.py`): per plant generation, capacity factor, full-load hours, starts (solved `start_up` for committable units,
else counted from dispatch and labelled), operating / fixed (PyPSA's effective capital cost read from the rebuilt network + `fom_cost` x window years) / fuel cost, revenue at the bus price; for gas plants the gas and H2 use (MWh_th),
the H2 share per hour (energy and vol), emissions and the emissions avoided against the same dispatch burnt as 100 % gas
(`e_g x H2 energy`); BESS charge / discharge and cycles; P2X LCOH. Fuel supplier rows are shared and not booked on a plant; fuel is valued
at the nodal price of the plant's fuel bus.

**MCP** (`tools_plants.py`): `list_plant_types` (read-only), `get_plant_results` (read-only), `add_plant`, `edit_plant`, `remove_plant`
(gated by `confirm`). `add_conversion` is unchanged.

**Run list.** `GET /api/runs` entries carry `isPathway` and `pathwayPeriods` (derived from the stored pathway block for runs saved before
the flag existed); the P2X results panel offers a period picker only for a pathway run.

### 5.11 `cost_basis.py` — PyPSA cost semantics, workbook schema version and the migration

`capital_cost` is PyPSA's periodised cost per modelled horizon, `overnight_cost` is annuitised by PyPSA
(`overnight × annuity(discount_rate, lifetime) × n.nyears`, plus `fom_cost`; `pypsa/costs.py`). Ragnarok passes both
through. Schema 1 (every workbook before 2026-10-28) held an OVERNIGHT price in `capital_cost` and annuitised it itself
(× `hours / 8760` for a single period); schema 2 is the PyPSA basis. The version is the one-row model sheet
`RAGNAROK_Schema` (`ragnarok_schema_version`), so it travels with the session store, a project xlsx / zip and a
transform's output.

**Migration (`migrate_cost_basis`)**, once, when an old workbook is loaded. A row with a nonzero `capital_cost` and no
`overnight_cost` becomes `overnight_cost = capital_cost`, `capital_cost = 0`, `discount_rate` = the project rate (the
caller's setting, else the active scenario preset, else `RAGNAROK_Settings`, else `simulation.migration_discount_rate`, 0.05, and
the report says which); extendable rows with an infinite or blank `lifetime` get 20 (`simulation.fallback_lifetime_years`)
because `annuity(r, inf) = r`. Non-extendable rows move too (their old `capital_cost` was ignored by the LP but PyPSA's
statistics report it; read as per-horizon it would overstate sunk capex by `1 / (annuity × nyears)`); their `lifetime` is left
alone because it also decides retirement in a multi-period run. Transformers were never converted by the old builder
and are left alone. Components with a piecewise `capital_cost` curve are **flagged for review** and untouched. Saved scenario presets (`RAGNAROK_Scenarios`) whose `modelOverrides` set `capital_cost` are retargeted to `overnight_cost` (the project rate is added as a `discount_rate` override for a row that has none, and reported). The solve is
unchanged because the old window factor equals `n.nyears`: the three audited objectives (capacity_expansion 1,194,599.23;
training_m17_store 948,727.73; training_m16 626,611,133.65) are bit-identical before and after
(`tests/test_cost_basis.py`, from the pre-change workbooks in `tests/fixtures/legacy_cost_basis`).
Multi-period models: PyPSA scales `overnight_cost` by each period's `nyears`; equal to the old figures while a period represents 8760 h.

Where it runs: `sqlite_store._ensure_cost_basis` (any session `project.db` without the sheet - a bundled or older example - is migrated on
first read; one journal entry records it, the report is kept in `_kv` and returned in `GET /api/session/meta` as
`costBasisMigration` until `POST /api/session/migration/ack`), and `save_model(..., legacy_origin=True)` (the browser opening an old
Ragnarok workbook: `POST /api/session/model` with `origin: "legacy"`, `discountRate`). Any other `save_model` (an importer, a plugin, an
agent, a PyPSA file) is stamped as current and not converted.

**Stored runs.** Every new run is stamped `options.buildVersion` (and `bundle.buildVersion`). A run without it is re-derived
(`statistics_query`, `derive_outputs`, `from_outputs`, P2X / plant results: `build_stored_network`) through
`model_for_stored_run`: the stored workbook is migrated **in memory** at the run's own `scenario.discountRate`, and PyPSA then prices it
as the original solve did. No legacy code path is kept; the stored run is never rewritten.

**`build_components`** is the 1:1 builder (network sheet, snapshots, components, time series, nothing else) used by every build that is
serialised back to a workbook: Forge transforms (`transforms.py`, `network_ops.py`) and the netcdf / h5 export. **Forge → Fill
discount rate** (`POST /api/forge/fill-discount-rate`) writes the Settings rate into `discount_rate` for rows with an `overnight_cost`.
Modules write PyPSA columns (conversion templates, plants, P2X: `overnight_cost`, `lifetime`, `discount_rate`, `fom_cost` = yearly O&M × `horizon_years`; the Siting scan and the Screening promote write their candidates' `overnight_cost` + `lifetime` (25 y, connection 40 y) + the `discount_rate` the caller passes and refuse without one).


### 5.12 `annual_budgets` — yearly energy and emission budgets as PyPSA horizon totals

**Module:** `backend/app/annual_budgets/`. PyPSA's `e_sum_min` / `e_sum_max` (generators) and the `constant` of a GlobalConstraint
(`primary_energy`, `operational_limit`) are totals over the weighted modelled snapshots and are never scaled to the horizon (Ragnarok used to scale
`e_sum` by `min(1, hours/8760)`, or the smallest period in a pathway, which under-scaled multi-year runs; it never scaled a GlobalConstraint, so an
annual CO2 cap typed for a 168 h run was non-binding; nothing else scales it: the DSL `emissions` atom and the structured MWh budgets only apportion a
whole-run literal across ROLLING windows, `window_fraction`). The yearly value now lives in the model sheet `RAGNAROK_AnnualBudgets`
(`component` generators | global_constraints, `name`, `attribute` e_sum_max | e_sum_min | constant, `annual`).

$$ V = A\,\frac{\sum_{t\in S} w_t\,y_{p(t)}}{8760} $$

ASCII: value = annual * sum_t(w[t] * y[period(t)]) / 8760. $w_t$ is the `generators` snapshot weighting (hours per snapshot: the weighting PyPSA applies in the
constraint, so a 4-hourly model with weight 4 counts real hours); $y_p$ the investment-period `years` weighting for global constraints (1 for `e_sum`, which
PyPSA does not weight by years). Single period: `annual × hours / 8760` (168 h → 168/8760; two years → 2×). Pathway: an `e_sum` is one whole-horizon total over
all periods (energy may move between periods); a global constraint with `investment_period = p` is that period's total (`annual × H_p/8760 × years_p`); without
one it covers all periods, each weighted by its years. Caps typed as totals (module 16's 10 / 4 / 0.3 Mt per period) have no row and pass through unchanged.
**Rolling horizon:** PyPSA applies the constant to every window, so a generator `e_sum` is split per window by committed hours (a declared constraint,
`annual_budgets.extra_functionality`; the column stays unbounded) and a GlobalConstraint budget is refused (400).

Where it runs: `build_network` after windowing (it needs the final weightings), so it is recomputed whenever the window changes; the table is in the run notes, in
`annualBudgets` of the results and `network.meta`; `POST /api/annual-budgets/apply` writes the values into the workbook rows for the workbook's own horizon (re-apply after
changing snapshots). The same step warns when the timestamp spacing disagrees with the weightings (`utils/weightings.py`; `model_check` code `weighting_spacing`): it only
warns, and the notes say which weighting was used. Run option `options.annualBudgets.enabled`. MCP: `get_annual_budgets` (read-only), `set_annual_budget`, `apply_annual_budgets`
(gated). Routes `/api/annual-budgets[/preview|/set|/apply]`.

**Migration (schema 2 → 3)** (`cost_basis.migrate_cost_basis`, `annual_budgets.migrate_e_sum`): finite generator `e_sum_*` values (annual semantics) move into the sheet and the
report lists them (`budgets`); inf / ≥1e9 placeholders and PyPSA-native files stay. `buildVersion` / `CURRENT_SCHEMA_VERSION` is 3 (carbon module + budgets). A stored run before 3 re-derives
unchanged: the carbon price is rebuilt from its `scenario` / `options`, and `legacy_e_sum_scale` applies the old build-time factor to its `e_sum` (`build_stored_network`).


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

**Cost breakdown accounting.** Fuel cost is `n.statistics.opex(cost_types=["marginal_cost"])` per generator (investment-period weighted),
load shedding is the `load_shedding_` generators' share of it, and carbon cost is the carbon-pricing module's objective term evaluated at the
solution (§7.5). `Fuel + Carbon + Load shedding (+ start-up, stand-by, other components, capital)` sums to the objective.

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
| `capital_cost` | PyPSA's periodised cost per unit for the modelled horizon (`c.capital_cost`: `capital_cost`, or `overnight_cost x annuity x n.nyears`) |
| `capex_horizon` | `n.statistics.capex` over the horizon (installed + expanded; no fom) |
| `capex_annual` | `capex_horizon / n.nyears`: the same cost PER YEAR (display basis; the only conversion) |
| `capex_expanded` / `capex_installed` | `n.statistics.expanded_capex` (new build) / `installed_capex` (already built, sunk) |
| `overnight_total`, `fom_total`, `nyears` | `n.statistics.overnight_cost`, `n.statistics.fom`, `n.nyears` |
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

Only attributes with `status="output"` in the runtime schema (`backend/app/pypsa_schema_builder.py`) are extracted.
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
(derived as `max(1, horizon - overlap)`; not read from payload). Storage is
always non-cyclic across windows (carried state); there is no terminal-state option.

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

**CVaR (`options.riskPreference`).** `{alpha, omega}` with `0 < alpha < 1` and
`0 <= omega <= 1` calls `network.set_risk_preference(alpha, omega)`
(`backend/pypsa/optimise_options.py`). It needs an enabled `stochasticConfig`, otherwise
the run is refused with HTTP 400. The GUI has no control for it. Use the API or the MCP
`submit_solve` options.

**Scenario-invariant attributes.** `is_scenario_invariant(attribute)` in `stochastic.py`
checks PyPSA's own `RE_INVARIANT_ATTRS`. An override on one of these attributes (for example
`p_nom_set` or `carrier`) is refused with HTTP 400 naming the scenario and the attribute.
PyPSA would raise a `ConsistencyError` at solve time, so the check runs first.

### 7.4 Security-constrained (SCLOPF)

Enabled via `options["securityConstrainedConfig"]["enabled"] = true`.

`run_pypsa` calls `network.optimize.optimize_security_constrained(...)`. This
enforces N-1 security for every passive branch (lines and transformers), or only the
`securityConstrainedConfig.branchOutages` subset when it is given (for example `'L1'` or
`'Transformer:T1'`). PyPSA adds line-loading constraints for every outage in that set.

SCLOPF cannot be combined with rolling horizon or stochastic mode. Pathway is allowed:
PyPSA 1.4 adds the N-1 constraints per investment period.

The `securityConstrained` key in the result dict reports `enabled: true` and
`branchCount` (lines + transformers).

### 7.5 Carbon price

**Module:** `backend/app/carbon_pricing/` (`config.py`, `term.py`). PyPSA has no native carbon price (its CO2 instrument is the
`primary_energy` GlobalConstraint), so the module sends one: the price is **one extra term of the objective**, added by
`extra_functionality` (`carbon_pricing.extra_functionality`, called first inside `run_pypsa`'s closure and by every study that
solves a copy). `marginal_cost` stays what the workbook states, so `n.statistics.opex` is the fuel cost.

$$ \min \; \ldots + \sum_t w_t\,\omega_{p(t)}\,\pi_t \sum_g \frac{e_{c(g)}}{\eta_{g,t}}\,p_{g,t} $$

ASCII: objective += sum_t w[t] * omega[period(t)] * price[t] * sum_g co2[carrier g] / eta[g,t] * p[g,t].
$w_t$ objective snapshot weighting (h), $\omega_p$ period objective weighting, $\pi_t$ price (currency/tCO2; a schedule supersedes the
scalar; pathway: the period label is the year), $e_c$ carrier `co2_emissions` (tCO2/MWh fuel), $\eta_{g,t}$ the generator's own
(static or time-varying) efficiency, $p$ MW. Stochastic runs weight it by the scenario probabilities. Links that convert a fuel bus
carry no emissions: the fuel generator does, at η = 1 (as `primary_energy`). The LP is identical to the old marginal-cost adder
(objectives equal to 1e-9 on the module 8 / 16 cases, schedules, time-varying η, rolling, stochastic, MGA).

* `CarbonPriceConfig`, `parse_carbon_price_config`, `config_from_run(scenario, options)`, `price_series(config, snapshots)`.
* `set_plan` / `plan_of`: the price a built network carries (`network.meta["ragnarok_carbon_price"]`).
* `adder_frame(network)`: currency/MWh per emitting generator and snapshot; `effective_marginal_cost`, `add_adder`: what merit order,
  finance, merchant, bidding and the market simulation price a MWh at (marginal cost + adder).
* `carbon_cost_by_generator(network)` / `carbon_cost`: the term evaluated at the solution. **Results:** fuel cost = `n.statistics.opex(marginal_cost)`
  (`stat_metrics.generator_operating_cost`), carbon cost = the term. The cost breakdown, company statement (with each generator's own η_t: the old
  static-η back-out was wrong when η varies), generator economics, KPIs and finance read these; no back-out arithmetic remains.
* `write_marginal_cost_adder(copy)`: the module's second form, ONLY on scratch copies of studies that rewrite marginal costs or build the model
  through a PyPSA entry point with no hook (MGA, strategic bidding / optimal bid). Merchant and asset swap pass the hook.
* Run options `options.carbonPricing.enabled` (default true). Refused (400): a price with CVaR (the tail constraints cannot see the term) and a
  price with a piecewise `marginal_cost` curve combined with MGA / bidding. A varying schedule with a piecewise curve now works (the term does not depend on the curve).
* MCP: `get_carbon_price` (read-only), `set_carbon_price` (writes the scenario preset). Route `POST /api/carbon-price/preview`.

Anyone solving `build_network`'s output with a bare `n.optimize()` gets no carbon term: pass `extra_functionality=carbon_pricing.extra_functionality`.

---

### 7.6 Other PyPSA 1.4 solve options

These are run-option keys (see `GET /api/run-options` for types, defaults and units). The
readers are the functions that consume them.

| Option | Effect | Reader |
|---|---|---|
| `solverName`, `solverOptions` | Installed linopy solver; raw solver options merged last | `optimise_options.py` (`parse_optimise_options`) |
| `transmissionLosses` | Line and link losses by secants or tangents | `optimise_options.py` |
| `linearizedUnitCommitment` | Relaxes committable binaries to an LP | `optimise_options.py` |
| `committableBigM` | Big-M for committable and extendable units | `optimise_options.py` |
| `cycleBasisMethod` | Cycle basis for Kirchhoff voltage law (`bfs-refined`, `paton`) | `optimise_options.py` |
| `computeInfeasibilities` | On an infeasible solve, appends the IIS for solvers that provide one | `optimise_options.py` |
| `riskPreference` | CVaR for stochastic mode ([§7.3](#73-stochastic)) | `optimise_options.py` |
| `iterativeExpansion` | Iterative transmission expansion (`optimize_transmission_expansion_iteratively`) | `optimise_extras.py` (`run_iterative_expansion`) |
| `twoStage` | Sizes capacities on the LP relaxation, fixes them, then re-solves the dispatch | `optimise_extras.py` (`run_two_stage`) |
| `nonLinearPowerFlowAfterOptimise` | AC power flow on a copy of the solved dispatch; result in `acFeasibility` | `optimise_extras.py` (`run_ac_feasibility`) |
| `powerFlowConfig` | Power-flow study (`lpf` or `pf`) instead of an LP | `results/power_flow.py` |

Network-analysis outputs (PTDF, BODF, cycles, incidence) need no solve. They are served by
`POST /api/analysis/network` and the MCP `network_analysis` tool.

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

Used when `scenario["constraintSpecs"]` is absent. Parses the text line by line;
`#` starts a comment; blank lines are ignored. Bad lines fail the solve (HTTP 400).

**Which DSL a run uses (precedence).** At submit time (`_resolve_payload_model`,
`backend/app/run_guards.py`): `scenario.constraintSpecs` when the key is present (even
`[]`), else `scenario.customDsl` when present (even `""`), else the text of the model's
`RAGNAROK_CustomDSL` sheet (first row, column `text`), which is copied into
`scenario.customDsl` so the queued snapshot carries it. The browser always sends
`constraintSpecs`, so its runs are unchanged; MCP and plugin-`contribute` DSL written to
the sheet now applies without a browser re-parse.

**Pre-run guards** (`run_guards.run_input_problems`, called from `_refuse_invalid_model`
and `/api/validate`; ported from the browser's run handler): an empty or inverted snapshot
window (`snapshotCount` wins, else `snapshotEnd - snapshotStart`), DSL text that does not
parse, and an enabled `carrier_*` constraint whose carrier no generator uses. Each refuses
the run with HTTP 400 and a sentence naming what to fix.

**Scenario presets on the backend.** `backend/app/scenario_presets.py` ports the
browser's preset, carbon-library and DSL-sheet logic; `/api/scenarios/*` serves it and the
MCP tools `list_scenarios`, `describe_scenario`, `submit_scenario`, `submit_scenarios` use
it. `backend/app/run_options_reference.py` documents every run key (`/api/run-options`,
MCP `describe_run_options`). `backend/tests/fixtures/scenario_parity.json` is shared
with the frontend's `backendParity.test.ts` so the two implementations stay equal.

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

### `backend/pypsa/utils/annuity.py` (removed)

Deleted: Ragnarok no longer annuitises anything. Use `pypsa.costs.annuity(discount_rate, lifetime)` (PyPSA's own; `annuity(r, inf) = r`) wherever a module needs an annuity of its own input.

### `backend/pypsa/constants.py`

| Function | Signature | Description |
|---|---|---|
| `default_carrier_color` | `(carrier) -> str` | Deterministic hex colour from a 30-colour palette by hashing the normalised carrier name. |
| `carrier_color` | `(network, carrier) -> str` | Prefers `network.carriers["color"]` when present and non-blank, falls back to `default_carrier_color`. |
| `generator_color` | `(network, generator) -> str` | Prefers explicit `network.generators["color"]`, then delegates to `carrier_color`. |

### `backend/pypsa/pypsa_schema.py`

Schema accessors over the runtime schema. `load_pypsa_schema()` calls
`backend/app/pypsa_schema_builder.build_pypsa_schema()`, which reads the installed PyPSA,
and is cached with `lru_cache(maxsize=1)`. The frontend gets the same schema from
`GET /api/config`, so a PyPSA upgrade changes both sides without code changes.
`network_import_policy.json` is the one curated file.

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
| `simulation` | `default_snapshot_count` | 24 | Default when not specified |
| `simulation` | `default_snapshot_weight` | 1.0 | Default hours per snapshot |
| `simulation` | `hours_in_year` | 8760.0 | Used for period-factor scaling of annual caps |
| `load_shedding` | `marginal_cost` | 2000.0 | Fallback VOLL cost (currency/MWh) |
| `load_shedding` | `carrier` | `"LoadShedding"` | Carrier assigned to VOLL generators |
| `session` | `max_chart_points_default` | 800 | Default `maxPoints` for series windows ([Section 11](#11-session-subsystem-server-side-working-model)) |
| `session` | `sheet_page_default` | 200 | Default page size for sheet reads |

The `simulation` keys reach the frontend as `simulation_defaults`
(`defaultSnapshotCount`, `defaultSnapshotWeight`) inside the
`GET /api/config` bundle (see [Section 15](#15-boot-config--apiconfig)).

### Environment overrides (`backend/.env`)

`backend/.env` (copy `backend/.env.example`) is loaded once at process start by
`backend/env_file.py` - from `backend/app/__init__.py` and the MCP entrypoint,
before any setting is read. A variable already in the process environment wins.
Every `RAGNAROK_*` / `CLIMATERISK_*` variable the code reads is listed in
`.env.example` (enforced by `backend/tests/test_env_file.py`). `RAGNAROK_PORT`
and `RAGNAROK_PLUGINS_ENV` are read by the launcher scripts only.

### FastAPI app settings

The FastAPI app (`backend/app/main.py`) adds a CORS middleware with
`allow_origins=["*"]`. In production, scope this to the specific frontend
origin.

The app is launched by `uvicorn` (see `architecture.md`).
`GET /api/log` polling noise is suppressed at the `uvicorn.access`
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
| `default_max_points()` / `default_page_size()` | Defaults from `system_defaults.json` → `session` (800 / 200). |

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
| `GET` | `/api/session/meta` | `?session_id` | meta + the journal's monotonic `version`, or `{}` when nothing is loaded |
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

## 11.6 Agent-safe mutation — actor context, journal, event stream

Three pieces that exist so a mutation can come from something other than a human at
a keyboard and still be accountable. An agent driving the model is only acceptable if
every edit is attributable, inspectable and reversible.

### `actor_context.py`

`ActorContextMiddleware` stamps each request with who is editing — `user` (a browser
with no actor header), `mcp` (a tool call over the MCP server) or `agent`. The value
rides in a context var, so the journal can record it without every endpoint having to
pass it down.

### `journal.py` + `routers/journal.py`

`wrap_model_store()` wraps the **store facade** (not the endpoints), so every session
mutation is journalled wherever it originates — a browser edit, an importer, an MCP
tool. It is installed in `main.py` before any request can reach a mutating endpoint;
order matters. Each entry records the actor, the sheets touched, a monotonic
`version`, and an undo snapshot of what changed.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/session/journal` | Mutation timeline for a session, newest last |
| `GET` | `/api/session/journal/{entry_id}/diff` | What that entry changed |
| `POST` | `/api/session/journal/{entry_id}/undo` | Revert one entry |
| `POST` | `/api/session/journal/revert` | Revert to a version |

Journal data lands under `backend/data/journal/` and is **gitignored** — it is runtime
state. Tests must not write there: `conftest.py` has an autouse fixture pointing
`RAGNAROK_JOURNAL_DIR` at the test's tmp dir, because the journal wraps the facade at
app import and would otherwise append to the repo from any test that touches a session.

### `events_bus.py` + `routers/events.py`

An SSE stream (`GET /api/events`) carrying `session.version` events, so a client sees
an out-of-band change without polling — which is what a second actor editing the same
session looks like. `GET /api/session/meta` also returns the current `version` as the
poll/reconnect fallback.

### MCP surface

`backend/mcp/server.py` exposes the backend as MCP tools, and `backend/mcp/client.py`
reaches the app purely over HTTP (`RAGNAROK_API_BASE`) — nothing in the tool surface
requires being in-process, so an external IDE can drive the same contract the GUI uses.
Coverage is the point: a capability reachable in the GUI but not as a tool is a gap, and
`backend/tests/test_mcp_server.py` is where that is held.

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
| `POST` | `/api/export/project` | Package an *unsaved* live model: body `{model, result, scenario, options, sessionId}` → project `.zip` (stored runs use `/api/runs/{name}/package`) |
| `POST` | `/api/export/workbook` | Build the INPUT workbook for Save / Save As: same body, `include_result=False` → `.xlsx` bytes |
| `POST` | `/api/import/project` | Upload a project `.zip` or bare `.xlsx`; parsed to a bundle and stored via `store_run` — the import becomes a History entry. Returns `{meta, name}`. |

Every export whose payload comes from the editor is **hydrated from the session
first** (`_model_with_session_series`): the browser holds only the static sheets,
so `model` arrives with each `<component>-<attr>` sheet empty and the server
re-attaches the session's copy. Without it an export ships the topology and no
profiles. Static sheets and any series the client did send always win, so
unsaved edits are preserved. `scenario` / `options` are written to the
`RAGNAROK_Constraints` / `_Settings` / `_RunState` sheets and are where a
re-import reads the run window back from — omit them and the re-imported project
opens with a 0-snapshot window.

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

### 14.1 Demand database — `/api/demand-db/*` (D2)

A Ragnarok-owned, offline snapshot of historical hourly load, so users pull demand without
per-user API calls or keys. Code: `backend/app/importers/demand_db/` (catalogue, parsers, store,
refresh CLI), the Data-view importer `importers/databases/demand_db/` (dataset id `demand_db`,
category demand), the router `routers/demand_db.py`, and the MCP tools in
`backend/mcp/tools_demand_db.py` (`list_demand_db`, `get_demand_db_slice`, gated
`import_demand_db`; see [bifrost-agent.md](./bifrost-agent.md) §2.7).

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/demand-db/coverage` | Manifest view: sources (definition, licence), slices (key, area, ISO-3, years, coverage, rows, sha256, retrieved date) |
| `GET` | `/api/demand-db/slice?series=opsd/DE&year_from=2019&year_to=2020` | One series as column arrays (`timestamps`, `load_mw`) + stats, definition, licence, source URLs. `country=DEU` instead of `series` picks the best national series. At most 12 years. Unknown series 404, bad window 400 |

Loading into a model goes through the normal importer: `POST /api/import/run` with
`dataset_ids: ["demand_db"]`, `country_iso`, and filters `series` (`auto` or `source/area`),
`year_from`, `year_to`, `fill_gaps`. It returns a national bus, a Load, an hourly `loads-p_set`
series and snapshot labels `YYYY-MM-DD HH:00`, like `entsoe_load` / `eia_demand`; interior gaps
are linearly interpolated (count shown in the preview), edge gaps are trimmed, never invented.
The dataset is listed `available: false` (503 on run) until a snapshot exists; its series list and
year bounds come from the manifest on every request, so a refresh needs no restart.

**Series and what they measure.** Every series is MW, UTC, timestamp = start of the hour.

| Source | Series key | Measures | Licence |
|---|---|---|---|
| Open Power System Data, `time_series_60min_singleindex.csv`, release 2020-10-06 | `opsd/<area>` (`DE`, `FR`, `GB_GBN`, `GB_UKM`, `IE_sem`, ... 30+ countries and sub-zones) | `<area>_load_actual_entsoe_transparency`: ENTSO-E *Actual Total Load* (6.1.A) cleaned and re-published by OPSD (net generation + imports - exports - pumping; includes grid losses); not the day-ahead forecast. DE is OPSD's sum of the TSO areas; `DE_LU` is the bidding zone. Data 2015-01 to 2020-09 only (OPSD's last release) | MIT for OPSD processing; underlying ENTSO-E Transparency data reusable with attribution |
| EIA Form-930 bulk balance files (`.../gridmonitor/sixMonthFiles/EIA930_BALANCE_<year>_<Jan_Jun\|Jul_Dec>.csv`) | `eia930/<BA code>` (`ERCO`, `PJM`, `CISO`, ... every BA in the files) | `Demand (MW) (Adjusted)` of a balancing authority (EIA's reported demand with gaps imputed and outliers corrected), falling back to `(Imputed)` then raw. Files are labelled *UTC Time at End of Hour*; shifted back one hour (RI4, same rule as `eia_demand`). Files are cut by local-time half-years, so one UTC year has a few edge hours in its neighbours. From 2015-07 | Public domain (US federal work) |
| ENTSO-E Transparency API (optional) | `entsoe/<ISO-3>` | Same *Actual Total Load* definition, national bidding zone (DE = DE-LU), sub-hourly points averaged to the hour. Only refreshed when a token is configured (`RAGNAROK_SECRET_ENTSOE_KEY` or the stored `entsoe_key`) | Free reuse with acknowledgement; token required |

**Refresh.**

```bash
python -m backend.app.importers.demand_db.refresh --countries DE FR GB --sources opsd
python -m backend.app.importers.demand_db.refresh --countries ERCO PJM CISO --sources eia930 --years 2023
python -m backend.app.importers.demand_db.refresh --countries DEU FRA --years 2021-2023 --sources entsoe   # needs a token
python -m backend.app.importers.demand_db.refresh --dry-run        # print the plan, touch nothing
```

`--countries` takes area codes (`DE`, `GB_GBN`, `ERCO`) or country codes (`DEU`, `GB` expands to
`GB_*`, `US`/`USA` = every BA); default all. `--years` takes years or ranges (default: all for OPSD,
the last three for EIA and ENTSO-E). `--force` re-downloads; `--dir` overrides the folder. Exit
status 1 when any source failed; the other sources still run.

**Layout** (folder `RAGNAROK_DEMAND_DB_DIR`, default `<RAGNAROK_DATA_DIR>/demand_db`, gitignored):

```
manifest.json                   one entry per slice: source, area, measure, licence, attribution, unit/tz/convention,
                                coverage_start/end, years, rows, bytes, sha256, retrieved_at, raw_files[url,sha256,bytes,fetched_at],
                                rejected_rows, schema_version
refresh_log.jsonl               append-only: per write, rows added and existing values changed (revisions)
slices/<source>/<area>.parquet  timestamp (UTC), load_mw, source_url   (~0.1 MB per BA-year span, ~0.6 MB per OPSD area)
raw/<source>/...                untouched downloads + .meta.json sidecar (url, sha256, etag, previous vintages)
```

**Failure behaviour.** Downloads stream to `.part` and are renamed on success; every JSON/parquet
write is temp + `os.replace`, so an interrupted run leaves the previous state and the next run
resumes (raw files whose size/ETag still match are reused; slices are rewritten only if content
changed). Retries: exponential backoff with jitter, `Retry-After` honoured, 5 attempts, one
download at a time. An HTTP 200 carrying an HTML page (EIA does this for files that do not exist,
e.g. `2015_Jan_Jun`) is treated as "not published", never parsed as data; an ENTSO-E
`Acknowledgement` document raises instead of reading as an empty series; the OPSD CSV is verified
against the sha256 in its `datapackage.json`. Rows failing validation (non-finite, negative,
> 1 TW, off the hour, duplicate timestamp) are dropped and counted per reason in the manifest; if
more than 20 % of a slice is rejected the write fails as schema drift. Re-runs are idempotent
(identical content: no file change, `retrieved_at` kept); a revised upstream figure replaces the
stored one and is counted under `changed` in `refresh_log.jsonl`.

Tests: `backend/tests/test_demand_db.py` (fixtures in `backend/tests/fixtures/demand_db/`, no
network). The live OPSD check is marked `integration`: `RAGNAROK_INTEGRATION=1 pytest -m integration`.

### 14.2 Screening — `/api/screening/*`

A statistical pre-screen of solar and wind sites, and of the regions they sit in, on uploaded historical
series, before the expansion-based siting (`POST /api/siting/scan`, the Siting tab). A tab module of its own
(frontend `src/modules/screening/`). Code: `backend/app/screening/` (`datasets.py` parse / validate / store,
`correlation.py` the statistics, `promote.py` the generator fragment; alignment reuses
`siting/core.py::align_cf_to_targets`), router `backend/app/routers/screening.py`, MCP tools
`backend/mcp/tools_screening.py` (names keep the `siting_` prefix; see [bifrost-agent.md](./bifrost-agent.md)).

**Dataset store.** A dataset is not model sheets. It lives per session under
`<data root>/screening_datasets/<session id>/<dataset id>/` as `series.parquet` (UTC timestamp index x site
columns, capacity factor 0-1, NaN-free) and `meta.json` (sites, step, window, validation report, provenance),
so it survives reload and restart. `kind="regions"` holds one series per region (meta key `regions`: `name, lat, lon, technology, unit, capacityMw,
geometry`); `kind="reference"` holds one load or price series (not normalised). Ids and session names are guarded
against path traversal. Datasets stored by the earlier Siting > Screening step sit under
`<data root>/siting_datasets/<session id>/`; `datasets_dir()` moves them into `screening_datasets/` the first time the
session is touched (idempotent; a dataset already present in the new folder is left alone), so they keep loading.

**Upload.** Series as CSV or xlsx in two layouts: *long* (`site, timestamp, value`) or *wide* (a timestamp
column, one column per site); the site table (file `sitesFile` or JSON `sitesJson`) has `name, lat, lon,
technology (solar|wind|other)`, optional `region`, `unit` (`cf` | `mw`) and `capacity_mw` (needed for `mw`).
Validation: unparseable timestamps (more than 5 % rejects), duplicate timestamps (averaged), gaps per site
(reported; `gapPolicy=interpolate` fills up to `maxInterpSteps`, default 48, linear in time, and drops what
remains; `drop` removes every timestamp with a gap), time zone (`timezone`, an IANA name, default UTC: naive
stamps are read in it and stored as UTC; stamps with an offset are converted as written), off-grid stamps
(averaged into the median step) and unit sanity (a series outside 0-1 after the MW / capacity division is an
error with a hint, never silently clipped).

| Method | Path | Description |
|---|---|---|
| `POST` | `/validate` | multipart; the validation report, nothing stored |
| `POST` | `/datasets` | multipart; validate and store (`name`, `kind`, `referenceKind`, `unit`, `sessionId`; for `kind=regions` the region table in `sitesFile` / `sitesJson` and optional polygons in `geojsonFile` / `geojson`) |
| `GET` | `/datasets` | `{items, total}` for the session (`kind` = sites | regions | reference, `limit`, `offset`; `siteCount`, `regionCount`) |
| `GET` | `/datasets/{id}` | sites (with mean CF), step, window, validation report |
| `DELETE` | `/datasets/{id}` | remove a dataset |
| `POST` | `/correlation` | matrix on a basis, correlation-vs-distance pairs, optional `reference` (`load`, `price` of a `run`, or an uploaded `dataset`; `align` exact or calendar) |
| `POST` | `/lagged` | cross-correlation of one site against others, lags -N..+N h (N <= 336) |
| `POST` | `/profiles` | diurnal (24), monthly (12), seasonal means per site and a down-sampled series |
| `POST` | `/metrics` | complementarity metrics of a weighted portfolio and its duration curve |
| `POST` | `/optimise` | long-only minimum-variance / maximum-mean portfolio, its metrics, an efficient frontier |
| `POST` | `/cluster` | hierarchical clustering on 1 - r: leaf order, labels, linkage |
| `POST` | `/regions` | the region series in use: members and normalised weights, capacity, centroid, polygon, mean CF |
| `POST` | `/regions/structure` | within- vs between-region correlation and site-vs-region table (site datasets) |
| `POST` | `/promote` | preview (default) or `apply`: sites become generators with `p_max_pu` |

(All paths are under `/api/screening`.) The statistic routes share the selection and basis fields
`datasetId, sites, basis (hourly|daily|weekly|monthly|seasonal|diurnal|month_hour|custom), rule (pandas offset
alias), seasonMap {month: label}, start, end, months, utcOffsetHours, method (pearson|spearman), anomaly,
anomalyStandardise, level, weighting, siteWeights, byTechnology, technology`. Window, clock offset and months apply before the basis; anomalies are hourly values minus
their (month, hour) mean and are refused on the diurnal / month-hour bases. NaN correlations (a constant series)
are returned as `null`.

**Upload, region dataset.** `kind=regions`: a series per region (wide or long) and a region table with `name`
(aliases `region`, `zone`, `area`, `country`), optional `lat` / `lon` (centroid), `technology` (blank allowed), `unit`,
`capacity_mw`, optional `geometry` (a GeoJSON Polygon / MultiPolygon as text, `[lon, lat]`); `geojson` is a
FeatureCollection whose `properties.name` (or `region`, `id`) matches a region. A region with no centroid takes
the shoelace centroid of its polygon's largest ring; with neither it is analysed but not drawn. Polygons are
validated (type, ring size, WGS84 range). The unit / CF-range / gap / time-zone validation is the site upload's.

**Region level.** `level` is `site` (default) or `region` on `/correlation`, `/lagged`, `/profiles`, `/metrics`,
`/optimise` and `/cluster`. At `region` the analysed series are region series: aggregated from the sites of a site
dataset (`weighting` equal | capacity | custom with `siteWeights {site: w}`; `byTechnology` gives
`"<region> | <technology>"` columns; `technology` keeps one) or the series of a region dataset (weights ignored).
CF aggregation: $X_{r,t} = \sum_{i\in r} w_i x_{it} / \sum_{i\in r} w_i$ (equal $w=1$, capacity $w=P_i$ MW, or
user); a capacity weighting needs a positive `capacity_mw` for every member; a region whose weights sum to 0 and
negative weights are 422. The response shapes are the site level's, with region names in `sites` and weights, and
`distance` between centroids (regions without one are left out); `regionCaps` on `/optimise` act on the region
label, so with `byTechnology` they cap a region's total across its technology columns. `/promote` stays
site-level.

**Region statistics** (all in `correlation.py`, pure): `aggregate_regions` (above); `pair_stats` (n, mean, median,
std, min, q1, q3, max of a set of correlations); `within_between_correlation(corr, group_of)`: for the site
correlation matrix $r_{ij}$, within sets $W_g=\{r_{ij}: g(i)=g(j)=g\}$ and between sets $B_{gh}=\{r_{ij}:
g(i)=g, g(j)=h\}$ summarised by `pair_stats`, pooled means $\bar r_W, \bar r_B$ and the gain $\bar r_W-\bar r_B$
(positive: sites of a region move together more than across regions, so spreading across regions buys
diversification; about 0: region borders carry no information); `site_region_correlation`: $r_{i,h}=
\mathrm{corr}(x_i,X_h)$ for every region and, for the site's own region, the leave-one-out $X_{g(i)}^{(-i)}$ (the full
series contains the site, so it would correlate for free); a site is *odd* when its best other region beats its own.
`/regions/structure` applies them to the site dataset on the chosen basis (at most
`RAGNAROK_SITING_MAX_STRUCTURE_SITES`, 400, since only per-region summaries are returned) and adds `aggregateR`,
the correlation of the two aggregated region series, to each between entry.

**Statistics** (each function in `correlation.py` carries an `Algorithm:` block with LaTeX and an ASCII line):
Pearson and Spearman (Pearson of average ranks); portfolio $y_t=\sum_i w_i x_{it}$ with mean CF, CV
$\sigma_y/\bar y$, P10 / P50 / P90 as *exceedance* (P90 is the 10th percentile: the output reached in 90 % of
the hours), low-output share $\Pr(y<\theta)$, coincident-low probability of a pair next to its independent
product, ramp correlation of the step changes, worst-N loss $1-\bar y_{(N)}/\bar y$ and diversification ratio
$\sum w_i\sigma_i/\sigma_y$; optimiser $\min w^\top\Sigma w$ s.t. $\mathbf 1^\top w=1$, $\mu^\top w\ge\mu^*$, $0\le
w\le w_{max}$, region sums $\le c_r$ (SLSQP; or $\max\mu^\top w$ s.t. $w^\top\Sigma w\le v_{cap}$); infeasible targets
are found first with an LP / the minimum variance and the error states the reachable value; clustering is
average-linkage (scipy) on $D=1-r$ with optimal leaf ordering. `scipy` is in `requirements.txt`.

**Promotion.** `POST /promote` builds one `WorkbookFragment` (carriers, generators, `generators-p_max_pu`,
snapshots, provenance) and returns it with an alignment report. Each site attaches to the nearest bus with
coordinates (or `busOverrides`); `pNomMw` defaults to the site capacity, else 100 MW; `extendable` makes
zero-capacity candidates (`p_nom_max`, `capitalCost`). Profiles go through
`siting/core.py::align_cf_to_targets` (UTC shifted by `utcOffset`, then exact hour, the same month-day-hour
of another year, or the hour-of-day mean); `report` lists per site the exact / calendar / hour-mean / unmatched
counts and `warnings` (no overlap, non-hourly dataset or model, name clashes, an empty model). The GUI keeps the
fragment and merges it itself (the Data-view path); `apply=true` (API, MCP) merges server-side through
`fragment_merge.merge_fragment` and answers 409 when `report.ok` is false unless `force=true`.

**Limits** (environment variables, defaults): `RAGNAROK_SITING_MAX_UPLOAD_BYTES` 200 MB,
`RAGNAROK_SITING_MAX_SITES` 400 per dataset, `RAGNAROK_SITING_MAX_MATRIX_SITES` 60 per analysis request (regions count as sites), `RAGNAROK_SITING_MAX_STRUCTURE_SITES` 400,
`RAGNAROK_SITING_MAX_CHART_POINTS` 500, `RAGNAROK_SITING_MAX_LAG_HOURS` 336,
`RAGNAROK_SITING_MAX_INTERP_STEPS` 48.

Tests: `test_screening_correlation.py` (analytical), `test_screening_regions.py` (region statistics: identical regions = 1,
one site repeated k times = that site, capacity weighting by hand, two independent blocks: within 0.80 +- 0.03 and
between 0.00 +- 0.03 at seed 7, leave-one-out, odd site, polygon centroid), `test_screening.py` (validation, routes, region
level, region upload, old-folder migration, promotion), `test_mcp_screening.py`.

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
| `simulation_defaults` | `{defaultSnapshotCount, defaultSnapshotWeight}` from `system_defaults.json` → `simulation` |
| `build_id` / `backend_version` | The frontend's cache key |

---

## 16. Tab-modules — `/api/modules/*`

A **tab-module** is a whole Ragnarok tab (see [module.md](./module.md)); a
**plugin** (`/api/plugins/*`) is a small extension. Third-party modules are
stored on the server by `app/tab_modules.py`:

```
backend/data/modules/<id>/tabmodule.json   manifest (id, label, hint, description, order, entry)
backend/data/modules/<id>/index.js         CommonJS entry exporting mount(el, ctx)
backend/data/modules/.state.json           {"<id>": {"enabled": true}}
```

Server-side on purpose: a module is project content, and the frontend's
`localStorage` is wiped both by the "Clear cache" button and by the build-id
reset that runs on every app update — a module kept there would be uninstalled
by the next deploy. `RAGNAROK_TAB_MODULES_DIR` overrides the location.

| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/modules` | `{modules: [{manifest, files, enabled, installedAt}]}`, ordered by bar position then id |
| `POST` | `/api/modules/install` | install/update from an uploaded `.zip` → the installed module |
| `POST` | `/api/modules/install-path` | install/update from a server-side directory (`{path}`) — the agent/CLI form |
| `POST` | `/api/modules/{id}/enabled` | `{enabled}` → show/hide the tab (persisted server-side) |
| `DELETE` | `/api/modules/{id}` | `{id, removed}` — deletes the package directory and its flag |

Rules the store enforces (all surfaced as HTTP 400):

- ids must match `^[A-Za-z][A-Za-z0-9_-]*$` and must not collide with a core tab
  (`Welcome`, `Build`, `Model`, `Market`, `Settings`, `Analytics`, `History`,
  `Plugins`) or a built-in module (`Data`, `Forge`, `PhysicalRisk`, `Siting`,
  `PostAnalysis`, `Training`);
- the manifest's `entry` file must exist in the package;
- zip entries with absolute or `..` paths are refused (zip-slip), and archive +
  unpacked sizes are capped (`RAGNAROK_MAX_MODULE_ZIP_MB`,
  `RAGNAROK_MAX_MODULE_UNZIPPED_MB`);
- re-installing an id replaces the directory but KEEPS its enabled flag;
- discovery never raises — a malformed module on disk is logged and skipped, so a
  broken package can't stop the backend from starting.

The same four operations are exposed over MCP (`list_tab_modules`,
`install_tab_module`, `set_tab_module_enabled`, `remove_tab_module`), with the
mutating three behind the autonomy guard.
