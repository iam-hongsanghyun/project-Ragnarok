# Frontend Details Reference

Implementation reference for `frontend/Ragnarok_default/src/`. Covers application
structure, root state and handlers, view and feature components, and shared
utilities. This is not a user manual (see `docs/guides/user-manual.md`) and not
an architecture overview (see `docs/architecture/`).

---

## Table of Contents

1. [Directory Layout](#1-directory-layout)
2. [App.tsx — Root Component](#2-apptsx--root-component)
   - 2.1 [State Overview](#21-state-overview)
   - 2.2 [Derived Values (useMemo)](#22-derived-values-usememo)
   - 2.3 [Model Lifecycle: resetForNewModel](#23-model-lifecycle-resetfornewmodel)
   - 2.4 [Undo / Redo](#24-undo--redo)
   - 2.5 [Model Edit Handlers](#25-model-edit-handlers)
   - 2.6 [File Open and Save](#26-file-open-and-save)
   - 2.7 [Project Import / Export](#27-project-import--export)
   - 2.8 [Result Workbook Export](#28-result-workbook-export)
   - 2.9 [CSV / netCDF / HDF5 Import-Export](#29-csv--netcdf--hdf5-import-export)
   - 2.10 [Run Lifecycle](#210-run-lifecycle)
   - 2.11 [Run-History Handlers](#211-run-history-handlers)
   - 2.12 [Scenario Handlers](#212-scenario-handlers)
   - 2.13 [Plugin Host Wiring](#213-plugin-host-wiring)
   - 2.14 [customDsl and constraintSpecs](#214-customdsl-and-constraintspecs)
   - 2.15 [Internal Helpers](#215-internal-helpers)
3. [Layout](#3-layout)
   - 3.1 [ActivityBar](#31-activitybar)
   - 3.2 [ResizablePanels](#32-resizablepanels)
4. [Views](#4-views)
   - 4.1 [BuildView](#41-buildview)
   - 4.2 [ModelView](#42-modelview)
   - 4.3 [SettingsView](#43-settingsview)
   - 4.4 [AnalyticsView](#44-analyticsview)
   - 4.5 [PluginsView](#45-pluginsview)
5. [Features](#5-features)
   - 5.1 [Build Authoring](#51-build-authoring)
   - 5.2 [Analytics Dashboard and Cards](#52-analytics-dashboard-and-cards)
   - 5.3 [Run Dialog and Run History](#53-run-dialog-and-run-history)
   - 5.4 [Plugin Host: frontendPlugins and pluginRuntime](#54-plugin-host-frontendplugins-and-pluginruntime)
   - 5.5 [PluginDetail](#55-plugindetail)
   - 5.6 [PluginPanel](#56-pluginpanel)
   - 5.7 [Input Tables](#57-input-tables)
   - 5.8 [Map Components](#58-map-components)
   - 5.9 [Validation](#59-validation)
   - 5.10 [Settings Hook](#510-settings-hook)
   - 5.11 [Constraints Table](#511-constraints-table)
6. [Shared — Types](#6-shared--types)
7. [Shared — Utilities](#7-shared--utilities)
   - 7.1 [workbook.ts](#71-workbookts)
   - 7.2 [exportResults.ts](#72-exportresultsts)
   - 7.3 [csvFolder.ts](#73-csvfolderts)
   - 7.4 [helpers.ts](#74-helpersts)
   - 7.5 [analytics.ts](#75-analyticsts)
   - 7.6 [deriveRunResults.ts](#76-deriverunresultsts)
   - 7.7 [deriveAssetDetails.ts](#77-deriveassetdetailsts)
   - 7.8 [constraintDsl.ts](#78-constraintdslts)
   - 7.9 [customDsl.ts](#79-customdslts)
   - 7.10 [usePersistedState.ts](#710-usepersistedstatets)
   - 7.11 [pathway.ts](#711-pathwayts)
   - 7.12 [rolling.ts](#712-rollingts)
   - 7.13 [scenarios.ts](#713-scenariosts)
   - 7.14 [exportChart.ts](#714-exportchartts)
   - 7.15 [formatRelTime.ts](#715-formatreltimets)

---

## 1. Directory Layout

```
frontend/Ragnarok_default/src/
  App.tsx                    Root component. Holds all shared state.
  index.tsx                  React entry point.
  layout/
    ActivityBar.tsx          Five-tab vertical nav strip.
    ResizablePanels.tsx      Draggable split container, sizes persisted.
  views/
    BuildView.tsx            Guided model-building wizard (re-exports from features/build).
    ModelView.tsx            Spreadsheet input editor.
    SettingsView.tsx         Section-nav + per-section forms.
    SettingsView.sections/   One file per settings section.
    AnalyticsView.tsx        Results + validation dashboard.
    AnalyticsView.features/  Sub-tab bodies, dashboard, subnav.
    PluginsView.tsx          Plugin install/select rail + PluginDetail main area.
    ModelView.features/      FileToolbar, SheetTree.
  features/
    build/                   BuildView, BuildNetworkMap, BuildDetailPane, steps.ts.
    analytics/               AnalyticsPane, ComparisonPane, useMetricOptions.
    run/                     RunDialog.
    run-history/             RunHistoryList, RunHistoryCard, RunComparisonTable.
    plugins/                 frontendPlugins.ts, pluginRuntime.ts, PluginDetail, PluginPanel.
    input/                   TablesPane, DataGrid, grid/range.ts, tsv.ts.
    map/                     MapPane, BuildNetworkMap, FitToBounds, MapLegend.
    validation/              ValidationPane, useModelIssues.
    settings/                useSettings.
    constraints/             GlobalConstraintsSection.
    modules/                 ModuleManagerSection (ConfigFieldRow).
  shared/
    types/index.ts           All shared TypeScript types and interfaces.
    utils/                   Utility modules (see Section 7).
    components/Toast.tsx     Toast notification context + hook.
  config/                    Runtime config (API_BASE, etc.).
  constants/                 Schema metadata, RUN_WINDOW, DEFAULT_CONSTRAINTS, etc.
```

---

## 2. App.tsx — Root Component

`App.tsx` exports two components. `App` is the public entry: it wraps `AppInner`
in `ToastProvider`. `AppInner` owns all application state and wires every
handler down to view components as props.

### 2.1 State Overview

| State variable | Type | Role |
|---|---|---|
| `model` | `WorkbookModel` | Live editable input workbook |
| `results` | `RunResults \| null` | Raw result from the last completed or restored run |
| `resultsModel` | `WorkbookModel \| null` | Topology snapshot taken at run or restore time |
| `resultsContext` | `{carbonPrice, snapshotWeight, discountRate} \| null` | Derivation inputs frozen at run or restore time |
| `runStatus` | `'idle' \| 'running' \| 'done' \| 'error'` | Current run lifecycle state |
| `runHistory` | `RunHistoryEntry[]` | Session-scoped list of past runs |
| `scenarioCatalog` | `ScenarioCatalog` | Named solver scenarios |
| `pathwayConfig` | `PathwayConfig` | Multi-period investment path settings |
| `rollingConfig` | `RollingHorizonConfig` | Rolling horizon solve settings |
| `stochasticConfig` | `StochasticConfig` | Stochastic scenario configuration |
| `sclopfConfig` | `SecurityConstrainedConfig` | SCLOPF toggle and settings |
| `constraints` | `CustomConstraint[]` | Active standard constraints |
| `customDsl` | `string` | Raw text of the Advanced Constraints code box |
| `carbonPrice` | `number` | Carbon price in current currency per tCO2 |
| `carbonPriceSchedule` | `CarbonPriceScheduleEntry[]` | Per-period carbon price overrides |
| `tab` | `WorkspaceTab` | Active view (Build / Model / Settings / Analytics / Plugins) |
| `analyticsSubTab` | `AnalyticsSubTab` | Active Analytics sub-tab |
| `settings` | `AppSettings` | Persisted app preferences (currency, solver, date format, etc.) |
| `maxSnapshots` | `number` | Upper bound for snapshot window sliders |
| `snapshotStart/End/Weight` | `number` | Run window sliders |
| `forceLp` | `boolean` | Force LP relaxation flag |
| `analyticsFocus` | `AnalyticsFocus` | Currently focused asset in Analytics |
| `chartSections` | `ChartSectionConfig[]` | Analytics dashboard card layout |
| `runDialogOpen` | `boolean` | Whether the Run dialog is open |
| `dryRun` | `boolean` | Whether the next run is a dry-run validation |
| `validateResult` | `ValidationResult \| null` | Backend dry-run result |
| `fileHandle` | `BrowserFileHandle \| null` | File System Access API handle for in-place saves |
| `projectProvenance` | `ProjectImportProvenance \| null` | Metadata from the last project import |

### 2.2 Derived Values (useMemo)

#### `displayResults`

Type: `RunResults | null`. The processed result fed to all analytics components.

- Non-pathway runs: calls `withDerivedAssetDetails(analyticsModel, results, currencySymbol)`.
- Pathway runs: calls `deriveRunResults(analyticsModel, outputs, {carbonPrice, currencySymbol, discountRate, snapshotWeight, selectedPeriod, pathway, rolling})` then merges pathway, merit order, plugin analytics, and CO2 shadow price back from the raw result.

Recomputes when `results`, `analyticsModel`, currency, carbon price, discount
rate, snapshot weight, or `pathwayConfig` change.

#### `analyticsModel`

Type: `WorkbookModel`. Evaluates to `resultsModel ?? model`. All analytics
always use this model, not the live editable model, so the user can edit
buses without corrupting the active result display.

#### `bounds` / `busIndex`

Geographic bounding box and name-to-row lookup derived from `model.buses`.
Analogues `analyticsBounds` / `analyticsBusIndex` are derived from
`analyticsModel.buses`.

#### `activeScenario`

The `ScenarioPreset` matching `scenarioCatalog.activeScenarioId`, or `null`.

#### `scenarioDirty`

`boolean`. True when the live slider state differs from `activeScenario`
(JSON comparison via `captureCurrentScenario`).

### 2.3 Model Lifecycle: resetForNewModel

```
resetForNewModel(nextModel: WorkbookModel, name?: string) -> void
```

Single choke-point for all model-load paths: open workbook, import project,
CSV folder import, netCDF import, HDF5 import, demo, plugin preview, and
history restore.

Actions performed in order:

1. Calls `normalizeInputDatesToIso(nextModel, settings.dateFormat)` — idempotent.
2. Reads snapshot range from `nextModel.snapshots` and updates `maxSnapshots` and `snapshotEnd`.
3. Reads `pathwayConfig`, `rollingConfig`, `customDsl`, and `scenarioCatalog` from the model.
4. Resets `results`, `resultsModel`, `resultsContext`, `runStatus`, `chartSections`, `validateResult`, `analyticsFocus`, `projectProvenance`.
5. Does NOT clear `runHistory` — prior runs survive model swaps.
6. Applies the imported active scenario (or a synthesised default) to all live sliders.

### 2.4 Undo / Redo

The undo stack is a `useRef<WorkbookModel[]>` bounded to 50 entries
(`HISTORY_LIMIT`). Every mutation handler calls `pushHistory()` before
changing `model`.

| Function | Action |
|---|---|
| `pushHistory()` | Saves `model` to undo stack; clears redo stack |
| `undo()` | Pops undo stack, pushes current model to redo stack, sets model |
| `redo()` | Pops redo stack, pushes current model to undo stack, sets model |

A `useEffect` registers keyboard shortcuts on `window`:
- `Ctrl/Cmd+Z` — undo
- `Ctrl/Cmd+Shift+Z` or `Ctrl+Y` — redo

Shortcuts fire only when the active `tab` is `'Model'` or `'Build'` and no
text input or textarea has focus.

### 2.5 Model Edit Handlers

All handlers call `pushHistory()` before mutating. All mutations produce a new
immutable model via `setModel`.

| Handler | Signature | Effect |
|---|---|---|
| `updateRowValue` | `(sheet, rowIndex, key, value) -> void` | Single-cell update |
| `bulkPaste` | `(sheet, edits, extraRows) -> void` | Multi-cell paste; appends `extraRows` schema-default rows first |
| `addRow` | `(sheet) -> void` | Appends a schema-default row via `getDefaultRowForSheet` |
| `deleteRow` | `(sheet, rowIndex) -> void` | Removes the row at `rowIndex` |
| `moveRow` | `(sheet, rowIndex, direction) -> void` | Swaps with neighbour; `direction` is `-1` or `1` |
| `addColumn` | `(sheet, col, defaultValue) -> void` | Inserts `col` with `defaultValue` on every existing row; idempotent |
| `deleteColumn` | `(sheet, col) -> void` | Removes `col` from every row |
| `renameColumn` | `(sheet, oldCol, newCol) -> void` | Renames column key on every row |
| `clearSheet` | `(sheet) -> void` | Replaces the sheet's row array with `[]` |

### 2.6 File Open and Save

| Handler | Notes |
|---|---|
| `handleOpenWorkbook()` | Uses `showOpenFilePicker` (Chromium) or hidden `<input type="file">`. Calls `resetForNewModel`. Stores the file handle. |
| `handleImport(event)` | `onChange` for the hidden file input fallback. Calls `resetForNewModel`. Does not retain a handle. |
| `saveWorkbook()` | Saves in place when a handle exists; falls through to `saveAsWorkbook`. |
| `saveAsWorkbook()` | Opens a save-file picker and writes via `workbookToArrayBuffer`. |

#### `saveFileWithPicker(opts)`

Shared helper used by all export functions.

| Option | Type | Meaning |
|---|---|---|
| `suggestedName` | `string` | Default filename |
| `description` | `string` | File-type filter label |
| `mime` | `string` | MIME type |
| `extensions` | `string[]` | e.g. `['.xlsx']` |
| `buildData` | `() => BlobPart` | Called lazily after the picker opens |
| `successMsg` | `string` | Toast on success |

Uses `window.showSaveFilePicker` when present; falls back to a programmatic
`<a download>` click. Silent on `AbortError` (user cancelled).

`XLSX_MIME` is `'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'`.

### 2.7 Project Import / Export

| Handler | Notes |
|---|---|
| `handleImportProject(event)` | Calls `parseProjectFile`, then `resetForNewModel`. Restores settings, constraints, run-state sliders, pathway and rolling config, and (when outputs are present) results via `deriveRunResults`. Prepends a synthetic `RunHistoryEntry`. |
| `handleExportProject()` | Serialises the currently displayed run (not run history) via `projectWorkbookToArrayBuffer`. Uses `analyticsModel` so the file is self-consistent with the active result. |

### 2.8 Result Workbook Export

`handleExportResultWorkbook()` — guards on `displayResults`, then calls
`fullResultsArrayBuffer(analyticsModel, displayResults)` and saves via
`saveFileWithPicker`. The exported file contains all `OUT_*` sheets.

### 2.9 CSV / netCDF / HDF5 Import-Export

| Handler | Notes |
|---|---|
| `handleExportCsvFolder()` | Dynamically imports `csvFolder.ts`, calls `exportModelAsCsvFolderZip`, triggers `<a download>` for a `.zip`. |
| `handleImportCsvFolder(event)` | Reads a `.zip`, calls `importCsvFolderZip`, normalises dates, calls `resetForNewModel`. |
| `exportViaBackend(endpoint, filenameOut)` | POSTs `{model, scenario, options}` JSON to `endpoint`; receives binary blob; triggers download. Used by `handleExportNetcdf` and `handleExportHdf5`. |
| `importViaBackend(endpoint, file)` | POSTs `multipart/form-data` to `endpoint`; receives `{model}` JSON; calls `resetForNewModel`. Used by `handleImportNetcdf` and `handleImportHdf5`. |

### 2.10 Run Lifecycle

#### `handleRunModel() -> Promise<void>`

Three-phase async workflow:

**Phase 1 — dry run:** When `dryRun` is true, POSTs to `/api/validate` and
routes to the Validation sub-tab. No job is started.

**Phase 2 — start job:** POSTs `{model, scenario, options}` to `/api/run`.
The `scenario` object includes `constraints`, `constraintSpecs` (parsed from
`customDsl` via `dslToSpecs`), `carbonPrice`, and `discountRate`. The `options`
object carries solver settings, snapshot window, pathway and rolling config,
stochastic and SCLOPF config, currency symbol, and other run-control keys.
Receives a `jobId`; sets `runStatus = 'running'`.

**Phase 3 — poll:** Inner `poll()` fetches `/api/run/:jobId` every
`RUN_POLLING.runningDelayMs` ms until status is no longer `'running'`. On 404
or non-OK, sets `runStatus = 'error'`. On network error, retries after
`RUN_POLLING.retryDelayMs`. On success, calls `applyResult`.

**`applyResult(rawResults)`** (inner closure): canonicalises output series
dates, updates `results`, `resultsModel`, `resultsContext`, appends a
`RunHistoryEntry` (capped to `MAX_UNPINNED_HISTORY` unpinned), and sets
`runStatus = 'done'`.

#### `handleCancelRun() -> Promise<void>`

Calls `stopPolling()`, sends `DELETE /api/run/:jobId`, clears `jobIdRef` and
`sessionStorage`, sets `runStatus = 'idle'`.

### 2.11 Run-History Handlers

| Handler | Signature | Effect |
|---|---|---|
| `handleRestoreRun` | `(entry) -> void` | Restores `results`, `resultsModel`, `resultsContext` from the entry; rehydrates model and all sliders; pushes current model to undo. |
| `handleRenameHistoryEntry` | `(id, label) -> void` | Updates the `label` field |
| `handlePinHistoryEntry` | `(id, pinned) -> void` | Sets `pinned`; re-applies the unpinned-entry cap |
| `handleDeleteHistoryEntry` | `(id) -> void` | Removes entry by `id` |
| `handleClearHistory` | `() -> void` | Confirms then resets `runHistory` to `[]` |
| `handleToggleComparison` | `(id, inComparison) -> void` | Toggles the Comparison tab inclusion flag |

### 2.12 Scenario Handlers

| Handler | Signature | Effect |
|---|---|---|
| `captureCurrentScenario` | `(overrides?) -> ScenarioPreset` | Builds a `ScenarioPreset` from the current live slider state |
| `applyScenarioPreset` | `(scenario) -> void` | Applies a preset to all live sliders; clamps snapshot window; shows toast |
| `handleSelectScenario` | `(scenarioId) -> void` | Looks up and applies a scenario by id |
| `handleCreateScenarioFromCurrent` | `() -> void` | Calls `captureCurrentScenario`; appends to catalog |
| `handleDuplicateScenario` | `() -> void` | Clones the active scenario (new id, label suffixed " copy") |
| `handleUpdateActiveScenarioFromCurrent` | `() -> void` | Overwrites the active scenario's fields; preserves id, label, notes |
| `handleDeleteScenario` | `() -> void` | Removes the active scenario; no-op if only one remains |
| `handleRenameScenario` | `(scenarioId, label) -> void` | Updates label in-place; falls back to existing if trim is empty |
| `handleScenarioNotesChange` | `(scenarioId, notes) -> void` | Updates the `notes` field |

### 2.13 Plugin Host Wiring

`App.tsx` calls `useFrontendPlugins()` once at the root level and stores the
result as `frontendPlugins`. This value is passed as the `host` prop to
`PluginsView`, which passes it to `PluginDetail`. All plugin installs,
uninstalls, config reads, and config writes go through `host`. None of them
touch the Ragnarok backend. There are no App-level plugin handler functions.

### 2.14 customDsl and constraintSpecs

`customDsl` is a `string` of raw Advanced Constraints DSL text. It is:

- Loaded into state by `resetForNewModel` via `readCustomDslFromModel`.
- Persisted to the model before backend exports via `writeCustomDslToModel`.
- Passed to `SettingsView` (Constraints section) and `PluginsView` as a
  prop so plugins can append new constraint lines via `onCustomDslChange`.
- Converted to `constraintSpecs` (a `ConstraintSpec[]`) by calling
  `dslToSpecs(customDsl)` at run time, just before the `/api/run` POST.

### 2.15 Internal Helpers

#### `prepareModelForBackend(source) -> WorkbookModel`

Deep-clones `source` and applies `normalizeInputDatesToIso` with the current
`settings.dateFormat`. Called before every backend POST to ensure canonical
ISO timestamps reach the solver.

#### `stopPolling() -> void`

Clears `pollTimerRef.current`. Called before cancel and on unmount.

#### `handleImportTsSheet(sheet, rows) -> void`

Canonicalises rows via `canonicalizeTemporalRows` and replaces `model[sheet]`
in place. Used by both `BuildView` and `ModelView` for per-sheet CSV imports.

---

## 3. Layout

### 3.1 ActivityBar

**File:** `layout/ActivityBar.tsx`

Vertical far-left strip with five view buttons: Build (B), Model (M),
Settings (S), Analytics (A), Plugins (P). Each button shows a single-letter
glyph and the full view name as a title tooltip.

**Props:**

| Prop | Type | Meaning |
|---|---|---|
| `tab` | `WorkspaceTab` | Currently active view |
| `onTabChange` | `(t: WorkspaceTab) => void` | View switch callback |
| `validateResult` | `ValidationResult \| null` | When set, shows an ok/error badge on the Analytics button |
| `pluginCount` | `number` | When non-zero, shows a count badge on the Plugins button |

The Analytics badge shows a green check when `validateResult.valid` is true,
or the total error + warning count when false.

### 3.2 ResizablePanels

**File:** `layout/ResizablePanels.tsx`

Flexbox split container with draggable gutters between child panels. Panel
sizes are stored as percentages and persisted to `localStorage` under the key
`pypsa.panelSizes.<id>`. Double-clicking a gutter resets to `initialSizes`.

**Props:**

| Prop | Type | Meaning |
|---|---|---|
| `id` | `string` | Stable key for localStorage persistence |
| `direction` | `'horizontal' \| 'vertical'` | Split axis |
| `children` | `React.ReactNode` | One element per panel; falsy children are dropped |
| `initialSizes` | `number[]` | Default sizes as percentages summing to 100 |
| `minSize` | `number` | Minimum panel size in px; default `140` |
| `className` | `string` | Additional class on the container element |

Nest two instances (one of each direction) to create 2-D layouts. `ModelView`
uses `[20, 40, 40]` for SheetTree / TablesPane / MapPane.

---

## 4. Views

Views are thin shell components. They own layout and local selection state;
all data mutations are delegated to callbacks received as props from `App.tsx`.

### 4.1 BuildView

**File:** `features/build/BuildView.tsx` (re-exported from the `views/` render path)

Guided wizard for constructing a PyPSA model from scratch. Renders a horizontal
step strip, a `TablesPane` scoped to the active step's sheet, a schema/issue
detail pane, and a `BuildNetworkMap`.

Each build step (defined in `steps.ts`) maps to one or two schema sheets in
dependency order: Network → Carriers → Buses → Generators → Loads → Storage →
Lines → Links → Transformers → Snapshots → Review. Switching steps does not
reset the model.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `model` | `WorkbookModel` | Live model |
| `busIndex` | `Record<string, GridRow>` | Bus name lookup for the map |
| `onUpdateRow` | `(sheet, rowIndex, col, val) => void` | Cell edit |
| `onAddRow` | `(sheet) => void` | Append row |
| `onDeleteRow` | `(sheet, rowIndex) => void` | Delete row |
| `onAddColumn` | `(sheet, col, defaultValue) => void` | Add column |
| `onDeleteColumn` | `(sheet, col) => void` | Delete column |
| `onRenameColumn` | `(sheet, oldCol, newCol) => void` | Rename column |
| `onClearTable` | `(sheet) => void` | Clear all rows |
| `onImportTsSheet` | `(sheet, rows) => void` | Import CSV into a TS sheet |
| `onBulkPaste` | `(sheet, edits, extraRows) => void` | Paste from clipboard |
| `modelIssues` | `ModelIssue[]` | Issues to highlight per sheet |
| `currencySymbol` | `string` | For CAPEX / cost columns |
| `dateFormat` | `DateFormat` | For snapshot parsing |
| `onOpenRunSetup` | `() => void \| undefined` | Open the run dialog |

### 4.2 ModelView

**File:** `views/ModelView.tsx`

The workbook input editor. Three resizable columns: `SheetTree` (left),
`TablesPane` (centre), `MapPane` (right). `FileToolbar` sits above the columns.

`ModelView` owns one piece of local state: `sel: TableSel`, the currently
selected sheet and kind (`'static'` or `'temporal'`). All other state is held
in `App.tsx`.

**Key props (extends `FileToolbarProps`):**

| Prop | Type | Meaning |
|---|---|---|
| `model` | `WorkbookModel` | Full input workbook |
| `bounds` | `LatLngBoundsExpression \| null` | Geographic bounds for `MapPane` |
| `busIndex` | `Record<string, GridRow>` | Bus name lookup for `MapPane` |
| `onUpdateRow` | `(sheet, rowIndex, col, val) => void` | Cell edit |
| `onAddRow` | `(sheet) => void` | Append default row |
| `onDeleteRow` | `(sheet, rowIndex) => void` | Delete row |
| `onAddColumn` | `(sheet, col, defaultValue) => void` | Add schema-extra column |
| `onDeleteColumn` | `(sheet, col) => void` | Remove column |
| `onRenameColumn` | `(sheet, oldCol, newCol) => void` | Rename column key |
| `onClearTable` | `(sheet) => void` | Remove all rows |
| `onImportTsSheet` | `(sheet, rows) => void` | Replace a TS sheet from CSV |
| `onBulkPaste` | `(sheet, edits, extraRows) => void` | Multi-row clipboard paste |
| `modelIssues` | `ModelIssue[]` | Cells to highlight |
| `jumpTo` | `{sheet, rowIndex} \| null` | Scroll to row after tab switch |
| `currencySymbol` | `string` | Cost column display |
| `dateFormat` | `DateFormat` | Snapshot parsing |
| `hasResults` | `boolean` | Enables the Export Result button |

File-operation props (`onOpen`, `onSave`, `onSaveAs`, `onImportProject`,
`onExportProject`, `onExportResult`, `onImportCsvFolder`, `onExportCsvFolder`,
`onImportNetcdf`, `onExportNetcdf`, `onImportHdf5`, `onExportHdf5`) are all
`() => void` callbacks passed through to `FileToolbar`.

#### `FileToolbar`

**File:** `views/ModelView.features/FileToolbar.tsx`

The file-operation toolbar at the top of `ModelView`. Less-common formats
(CSV folder, netCDF, HDF5) are grouped under a `<details>` disclosure element
labelled "More formats…".

#### `SheetTree`

**File:** `views/ModelView.features/SheetTree.tsx`

Left-column component navigator. Shows only groups where the static sheet or
at least one temporal sheet has data. Supports a text filter and collapsible
groups. Issue badge counts are memoized from `ModelIssue[]`. Groups are
defined by `TABLE_GROUPS` from `constants/index.ts`.

### 4.3 SettingsView

**File:** `views/SettingsView.tsx`

Left section-nav + active section editor. The view owns one piece of local
state: `section: SectionId`, persisted to `localStorage` via `usePersistedState`.
Section navigation and the main content area are wrapped in `ResizablePanels`
with initial sizes `[20, 80]`.

**Section groups and IDs (as defined in the source):**

| Group | Section ID | Label |
|---|---|---|
| Setup | `scenarios` | Scenarios |
| Setup | `window` | Simulation window |
| Setup | `planning` | Multi-year planning |
| Setup | `rolling` | Rolling horizon |
| Policy | `carbon` | Carbon price |
| Policy | `constraints` | Standard Constraints |
| Policy | `constraintsAdvanced` | Advanced Constraints |
| Solve | `stochastic` | Stochastic |
| Solve | `sclopf` | Security-constrained (SCLOPF) |
| Solve | `solver` | Solver |
| App | `appearance` | Appearance |
| App | `projectDefaults` | Project defaults |

**Section files under `views/SettingsView.sections/`:**

| File | Section ID |
|---|---|
| `Scenarios.tsx` | `scenarios` |
| `Window.tsx` | `window` |
| `Carbon.tsx` | `carbon` |
| `Planning.tsx` | `planning` |
| `Rolling.tsx` | `rolling` |
| `Stochastic/Stochastic.tsx` | `stochastic` |
| `Sclopf.tsx` | `sclopf` |
| `Constraints.tsx` | `constraints` and `constraintsAdvanced` (exports `StandardConstraintsSection` and `AdvancedConstraintsSection`) |
| `Solver.tsx` | `solver` |
| `Appearance.tsx` | `appearance` |
| `ProjectDefaults.tsx` | `projectDefaults` |

`SettingsView` never calls `setModel` directly. All mutations go through the
callbacks, which live in `App.tsx`.

### 4.4 AnalyticsView

**File:** `views/AnalyticsView.tsx`

Results and validation dashboard with four sub-tabs: Validation, Result,
Analytics, Comparison. The view owns no local state; sub-tab routing is driven
by `analyticsSubTab` from `App.tsx`. Layout: left sidebar with `RunHistoryList`,
main area with the active sub-tab body and `AnalyticsSubnav`.

Sub-tab routing:
- `'Validation'` → `ValidationPane`
- `'Result'` → `AnalyticsPane` (or `EmptyAnalytics` when no results)
- `'Analytics'` → `AnalyticsDashboard`
- `'Comparison'` → `ComparisonPane`

**Representative props:**

| Prop | Type | Meaning |
|---|---|---|
| `analyticsSubTab` | `AnalyticsSubTab` | Active sub-tab |
| `onAnalyticsSubTabChange` | `(s) => void` | Sub-tab switch |
| `displayResults` | `RunResults \| null` | Derived results |
| `model` | `WorkbookModel` | Results-owning topology |
| `bounds` | `LatLngBoundsExpression \| null` | Analytics map bounds |
| `busIndex` | `Record<string, GridRow>` | Bus lookup |
| `analyticsFocus` | `AnalyticsFocus` | Focused asset |
| `setAnalyticsFocus` | `(focus) => void` | Focus change |
| `chartSections` | `ChartSectionConfig[]` | Dashboard layout |
| `runHistory` | `RunHistoryEntry[]` | All history entries |
| `pathwayConfig` | `PathwayConfig` | Period selector state |
| `onSelectedPeriodChange` | `(period) => void` | Period pill click |
| `onRestoreRun` | `(entry) => void` | View a past run |
| `onToggleComparison` | `(id, inComparison) => void` | Comparison checkbox |

### 4.5 PluginsView

**File:** `views/PluginsView.tsx`

Two-column layout (via `ResizablePanels`, initial sizes `[22, 78]`): a left
rail for install and plugin selection, and a `PluginDetail` main area. The
view owns one piece of local state: `selectedId`, the id of the plugin shown
in the main area. When `selectedId` is null or the plugin is uninstalled, the
view falls back to `installed[0]`.

**Props:**

| Prop | Type | Meaning |
|---|---|---|
| `host` | `FrontendPluginHost` | Plugin host from `useFrontendPlugins()` |
| `model` | `WorkbookModel` | Live workbook, passed to `PluginDetail` |
| `onReplaceModel` | `(next: WorkbookModel) => void` | Called when a plugin replaces the workbook |
| `onMergeSheets` | `(sheets) => void` | Called when a plugin contributes sheets |
| `customDsl` | `string` | Current constraint DSL text |
| `onCustomDslChange` | `(text: string) => void` | Called when a plugin appends constraint lines |
| `results` | `unknown` | Last run results, passed to the plugin `analyze` hook |

**Left rail behaviour:**
- "Install plugin…" button opens a hidden `<input type="file" accept=".zip">`.
  On selection, calls `host.install(file)`. Success toasts with the installed id
  and selects the new plugin.
- Each installed plugin is a button. An `x` button calls `host.uninstall(id)`.
- There is no enable/disable toggle. Every installed plugin is immediately
  available.

---

## 5. Features

### 5.1 Build Authoring

**Files:** `features/build/`

#### `BuildNetworkMap`

Interactive Leaflet map for the Build wizard. The active step's layer is
fully interactive; all other layers render as faint context.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `model` | `WorkbookModel` | Current topology |
| `activeSheet` | `string` | Sheet being edited in the current build step |
| `selectedRowIndex` | `number \| null` | Highlighted row |
| `onSelectRow` | `(rowIndex: number) => void` | Row selection callback |
| `onPlaceComponent` | `(lat, lng) => void` | Right-click to place a new component |
| `onUpdateCoords` | `(sheet, rowIndex, x, y) => void` | Drag marker to update x/y |
| `onLinkToBus` | `(rowIndex, busName) => void` | Link-mode: attach component to bus |
| `linkMode` | `LinkMode` | Whether link-to-bus mode is active |
| `onLinkModeChange` | `(mode: LinkMode) => void` | Toggle link mode |

**Exported constants:**
- `BRANCH_SHEETS` — `Set<string>`: `{'lines', 'links', 'transformers'}`.
- `isGeoSheet(sheet) -> boolean` — true for sheets that support map placement.
- `LinkMode` — `'off' | 'active'`.

#### `BUILD_STEPS` (from `steps.ts`)

Array of `BuildStep` objects defining the build wizard order. Each step has
`id`, `label`, `sheets`, `description`, and `helpText`.

#### `getStepIssues(step, modelIssues) -> ModelIssue[]`

Filters `modelIssues` to only those belonging to the step's sheets.

#### `BuildDetailPane`

Displays schema documentation and validation issues for the active step.
Purely presentational.

#### `BuildAttributeForm`

Inline attribute form shown when a row is selected on the build map. Renders
schema-driven field inputs for the selected row.

### 5.2 Analytics Dashboard and Cards

**Files:** `features/analytics/`, `views/AnalyticsView.features/Dashboard/`

#### `AnalyticsPane`

Main analytics result panel for the `'Result'` sub-tab. Hosts the analytics
display and optionally a pathway period selector strip.

#### `EmptyAnalytics`

Placeholder shown when no results exist. Renders a heading and instructions.

#### `ComparisonPane`

Renders `RunComparisonTable` in a pane container.

#### `AnalyticsDashboard`

Drag-and-drop dashboard for the `'Analytics'` sub-tab. Manages a grid layout
of chart cards (capacity, dispatch, price, emissions, merit order, etc.). Users
can add, remove, and reorder cards.

#### `Dashboard`

Core drag-and-drop grid container. Renders `DashboardCard` items in a CSS grid
and handles drop events to reorder cards.

#### `useDashboardLayout(storageKey, defaultLayout) -> [layout, setLayout, resetLayout]`

Hook that persists the dashboard card layout to `localStorage`. Returns the
current layout, a setter, and a reset-to-default function.

#### `PRESETS` (from `presets.ts`)

Array of named dashboard preset configurations (e.g. "Overview", "Capacity",
"Dispatch"). Each preset is a list of card descriptors.

#### `buildResultPreset(results) -> DashboardPreset`

Builds a dashboard preset tailored to the specific results: includes capacity
expansion cards only when extendable assets exist, pathway cards only for
multi-period solves, etc.

#### `useMetricOptions(results, ...) -> MetricOption[]`

Hook that derives the list of metric options (dispatch, price, storage, load,
emissions) available for interactive chart cards. Returns memoized options
based on current results and dispatch rows.

#### `AnalyticsSubnav`

Horizontal sub-tab navigation bar rendered above the analytics main area.
Displays the four sub-tab labels with optional issue or validation badges.

### 5.3 Run Dialog and Run History

**Files:** `features/run/RunDialog.tsx`, `features/run-history/`

#### `RunDialog`

Modal dialog for configuring and triggering a solve. Returns `null` when
`open` is false. Clicking the backdrop calls `onClose`.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `open` | `boolean` | Whether the dialog is visible |
| `onClose` | `() => void` | Backdrop click or Cancel |
| `forceLp` | `boolean` | Current Force LP toggle state |
| `dryRun` | `boolean` | Current Dry Run toggle state |
| `activeScenarioLabel` | `string \| null` | Label shown in Planning summary |
| `activeConstraintCount` | `number` | Count of enabled constraints |
| `snapshotStart` | `number` | Snapshot window start index |
| `snapshotEnd` | `number` | Snapshot window end index |
| `snapshotWeight` | `number` | Snapshot weight (hours per snapshot) |
| `pathwayConfig` | `PathwayConfig` | Used to show "N pathway periods" |
| `rollingConfig` | `RollingHorizonConfig` | Used to show rolling horizon summary |
| `onForceLpChange` | `(v: boolean) => void` | Toggle Force LP |
| `onDryRunChange` | `(v: boolean) => void` | Toggle Dry Run |
| `onRun` | `() => void` | "Run model" or "Validate" button |

The primary button label switches to `'Validate'` when `dryRun` is true.

#### `RunHistoryList`

Vertical list of `RunHistoryCard` components, one per entry in `runHistory`.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `runHistory` | `RunHistoryEntry[]` | Entries to display |
| `onRestoreRun` | `(entry) => void` | "View results" click |
| `onRenameHistoryEntry` | `(id, label) => void` | Commit rename |
| `onPinHistoryEntry` | `(id, pinned) => void` | Pin/unpin |
| `onDeleteHistoryEntry` | `(id) => void` | Delete entry |
| `onToggleComparison` | `(id, inComparison) => void` | Comparison tab toggle |
| `currencySymbol` | `string` | For carbon price KPI display |

#### `RunHistoryCard`

Single card for one `RunHistoryEntry`. Manages its own internal state for
inline label editing and delete confirmation. Label editing commits on blur
or Enter. Delete requires a two-step confirm.

#### `RunComparisonTable`

Side-by-side comparison table for all entries where `inComparison === true`.
Returns `null` when fewer than two entries exist. Entries are sorted
newest-first. Each non-active column shows a percentage-delta badge relative
to the active run for every numeric KPI row.

### 5.4 Plugin Host: frontendPlugins and pluginRuntime

**Files:** `features/plugins/frontendPlugins.ts`, `features/plugins/pluginRuntime.ts`

#### `useFrontendPlugins() -> FrontendPluginHost`

Hook that manages the frontend-only plugin system. Plugins are a pure browser
concern: installed from a `.zip` file into `localStorage`, configured in the
Plugins tab, and executed in the browser. They never contact the Ragnarok
backend directly.

**Returned object (`FrontendPluginHost`):**

| Field | Type | Meaning |
|---|---|---|
| `installed` | `InstalledPlugin[]` | All currently installed plugins |
| `install(file)` | `(File) => Promise<{ok, error?, id?}>` | Parse a `.zip` and add to `localStorage`; replaces any existing plugin with the same id |
| `uninstall(id)` | `(string) => void` | Remove a plugin from `installed` |
| `getConfig(id)` | `(string) => Record<string, unknown>` | Return stored config for the plugin id (empty object if none) |
| `setConfig(id, value)` | `(string, Record<string, unknown>) => void` | Replace the entire config for a plugin |
| `setConfigField(id, key, value)` | `(string, string, unknown) => void` | Update a single config field |

There is no enable/disable toggle. Every installed plugin is available
immediately.

**localStorage keys:**
- `ragnarok:fe-plugins:installed` — JSON array of `InstalledPlugin` objects.
- `ragnarok:fe-plugins:configs` — JSON object keyed by plugin id.

`FrontendPluginHost` is the return type of `useFrontendPlugins()` (`ReturnType<typeof useFrontendPlugins>`).

#### `InstalledPlugin` interface

| Field | Type | Meaning |
|---|---|---|
| `id` | `string` | Unique identifier from `module.json` |
| `name` | `string` | Display name from `module.json` |
| `version` | `string \| undefined` | Optional semver string |
| `description` | `string \| undefined` | Optional description text |
| `manifest` | `Record<string, unknown>` | Full parsed `module.json` |
| `files` | `Record<string, string>` | Text files from the package keyed by relative path |

#### `pluginRuntime.ts`

Provides the in-browser CommonJS evaluator for plugin entry files.

**`loadPluginModule(plugin) -> PluginModule`**

Reads `plugin.files[manifest.entry]`, evaluates it as CommonJS via
`new Function('module', 'exports', src)`, and returns `module.exports`. Throws
if the entry file is missing.

**`pluginCapabilities(plugin) -> CapabilityFlags`**

Calls `loadPluginModule` and checks which of `transform`, `contribute`, and
`analyze` are exported functions. Returns `{transform, contribute, analyze}`
booleans. Returns all `false` on any load error.

**`PluginModule` interface:**

```typescript
interface PluginModule {
  transform?: (model: WorkbookModel, config: Record<string, unknown>)
    => WorkbookModel | Promise<WorkbookModel>;
  contribute?: (model: WorkbookModel, config: Record<string, unknown>)
    => PluginContribution | Promise<PluginContribution>;
  analyze?: (result: unknown, config: Record<string, unknown>)
    => Record<string, unknown> | Promise<Record<string, unknown>>;
}
```

`PluginContribution` is `{ sheets?: Record<string, GridRow[]>; constraints?: string[] }`.

### 5.5 PluginDetail

**File:** `features/plugins/PluginDetail.tsx`

Detail pane for one installed plugin. Renders config fields, run actions, and
analyze output.

When the manifest declares a config schema (field descriptors with a `type`
property), `PluginDetail` renders the full `PluginPanel` GUI: Description /
Input / Output inner tabs, the `panel.inputLayout` grid, grouped sections, and
every field or table editor. A schema-less manifest falls back to a raw JSON
config textarea. Everything runs in the browser.

**Key props (`PluginDetailProps`):**

| Prop | Type | Meaning |
|---|---|---|
| `host` | `FrontendPluginHost` | Plugin host from `useFrontendPlugins()` |
| `plugin` | `InstalledPlugin` | The plugin to display |
| `model` | `WorkbookModel` | Current workbook, passed to plugin hooks |
| `onReplaceModel` | `(next: WorkbookModel) => void` | Called when `transform` replaces the workbook |
| `onMergeSheets` | `(sheets) => void` | Called when `contribute` adds or updates sheets |
| `customDsl` | `string` | Current constraint DSL text |
| `onCustomDslChange` | `(text: string) => void` | Called when `contribute` appends constraint lines |
| `results` | `unknown` | Last run results, passed to the `analyze` hook |

**Plugin hook dispatch:**
- `transform(model, config)` — replaces the entire workbook; triggered by "Apply to model" or an `action` field with `hook: "transform"`.
- `contribute(model, config)` — merges sheets and/or appends constraint DSL lines.
- `analyze(results, config)` — called automatically when `results` changes; output shown in the Output tab.
- Named hooks (e.g. `connect`) — invoked by `action` fields whose `hook` matches the export name; return value shown as a toast.

**`ServerSetupNotice`** (internal): When the manifest declares a `server` block,
renders an advisory showing the `plugins.env` entry the user must add so
`run.command` will launch the server. The Ragnarok backend does not launch
plugin servers; this component is advisory only.

### 5.6 PluginPanel

**File:** `features/plugins/PluginPanel.tsx`

Panel area for one or more plugins with a manifest config schema. Renders
Description / Input / Output inner tabs.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `modules` | `ModuleDescriptor[]` | Plugin descriptors (built from `InstalledPlugin` manifests by `PluginDetail`) |
| `moduleConfigs` | `Record<string, Record<string, unknown>>` | Config values per plugin id |
| `onModuleConfigChange` | `(moduleId, key, value) => void` | Config field change |
| `carriers` | `string[] \| undefined` | Carrier names for action fields with carrier autocomplete |
| `pluginAnalytics` | `Record<string, PluginAnalyticsEntry>` | `analyze`-hook output keyed by plugin id |
| `onModuleAction` | `(moduleId, fieldKey, field) => Promise<void>` | Action button handler |

**Inner tabs:**
- `Description` — renders `panel.descriptionSections` or `module.description`.
- `Input` — renders config fields grouped by `type: "group"` entries in the schema.
- `Output` — renders `PluginResults` from the `analyze` hook output, grouped by `hint.section`.

#### `ConfigFieldRow`

Renders one plugin config field row. Supports types: `text`, `number`,
`boolean` toggle, `select`, `file` picker, `action` button. Exported from
`features/modules/ModuleManagerSection.tsx` for reuse in both `PluginPanel`
and `PluginDetail`.

### 5.7 Input Tables

**Files:** `features/input/`

#### `TablesPane`

The central table editor. Renders a sheet-selector rail on the left and a
`DataGrid` on the right, wrapped in `ResizablePanels`. For temporal sheets,
also renders an `InputAnalyser` above the grid.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `model` | `WorkbookModel` | Full model for row data and TS lookup |
| `sel` | `TableSel` | Currently selected sheet and kind (`static` / `temporal`) |
| `onSelChange` | `(sel) => void` | Sheet selection change |
| `onUpdate` | `(sheet, rowIndex, col, val) => void` | Cell edit |
| `onBulkPaste` | `(sheet, edits, extraRows) => void` | Multi-cell paste |
| `jumpTo` | `{sheet, rowIndex} \| null` | Scroll to a specific row |
| `modelIssues` | `ModelIssue[]` | Highlighted cells |
| `currencySymbol` | `string` | For cost column display |
| `dateFormat` | `DateFormat` | For snapshot parsing |

#### `DataGrid`

Low-level spreadsheet grid. Renders rows and columns as a styled `<table>`.
Handles single-cell edits, keyboard navigation, multi-cell selection, and
clipboard paste. Highlights cells with model issues.

#### `range.ts`

- `parseRange(sel) -> {start, end}` — parses a selection range object.
- `selectionToEdits(selection, parsedTsv, sheet, rows, columns) -> {rowIndex, col, val}[]` — maps a clipboard paste onto the correct grid cells.

#### `tsv.ts`

- `parseTsv(text) -> string[][]` — parses a tab-separated value string (e.g. from clipboard) into a 2D array. Handles quoted fields with embedded tabs and newlines.

### 5.8 Map Components

**Files:** `features/map/`

#### `MapPane`

Read-only Leaflet map displaying the model topology. Shows buses as circle
markers, generators and loads as smaller markers, and lines/links/transformers
as polylines. Togglable layers per component type. Results-agnostic.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `model` | `WorkbookModel` | Topology to render |
| `bounds` | `LatLngBoundsExpression \| null` | Auto-fit viewport |
| `busIndex` | `Record<string, GridRow>` | Bus coordinate lookup |

#### `FitToBounds`

Leaflet child component that calls `map.fitBounds(bounds)` whenever `bounds`
changes. Uses `NoZoomAnimation` to prevent jarring tile flicker.

#### `MapLegend`

Static legend overlay labelling each component type with its colour.

#### `NoZoomAnimation`

Disables Leaflet's CSS zoom animation (`zoomAnimation: false`) for programmatic
bounds fitting.

### 5.9 Validation

**Files:** `features/validation/`

#### `ValidationPane`

Displays model issues from `useModelIssues` and optionally a backend validation
result. Issues are shown in a scrollable list (truncated to 20 by default, with
a "Show all" toggle). Each issue item navigates to the relevant sheet and row.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `validateResult` | `ValidationResult \| null` | Backend dry-run result |
| `issues` | `ModelIssue[]` | Client-side model issues |
| `onValidate` | `() => void` | Trigger a dry run |
| `onRun` | `() => void` | Open the run dialog |
| `onNavigate` | `(sheet, rowIndex) => void` | Navigate Model tab to a row |

#### `useModelIssues(model) -> ModelIssue[]`

Returns a memoized array of `ModelIssue` objects. Checks performed on every
model update:

- Duplicate names within a sheet.
- Required fields that are blank.
- Bus references (`bus`, `bus0`, `bus1`, etc.) that name a non-existent bus.
- Type references in `lines` or `transformers` not in the combined catalogue.
- Non-negative attribute violations (`p_nom`, `capital_cost`, etc.).
- Per-unit range violations for `*_pu` attributes (outside `[0, 1]`).
- Efficiency > 5 (likely in % not ratio).
- CO2 emissions > 5 (likely wrong units).
- Carrier cross-references naming a carrier absent from the `carriers` sheet.
- Temporal sheet: row count vs snapshot count mismatch, missing snapshot
  label column, unknown component column names, out-of-range per-unit or
  load values.

`ModelIssue` shape: `{sheet, rowIndex, col?, severity: 'error'|'warning', message}`.

### 5.10 Settings Hook

**File:** `features/settings/useSettings.ts`

#### `useSettings() -> [AppSettings, (patch: Partial<AppSettings>) => void]`

Loads `AppSettings` from `localStorage` on mount and provides a stable
`updateSettings` callback. Settings are persisted on every update.

**`AppSettings` fields:**

| Field | Type | Default |
|---|---|---|
| `dateFormat` | `DateFormat` | `'auto'` |
| `solverThreads` | `number` | `0` (let HiGHS decide) |
| `solverType` | `SolverType` | `'simplex'` |
| `currencyCode` | `string` | `'USD'` |
| `currencySymbol` | `string` | `'$'` |
| `enableLoadShedding` | `boolean` | `false` |
| `loadSheddingCost` | `number` | VOLL in selected currency per MWh |
| `discountRate` | `number` | `0.05` |

### 5.11 Constraints Table

**File:** `features/constraints/GlobalConstraintsSection.tsx`

Renders a table for adding and editing `CustomConstraint` rows (metric, carrier,
value, unit, enabled toggle). Used by `SettingsView` for the Standard
Constraints section.

---

## 6. Shared — Types

**File:** `shared/types/index.ts`

Key types and their meanings:

| Type | Definition |
|---|---|
| `Primitive` | `string \| number \| boolean \| null` |
| `GridRow` | `Record<string, Primitive>` |
| `WorkbookModel` | `Record<string, GridRow[]>` — a map from sheet name to rows |
| `SheetName` | `string` (sheet names are schema-driven; not an enum) |
| `WorkspaceTab` | `'Build' \| 'Model' \| 'Settings' \| 'Analytics' \| 'Plugins'` |
| `AnalyticsSubTab` | `'Validation' \| 'Result' \| 'Analytics' \| 'Comparison'` |
| `ChartMode` | `'line' \| 'area' \| 'bar'` |
| `TimeframeOption` | `'aggregated' \| 'yearly' \| 'monthly' \| 'weekly' \| 'daily' \| 'hourly'` |
| `PlanningMode` | `'single_period' \| 'pathway'` |
| `ConstraintMetric` | Union of 8 constraint type strings (co2_cap, carrier_max_gen, etc.) |
| `CustomConstraint` | `{id, enabled, label, metric, carrier, value, unit}` |
| `PathwayConfig` | `{planningMode, enabled, snapshotMappingMode, overridePolicy, periods, selectedPeriod}` |
| `RollingHorizonConfig` | `{enabled, horizonSnapshots, overlapSnapshots, stepPolicy, stepSnapshots, preserveTerminalState, selectedWindow}` |
| `StochasticConfig` | `{enabled, scenarios: StochasticScenarioOverride[]}` |
| `SecurityConstrainedConfig` | `{enabled}` |
| `AnalyticsFocus` | `{type: 'system'} \| {type: 'asset', sheet, name}` |
| `RunHistoryEntry` | Entry in the session run history; carries a full results and topology snapshot |
| `ScenarioCatalog` | `{scenarios: ScenarioPreset[], activeScenarioId: string \| null}` |
| `ScenarioPreset` | Full solver configuration snapshot saved by the user |
| `ConstraintSpec` | Wire format sent to the backend for DSL-parsed constraints |
| `ModuleDescriptor` | Descriptor built from an `InstalledPlugin` manifest for `PluginPanel` |

`WorkbookModel` is dynamically keyed. `createEmptyWorkbook()` pre-populates
every documented PyPSA sheet with `[]`, so `model.generators` and similar
are always defined at runtime.

---

## 7. Shared — Utilities

### 7.1 workbook.ts

Handles all XLSX read/write and the project round-trip format. Every temporal
sheet is canonicalised on entry (ISO-8601 `T`-separated snapshot values, with
`period?` then `snapshot` as leading columns) regardless of the import path.

**Private metadata sheet name constants:**

`RESULT_META_SHEET`, `PLUGIN_ANALYTICS_SHEET`, `SETTINGS_SHEET`,
`CONSTRAINTS_SHEET`, `RUN_STATE_SHEET`, `RUN_HISTORY_SHEET`, `PROVENANCE_SHEET`

**Temporal canonicalisation functions:**

| Function | Signature | Effect |
|---|---|---|
| `normalizeCell` | `(value) -> Primitive` | Converts a raw SheetJS cell value to `Primitive`; JS `Date` objects become ISO strings |
| `hasSnapshotColumn` | `(rows) -> boolean` | True if any row has a `'snapshot'` key |
| `orderTemporalRow` | `(row) -> GridRow` | Returns a copy with `period?` then `snapshot` as the first two keys |
| `canonicalizeTemporalRows` | `(rows, fmt) -> GridRow[]` | Converts `snapshot` to ISO; re-orders columns. Idempotent |
| `canonicalizeTemporalSheets` | `(sheets, fmt) -> void` | Applies `canonicalizeTemporalRows` in place to every sheet with a `snapshot` column |
| `canonicalizeOutputSeries` | `(series, fmt) -> void` | Thin wrapper scoped to `outputs.series` |
| `normalizeInputDatesToIso` | `(model, fmt) -> void` | Applies `canonicalizeTemporalSheets` to the whole model in place |

`prepareTemporalRowsForExport` is an alias for `canonicalizeTemporalRows`,
exported for back-compat.

**Workbook construction and parsing:**

| Function | Signature | Effect |
|---|---|---|
| `createEmptyWorkbook` | `() -> WorkbookModel` | Returns a model with every known sheet initialised to `[]` |
| `parseSheets` | `(workbook) -> WorkbookModel` | Converts a SheetJS workbook to `WorkbookModel` |
| `parseWorkbook` | `(file) -> Promise<WorkbookModel>` | Reads a `File`, calls `XLSX.read`, delegates to `parseSheets` |
| `buildWorkbook` | `(model, dateFormat?) -> XLSX.WorkBook` | Constructs a SheetJS workbook from the model |
| `workbookToArrayBuffer` | `(model, dateFormat?) -> ArrayBuffer` | Calls `buildWorkbook` then `XLSX.write`; used for file saves |
| `exportWorkbook` | `(model, filename?, dateFormat?) -> void` | Calls `buildWorkbook` then `XLSX.writeFile`; triggers browser download |

**CSV parsing:**

| Function | Signature | Effect |
|---|---|---|
| `parseDelimitedTextToGridRows` | `(text) -> GridRow[]` | Parses CSV or TSV; column 0 stays as string, others cast to number where parseable |
| `parseCsvToGridRows` | `(file) -> Promise<GridRow[]>` | Reads a `File` as text and calls `parseDelimitedTextToGridRows` |

**Project workbook (round-trip with outputs and metadata):**

| Function | Signature | Effect |
|---|---|---|
| `buildProjectWorkbook` | `(model, outputs?, metadata?) -> XLSX.WorkBook` | Full project `.xlsx`: input sheets, output sheets, internal config sheets, metadata sheets |
| `projectWorkbookToArrayBuffer` | `(model, outputs, metadata) -> ArrayBuffer` | Calls `buildProjectWorkbook` and serialises |
| `parseProjectWorkbook` | `(arrayBuffer) -> {model, outputs, metadata}` | Reverses `buildProjectWorkbook` |
| `parseProjectFile` | `(file) -> Promise<{model, outputs, metadata}>` | Async wrapper using `FileReader` |

`buildProjectWorkbook` chunks long JSON values across rows to respect Excel's
32 767-character cell limit. `parseProjectWorkbook` reassembles multi-chunk
values in `part` order.

**Temporal header helper:**

`temporalHeader(rows) -> string[]` — returns `['period'?, 'snapshot', ...rest]`;
used by `temporalSheetToWorksheet` to fix column order before SheetJS export.

### 7.2 exportResults.ts

Builds the standalone result workbook exported via the Export Result button.
All column widths are auto-fitted (capped at 40 characters).

#### `buildFullResultsWorkbook(model, results) -> XLSX.WorkBook`

Starts from `buildWorkbook(model)` then appends `OUT_*` sheets:

| Sheet | Content |
|---|---|
| `OUT_Summary` | KPI summary rows |
| `OUT_Dispatch` | Carrier dispatch time series (pivoted) |
| `OUT_GenDispatch` | Generator-level dispatch (pivoted) |
| `OUT_SysPrice` | System marginal price per snapshot |
| `OUT_Emissions` | System emissions per snapshot |
| `OUT_Storage` | Aggregate storage charge / discharge / state |
| `OUT_CarrierMix` | Total energy by carrier |
| `OUT_CostBreakdown` | Fuel, carbon, load-shedding, CAPEX costs |
| `OUT_NodalBalance` | Mean load and generation per bus |
| `OUT_LineLoading` | Peak loading % per branch |
| `OUT_GenDetail` | Per-generator hourly output |
| `OUT_StorageDetail` | Per-storage-unit hourly state |
| `OUT_BranchFlow` | Per-branch p0/p1 per snapshot |
| `OUT_MeritOrder` | Generator merit order (if present) |
| `OUT_Expansion` | Capacity expansion results (if present) |
| `OUT_EmissionsByGen` | Emissions breakdown by generator |
| `OUT_EmissionsByCarrier` | Emissions breakdown by carrier |
| `OUT_CO2Shadow` | CO2 shadow price (if present) |

#### `fullResultsArrayBuffer(model, results) -> ArrayBuffer`

Calls `buildFullResultsWorkbook` and serialises to bytes for `saveFileWithPicker`.

### 7.3 csvFolder.ts

PyPSA-native CSV folder import/export. Round-trips with
`pypsa.Network.import_from_csv_folder` / `export_to_csv_folder`. Zip structure
is `<archiveName>/<sheetName>.csv`.

| Function | Signature | Effect |
|---|---|---|
| `exportModelAsCsvFolderBytes` | `(model, archiveName) -> Uint8Array` | Converts known non-empty model sheets to CSV; packs into a deflated zip via `fflate.zipSync` |
| `exportModelAsCsvFolderZip` | `(model, archiveName) -> Blob` | Wraps bytes as `application/zip` |
| `importCsvFolderZip` | `(file) -> Promise<CsvFolderImportResult>` | Decompresses via `fflate.unzipSync`; parses known PyPSA sheet names via SheetJS; returns `{model, unknownFiles, importedSheets}` |

### 7.4 helpers.ts

General-purpose value coercions, colour utilities, and geometry helpers.

| Function | Signature | Effect |
|---|---|---|
| `numberValue` | `(value) -> number` | Coerces to finite number; returns `0` for non-finite, null, undefined |
| `stringValue` | `(value) -> string` | Returns `''` for null/undefined; otherwise `String(value)` |
| `hashColor` | `(value) -> string` | Deterministic `hsl(H 65% 46%)` colour from a string |
| `setCarrierColorOverrides` | `(rows) -> void` | Rebuilds module-level override map from `{name, color}` rows |
| `carrierColor` | `(carrier) -> string` | User override first, then deterministic palette; `'#94a3b8'` for blank |
| `resolvedColor` | `(explicitColor, carrier?) -> string` | Explicit hex if valid; else `carrierColor(carrier)` |
| `clamp` | `(value, min, max) -> number` | Standard numeric clamp |
| `inferInputValue` | `(raw, current) -> Primitive` | Infers correct `Primitive` type from user-typed text and existing cell value |
| `getColumns` | `(rows, sheet) -> string[]` | Union of schema default columns and all keys in rows; `'name'` pinned first |
| `getTsFirstCol` | `(rows) -> string` | First timestamp-like column name in `rows[0]`; falls back to `'snapshot'` |
| `orderByCarrierRows` | `(carrierRows, keys) -> string[]` | Sorts keys so user-defined carriers come first in their declared order |
| `priceColor` | `(value, min, max) -> string` | Interpolated teal-to-red colour for nodal price choropleth |
| `loadingColor` | `(pct) -> string` | Green at 0%, yellow at 50%, red at 100% |
| `rowCoords` | `(row) -> [number, number] \| null` | Returns `[lat, lng]` from row `y`/`x`; null if either is missing |
| `getBounds` | `(model) -> LatLngBoundsExpression \| null` | `[lat, lng]` pairs for buses and generators with coordinates |
| `getBusIndex` | `(model) -> Record<string, GridRow>` | `name -> row` lookup over `model.buses` |
| `isoDate` | `(d) -> string` | `'YYYY-MM-DD'` using local date components |
| `isoTime` | `(d) -> string` | `'HH:MM'` using local date components |
| `formatTimestamp` | `(raw?) -> string` | Parses ISO and formats as `'YYYY-MM-DD HH:MM'`; returns raw if unparseable |
| `normalizeDateToIso` | `(raw, fmt?) -> string` | Converts user date format to ISO; four-digit leading component overrides fmt |
| `snapshotMaxFromWorkbook` | `(rows) -> number` | Row count of `snapshots` sheet; minimum 1 |

### 7.5 analytics.ts

Utility functions for chart data preparation and aggregation.

| Function | Signature | Effect |
|---|---|---|
| `normalizeSeriesPoint` | `(point) -> TimeSeriesRow` | Flattens a `SeriesPoint` (nested `values` map or flat numeric keys) into a `TimeSeriesRow` |
| `buildRowsFromGeneratorDetails` | `(generators, mode) -> TimeSeriesRow[]` | Aggregates per-generator output series by generator name or carrier |
| `buildSystemLoadRows` | `(results) -> TimeSeriesRow[]` | Returns load time-series; falls back to aggregating `netSeries.load` across buses |
| `aggregateValues` | `(values, reducer) -> number` | `'sum'`, `'mean'`, or `'last'`; returns `0` for empty arrays |
| `getTimeBucket` | `(timestamp, timeframe) -> string` | Maps an ISO timestamp to a bucket label for the chosen aggregation level |
| `aggregateMetricRows` | `(metric, startIndex, endIndex, timeframe) -> TimeSeriesRow[]` | Slices and groups by time bucket; applies `aggregateValues` per series key |
| `buildDonutFromMetric` | `(metric, startIndex, endIndex) -> Array<{label, value, color}>` | Aggregates to one total per series key; filters zeros; sorts descending |

### 7.6 deriveRunResults.ts

Derives a full `RunResults` object from `(model, outputs)` without a backend
call. Used on the project-import path.

#### `deriveRunResults(model, outputs, options?) -> RunResults`

**Params:**
- `model` — `WorkbookModel`: input topology.
- `outputs` — `{static, series}`: raw PyPSA output from the backend or imported project.
- `options` — `DeriveRunResultsOptions`: optional overrides for `carbonPrice`, `currencySymbol`, `discountRate`, `snapshotWeight`, `narrative`, `selectedPeriod`, `pathway`, `rolling`.

**Returns:** Complete `RunResults` including dispatch series, system price and
emissions series, storage series, nodal price series, carrier mix, cost
breakdown, nodal balance, line loading, expansion results, merit order,
emissions breakdown by generator and carrier, CO2 shadow price (always
`found: false` — duals are only available from a fresh solve), and asset
details. Multi-period runs filter `outputs.series` to `activePeriod` before
derivation. CAPEX annualisation uses `annuityFactor(rate, lifetime)` matching
the backend Python formula.

### 7.7 deriveAssetDetails.ts

#### `withDerivedAssetDetails(model, results, currencySymbol?) -> RunResults`

Returns a new `RunResults` with `assetDetails` populated. Used on the
non-pathway run path in `App.tsx`.

#### `deriveAssetDetails(model, outputs, currencySymbol?, snapshotWeight?) -> AssetDetails`

Builds `{generators, buses, storageUnits, stores, branches, processes, shuntImpedances}`
maps from output series and static data. Each entry carries a `name`,
`outputSeries`/`netSeries`/`flowSeries`/`stateSeries` array, KPI scalars
(total energy, average output, capital cost, etc.), and display metadata
(carrier, bus, color).

### 7.8 constraintDsl.ts

Parses the human-friendly Advanced Constraints code box into structured
`ConstraintSpec` objects (the wire format sent to the backend). Mirrors the
backend parser in `backend/pypsa/network/constraint_dsl.py`.

**Grammar (one constraint per line; `#` comments; blank lines ignored):**
```
line    := linexpr ("<="|">="|"==") linexpr
linexpr := term (("+"|"-") term)*
term    := [NUMBER "*"] atom
atom    := ("gen"|"cap"|"cf"|"emissions") ["(" CARRIER ")"] | "load_shed" | NUMBER
```

| Function | Signature | Effect |
|---|---|---|
| `parseConstraintDsl` | `(text) -> ParsedConstraintLine[]` | Parses all lines; returns per-line `{spec?, lineNo, raw, error?}` |
| `dslToSpecs` | `(text) -> ConstraintSpec[]` | Convenience: valid specs only (drops lines with parse errors) |

`ParsedConstraintLine.spec` is a `ConstraintSpec` with `{id, lhs, sense, rhs}`.
`ConstraintTerm` has `{coef, kind: ConstraintTermKind, carrier?}`.

### 7.9 customDsl.ts

Persistence for the free-text Advanced Constraints DSL. Stored as a single-row
sheet `RAGNAROK_CustomDSL` holding the raw multiline text.

| Function | Signature | Effect |
|---|---|---|
| `readCustomDslFromModel` | `(model) -> string` | Reads `model[CUSTOM_DSL_SHEET][0].text`; returns `''` if absent |
| `writeCustomDslToModel` | `(model, text) -> WorkbookModel` | Returns new model with `CUSTOM_DSL_SHEET` overwritten |

`CUSTOM_DSL_SHEET` is the constant `'RAGNAROK_CustomDSL'`.

### 7.10 usePersistedState.ts

#### `usePersistedState<T>(key, initial) -> [T, (v: T) => void]`

`useState` backed by `localStorage`. Survives view remounts and full page
reloads. Uses `initial` on the first run and whenever stored JSON fails to
parse. Silently ignores quota errors.

Used by `App.tsx` for `tab` (key `'ui:workspace-tab'`) and by `SettingsView`
for the active section (key `'ui:settings-section'`).

### 7.11 pathway.ts

Pathway (multi-period investment) config serialisation.

| Function | Signature | Effect |
|---|---|---|
| `defaultPathwayConfig` | `() -> PathwayConfig` | `enabled: false`, `planningMode: 'single_period'`, empty periods |
| `readPathwayConfigFromModel` | `(model) -> PathwayConfig` | Reads `RAGNAROK_Pathway` and `RAGNAROK_PathwayPeriods`; sorts periods ascending |
| `writePathwayConfigToModel` | `(model, config) -> WorkbookModel` | Overwrites pathway internal sheets |
| `samePathwayConfig` | `(a, b) -> boolean` | JSON-equality check for change detection |
| `getDefaultSelectedPeriod` | `(config) -> number \| null` | `config.selectedPeriod` if present; else first period; else `null` |

### 7.12 rolling.ts

Rolling-horizon config serialisation.

| Function | Signature | Effect |
|---|---|---|
| `defaultRollingConfig` | `() -> RollingHorizonConfig` | `enabled: false`, `horizonSnapshots: 168`, `overlapSnapshots: 24`, `stepSnapshots: 144`, `preserveTerminalState: true` |
| `readRollingConfigFromModel` | `(model) -> RollingHorizonConfig` | Reads `RAGNAROK_Rolling` first row |
| `writeRollingConfigToModel` | `(model, config) -> WorkbookModel` | Overwrites `RAGNAROK_Rolling` |
| `normalizeRollingConfig` | `(config) -> RollingHorizonConfig` | Clamps snapshot counts to positive integers; derives `stepSnapshots` when `stepPolicy === 'derived'` |
| `sameRollingConfig` | `(a, b) -> boolean` | JSON-equality check |

### 7.13 scenarios.ts

Scenario catalog serialisation.

| Function | Signature | Effect |
|---|---|---|
| `createScenarioId` | `() -> string` | Returns `'scenario-<timestamp>-<random>'` |
| `buildScenarioPreset` | `(input) -> ScenarioPreset` | Constructs a preset; generates id if none provided; deep-clones pathway, rolling, constraints |
| `defaultScenarioCatalog` | `(params) -> ScenarioCatalog` | Single default scenario built from params |
| `readScenarioCatalogFromModel` | `(model) -> ScenarioCatalog` | Reads `RAGNAROK_Scenarios`; each row stores full scenario JSON |
| `writeScenarioCatalogToModel` | `(model, catalog) -> WorkbookModel` | Overwrites `RAGNAROK_Scenarios` |
| `sameScenarioCatalog` | `(a, b) -> boolean` | JSON-equality check |

### 7.14 exportChart.ts

#### `svgToPng(svgEl) -> Promise<string | null>`

Serialises an SVG element to a PNG base64 string via an off-screen canvas at
2x resolution for retina sharpness. Returns `null` on any error.

#### `exportChartToExcel(title, headers, rows, containerEl, filename?) -> Promise<void>`

Writes an ExcelJS workbook with a `Data` sheet (bold header row, auto-width
columns) and a `Chart` sheet (embedded PNG if SVG render succeeded). The first
`<svg>` child of `containerEl` is used for the chart image. Triggers a
`<a download>` browser download. Default filename is `<title>_<date>.xlsx`.

### 7.15 formatRelTime.ts

#### `formatRelTime(iso) -> string`

Returns a human relative time label from an ISO 8601 timestamp: `'just now'`
(less than 1 minute), `'Nm ago'` (less than 1 hour), `'Nh ago'` (less than 1
day), `'Nd ago'` (otherwise). Used in `RunHistoryCard`.
