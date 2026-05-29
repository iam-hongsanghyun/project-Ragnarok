# Ragnarok — Architecture Reference

> **Purpose:** This document is the single-file orientation guide for new contributors and AI
> sessions. Read it first. You should not need to grep across 60+ files to understand the
> codebase — everything essential is here. (~5-minute read)

### Documentation map

| Document | Read it for |
|---|---|
| **ARCHITECTURE.md** (this file) | System overview, tech stack, repo layout, data flow |
| [docs/CAPABILITIES.md](./docs/CAPABILITIES.md) | What Ragnarok can and cannot do (code-checked) |
| [docs/PROCESSES.md](./docs/PROCESSES.md) | Step-by-step logic of each process (open, run, build, solve, extract, export) |
| [docs/USER_MANUAL.md](./docs/USER_MANUAL.md) | End-user manual for analysts (open/edit/run/analyse/export) |
| [docs/reference/](./docs/reference/) | Per-module function reference (backend + frontend) |
| [docs/SUPPORT_MATRIX.md](./docs/SUPPORT_MATRIX.md) | Generated feature support matrix |
| [docs/module-system-v1.md](./docs/module-system-v1.md) · [authoring guide](./docs/module-authoring-guide.md) | Plugin system spec + how to write plugins |
| [DESIGN.md](./DESIGN.md) | UI design philosophy |

---

## What this app does

Ragnarok is a browser-based GUI for building and running single-year PyPSA power-system models.
The user opens or edits an Excel workbook (one sheet per PyPSA component), configures run
parameters in a modal dialog, and the React frontend posts the workbook data to a local FastAPI
backend that constructs a `pypsa.Network`, solves it with HiGHS, and returns structured results.
Charts, maps, and tables then display the outputs without any round-trips to a remote server.

## Extension system (Plugin System v1)

Ragnarok ships a fully operational plugin system. The full spec and authoring guide are in:

- [docs/module-system-v1.md](./docs/module-system-v1.md)
- [docs/module-authoring-guide.md](./docs/module-authoring-guide.md)

### Backend implementation

