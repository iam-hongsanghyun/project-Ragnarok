# Ragnarok — Architecture Reference

> **Purpose:** This document is the single-file orientation guide for new contributors and AI
> sessions. Read it first. You should not need to grep across 60+ files to understand the
> codebase — everything essential is here. (~5-minute read)

### Documentation map

| Document | Read it for |
|---|---|
| **architecture/ARCHITECTURE.md** (this file) | System overview, tech stack, repo layout, data flow |
| [architecture/PROCESSES.md](./PROCESSES.md) | Step-by-step logic of each process (open, run, build, solve, extract, export) |
| [architecture/DESIGN.md](./DESIGN.md) | UI design philosophy |
| [CAPABILITIES.md](../CAPABILITIES.md) | What Ragnarok can and cannot do (code-checked) |
| [SUPPORT_MATRIX.md](../SUPPORT_MATRIX.md) | Generated feature support matrix |
| [guides/USER_MANUAL.md](../guides/USER_MANUAL.md) | End-user manual for analysts (open/edit/run/analyse/export) |
| [guides/PLUGIN_AUTHORING.md](../guides/PLUGIN_AUTHORING.md) | Plugin system + how to write plugins |
| [reference/](../reference/) | Per-module function reference (backend + frontend) |
| [TODO.md](../TODO.md) | Living project task log and roadmap |

---

## What this app does

Ragnarok is a browser-based GUI for building and running single-year PyPSA power-system models.
The user opens or edits an Excel workbook (one sheet per PyPSA component), configures run
parameters in a modal dialog, and the React frontend posts the workbook data to a local FastAPI
backend that constructs a `pypsa.Network`, solves it with HiGHS, and returns structured results.
Charts, maps, and tables then display the outputs without any round-trips to a remote server.

## Communication topology

Understanding which components talk to which is the single most important orientation fact
for plugin authors and contributors.

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

**The rule is absolute:**

| Link | Allowed |
|---|---|
| Plugin JS <-> Ragnarok frontend | Yes — plugins run in the browser and can call frontend APIs |
| Ragnarok frontend <-> Ragnarok backend | Yes — the only path to the solver |
| Plugin <-> Ragnarok backend | No — the Ragnarok backend is plugin-agnostic and exposes no plugin endpoints |

The Ragnarok backend receives `{model, scenario, options}` and solves. It never discovers,
loads, or executes plugin code of any kind. There is no `module_host.py`, no
`execute_plugins_at_stage()`, and no `/api/modules` route. Plugins that need server-side
computation run their own separate local server and communicate with it directly from the
browser.

The backend is currently assumed to run locally at `http://127.0.0.1:8000`. The
architecture is being moved toward a remote server model; the communication rule above
is what makes that safe — the frontend is the only client of the Ragnarok backend, so
moving the backend server-side requires no plugin changes.

---

## Extension system (plugins)

Ragnarok ships a frontend-only plugin system. The full authoring guide is in
[guides/PLUGIN_AUTHORING.md](../guides/PLUGIN_AUTHORING.md).

### Plugin runtime

Plugins are a **frontend-only** concern.

**`src/features/plugins/frontendPlugins.ts` — `useFrontendPlugins()`**

Custom hook that owns all plugin state in the browser:
- `installed` — list of `InstalledPlugin` objects, persisted to `localStorage`
  under `ragnarok:fe-plugins:installed`
- `configs` — per-plugin config values, persisted to `localStorage` under
  `ragnarok:fe-plugins:configs`
- `install(file)` — unpacks the `.zip` in-browser via `fflate`, validates
  `module.json`, and persists; no backend call is made
- `uninstall(id)` — removes the plugin from `localStorage`; no backend call is made

There is no "enable/disable" toggle. Installed plugins are always active in the
Plugins tab.

**Package format**

A plugin is a `.zip` containing at minimum a `module.json` manifest. The manifest
may sit at the archive root or one directory deep. Text files (JS entry, templates)
are retained in-memory as plain strings keyed by relative path.

**JS hooks**

A plugin's JS entry file may export any combination of:

| Export | When called | What it does |
|---|---|---|
| `transform(model, config)` | "Apply to model" | Replaces the entire `WorkbookModel` |
| `contribute(model, config)` | "Apply to model" | Merges sheets and appends constraint DSL lines |
| `analyze(results, config)` | Auto-run after each solve | Reads `RunResults` and returns display data |
| Named hook (e.g. `connect`) | Action button in the config UI | Any named export invocable via an `action`-type config field |

