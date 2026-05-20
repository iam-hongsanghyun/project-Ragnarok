# Ragnarok

**Free, open-source energy system modelling — built to destroy the market for expensive closed-source tools.**

Ragnarok is a browser-based power system optimisation tool built on [PyPSA](https://pypsa.org). It lets power system analysts and energy investors build, solve, and analyse single-year dispatch and capacity expansion models without writing a line of code — and without a six-figure software licence.

This repository is a local React + FastAPI application for editing a PyPSA-style workbook, running a PyPSA optimisation, and exploring the solved results in a map- and chart-based analytics dashboard.

This README is written as a handoff document for another AI or engineer. It explains the current structure, how data flows through the app, where the key logic lives, and which parts are still fragile.

## Plugin System

Ragnarok ships a fully operational v1 plugin system for `user-installed trusted local modules`.

- host/runtime/SDK spec: [docs/module-system-v1.md](./docs/module-system-v1.md)
- module authoring guide: [docs/module-authoring-guide.md](./docs/module-authoring-guide.md)

### What is implemented

**Backend**
- Discovery of installed local modules from the managed directory (`~/.ragnarok/modules/` or project-local `.ragnarok/modules/`)
- `module.json` manifest validation against SDK version, capabilities, and permissions
- `GET /api/modules` — inventory endpoint
- `POST /api/modules/install` — upload a `.zip` package and install it
- `DELETE /api/modules/{id}` — uninstall a module by ID
- **Full plugin execution pipeline** across four stages:

| Stage | Trigger | Hook function | Typical use |
|---|---|---|---|
| `pre-build` | before `build_network()` | `transform(model, scenario, options)` | data-importer, model rewriter |
| `post-build` | after `build_network()`, before `optimize()` | `manipulate(network, scenario, options)` | topology patcher, validator |
| `in-solve` | inside PyPSA's `extra_functionality` | `add_constraints(network, model, scenario, options)` | custom solver constraints |
| `post-solve` | after `network.optimize()` | `analyse(network, results, scenario, options)` | KPI reporter, cost breakdown |

- Per-plugin isolated error handling — a failing plugin logs an error and is reported in the frontend, but does not abort the solve pipeline (exception: `in-solve` failures are re-raised to prevent silently incorrect results)
- Plugin analytics results (`pluginAnalytics` dict) returned inside the `RunResults` payload alongside model results

**Frontend**
- `ModuleManagerSection` in the sidebar: install, uninstall, enable/disable, and module status
- `useModuleHost` hook: localStorage persistence for enabled IDs and module configs
- `PluginPanel` workspace tab: shown when at least one plugin is enabled; renders per-plugin tabs with nested Description / Input / Output views
- Config field types supported: `boolean`, `number` (bare input or slider when `min`/`max` are set), `select`, `carrier-select` (multi-checkbox populated from workbook carriers)
- Result rendering: scalar values, formatted numbers/currencies, and nested sub-tables (keyed by `format` in `module.json`'s `ui` map)
- Blue dot indicator on plugin tabs that have received post-solve results

**Sample plugins** (in `sample-plugins/`, ready to install as `.zip`):

| Plugin | Stage | Capability | Description |
|---|---|---|---|
| `ragnarok-cost-reporter` | post-solve | analytics-pack | Total system cost, LCOE, nodal price stats, carrier cost breakdown |
| `ragnarok-renewable-floor` | in-solve | constraint-pack | Adds a minimum renewable energy share constraint via `extra_functionality` |
| `ragnarok-network-patcher` | post-build | data-manipulator | Logs topology stats, clamps negative `p_nom_min`, warns zero-capacity generators |
| `ragnarok-log-importer` | pre-build | data-importer | Logs model summary before build; baseline template for data-importer plugins |

### What is not in v1

- Remote module registry or marketplace
- Sandboxed or worker-process isolation for untrusted code
- Frontend UI injection from module entrypoints (charts/panels must use the generic `PluginPanel` result renderer)
- `activate()` / `deactivate()` lifecycle hooks (plugins are stateless callables, not long-lived objects)

## 1. High-Level Architecture

- Frontend: React + TypeScript in `/Users/sanghyun/github/pypsa_gui/src`
- Backend: FastAPI + PyPSA in `/Users/sanghyun/github/pypsa_gui/backend`
- Dev launcher: `/Users/sanghyun/github/pypsa_gui/run.command`
- Build output: `/Users/sanghyun/github/pypsa_gui/build`

The app has three major user surfaces:

- `Map`
  - shows the network map and component locations
- `Tables`
  - lets the user edit workbook-like component tables directly
- `Analytics`
  - shows solved results after a run, with a map on top and user-defined chart sections below

## 2. Main Files

### Frontend

- `/Users/sanghyun/github/pypsa_gui/src/App.tsx`
  - almost the entire frontend application is in this file
  - contains:
    - workbook defaults
    - workbook parsing/export
    - map rendering
    - run dialog
    - analytics focus selection
    - chart builder UI
    - chart rendering logic
    - result type definitions

- `/Users/sanghyun/github/pypsa_gui/src/index.css`
  - global styling
  - chart builder layout
  - map and pane styling
  - legend and donut chart styling

### Backend

- `/Users/sanghyun/github/pypsa_gui/backend/main.py`
  - FastAPI app
  - payload parsing
  - synthetic demo network/workbook conversion into a PyPSA network
  - snapshot weighting logic
  - PyPSA optimization call
  - result extraction for system, bus, generator, storage, store, and branch outputs

- `/Users/sanghyun/github/pypsa_gui/backend/requirements.txt`
  - backend Python dependencies

### Runtime helper

- `/Users/sanghyun/github/pypsa_gui/run.command`
  - creates `.venv-pypsa` if needed
  - installs backend requirements
  - starts uvicorn on `127.0.0.1:8000`
  - waits for `/api/health`
  - starts React dev server

## 3. Frontend State Model

Important state variables in `/Users/sanghyun/github/pypsa_gui/src/App.tsx`:

- `model`
  - in-memory workbook model across all sheets
- `tab`
  - `Map | Tables | Analytics`
- `activeSheet`
  - currently selected workbook sheet in table view
- `selection`
  - selected table row
- `runSettings`
  - currently supports:
    - `snapshotCount`
    - `snapshotWeight`
- `results`
  - backend run result payload
- `analyticsFocus`
  - currently selected focus in analytics map:
    - `system`
    - `generator`
    - `bus`
    - `storageUnit`
    - `store`
    - `branch`
- `chartSections`
  - user-defined analytics chart cards

## 4. Workbook Model

The workbook is represented as a TypeScript object keyed by sheet name.

Important sheet names:

- `network`
- `snapshots`
- `carriers`
- `buses`
- `generators`
- `loads`
- `links`
- `lines`
- `stores`
- `storage_units`
- `transformers`
- `shunt_impedances`
- `global_constraints`
- `shapes`
- `processes`

`createDefaultWorkbook()` in `/Users/sanghyun/github/pypsa_gui/src/App.tsx` builds the demo case used by default.

## 5. Backend Flow

The backend entrypoint is:

- `POST /api/run`

Primary backend flow in `/Users/sanghyun/github/pypsa_gui/backend/main.py`:

1. parse `RunPayload`
2. read workbook tables from `payload.model`
3. derive `snapshotCount` and `snapshotWeight`
4. create a PyPSA network with `build_network()`
5. apply snapshot weighting to:
   - `network.snapshot_weightings.objective`
   - `network.snapshot_weightings.stores`
   - `network.snapshot_weightings.generators`
6. scale period-sensitive attributes such as:
   - `*_sum_min`
   - `*_sum_max`
7. run `network.optimize(solver_name="highs")`
8. extract solved outputs into a frontend-friendly JSON payload

Health endpoint:

- `GET /api/health`

## 6. Result Payload Structure

Top-level result fields currently include:

- `summary`
- `dispatchSeries`
- `generatorDispatchSeries`
- `systemPriceSeries`
- `systemEmissionsSeries`
- `storageSeries`
- `carrierMix`
- `nodalBalance`
- `lineLoading`
- `narrative`
- `runMeta`
- `assetDetails`

### `runMeta`

Includes:

- `snapshotCount`
- `snapshotWeight`
- `modeledHours`
- `storeWeight`

### `assetDetails`

Includes:

- `generators`
- `buses`
- `storageUnits`
- `stores`
- `branches`

These are lookup objects keyed by component name.

## 7. Analytics Map Structure

The Analytics tab is intentionally split into:

- top: map section
- bottom: chart section

The map is interactive. Clicking a component changes `analyticsFocus`.

Focus targets:

- generator marker -> generator analytics
- bus marker -> bus analytics
- line/link/transformer -> branch analytics
- storage unit marker -> storage unit analytics
- store marker -> store analytics

Reset focus returns to `system`.

## 8. Chart Builder Structure

The chart builder in `/Users/sanghyun/github/pypsa_gui/src/App.tsx` is user-defined rather than fixed.

Each chart section is a `ChartSectionConfig` with:

- `metricKey`
- `chartType`
- `timeframe`
- `startIndex`
- `endIndex`
- `stacked`

User controls currently include:

- `Value`
- `Timeframe`
- `Chart`
- `Stacking`
- shared start/end time window for that card

Users can:

- add a new chart section with `Add Chart`
- clear a section with `Clean`

## 9. System-Level Metric Options

When `analyticsFocus.type === 'system'`, the chart builder currently exposes:

- `Dispatch by carrier`
- `Dispatch by generator`
- `Total load`
- `System marginal price`
- `System emissions`
- `Storage power`
- `Storage state of charge`

These are built from:

- top-level backend system payloads, or
- fallback reconstruction from component-level outputs when needed

## 10. Component-Level Metric Options

### Generator focus

- `Output`
- `Available output`
- `Curtailment`
- `Emissions`

### Bus focus

- `Load`
- `Generation`
- `SMP`
- `Emissions`
- `Voltage magnitude` when available
- `Voltage angle` when available

### Storage unit focus

- `Dispatch`
- `Storage power`
- `State of charge`

### Store focus

- `Energy`
- `Power`

### Branch focus

- `Terminal flows`
- `Loading`
- `Losses`

## 11. Chart Rendering Rules

Important logic lives in `/Users/sanghyun/github/pypsa_gui/src/App.tsx`:

- `aggregateMetricRows(...)`
- `buildDonutFromMetric(...)`
- `InteractiveTimeSeriesCard(...)`
- `DonutChart(...)`
- `UserDefinedChartCard(...)`

Current chart types:

- `line`
- `area`
- `bar`
- `donut`

Current behavior:

- `line`, `area`, `bar`
  - can be `stacked` or `normal`
- `donut`
  - is intended to represent a single aggregated value over the selected time window
  - should only be used in aggregated mode

## 12. Important Current Constraints

These constraints were explicitly requested and should be preserved unless the user changes direction:

- do not mix different units in one chart
- one chart should represent one information family only
- no fake annual or projected outputs
- analytics should remain user-defined rather than hardcoded
- map section must stay above chart section
- timeline changes should affect the selected chart window

## 13. Known Fragile Areas

This is the most important section for another AI.

### A. System dispatch payload shape is still fragile

The frontend currently tries to support more than one payload shape for system series.

Expected shape:

```json
{
  "label": "00:00",
  "timestamp": "2026-01-11T00:00:00",
  "values": {
    "Coal": 1000,
    "LNG": 900
  },
  "total": 3200
}
```

But some runtime behavior suggests stale or mismatched shapes can still appear in the browser.

The frontend now defensively normalizes:

- nested `values`
- top-level numeric fields
- fallback reconstruction from generator output series

Even with that, the screenshots show `Dispatch by carrier` can still collapse into a single `dispatch` series, which means the live browser payload may still not match the current assumptions.

### B. Chart visuals can still look strange

The screenshots provided by the user are a valid concern.

Examples:

- `Dispatch by generator` stacked area can become visually dense because there are many series on a small hourly window
- `Dispatch by carrier` showing only one legend item is a sign of a data-shape problem, not only a styling problem

### C. Too much frontend logic is in one file

`/Users/sanghyun/github/pypsa_gui/src/App.tsx` is doing too much:

- data definitions
- workbook editing
- analytics logic
- charting
- map interaction
- run orchestration

This makes regression risk high.

## 14. Recommended Refactor Direction

If another AI is asked to continue this work, the cleanest next refactor is:

1. split `/Users/sanghyun/github/pypsa_gui/src/App.tsx` into:
   - `types.ts`
   - `workbook.ts`
   - `analytics.ts`
   - `components/`
2. define one stable result contract for:
   - system metrics
   - focus-level metrics
3. stop using multiple fallback payload shapes once the contract is stable
4. add explicit metric metadata from backend, instead of reconstructing chart series heuristically in the frontend

## 15. Recommended Debugging Order For Analytics Bugs

When a chart looks wrong, debug in this order:

1. inspect backend `POST /api/run` response payload
2. check whether the metric rows in frontend contain the expected numeric keys
3. check whether `metric.series` matches those row keys
4. only then inspect SVG rendering

For this project, many visible chart bugs are really payload-shape bugs.

## 16. Commands

### Start app

```bash
/Users/sanghyun/github/pypsa_gui/run.command
```

### Frontend only

```bash
cd /Users/sanghyun/github/pypsa_gui
npm start
```

### Backend only

```bash
cd /Users/sanghyun/github/pypsa_gui
.venv-pypsa/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

### Build frontend

```bash
cd /Users/sanghyun/github/pypsa_gui
npm run build
```

### Verify backend syntax

```bash
cd /Users/sanghyun/github/pypsa_gui
python3 -m py_compile backend/main.py
```

## 17. Immediate Open Issue

Based on the latest screenshots, yes, the current behavior is still weird.

Most likely current issue:

- `Dispatch by carrier` is still being populated with the wrong row keys in the live UI, so the chart reduces to a single `dispatch` series instead of one series per carrier

The next debugging step should be:

1. run the app
2. trigger a model run
3. inspect the live `/api/run` JSON in the browser network tab
4. compare:
   - `dispatchSeries`
   - `generatorDispatchSeries`
   - `assetDetails.generators[*].outputSeries`

That will reveal whether the bug is:

- backend payload construction
- stale dev bundle
- frontend normalization
- chart metric mapping