**API endpoints**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/modules` | Return `ModuleHostInventory` (all discovered modules + host metadata) |
| `POST` | `/api/modules/install` | Upload `.zip`, extract to managed dir, validate, return module descriptor |
| `DELETE` | `/api/modules/{id}` | Remove module directory from managed root |

**Module discovery** (`backend/app/module_host.py`)

On every `/api/modules` call the backend scans the managed module root
(`${PROJECT_ROOT}/.ragnarok/modules/` by default, overridable in `system-defaults.yaml`),
reads each `module.json`, validates it against the host's supported SDK version, capabilities,
and permissions, and returns a full descriptor per module including `status`, `valid`,
`compatible`, `entryExists`, and `diagnostics`.

**Execution pipeline**

When `POST /api/run` fires, `run_pypsa()` in `backend/pypsa/results/__init__.py` calls
`execute_plugins_at_stage()` from `module_host.py` at each stage with the IDs and configs
that were sent in `options.enabledModules` / `options.moduleConfigs`:

| Stage | When it runs | Hook fn signature | Typical plugin type |
|---|---|---|---|
| `pre-build` | Before `build_network()` | `transform(model, scenario, options)` | `data-importer` |
| `post-build` | After `build_network()`, before `optimize()` | `manipulate(network, scenario, options)` | `data-manipulator` |
| `in-solve` | Inside PyPSA `extra_functionality` | `add_constraints(network, model, scenario, options)` | `constraint-pack` |
| `post-solve` | After `network.optimize()` | `analyse(network, results, scenario, options)` | `analytics-pack` |

`execute_plugins_at_stage()` loads each enabled module's Python entry file via
`importlib`, looks up the hook function named in `manifest.hook`, calls it with only
the stage-specific kwargs, and collects return values. Per-module configs are injected as
`options["moduleConfig"]` so plugins stay ID-agnostic. Failures are caught, logged, and
stored as `{"error": "..."}` — except `in-solve` failures which re-raise to prevent the
solver from running without a declared constraint.

Post-solve outputs are enriched with display metadata from `module.json`'s `ui` map and
returned inside the `RunResults` payload under `pluginAnalytics`.

### Frontend implementation

**`src/features/modules/useModuleHost.ts`**

Custom hook that owns all module-system state:
- `inventory` — fetched from `/api/modules` on mount
- `enabledIds` — persisted to `localStorage`
- `moduleConfigs` — per-plugin config values, persisted to `localStorage`
- `installFromFile()` / `uninstall()` — call the install/delete endpoints and re-fetch inventory

**`src/features/modules/ModuleManagerSection.tsx`**

Sidebar section rendered inside the `Modules` `SidebarGroup`. Each plugin gets a
collapsible `ModuleCard` showing status, version, capabilities, diagnostics, and manager
buttons.

The plugin input form no longer lives in the sidebar. It lives in the main **Plugins**
workspace instead.

Config field types rendered in the main plugin input view:

| `type` in `module.json` | Rendered as |
|---|---|
| `boolean` | checkbox |
| `number` (no range) | number input |
| `number` (with `min`/`max`) | range slider + live value label |
| `select` | `<select>` dropdown |
| `carrier-select` | multi-checkbox list populated from workbook carriers |

**`src/features/plugins/PluginPanel.tsx`**

Full-page workspace tab (labelled **Plugins**) shown when at least one plugin is enabled.
Renders:
- a tab bar with one tab per enabled plugin
- nested **Description / Input / Output** subtabs
- layout-aware section grids driven by `module.json` panel metadata
- `PluginResults` tables formatted via the `ui` hints from `module.json`

Result `format` values supported: `number`, `currency` (locale-formatted), `table`
(nested sub-table for `Record<string, unknown>` values), plain string fallback.

**Wiring in `App.tsx`**

`moduleHost.enabledIds` and `moduleHost.moduleConfigs` are passed in the `RunPayload`
as `options.enabledModules` and `options.moduleConfigs`, connecting frontend selection
to backend execution. `results?.pluginAnalytics` is forwarded to `PluginPanel` after
each successful run.

### Sample plugins

Four ready-to-install sample plugins live in `sample-plugins/` (pack each sub-directory
into a `.zip` and use the Install button in the sidebar):

| Directory | Stage | Capability | What it does |
|---|---|---|---|
| `ragnarok-cost-reporter` | post-solve | analytics-pack | Total cost, LCOE, nodal price stats, cost-by-carrier table |
| `ragnarok-renewable-floor` | in-solve | constraint-pack | Minimum renewable share constraint; carriers and floor % are configurable |
| `ragnarok-network-patcher` | post-build | data-manipulator | Topology log, clamps `p_nom_min < 0`, warns zero-capacity generators |
| `ragnarok-log-importer` | pre-build | data-importer | Model summary log before build; reference template for importers |

### What is NOT in v1

- Remote registry, signed modules, or sandboxed worker-process isolation
- Dynamic frontend UI injection from module entrypoints (all plugin UI goes through `PluginPanel`'s generic renderer)
- `activate()` / `deactivate()` lifecycle hooks — plugins are stateless Python callables

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
│   │   ├── config.py               ← loads backend/config/*.json (system defaults, module host)
│   │   ├── module_host.py          ← plugin discovery / execution system
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
            │                          modules, plugins, settings
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

### A new constraint metric

1. Add the new `ConstraintMetric` string literal to `src/types/index.ts`.
2. Add the UI row to `GlobalConstraintsSection.tsx`.
3. Handle the new metric in `backend/pypsa/network/custom_constraints.py`.

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
[docs/CAPABILITIES.md](./docs/CAPABILITIES.md). The headline limitations:

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
- **Local backend** — the app assumes the FastAPI server is running at `http://127.0.0.1:8000`.
  There is no cloud deployment path or authentication layer.
- **Session-scoped run history, not a persisted scenario manager** — past runs can be viewed,
  compared, pinned, renamed, restored, and exported, but the list lives only for the browser
  session (cleared by "Clear all" or reload). Run configurations are not saved to disk.