`transform` and `contribute` are mutually exclusive per plugin. `analyze` runs
automatically when `results` changes. Named action hooks are invoked by `handleAction`
in `PluginDetail` and receive the merged config (schema defaults + stored values).

**`src/features/plugins/PluginDetail.tsx`**

Renders one installed plugin's detail pane. When the manifest declares a config
schema (field descriptors with a `type`), it delegates to `PluginPanel` for the
V1-style Description / Input / Output subtab layout, section grids, and every
field type. A schema-less manifest falls back to a raw JSON config textarea.

Config field types rendered by `PluginPanel`:

| `type` in `module.json` | Rendered as |
|---|---|
| `boolean` | checkbox |
| `number` (no range) | number input |
| `number` (with `min`/`max`) | range slider + live value label |
| `select` | `<select>` dropdown |
| `carrier-select` | multi-checkbox list populated from workbook carriers |
| `group` | visual section separator |
| `action` | button that fires a named hook |

**`src/features/plugins/PluginPanel.tsx`**

Full-page workspace tab (labelled **Plugins**) shown when at least one plugin is installed.
Renders:
- a tab bar with one tab per installed plugin
- nested **Description / Input / Output** subtabs
- layout-aware section grids driven by `module.json` panel metadata
- analytics output tables formatted via `ui` hints from `module.json`

**Wiring in `App.tsx`**

`useFrontendPlugins()` is called at the `AppInner` root. The resulting `frontendPlugins`
handle is threaded down to `PluginsView`. Plugin actions (`transform`, `contribute`) mutate
React model state directly in the browser before any run is submitted. The Ragnarok backend
never sees plugin identity — the `RunPayload` sent to `POST /api/run` contains only the
resulting `{model, scenario, options}`.

### Plugin local server (optional)

A plugin that needs server-side computation (for example, a PyPSA-based data builder)
may declare a `server` block in its `module.json`:

```json
{
  "server": {
    "run": "python server.py --port 8765",
    "cwd": "backend",
    "port": 8765,
    "health": "/health"
  }
}
```

**Registration via `plugins.env` and `run.command`**

The Ragnarok project's `run.command` reads `plugins.env` (project root, next to
`run.command`) at startup and launches each registered server whose directory exists.
The format is one `<absolute server dir>|<run command>` line per plugin. Blank lines
and lines starting with `#` are ignored.

```
# Example: Dashboard Importer plugin backend
/Users/you/my-plugin/backend|python server.py --port 8765
```

If the server directory contains a `.venv`, `run.command` activates it automatically
so the plugin's own Python dependencies take precedence. An explicit interpreter in the
command (e.g. `.venv/bin/python ...`) always takes precedence over the ambient PATH.

The browser plugin connects to this local server directly (via `fetch` to `localhost:<port>`).
The Ragnarok backend is not involved.

`PluginDetail` renders a **Server setup** advisory when the manifest declares a `server`
block, showing the exact `plugins.env` entry the user needs to add (with a placeholder
for the absolute path, since the browser cannot discover the filesystem location) and
the three-step registration flow.

### What is NOT in v1

- Remote registry, signed modules, or sandboxed worker-process isolation
- Backend plugin loading, Python plugin hooks, or plugin-side PyPSA access via the
  Ragnarok backend (plugins that need PyPSA run their own separate local server)
- `activate()` / `deactivate()` lifecycle hooks — plugins are stateless JS modules

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Create React App (react-scripts 5) |
| Mapping | react-leaflet / Leaflet |
| Charting | Recharts |
| Workbook I/O | SheetJS (xlsx) |
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Power model | PyPSA |
| Solver | HiGHS (via PyPSA default) |
| Transport | REST JSON over `http://127.0.0.1:8000` |

---

## Repository layout

The repository is a pluggable **frontend** + pluggable **backend**. The backend
is further split into an engine-agnostic **host** (`backend/app/`) and the
reference **engine** (`backend/pypsa/`); a second engine would be a sibling
package under `backend/`. The frontend lives in its own npm package
(`frontend/Ragnarok_default/`); a second frontend would be a sibling under
`frontend/`. The tree below is representative, not exhaustive.

