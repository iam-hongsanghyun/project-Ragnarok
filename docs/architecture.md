# Ragnarok — Architecture

This document is the system-level orientation guide for contributors and AI sessions.
It covers tech stack, repository layout, communication topology, end-to-end data flow,
process logic for every major operation, constraint mechanisms, plugin runtime, and UI
design philosophy.

Per-function and per-component reference detail lives in the reference docs, not here.
For end-user click-by-click instructions, see the user manual. For plugin authoring
detail, see the plugin guide.

---

## Table of contents

1. [Overview and tech stack](#1-overview-and-tech-stack)
2. [Repository layout](#2-repository-layout)
3. [Communication topology](#3-communication-topology)
4. [End-to-end data flow](#4-end-to-end-data-flow)
5. [RunPayload schema](#5-runpayload-schema)
6. [WorkbookModel sheet index](#6-workbookmodel-sheet-index)
7. [Process logic](#7-process-logic)
   - 7.1 [Opening a workbook](#71-opening-a-workbook)
   - 7.2 [Editing the model](#72-editing-the-model)
   - 7.3 [Validation (dry run)](#73-validation-dry-run)
   - 7.4 [The run lifecycle](#74-the-run-lifecycle)
   - 7.5 [Network build: `build_network`](#75-network-build-build_network)
   - 7.6 [Solve branch logic in `run_pypsa`](#76-solve-branch-logic-in-run_pypsa)
   - 7.7 [Result extraction: `run_pypsa` to `RunResults`](#77-result-extraction-run_pypsa-to-runresults)
   - 7.8 [Rendering results in the frontend](#78-rendering-results-in-the-frontend)
   - 7.9 [Run history](#79-run-history)
   - 7.10 [Export and import pipelines](#710-export-and-import-pipelines)
   - 7.11 [Pathway (multi-year) planning](#711-pathway-multi-year-planning)
   - 7.12 [Rolling horizon](#712-rolling-horizon)
   - 7.13 [Stochastic mode](#713-stochastic-mode)
   - 7.14 [Security-constrained (SCLOPF)](#714-security-constrained-sclopf)
8. [Constraints](#8-constraints)
9. [Plugin runtime](#9-plugin-runtime)
10. [UI design philosophy](#10-ui-design-philosophy)
11. [Current scope and limitations](#11-current-scope-and-limitations)
12. [Server-side deployment & frontend/backend separation](#12-server-side-deployment--frontendbackend-separation)

---

## 1. Overview and tech stack

Ragnarok is a browser-based GUI for building and running single-year (and multi-year)
PyPSA power-system models. The user opens or edits an Excel workbook — one sheet per
PyPSA component — configures run parameters in a modal dialog, and the React frontend
posts the workbook data to a local FastAPI backend. The backend constructs a
`pypsa.Network`, solves it with HiGHS, and returns structured results. Charts, maps,
and tables display the outputs without any round-trips to a remote server.

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Create React App (react-scripts 5) |
| Mapping | react-leaflet / Leaflet |
| Charting | Recharts |
| Workbook I/O | SheetJS (xlsx) |
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Power model | PyPSA |
| Solver | HiGHS (via PyPSA default linopt interface) |
| Transport | REST JSON over `http://127.0.0.1:8000` |

---

## 2. Repository layout

The repository is a pluggable frontend plus a pluggable backend. The backend is split
into an engine-agnostic host (`backend/app/`) and the reference engine
(`backend/pypsa/`); a second engine would be a sibling package under `backend/`. The
frontend lives in its own npm package (`frontend/Ragnarok_default/`); a second
frontend would be a sibling under `frontend/`. The tree below is representative, not
exhaustive.

```
pypsa_gui/
├── backend/
│   ├── app/                         engine-agnostic FastAPI host (no PyPSA imports)
│   │   ├── main.py                  FastAPI app, run lifecycle, file-converter endpoints
│   │   ├── models.py                RunPayload request/response models
│   │   ├── config.py                loads backend/config/*.json (system defaults)
│   │   └── backends/                pluggable-backend seam
│   │       ├── base.py              Backend protocol + BackendError
│   │       └── registry.py          get_backend / available_backends / register_backend
│   ├── pypsa/                       PyPSA reference engine (the only backend today)
│   │   ├── adapter.py               PypsaBackend — implements the Backend protocol
│   │   ├── network/                 build_network() — assembles pypsa.Network from the model
│   │   │   ├── __init__.py          public entry: build_network(), validate_model()
│   │   │   ├── components.py        generic schema-driven component import loop
│   │   │   ├── network_sheet.py     `network` sheet runtime-import allow-list
│   │   │   ├── snapshots.py         snapshot index (flat / pathway MultiIndex)
│   │   │   ├── custom_constraints.py  carrier-share / CO2-cap constraints
│   │   │   ├── constraint_dsl.py    apply_constraint_specs / apply_dsl_constraints
│   │   │   ├── load_shedding.py     optional load-shedding backstop generator
│   │   │   └── validators.py        structural pre-solve validation checks
│   │   ├── results/                 extract results from the solved network
│   │   │   ├── __init__.py          public entry: run_pypsa() → RunResults dict
│   │   │   ├── full_outputs.py      schema-driven solved-output cache
│   │   │   ├── dispatch.py          carrier- and generator-level dispatch series
│   │   │   ├── emissions.py         system + per-generator CO2 series
│   │   │   ├── expansion.py         capacity expansion delta (p_nom_opt − p_nom)
│   │   │   ├── market.py            merit order, CO2 shadow price, applied constraints
│   │   │   └── summaries.py         per-scenario / KPI summaries
│   │   ├── pathway.py               multi-period pathway planning helpers
│   │   ├── rolling.py               rolling-horizon helpers
│   │   ├── stochastic.py            two-stage stochastic scenario helpers
│   │   ├── carbon_price.py          carbon-price schedule parsing/application
│   │   ├── pypsa_schema.py          PyPSA-facing schema helpers (input/output attributes)
│   │   ├── constants.py             carrier → colour map shared by builder + extractors
│   │   └── utils/
│   │       ├── coerce.py            number(), text(), bool_value() — safe type coercion
│   │       ├── workbook.py          workbook_rows(), apply_scaled_static_attributes()
│   │       ├── series.py            weighted_sum() and pandas series helpers
│   │       └── annuity.py           capital-recovery factor for expansion cost annualisation
│   ├── config/                      JSON config consumed by backend/app/config.py
│   └── tests/                       pytest suite
│
└── frontend/
    └── Ragnarok_default/            default React/TypeScript UI (its own npm package)
        ├── package.json             npm project root (proxy → 127.0.0.1:8000)
        ├── public/                  CRA static root (index.html)
        ├── scripts/                 build-time codegen (*.mjs) for src/config JSON + docs
        └── src/
            ├── App.tsx              Root component: state, event handlers, run flow
            ├── index.tsx            ReactDOM entry point
            ├── index.css            All CSS (scoped by component prefix)
            ├── config/              generated JSON (pypsa_schema.json, capabilities.json …)
            ├── constants/           schema adapters + shared constants
            ├── layout/              ActivityBar, Sidebar, and chrome
            ├── views/               top-level tab views (Model, Analytics, Settings, Plugins)
            ├── features/            feature folders: build, input, map, analytics,
            │                          constraints, validation, run, run-history,
            │                          plugins, settings
            └── shared/              cross-feature types, utils, and components
```

Per-module function reference for the backend is in
[`docs/reference/backend.md`](backend.md). Frontend component reference is in
[`docs/reference/frontend.md`](frontend.md).

---

## 3. Communication topology

Understanding which components talk to which is the single most important orientation
fact for plugin authors and contributors.

```
Browser (Ragnarok frontend)
  |
  |  REST JSON  (http://127.0.0.1:8000 — or remote server in future deployments)
  v
Ragnarok backend  (FastAPI / HiGHS solver)

Browser (Ragnarok frontend)
  |
  |  REST / fetch  (localhost:<plugin port> — registered per-plugin)
  v
Plugin's own local backend server  (optional; any language/framework)
```

The rule is absolute:

| Link | Allowed |
|---|---|
| Plugin JS <-> Ragnarok frontend | Yes — plugins run in the browser and call frontend APIs |
| Ragnarok frontend <-> Ragnarok backend | Yes — the only path to the solver |
| Plugin <-> Ragnarok backend | No — the Ragnarok backend is plugin-agnostic |

The Ragnarok backend receives `{model, scenario, options}` and solves. It never
discovers, loads, or executes plugin code of any kind. There is no `module_host.py`,
no `execute_plugins_at_stage()`, and no `/api/modules` route. Plugins that need
server-side computation run their own separate local server and communicate with it
directly from the browser.

The backend currently runs locally at `http://127.0.0.1:8000`. The architecture is
being moved toward a remote server model; the communication rule above is what makes
that safe — the frontend is the only client of the Ragnarok backend, so moving the
backend server-side requires no plugin changes.

---

## 4. End-to-end data flow

```
1. OPEN
   User opens .xlsx → parseWorkbook() (SheetJS)
   → WorkbookModel { network, buses, generators, ... }   (all in React state)

2. EDIT
   TablesPane → updateRowValue / addRow / deleteRow / addColumn
   → mutates WorkbookModel in state (no backend call)

3. RUN
   Run button → RunDialog (modal)
   → user picks snapshotStart/End, snapshotWeight, carbonPrice, dryRun

   POST /api/run  (or /api/validate for dry-run)
   Body: RunPayload {
     model: WorkbookModel,       entire sheet data as JSON
     scenario: { constraints, constraintSpecs, carbonPrice },
     options:  { snapshotCount, snapshotStart, snapshotWeight, ... }
   }

4. BACKEND
   build_network(model, scenario, options)
     → attach buses, loads, generators, lines, links, transformers,
       storage_units, stores, global_constraints
     → attach time-series profiles (p_max_pu, p_min_pu, loads-p_set, inflow)
     → slice & weight snapshots

   extra_functionality applies constraintSpecs / custom_constraints

   network.optimize()  — HiGHS via PyPSA linopt
       (or optimize_with_rolling_horizon / optimize_security_constrained)

   run_pypsa(model, scenario, options)
     → extract dispatch, emissions, prices, storage, line loading
     → per-asset details (generators, buses, storage_units, stores, branches)
     → merit order, CO2 shadow, capacity expansion delta
     → build RunResults dict

5. RENDER
   RunResults → React state (results)
   ResultsDashboard — fixed predefined charts (dispatch, load, price, storage …)
   AnalyticsPane (Analytics tab) — interactive map + user-defined chart cards
   Sidebar "Results" group — KPI summary cards
```

---

## 5. RunPayload schema

Sent as JSON to `POST /api/run` and `POST /api/validate`.

```json
{
  "model": {
    "network":            [{ "name": "my_network", ... }],
    "snapshots":          [{ "name": "2019-01-01 00:00", ... }],
    "carriers":           [{ "name": "solar", "co2_emissions": 0, ... }],
    "buses":              [{ "name": "Bus1", "x": 127.0, "y": 37.5, ... }],
    "generators":         [{ "name": "Solar1", "bus": "Bus1", "carrier": "solar", ... }],
    "loads":              [{ "name": "Load1", "bus": "Bus1", "p_set": 100, ... }],
    "lines":              [...],
    "links":              [...],
    "stores":             [...],
    "storage_units":      [...],
    "transformers":       [...],
    "shunt_impedances":   [...],
    "global_constraints": [...],
    "shapes":             [...],
    "processes":          [...],
    "generators-p_max_pu":   [{ "name": "2019-01-01 00:00", "Solar1": 0.85, ... }],
    "generators-p_min_pu":   [...],
    "loads-p_set":            [...],
    "storage_units-inflow":   [...],
    "links-p_max_pu":         [...]
  },
  "scenario": {
    "constraints": [
      { "id": "c1", "enabled": true, "label": "CO2 cap",
        "metric": "co2_cap", "carrier": "", "value": 1000, "unit": "ktCO2" }
    ],
    "constraintSpecs": [
      { "type": "carrier_share_min", "carrier": "solar", "value": 0.3 }
    ],
    "carbonPrice": 0
  },
  "options": {
    "snapshotCount": 24,
    "snapshotStart": 0,
    "snapshotWeight": 1
  }
}
```

Time-series sheets (`generators-p_max_pu` etc.) use the first column as the snapshot
label (`name` key) and subsequent columns keyed by component name.

---

## 6. WorkbookModel sheet index

| Sheet | Type | PyPSA component | Notes |
|---|---|---|---|
| `network` | static | `Network` attrs | name, co2_limit etc. |
| `snapshots` | static | `Network.snapshots` | `name` column = datetime strings |
| `carriers` | static | `Carrier` | `co2_emissions` in t/MWh |
| `buses` | static | `Bus` | `x`/`y` for map, `v_nom` |
| `generators` | static | `Generator` | `p_nom_extendable`, `capital_cost`, `marginal_cost` |
| `loads` | static | `Load` | static `p_set` (overridden by `loads-p_set`) |
| `lines` | static | `Line` | `bus0`, `bus1`, `s_nom`, `x`, `r` |
| `links` | static | `Link` | `bus0`, `bus1`, `p_nom`, `efficiency` |
| `stores` | static | `Store` | `bus`, `e_nom`, `capital_cost` |
| `storage_units` | static | `StorageUnit` | `bus`, `p_nom`, `max_hours` |
| `transformers` | static | `Transformer` | `bus0`, `bus1`, `s_nom`, `x` |
| `shunt_impedances` | static | `ShuntImpedance` | rarely used |
| `global_constraints` | static | `GlobalConstraint` | `type`, `carrier_attribute`, `sense`, `constant` |
| `shapes` | static | geometry | optional GeoJSON shapes |
| `processes` | static | custom | app-specific process metadata |
| `generators-p_max_pu` | time-series | `Generator.p_max_pu` | columns = generator names |
| `generators-p_min_pu` | time-series | `Generator.p_min_pu` | columns = generator names |
| `loads-p_set` | time-series | `Load.p_set` | columns = load names |
| `storage_units-inflow` | time-series | `StorageUnit.inflow` | columns = storage unit names |
| `links-p_max_pu` | time-series | `Link.p_max_pu` | columns = link names |

For the authoritative attribute counts per component (input static, input time-series,
outputs, map marker availability), see [SUPPORT_MATRIX.md](SUPPORT_MATRIX.md).

---

## 7. Process logic

### 7.1 Opening a workbook

Entry point: `handleOpenWorkbook` in `App.tsx`.

1. On Chromium, `showOpenFilePicker` returns a `FileSystemFileHandle`. On other
   browsers the hidden `<input type="file">` fires `handleImport` instead.
2. Either path calls `parseWorkbook(file)` in
   `src/shared/utils/workbook.ts`. SheetJS reads the `ArrayBuffer` via
   `XLSX.read(arrayBuffer, { type: 'array', cellDates: true })`.
3. `parseSheets` iterates every sheet, normalises the sheet name to a canonical key,
   and calls `XLSX.utils.sheet_to_json` with `defval: null`. Each cell passes through
   `normalizeCell`, which converts `Date` objects to ISO-8601 strings and coerces
   numbers and booleans.
4. The result is a `WorkbookModel` — a plain object keyed by sheet name, where each
   value is `GridRow[]`.
5. `normalizeInputDatesToIso` walks every temporal sheet and calls
   `normalizeSnapshotIso` (respecting the user's date-format setting), converting
   Excel date serials and `Date` objects to `YYYY-MM-DDTHH:MM:SS`.
6. `resetForNewModel` is the single choke point for loading any model into live state.
   It reads embedded pathway, rolling, and scenario config from the model, applies the
   active scenario's parameters to the React state sliders, and clears `results`,
   `resultsModel`, `resultsContext`, and `runStatus`.

**Project import** (`handleImportProject`) follows the same path but calls
`parseProjectWorkbook`, which splits static component sheets into input columns (model)
and solved output columns (`outputs.static`). Private `RAGNAROK_*` sheets carry
settings, constraints, run-state, provenance, and plugin analytics, each decoded by its
own branch.

### 7.2 Editing the model

All model state lives in a single `model: WorkbookModel` React state value in
`App.tsx`. Every mutation produces a new object; nothing is mutated in place.

`pushHistory()` snapshots the current model onto `undoStack` (capped at 50 entries).
`undo()` / `redo()` pop from the respective stacks. Keyboard shortcuts (`Ctrl/Cmd+Z`,
`Ctrl+Shift+Z`, `Ctrl+Y`) are wired only on the Model and Build tabs and are
suppressed when a text input has focus.

Core mutation helpers:

| Function | What it does |
|---|---|
| `updateRowValue(sheet, rowIndex, key, value)` | Single-cell edit |
| `bulkPaste(sheet, edits, extraRows)` | Multi-cell paste as one undoable operation |
| `addRow(sheet)` | Appends a row seeded from `getDefaultRowForSheet` |
| `deleteRow(sheet, rowIndex)` | Removes row by index |
| `moveRow(sheet, rowIndex, direction)` | Swaps row with its neighbour |
| `addColumn(sheet, col, defaultValue)` | Adds a column to every row if absent |
| `deleteColumn(sheet, col)` | Removes a key from every row |
| `renameColumn(sheet, oldCol, newCol)` | Renames a key across every row |
| `clearSheet(sheet)` | Replaces the array with `[]` |

Pathway config, rolling config, and scenario catalog are stored in their own React
state values. Three `useEffect` hooks write them back to the embedded `RAGNAROK_*`
model sheets only when a round-trip read detects an actual change, preventing
re-render loops.

### 7.3 Validation (dry run)

1. The user opens `RunDialog`, toggles "Dry run", and clicks "Validate".
2. `handleRunModel` deep-clones the model and ISO-normalises timestamps via
   `prepareModelForBackend`, then posts `{ model, scenario, options }` to
   `POST /api/validate`.
3. `backend/app/main.py`'s `validate_case` handler calls `validate_model(payload)` from
   `backend/pypsa/network/validators.py`.
4. `validate_model` performs schema-driven checks without building a `pypsa.Network`:
   unknown sheets, duplicate names, required fields, bus references, numeric sanity,
   carrier references, and time-series column/snapshot alignment.
5. Returns `{ valid, errors, warnings, notes, snapshotCount, networkSummary }`.
6. The frontend stores the result in `validateResult` state and switches to the
   Analytics → Validation sub-tab.

### 7.4 The run lifecycle

#### Options assembly (frontend)

`handleRunModel` in `App.tsx` assembles:

- `scenario`: `{ constraints: enabled[], constraintSpecs: compiledSpec[],
  customDsl: string, carbonPrice, discountRate }`. `constraintSpecs` is the compiled
  JSON representation of Advanced Constraints (from the `RAGNAROK_CustomDSL` sheet
  and any plugin `contribute` output); `customDsl` is the raw DSL text accepted as a
  fallback.
- `options`: snapshot window (`snapshotStart`, `snapshotCount`, `snapshotWeight`),
  solver settings (`solverThreads`, `solverType`), feature flags (`forceLp`,
  `enableLoadShedding`, `loadSheddingCost`), backend selector (`backend: 'pypsa'`),
  `pathwayConfig`, `rollingConfig`, `stochasticConfig`, `securityConstrainedConfig`,
  `carbonPriceSchedule`.

#### Starting the job (`POST /api/run`)

1. `POST /api/run` in `backend/app/main.py` receives `RunPayload`.
2. The backend validates the backend name via `get_backend`; unknown names return 400.
3. Stale completed or cancelled jobs are pruned from the `_jobs` dict.
4. A UUID `job_id` is generated. A multiprocessing `Queue` and a `Process` are created
   using `mp.get_context("spawn")` so the worker imports cleanly in a fresh
   interpreter. The target is `_solve_worker`.
5. `_solve_worker` runs in the child process. It calls `get_backend(options["backend"])`
   — currently always `PypsaBackend` from `backend/pypsa/adapter.py` — then calls
   `backend.run(model, scenario, options)`, which calls `run_pypsa`. On completion it
   puts `("ok", result)` or `("err", message)` into the queue.
6. An asyncio task `_collect_job(job_id)` polls the queue every 0.5 s.
7. `{ jobId, status: "running" }` is returned synchronously to the frontend.

#### Polling (`GET /api/run/{job_id}`)

The frontend polls starting after `RUN_POLLING.initialDelayMs`. Each poll:

- A 404 means the server restarted and lost the job; the UI transitions to `'error'`.
- A network error schedules a retry after `RUN_POLLING.retryDelayMs`.
- When `data.status === 'running'`, the next poll is scheduled after
  `RUN_POLLING.runningDelayMs`.
- When `data.status === 'done'`, `applyResult(data.result)` is called and the job is
  removed from `_jobs` to free memory.

Cancel (`handleCancelRun`) calls `DELETE /api/run/{jobId}`, which terminates the child
process via `proc.terminate()` and `proc.join(3)`.

#### Applying the result (frontend)

`applyResult(rawResults)` in `App.tsx`:

1. Canonicalises backend output timestamps via `canonicalizeOutputSeries`.
2. Updates `pathwayConfig` and `rollingConfig` from returned metadata.
3. Freezes `resultsModel` to the exact topology submitted, so later edits do not
   corrupt analytics for this run.
4. Freezes `resultsContext` (`carbonPrice`, `snapshotWeight`, `discountRate`) so
   pathway KPIs stay stable even if the user moves the live sliders.
5. Appends a `RunHistoryEntry` to `runHistory`.

### 7.5 Network build: `build_network`

`build_network(model, scenario, options)` in `backend/pypsa/network/__init__.py`
returns `(network, notes)`. This is the sole public entry for network assembly;
internal sub-modules are not imported directly from outside `network/`.

1. **Parse options.** `parse_pathway_config` and `parse_stochastic_config` build typed
   config objects.
2. **Create the network.** `pypsa.Network()` is instantiated. `_apply_network_sheet`
   applies the `network` sheet (name, CRS) from a runtime-import allow-list.
3. **Build the snapshot index.** `_snapshots_index` reads the `snapshots` sheet. For
   pathway mode with `explicit_period_column`, it constructs a
   `pd.MultiIndex(["period", "timestep"])`. For single-period mode it deduplicates
   labels and calls `pd.to_datetime`. `_apply_pathway_config` calls
   `network.set_investment_periods` and populates `investment_period_weightings`.
4. **Add components.** `_ordered_component_sheets` returns all component sheets in
   dependency-safe order (carriers → buses → everything else). For each sheet: rows
   without a `name` are dropped; a DataFrame is built; schema-driven column filtering
   removes non-input attributes; `_drop_broken_bus_refs` removes rows with invalid bus
   references; `_ensure_carriers` auto-adds missing carriers; `network.add(cls, names,
   **kwargs)` bulk-inserts.
5. **Attach time-series sheets.** Every model key containing `-` is parsed as
   `list_name-attr`. Each sheet is converted to a DataFrame aligned to
   `network.snapshots` (including period-broadcast for pathway mode) and stitched onto
   `network.<list_name>_t.<attr>`.
6. **Snapshot windowing.** `snapshotStart` / `snapshotCount` / `snapshotWeight` slice
   and downsample `network.snapshots`. For pathway mode the full snapshot set is kept.
   `snapshot_weightings` columns are set to `float(step)`.
7. **Period-factor scaling.** Annual energy caps (`*_sum_min`, `*_sum_max`) are scaled
   by `min(modelled_hours / 8760, 1.0)` so they are proportional to the modelled
   window.
8. **Carbon price.** `apply_carbon_price` adds `price × emission_factor` to each
   emitting generator's marginal cost in both static and `_t` frames. A varying
   schedule is always written to `_t`.
9. **CAPEX annuitisation.** For extendable components, `capital_cost` is multiplied by
   `annuity_factor(discount_rate, lifetime)` from `utils/annuity.py`. Lifetime
   defaults to 20 years when absent.
10. **Force-LP.** If `options["forceLp"]` is true, all `committable=True` flags on
    generators are set to `False`.
11. **Load shedding.** `add_load_shedding` adds a `Generator` named
    `load_shedding_{bus}` per bus when `enableLoadShedding` is true.
12. **Stochastic expansion.** `apply_scenarios` calls
    `network.set_scenarios(weights)` and applies per-scenario overrides to both static
    and dynamic frames.

### 7.6 Solve branch logic in `run_pypsa`

`run_pypsa(model, scenario, options)` in `backend/pypsa/results/__init__.py`
orchestrates the solve after `build_network` completes. This is the sole public entry
for result extraction.

**Mode selection and mutual-exclusion checks** happen first. The function raises
HTTP 400 if stochastic + rolling, or SCLOPF + rolling/stochastic/pathway are combined.

**`extra_functionality(n, snapshots)`** is a closure passed into every solve call. It
calls `apply_custom_constraints` to apply UI-authored point-and-click constraints, then
applies `constraintSpecs` via `apply_constraint_specs`, or falls back to
`apply_dsl_constraints` for raw DSL text when `constraintSpecs` is absent. All
constraint additions are made to `n.model` (the linopy model) before the solver runs.
The backend is plugin-agnostic: no plugin code executes at any solve stage.

**Solve branches:**

| Mode | PyPSA call |
|---|---|
| Rolling horizon | `network.optimize.optimize_with_rolling_horizon(horizon, overlap, multi_investment_periods, ...)` |
| Security-constrained (SCLOPF) | `network.optimize.optimize_security_constrained(...)` |
| Single-period or pathway | `network.optimize(multi_investment_periods=pathway.enabled, ...)` |

All three receive `solver_name="highs"`, a `solver_options` dict (threads,
simplex/IPM), and `extra_functionality`.

If the solver returns without raising but the solve condition is not `'optimal'`, the
backend raises HTTP 500 with a diagnostic message identifying common causes (placeholder
`1e12`/`inf` values, conflicting constraints).

### 7.7 Result extraction: `run_pypsa` to `RunResults`

After the solve, `run_pypsa` assembles the `RunResults` dict. The extraction runs
entirely in the backend worker process before the result is placed in the
multiprocessing queue.

| Output field | Source |
|---|---|
| `dispatchSeries`, `generatorDispatchSeries` | `build_dispatch_series` in `results/dispatch.py` |
| `systemPriceSeries`, `systemEmissionsSeries` | `build_price_emissions_series` in `dispatch.py` |
| `storageSeries` | `build_storage_series` in `dispatch.py` |
| `carrierMix` | `dispatch_by_carrier` groups `generators_t.p` by carrier; `weighted_sum` with `snapshot_weightings["generators"]` |
| `costBreakdown` | Fuel cost, carbon cost, load-shedding cost, expansion CAPEX per generator using `get_switchable_as_dense` for marginal cost |
| `nodalBalance` | Per-bus average load and generation |
| `lineLoading` | Peak `\|p0\| / s_nom * 100` for lines, links, transformers |
| `meritOrder` | `build_merit_order` in `results/market.py` |
| `co2Shadow` | `build_co2_shadow` in `market.py` |
| `emissionsBreakdown` | `build_emissions_breakdown` in `results/emissions.py` |
| `expansionResults` | `build_expansion_results` in `results/expansion.py` |
| `pathway.summaries` | `_pathway_period_summaries` in `results/summaries.py` |
| `outputs` | `build_full_outputs(network)` in `results/full_outputs.py` |

**`build_full_outputs`** is the schema-driven full extraction pass. It walks every
component in `load_pypsa_schema()`, splits output attributes into static vs series
categories, and emits:

- Static output attributes (e.g. `p_nom_opt`, `mu_upper`) into
  `static_out[list_name][component_name][attr]`.
- Time-series output attributes (e.g. `p`, `state_of_charge`, `marginal_price`) into
  `series_out["<list_name>-<attr>"]`, with one row per snapshot keyed by component
  name.

The shape mirrors the input model format so the same workbook parser handles project
export/import round-trips.

**`summary`** is a six-item list of human-readable KPIs: installed capacity, peak
demand, reserve position, peak price, system emissions, transmission stress.

**`runMeta`** carries `snapshotCount`, `snapshotWeight`, `modeledHours`,
`planningMode`, `investmentPeriods`, and embedded rolling/pathway descriptors.

### 7.8 Rendering results in the frontend

**`displayResults` memo** in `App.tsx` is the single transformation point from raw
`results` to display-ready data.

- For non-pathway results: `withDerivedAssetDetails(analyticsModel, results,
  currencySymbol)` walks `results.outputs` to build `assetDetails.generators`,
  `assetDetails.storageUnits`, `assetDetails.buses`, `assetDetails.branches`, and
  `assetDetails.stores` records with per-asset output series attached.
- For pathway results: `deriveRunResults(analyticsModel, results.outputs,
  derivationContext)` re-derives carrier mix, cost breakdown, dispatch series, nodal
  balance, and all other KPIs from `outputs.static` and `outputs.series` for the
  selected pathway period, applying the frozen `carbonPrice`, `snapshotWeight`, and
  `discountRate` values.

**`analyticsModel`** is `resultsModel ?? model`. When `resultsModel` is set (after a
run or after restoring a history entry), analytics use the frozen topology snapshot
rather than the live editable model.

### 7.9 Run history

At the end of `applyResult`, a `RunHistoryEntry` is prepended to `runHistory` state.
The entry stores the full raw `RunResults`, a deep clone of the submitted model, and
frozen derivation context values. Pinned entries are retained indefinitely. Unpinned
entries are trimmed to `MAX_UNPINNED_HISTORY`. Run history is session-scoped in-memory
React state — it is never written to disk and does not survive a page reload.

`handleRestoreRun(entry)` restores both results and model state, pushes the current
live model onto the undo stack, and pins analytics to the stored topology. It does not
switch tabs.

### 7.10 Export and import pipelines

All exports that produce a file use `saveFileWithPicker` in `App.tsx`, which opens
`showSaveFilePicker` (Chromium) or falls back to a programmatic `<a>` download.

**Export Project (inputs + outputs as one xlsx)**

`buildProjectWorkbook` writes every static component sheet merged with solved output
columns, all input and output time-series sheets, embedded config sheets
(`RAGNAROK_PathwayConfig`, `RAGNAROK_RollingConfig`, `RAGNAROK_Scenarios`), and
private metadata sheets (`RAGNAROK_ResultMeta`, `RAGNAROK_Settings`,
`RAGNAROK_Constraints`, `RAGNAROK_RunState`, `RAGNAROK_Provenance`). The file is an
ordinary `.xlsx` that PyPSA can import natively.

**Export Result Workbook**

`buildFullResultsWorkbook` starts from all input sheets and appends `OUT_*` sheets for
every result category: `OUT_Summary`, `OUT_Dispatch`, `OUT_GenDispatch`,
`OUT_SysPrice`, `OUT_Emissions`, `OUT_Storage`, `OUT_CarrierMix`, `OUT_CostBreakdown`,
`OUT_NodalBalance`, `OUT_LineLoading`, `OUT_GenDetail`, `OUT_StorageDetail`,
`OUT_BranchFlow`, and conditionally `OUT_MeritOrder`, `OUT_Expansion`,
`OUT_EmissionsByGen`, `OUT_EmissionsByCarrier`, `OUT_CO2Shadow`.

**Export / Import CSV Folder**

Each sheet is written as a separate CSV into a zip archive via `exportModelAsCsvFolderZip`
in `src/shared/utils/csvFolder.ts`.

**Export / Import netCDF and HDF5**

Both formats require a backend round-trip because the browser has no native parser.

- Export: the frontend POSTs the current model to `POST /api/export/netcdf` or
  `/api/export/hdf5`. The backend calls `build_network` (no solve), then
  `network.export_to_netcdf` or `network.export_to_hdf5`, and returns the bytes.
- Import: the frontend uploads the file to `POST /api/import/netcdf` or
  `/api/import/hdf5`. The backend reads it via `pypsa.Network().import_from_netcdf`
  or `import_from_hdf5`, then serialises the network back into the `{sheet: rows[]}`
  format via `_network_to_model_json`.

### 7.11 Pathway (multi-year) planning

Pathway mode enables multi-investment-period capacity planning across several years.
`parse_pathway_config` builds a `PathwayConfig` from `options.pathwayConfig`. The
snapshot index becomes a `pd.MultiIndex(["period", "timestep"])` when
`snapshot_mapping_mode == "explicit_period_column"`. `network.set_investment_periods`
and `investment_period_weightings` are populated from the pathway period objects.
`network.optimize(multi_investment_periods=True)` lets PyPSA handle investment-period
coupling natively. `_pathway_period_summaries` groups the snapshot MultiIndex by
`period` and computes per-period total dispatch, emissions, average price, peak load,
and objective weight. The frontend's `deriveRunResults` re-derives all KPIs for the
selected period from `outputs.static` and `outputs.series`.

### 7.12 Rolling horizon

`parse_rolling_config` builds a `RollingConfig` from `options.rollingConfig`.
`_rolling_window_summaries` pre-computes window metadata before the solve so the
result payload carries it even if the solve raises. The solve is
`network.optimize.optimize_with_rolling_horizon(horizon, overlap,
multi_investment_periods, ...)`. Rolling horizon and stochastic mode cannot be combined.
Rolling horizon and SCLOPF cannot be combined.

### 7.13 Stochastic mode

`parse_stochastic_config` builds a `StochasticConfig` from `options.stochasticConfig`.
`apply_scenarios` calls `network.set_scenarios(weights)` to expand all frames to a
`(scenario, name)` MultiIndex, then applies per-scenario `ScenarioOverride` objects.
After the solve, `per_scenario_summaries` computes per-scenario energy/emissions/cost
totals. `collapse_to_representative_scenario` then slices all static and dynamic frames
to the highest-weight scenario, restoring the deterministic shape that all downstream
extraction code expects.

### 7.14 Security-constrained (SCLOPF)

When `securityConstrainedConfig.enabled` is true, the solve is
`network.optimize.optimize_security_constrained(...)`. PyPSA enforces N-1 security by
adding line-loading constraints for each passive branch. SCLOPF cannot be combined with
rolling horizon, stochastic mode, or pathway mode.

---

## 8. Constraints

Ragnarok has three distinct constraint mechanisms, all of which converge at
`extra_functionality` inside `run_pypsa`. The backend is unaware of which mechanism
produced any given constraint.

### Standard constraints (`global_constraints` sheet)

Native PyPSA `GlobalConstraint` rows live in the `global_constraints` workbook sheet.
They are imported by `build_network()` directly into `network.global_constraints` and
applied by PyPSA's own optimizer without any special backend logic.

### Advanced constraints (custom DSL to `constraintSpecs`)

The Constraints workspace tab exposes a text-based DSL. Before submission, the frontend
compiles the DSL text into a `constraintSpecs` JSON array via `dslToSpecs()` in
`src/shared/utils/constraintDsl.ts`. The `constraintSpecs` array is sent inside
`scenario.constraintSpecs` in the `RunPayload`. The backend applies them via
`apply_constraint_specs()` in `backend/pypsa/network/constraint_dsl.py` inside
`extra_functionality`. Older payloads that still contain raw DSL text in
`scenario.customDsl` are accepted as a fallback; the backend prefers `constraintSpecs`
when both are present.

### Plugin-contributed constraints

A plugin's `contribute` hook may return a `constraints` array of DSL strings alongside
optional sheet rows. `PluginDetail` appends those strings to the live `customDsl` state
(prefixed with a `# plugin-name` comment), or the plugin may produce a
`RAGNAROK_CustomDSL` sheet via `contribute`; the frontend merges that sheet into
`customDsl` in the same way. Either path passes through the same `dslToSpecs()`
compilation step and arrives at the backend as part of `constraintSpecs`,
indistinguishable from constraints the user typed directly. There is no separate plugin
execution stage on the backend.

---

## 9. Plugin runtime

Plugins are a frontend-only concern. The Ragnarok backend is plugin-agnostic: it never
loads, executes, or is aware of any plugin code. For full authoring detail see
[`docs/guides/PLUGIN_AUTHORING.md`](plugin.md).

A plugin is a `.zip` package containing at minimum a `module.json` manifest. The
package is installed into browser `localStorage` by `useFrontendPlugins()` in
`src/features/plugins/frontendPlugins.ts` — no backend call is made. There is no
enable/disable toggle; a plugin is either installed or not.

**JS hook contracts** (all run in the browser, called from `PluginDetail.tsx`):

| Hook | When called | Effect |
|---|---|---|
| `transform(model, config)` | "Apply to model" button | Replaces the entire `WorkbookModel` in React state |
| `contribute(model, config)` | "Apply to model" button | Merges sheets and appends DSL constraint lines |
| `analyze(result, config)` | After each successful solve | Returns display data rendered in the plugin's Output tab |
| Named hooks (e.g. `connect`) | Action-type field button | Returns `{ ok, message }`; used for server health checks |

`transform` and `contribute` are mutually exclusive per plugin. `analyze` runs
automatically when `results` changes. Plugin actions mutate React model state directly
in the browser before any run is submitted. The `RunPayload` sent to `POST /api/run`
contains only the resulting `{model, scenario, options}` — the backend never sees
plugin identity.

**Optional local plugin server.** A plugin may declare a `server` block in its
`module.json` (`run`, optional `cwd`, `port`, `health` fields). To auto-start the
server, the user adds a line to the Ragnarok project's `plugins.env` file at the
project root (next to `run.command`) in the form:

```
<absolute path to server dir>|<run command>
```

`run.command` reads `plugins.env` at startup and starts each listed server in a
subshell, activating the server directory's `.venv` if present. The plugin's frontend
code then contacts the server directly over localhost. The Ragnarok backend is not
involved.

`PluginDetail` renders a "Server setup" advisory when the manifest declares a `server`
block, showing the exact `plugins.env` entry the user needs to add.

**What is not in v1:**

- Remote registry, signed modules, or sandboxed worker-process isolation
- Backend plugin loading, Python plugin hooks, or plugin-side PyPSA access via the
  Ragnarok backend
- `activate()` / `deactivate()` lifecycle hooks

---

## 10. UI design philosophy

The aesthetic is simple and monochromatic: an engineering tool, not a consumer app.
Flat surfaces, square corners, a monospace voice for anything that reads like data, one
accent colour, and no decoration that does not carry information. When in doubt, remove
it.

The single source of truth for visual decisions is the design-token block at the top of
`src/index.css` (`:root`). Component CSS reads from those variables; nothing else
should hardcode a colour, radius, or font stack.

**Corners are square. Only buttons are rounded.**

- Boxes are square: cards, panels, inputs, selects, textareas, modals, table wrappers,
  the map frame, badges, chips — every rectangular container has `border-radius: 0`.
- Buttons are the sole exception, using `var(--radius-button)` (4 px).
- Circles (`50%`) and pills (`999px`) are intentional geometry, not rounded boxes.

**One accent colour: teal.**

```
--brand         #0f766e   active / focus / primary CTA
--brand-strong  #0b5d56   pressed / emphasis
--brand-soft    #f0fdfa   tint backgrounds
```

There is no blue. Semantic colours are reserved for meaning: `--danger #dc2626`
(errors), `--warn #f59e0b` (warnings). Status text is neutral by default, coloured
only when the colour is the signal.

**Typography: sans for prose, mono for data.**

```
--font-sans   IBM Plex Sans     body, labels, descriptions, headings
--font-mono   JetBrains Mono    numbers, IDs, counts, filenames, chips, code-like values
```

Use mono wherever the content is a value read precisely (MW/kV figures, snapshot
timestamps, component names in chips). Base size is 13 px. Sizes are drawn from a
fixed rem scale; do not introduce new sizes.

**Spacing** uses the rung: 4 / 6 / 8 / 12 / 14 / 18 / 24 px.

**Tables are sized to content.** Data-grid columns are measured from the header and a
sample of cell values, clamped by `COL_MIN_WIDTH` and `COL_MAX_WIDTH` in
`src/features/input/grid/DataGrid.tsx`. Fixed uniform widths are avoided.

**CSS hygiene.** `src/index.css` has one canonical rule per selector. Appending a
second top-level block for the same selector is the main source of "I changed it and
nothing happened" bugs. New visual constants go in the `:root` token block.

---

## 11. Current scope and limitations

For the authoritative, code-checked list see [CAPABILITIES.md](user-manual.md). The
headline limitations are:

- **Optimization only.** Every run goes through `network.optimize()`. PyPSA's `pf()` /
  `lpf()` power-flow modes are roadmapped, not implemented.
- **Multiple study modes are supported.** Beyond single-period, the backend runs
  multi-period pathway, rolling-horizon, two-stage stochastic, and
  security-constrained (SCLOPF / N-1) solves.
- **Copper-plate by default.** If no lines/links are defined, all buses are effectively
  connected without congestion. DC-OPF spatial routing requires impedances and `s_nom`
  limits in the workbook.
- **No ETS / carbon market.** Carbon price is a flat $/tCO2 adder to generator
  marginal costs; there is no ETS permit price curve or intertemporal banking.
- **HiGHS only.** The solver is fixed to HiGHS via PyPSA's default linopt interface.
  GLPK and Gurobi are not exposed in the UI.
- **Backend assumed local by default.** The app defaults to `http://127.0.0.1:8000`.
  Moving the backend server-side is architecturally safe (the frontend/backend
  separation is already clean) but no authentication layer exists yet.
- **Session-scoped run history.** Past runs can be viewed, compared, pinned, renamed,
  restored, and exported, but the list lives only for the browser session.

---

## 12. Server-side deployment & frontend/backend separation

Ragnarok is built so the **backend is the single source of truth** and the
frontend is a thin terminal — the shape a server-side (and eventually iPad)
deployment needs.

**What lives where**

- **Backend owns the model.** The working model is a server-side *session*
  (`backend/app/session_store.py`): static sheets as JSON, time-series as
  Parquet, under `backend/data/session/<session_id>/`. The frontend imports a
  model once (`POST /api/session/model`) and thereafter fetches only what's on
  screen — a page of rows (`GET …/sheet/{name}`) or a windowed, downsampled
  series slice (`GET …/series/{name}`). Edits go back as patches
  (`PATCH …/sheet/{name}`). The heavy model never lives in browser memory.
- **Runs submit by `sessionId`.** `POST /api/queue` takes `{sessionId, scenario,
  options}`; the backend snapshots the session model into the queued item. The
  giant model payload never travels from the browser.
- **Results are split.** `GET /api/runs/{name}/analytics` returns a light bundle
  (KPIs, carrier-level series, topology) for an instant View; per-component
  series are served windowed on demand from `…/series/{sheet}`. The lossless
  bundle stays on disk as the export source.
- **Compute is server-side.** The solve runs in a backend worker process; backend
  plugins (below) also run in-process.

**Two plugin kinds, one hook contract** (see `docs/plugin.md`). Ragnarok ships
**no plugins** — they are purely 3rd-party (examples in `example_plugins/`). Both
kinds expose `transform(model,config)→model`, `contribute(model,config)→{sheets,
constraints}`, and/or `analyze(result,config)→data`.

- *Frontend plugin* — browser JS (`.zip` of module.json + index.js, kept in
  localStorage); may run its **own** local server registered in `plugins.env`.
- *Backend plugin* — `.zip` of manifest.json + plugin.py, **installed by upload**
  into the gitignored `backend/data/plugins/`; runs in the backend and imports the
  bundled PyPSA source directly; **nothing in `plugins.env`**. `transform`/
  `contribute` write straight into the session. Endpoints: `GET /api/plugins`,
  `POST /api/plugins/install`, `DELETE /api/plugins/{id}`,
  `POST /api/plugins/{id}/transform|contribute|analyze`. (Install runs uploaded
  Python — RCE by design; gate behind auth for multi-user.)

**Already remote-ready**

- `session_id` is a first-class parameter everywhere (default `"default"`), so
  multi-session is a config flip, not a rewrite.
- CORS is open (`allow_origins=["*"]`); `API_BASE` is env-configurable; no
  hardcoded `127.0.0.1` in the data-path code.

**Remaining for a hardened multi-user server** (not yet built)

- **Auth** — there is no authentication/authorization layer.
- **Per-user sessions** — a single `"default"` session is assumed; concurrent
  users would need session isolation and a shared store (Redis/DB/object
  storage) instead of the warm single-process cache.
- **`run.command` launches local processes** — fine for a workstation; a server
  deployment runs the backend (and any backend plugins) as a managed service.
- **A few result objects** (e.g. `assetDetails`) are still derived in the
  browser from raw outputs; the per-component series fetch is on-demand.