```
pypsa_gui/
├── backend/
│   ├── app/                        ← engine-agnostic FastAPI host (no PyPSA imports)
│   │   ├── main.py                 ← FastAPI app, run lifecycle, file-converter endpoints
│   │   ├── models.py               ← RunPayload request/response models
│   │   ├── config.py               ← loads backend/config/*.json (system defaults)
│   │   └── backends/               ← pluggable-backend seam
│   │       ├── base.py             ← Backend protocol + BackendError
│   │       └── registry.py         ← get_backend / available_backends / register_backend
│   ├── pypsa/                      ← PyPSA reference engine (the only backend today)
│   │   ├── adapter.py              ← PypsaBackend — implements the Backend protocol
│   │   ├── network/                ← build_network() — assembles pypsa.Network from the model
│   │   │   ├── __init__.py         ← public entry: build_network(), validate_model()
│   │   │   ├── components.py       ← generic schema-driven component import loop
│   │   │   ├── network_sheet.py    ← `network` sheet runtime-import allow-list
│   │   │   ├── snapshots.py        ← snapshot index (flat / pathway MultiIndex)
│   │   │   ├── custom_constraints.py ← carrier-share / CO2-cap constraints
│   │   │   ├── load_shedding.py    ← optional load-shedding backstop generator
│   │   │   └── validators.py       ← structural pre-solve validation checks
│   │   ├── results/                ← extract results from the solved network
│   │   │   ├── __init__.py         ← public entry: run_pypsa() → RunResults dict
│   │   │   ├── full_outputs.py     ← schema-driven solved-output cache
│   │   │   ├── dispatch.py         ← carrier- and generator-level dispatch series
│   │   │   ├── emissions.py        ← system + per-generator CO2 series
│   │   │   ├── expansion.py        ← capacity expansion delta (p_nom_opt − p_nom)
│   │   │   ├── market.py           ← merit order, CO2 shadow price
│   │   │   └── summaries.py        ← per-scenario / KPI summaries
│   │   ├── pathway.py              ← multi-period pathway planning helpers
│   │   ├── rolling.py              ← rolling-horizon helpers
│   │   ├── stochastic.py          ← two-stage stochastic scenario helpers
│   │   ├── carbon_price.py        ← carbon-price schedule parsing/application
│   │   ├── pypsa_schema.py        ← PyPSA-facing schema helpers (input/output attributes)
│   │   ├── constants.py           ← carrier → colour map shared by builder + extractors
│   │   └── utils/
│   │       ├── coerce.py          ← number(), text(), bool_value() — safe type coercion
│   │       ├── workbook.py        ← workbook_rows(), apply_scaled_static_attributes()
│   │       ├── series.py          ← weighted_sum() and pandas series helpers
│   │       └── annuity.py         ← capital-recovery factor for expansion cost annualisation
│   ├── config/                     ← JSON config consumed by backend/app/config.py
│   └── tests/                      ← pytest suite (run with .venv-pypsa)
│
└── frontend/
    └── Ragnarok_default/           ← default React/TypeScript UI (its own npm package)
        ├── package.json            ← npm project root (proxy → 127.0.0.1:8000)
        ├── public/                 ← CRA static root (index.html)
        ├── scripts/                ← build-time codegen (*.mjs) for src/config JSON + docs
        └── src/
            ├── App.tsx             ← Root component: state, event handlers, run flow
            ├── index.tsx           ← ReactDOM entry point
            ├── index.css           ← All CSS (scoped by component prefix, see Conventions)
            ├── config/             ← generated JSON (pypsa_schema.json, capabilities.json…)
            ├── constants/          ← schema adapters + shared constants
            ├── layout/             ← ActivityBar, Sidebar, and chrome
            ├── views/              ← top-level tab views (Model, Analytics, Settings, Plugins)
            ├── features/           ← feature folders: build, input, map, analytics,
            │                          constraints, validation, run, run-history,
            │                          plugins, settings
            └── shared/             ← cross-feature types, utils, and components
```

---

## Data flow

```
1. OPEN
   User opens .xlsx → parseWorkbook() (SheetJS)
   → WorkbookModel { network, buses, generators, ... }   (all in React state)

2. EDIT
   TablesPane → updateRowValue / addRow / deleteRow / addColumn
   → mutates WorkbookModel in state (no backend call)

3. RUN
   ▶ Run button → RunDialog (modal)
   → user picks snapshotStart/End, snapshotWeight, carbonPrice, dryRun

   POST /api/run (or /api/validate for dry-run)
   Body: RunPayload {
     model: WorkbookModel,     ← entire sheet data as JSON
     scenario: { constraints, carbonPrice },
     options: { snapshotCount, snapshotStart, snapshotWeight }
   }

4. BACKEND
   build_network(payload)
     → attach buses, loads, generators, lines, links, transformers,
       storage_units, stores, global_constraints
     → attach time-series profiles (p_max_pu, p_min_pu, loads-p_set, inflow)
     → slice & weight snapshots

   network.optimize()     ← HiGHS via PyPSA linopt

   run_pypsa(payload)
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

## RunPayload schema

Sent as JSON to `POST /api/run` and `POST /api/validate`.

```json
{
  "model": {
    "network":           [{ "name": "my_network", ... }],
    "snapshots":         [{ "name": "2019-01-01 00:00", ... }],
    "carriers":          [{ "name": "solar", "co2_emissions": 0, ... }],
    "buses":             [{ "name": "Bus1", "x": 127.0, "y": 37.5, ... }],
    "generators":        [{ "name": "Solar1", "bus": "Bus1", "carrier": "solar", ... }],
    "loads":             [{ "name": "Load1", "bus": "Bus1", "p_set": 100, ... }],
    "lines":             [...],
    "links":             [...],
    "stores":            [...],
    "storage_units":     [...],
    "transformers":      [...],
    "shunt_impedances":  [...],
    "global_constraints":[...],
    "shapes":            [...],
    "processes":         [...],
    "generators-p_max_pu":  [{ "name": "2019-01-01 00:00", "Solar1": 0.85, ... }],
    "generators-p_min_pu":  [...],
    "loads-p_set":           [...],
    "storage_units-inflow":  [...],
    "links-p_max_pu":        [...]
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

Time-series sheets (`generators-p_max_pu` etc.) use the **first column as the snapshot label**
(`name` key) and subsequent columns keyed by component name.

---

## WorkbookModel sheet index

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

---

## Constraints

Ragnarok has three distinct constraint mechanisms. They are independent at authoring time
but all converge at `extra_functionality` inside `run_pypsa()`.

### Standard constraints (global_constraints sheet)

Native PyPSA `GlobalConstraint` rows live in the `global_constraints` workbook sheet.
They are imported by `build_network()` directly into `network.global_constraints` and
are applied by PyPSA's own optimizer without any special backend logic.

### Advanced constraints (custom DSL → constraintSpecs)

The Constraints workspace tab exposes a text-based DSL. Before submission, the frontend
compiles the DSL text into a `constraintSpecs` JSON array via `dslToSpecs()` in
`src/shared/utils/constraintDsl.ts`. The `constraintSpecs` array is sent inside
`scenario.constraintSpecs` in the `RunPayload`. The backend applies them via
`apply_constraint_specs()` in `backend/pypsa/network/constraint_dsl.py` inside
`extra_functionality`.

Older payloads that still contain raw DSL text in `scenario.customDsl` are accepted as a
fallback; the backend prefers `constraintSpecs` when both are present.

### Plugin-contributed constraints

A plugin's `contribute` hook may return a `constraints` array of DSL strings alongside
optional sheet rows. `PluginDetail` appends those strings to the live `customDsl` state in
the browser (prefixed with a `# plugin-name` comment). They pass through the same
`dslToSpecs()` compilation step and arrive at the backend as part of `constraintSpecs`,
indistinguishable from constraints the user typed directly.

A plugin may alternatively produce a `RAGNAROK_CustomDSL` sheet in the workbook via its
`contribute` hook; the frontend reads that sheet and merges it into `customDsl` in the
same way.

In all three cases the solver sees the constraints through a single `extra_functionality`
call — there is no separate plugin execution stage on the backend.

---

## Key conventions

### Frontend

**CSS class prefixes** (each component owns its prefix — avoids global collisions):

| Prefix | Component / scope |
|---|---|
| `topbar-` | Top navigation bar |
| `tab-` | Workspace tab buttons |
| `app-sidebar` | Sidebar shell (aside element) |
| `sg-` | `SidebarGroup` |
| `modal-` | `RunDialog` (backdrop + card) |
| `run-` | Run button and run-dialog controls |
| `chart-` | Chart cards |
| `kpi-` | `SummaryCards` |
| `dual-range-` | `DualRangeSlider` |
| `analytics-` | `AnalyticsPane` |
| `pane` | Workspace pane shells |
| `tb-btn` | Toolbar / compact buttons |

State modifiers use BEM `--` suffix: `tb-btn--muted`, `app-sidebar--collapsed`,
`analytics-subtab--active`, `tab-button--error`, `sc-status--done`.

**Coerce helpers** (always use these, never raw casts):
- `numberValue(v)` — in `helpers.ts`; returns 0 for null/NaN/undefined
- `stringValue(v)` — in `helpers.ts`; returns `''` for null/undefined
- `carrierColor(carrier)` — deterministic carrier → hex colour

**Prop patterns:**
- Callback props are named `on<Action>` (e.g. `onRun`, `onClose`, `onChange`).
- State setter props lift plain setters directly: `onSnapshotStartChange={setSnapshotStart}`.
- Heavy derived data (`metricOptions`, `dispatchRows`) is computed in `App.tsx` via
  `useMemo` and passed down as props — components are pure-render, no internal data fetching.

### Backend

**Workbook access pattern** (use these in every module, never `model["sheet"]` directly):
```python
from ..utils.workbook import workbook_rows
from ..utils.coerce import number, text, bool_value

rows = workbook_rows(model, "generators")   # → list[dict]
for row in rows:
    name = text(row.get("name"))
    p_nom = number(row.get("p_nom"), default=0.0)
```

**`network/__init__.py` is the only public entry** — callers import `build_network` and
`validate_model`; internal sub-modules are not imported directly from outside `network/`.

**`results/__init__.py` is the only public entry** — callers import `run_pypsa`.

---

## Where to add…

### A new predefined result chart

1. Create `src/components/charts/MyNewCard.tsx`.
2. Add it to `ResultsDashboard.tsx` in the appropriate section.
3. If it needs a new data series, add it to `RunResults` in `src/types/index.ts` and extract
   it in the relevant `backend/pypsa/results/*.py` module.

### A new constraint metric (Standard Constraints)

These are the point-and-click constraints in the Constraints tab that compile to the
`scenario.constraints` array (not the DSL).

1. Add the new `ConstraintMetric` string literal to `src/types/index.ts`.
2. Add the UI row to `GlobalConstraintsSection.tsx`.
3. Handle the new metric in `backend/pypsa/network/custom_constraints.py` inside
   `apply_custom_constraints()`.

### A new backend result field

1. Add the field to the `RunResults` interface in `src/types/index.ts`.
2. Compute and return the field from `run_pypsa()` in `backend/pypsa/results/__init__.py`
   (or delegate to a new file in `results/`).
3. Consume the field in a chart card or the `ResultsDashboard`.

### A new workbook sheet

1. Add the sheet name to `SHEETS` (static) or `TS_SHEETS` (time-series) in
   `src/constants/sheets.ts`.
2. Add the corresponding key to the `WorkbookModel` interface in `src/types/index.ts`.
3. Add default rows to `DEFAULT_SHEET_ROWS` in `src/constants/index.ts`.
4. Add column definitions to `src/constants/pypsa_attributes.ts`.
5. Add a backend parser in the appropriate `backend/pypsa/network/*.py` file and call it from
   `build_network()`.

### A new analytics focus type

1. Add the new union member to `AnalyticsFocus` in `src/types/index.ts`.
2. Add asset detail types (if needed) to `RunResults.assetDetails`.
3. Add the metric options branch to the `metricOptions` useMemo in `App.tsx`.
4. Add the asset detail extractor in `backend/pypsa/results/assets/`.

---

## Current scope / limitations

For the authoritative, code-checked list of what the product can and cannot do, see
[CAPABILITIES.md](../CAPABILITIES.md). The headline limitations:

- **Optimization only — no standalone power-flow study.** Every run goes through
  `network.optimize()`. PyPSA's `pf()` / `lpf()` power-flow modes are roadmapped, not
  implemented (`studyModes: ["optimize"]` in `backend/pypsa/adapter.py`).
- **Multiple study modes ARE supported.** Beyond single-period, the backend runs multi-period
  **pathway** (investment planning), **rolling-horizon**, two-stage **stochastic**, and
  **security-constrained** (SCLOPF / N-1) solves. See `backend/pypsa/results/__init__.py`.
- **Copper-plate** by default — if no lines/links are defined, all buses are effectively
  connected without congestion. Line flows are extracted if branches exist, but no DC-OPF
  spatial routing is done unless the workbook provides impedances and `s_nom` limits.
- **No ETS / carbon market** — carbon price is a flat $/tCO₂ adder to generator marginal
  costs; there is no ETS permit price curve or intertemporal banking.
- **HiGHS only** — solver is fixed to HiGHS via PyPSA's default linopt interface. GLPK/Gurobi
  are not exposed in the UI.
- **Backend assumed local by default** — the app currently defaults to `http://127.0.0.1:8000`.
  The backend is being moved to a remote server model; the frontend/backend separation is already
  clean enough to support this, but no authentication layer exists yet.
- **Session-scoped run history, not a persisted scenario manager** — past runs can be viewed,
  compared, pinned, renamed, restored, and exported, but the list lives only for the browser
  session (cleared by "Clear all" or reload). Run configurations are not saved to disk.
