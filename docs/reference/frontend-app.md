# frontend-app.md

Function reference for `frontend/Ragnarok_default/src/App.tsx`.

`App.tsx` is the root of the Ragnarok frontend. It holds the entire application
state — the live `WorkbookModel`, run results, undo/redo history, settings,
and run-history — and wires every handler down into the view components.
`AppInner` is the real component; `App` wraps it in `ToastProvider`.

---

## State overview (App-level)

| State variable | Type | Role |
|---|---|---|
| `model` | `WorkbookModel` | Live editable input workbook |
| `results` | `RunResults \| null` | Raw result from the last completed or restored run |
| `resultsModel` | `WorkbookModel \| null` | Topology snapshot taken at run/restore time |
| `resultsContext` | `{carbonPrice, snapshotWeight, discountRate} \| null` | Derivation inputs frozen at run/restore time |
| `runStatus` | `'idle' \| 'running' \| 'done' \| 'error'` | Current run lifecycle state |
| `runHistory` | `RunHistoryEntry[]` | Session-scoped list of past runs |
| `scenarioCatalog` | `ScenarioCatalog` | Named solver scenarios |
| `pathwayConfig` | `PathwayConfig` | Multi-period investment path settings |
| `rollingConfig` | `RollingHorizonConfig` | Rolling horizon solve settings |
| `constraints` | `CustomConstraint[]` | Active custom constraints |
| `carbonPrice` | `number` | Carbon price in current currency per tCO2 |

---

## Undo / redo infrastructure

### `pushHistory() -> void`

Saves the current `model` onto the undo stack before any mutation. The stack is
bounded to 50 entries (`HISTORY_LIMIT`). Clears the redo stack on every push
so branching is not possible.

**Notes:** Called at the top of every mutation handler (`updateRowValue`,
`addRow`, `deleteRow`, `addColumn`, `deleteColumn`, `renameColumn`,
`clearSheet`, `bulkPaste`, `moveRow`, `handleRestoreRun`).

### `undo() -> void`

Pops one snapshot from the undo stack, saves the current `model` on the redo
stack, and calls `setModel`.

### `redo() -> void`

Pops one snapshot from the redo stack, saves the current `model` on the undo
stack, and calls `setModel`.

**Notes:** A `useEffect` registers `Ctrl/Cmd+Z` (undo) and `Ctrl/Cmd+Shift+Z`
/ `Ctrl+Y` (redo) on the window. These fire only when the active tab is
`'Model'` or `'Build'` and no text input or textarea has focus, so they do not
hijack native browser undo inside input fields.

---

## Model edit handlers

### `updateRowValue(sheet, rowIndex, key, value) -> void`

**Params:**
- `sheet` — `SheetName`: the component sheet to update.
- `rowIndex` — `number`: zero-based index into the sheet array.
- `key` — `string`: column name.
- `value` — `Primitive`: the new cell value.

Calls `pushHistory()` then produces a new immutable model via `setModel` with
only the targeted row updated. Used for single-cell edits from `DataGrid`.

### `bulkPaste(sheet, edits, extraRows) -> void`

**Params:**
- `sheet` — `SheetName`.
- `edits` — `Array<{rowIndex, col, val}>`: list of cell edits to apply atomically.
- `extraRows` — `number`: rows to append (seeded from the schema default) before
  applying edits. Enables multi-row paste from Excel as one undoable operation.

Skips if both `edits.length` and `extraRows` are zero. Sets a status message
noting how many cells were pasted and how many rows were appended.

### `addRow(sheet) -> void`

**Params:** `sheet` — `SheetName`.

Appends a schema-default row (via `getDefaultRowForSheet`) to the named sheet.

### `deleteRow(sheet, rowIndex) -> void`

**Params:** `sheet` — `SheetName`; `rowIndex` — `number`.

Removes the row at `rowIndex` from the sheet array.

### `moveRow(sheet, rowIndex, direction) -> void`

**Params:** `sheet` — `SheetName`; `rowIndex` — `number`; `direction` — `-1 | 1`.

Swaps the row at `rowIndex` with its neighbour. No-op if already at the boundary.

### `addColumn(sheet, col, defaultValue) -> void`

**Params:** `sheet` — `SheetName`; `col` — `string`; `defaultValue` — `string | number | boolean`.

Inserts a new column with `defaultValue` on every row that does not already have
that key. Idempotent on existing keys.

### `deleteColumn(sheet, col) -> void`

Removes the column `col` from every row in `sheet`.

### `renameColumn(sheet, oldCol, newCol) -> void`

Renames a column key on every row. No-op if `newCol === oldCol` or is empty.

### `clearSheet(sheet) -> void`

Replaces the sheet's row array with `[]`. Equivalent to deleting all rows at
once as a single undoable operation.

---

## File open and save

### `handleOpenWorkbook() -> Promise<void>`

Uses the File System Access API (`showOpenFilePicker`) when available (Chromium)
and falls back to a hidden `<input type="file">` click elsewhere. Reads the
selected `.xlsx` file via `parseWorkbook`, canonicalises dates, and calls
`resetForNewModel`. Stores the file handle for in-place saves.

### `handleImport(event) -> Promise<void>`

`onChange` handler for the hidden file input fallback. Parses the workbook and
calls `resetForNewModel`. Does not retain a file handle (so subsequent saves
prompt "Save As").

### `saveWorkbook() -> Promise<void>`

Saves in place when a file handle exists; falls through to `saveAsWorkbook`
otherwise.

### `saveAsWorkbook() -> Promise<void>`

Opens a save-file picker (or `window.prompt` fallback) and writes the model via
`workbookToArrayBuffer`.

---

## Project import / export

### `handleImportProject(event) -> Promise<void>`

`onChange` handler for the hidden project-import input. Calls `parseProjectFile`
which splits the workbook into `{model, outputs, metadata}`. Restores full state:
- settings, constraints, run-state sliders
- pathway + rolling config from stored metadata
- results via `deriveRunResults` when outputs are present
- pushes a synthetic `RunHistoryEntry` to the run history

The imported entry is prepended (not replacing existing history) so prior runs
remain available for comparison.

### `handleExportProject() -> Promise<void>`

Serialises the current state (live model, `results?.outputs`, full metadata)
into a project `.xlsx` via `projectWorkbookToArrayBuffer`. Opens a save-file
picker. Exports the `analyticsModel` (not the live model) so the file is
self-consistent with whatever run is currently displayed.

**Note:** run history is intentionally NOT written to the file; only the
currently viewed run is exported.

---

## Result workbook export

### `handleExportResultWorkbook() -> Promise<void>`

Guard: returns immediately if `displayResults` is null. Calls
`fullResultsArrayBuffer(analyticsModel, displayResults)` and saves via
`saveFileWithPicker`. The exported file contains every `OUT_*` sheet (dispatch,
prices, emissions, per-asset detail, merit order, expansion, etc.).

---

## Shared file-save helper

### `saveFileWithPicker(opts) -> Promise<void>`

**Params (opts object):**
- `suggestedName` — `string`: default filename.
- `description` — `string`: human label for the file-type filter.
- `mime` — `string`: MIME type (e.g. `XLSX_MIME`).
- `extensions` — `string[]`: e.g. `['.xlsx']`.
- `buildData` — `() => BlobPart`: called lazily after the picker opens (so
  heavy serialisation does not block the picker's user-activation window).
- `successMsg` — `string`: toast / status message on success.

**Behaviour:** Uses `window.showSaveFilePicker` when present (Chromium); falls
back to a programmatic `<a download>` click elsewhere. Silent on
`AbortError` (user cancelled). Shows an error toast on any other failure.

### `XLSX_MIME` (constant)

```
'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
```

Used by every XLSX save call. Defined at module level inside `AppInner`.

---

## CSV / netCDF / HDF5 import-export

### `handleExportCsvFolder() -> Promise<void>`

Dynamically imports `csvFolder.ts` and calls `exportModelAsCsvFolderZip`; triggers
a `<a download>` for a `.zip` archive containing one CSV per PyPSA sheet.

### `handleImportCsvFolder(event) -> Promise<void>`

Reads a `.zip` file, calls `importCsvFolderZip`, normalises dates, and calls
`resetForNewModel`. Reports the number of imported sheets and any skipped
unknown files.

### `exportViaBackend(endpoint, filenameOut) -> Promise<void>`

Generic backend-export helper. Posts `{model, scenario, options}` JSON to
`endpoint`, receives a binary blob, and triggers a download. Used by
`handleExportNetcdf` and `handleExportHdf5`.

### `importViaBackend(endpoint, file) -> Promise<void>`

Posts a `multipart/form-data` file to `endpoint`, receives `{model}` JSON,
and calls `resetForNewModel`. Used by `handleImportNetcdf` and
`handleImportHdf5`.

---

## Run lifecycle

### `handleRunModel() -> Promise<void>`

The main run handler. Three-phase async workflow:

**Phase 1 — dry run (validate):** When `dryRun` is true, posts to
`/api/validate` and routes to the Validation sub-tab. No job is started.

**Phase 2 — start job:** Posts `{model, scenario, options}` to `/api/run`.
Receives a `jobId`. The `options` object carries solver settings, snapshot
window, pathway and rolling config, stochastic and SCLOPF config, currency
symbol, and any other run-control keys. Sets `runStatus = 'running'`.

**Phase 3 — poll:** Inner `poll()` function fetches `/api/run/:jobId` every
`RUN_POLLING.runningDelayMs` ms until status is no longer `'running'`. On
404 (server restart) or non-OK, sets `runStatus = 'error'`. On network
error, retries silently after `RUN_POLLING.retryDelayMs`. On success, calls
`applyResult`.

**`applyResult(rawResults)`** (inner closure): canonicalises output series
dates, updates `results`, `resultsModel`, `resultsContext`, appends an entry
to `runHistory` (capped to `MAX_UNPINNED_HISTORY` unpinned), and sets
`runStatus = 'done'`.

### `handleCancelRun() -> Promise<void>`

Stops polling via `stopPolling()`, sends `DELETE /api/run/:jobId` to the
backend, clears `jobIdRef` and `sessionStorage`, and sets `runStatus = 'idle'`.

---

## Run-history handlers

### `handleRestoreRun(entry) -> void`

**Params:** `entry` — `RunHistoryEntry`.

Restores a past run into the active display:
- Sets `results`, `resultsModel`, `resultsContext` from the entry's snapshot.
- Rehydrates `model` (pushing the current model to undo), adjusts snapshot
  window, carbon price, discount rate, pathway config, and rolling config to
  match the stored run.
- Re-canonicalises output series in place if they predate date normalisation.
- Does not switch the active tab or reset the analytics focus (focus reset is
  handled by a `useEffect`).

### `handleRenameHistoryEntry(id, label) -> void`

Updates the `label` field on the entry with the given `id`.

### `handlePinHistoryEntry(id, pinned) -> void`

Sets `pinned` on the entry. After pinning/unpinning, re-applies the capacity
cap: unpinned entries beyond `MAX_UNPINNED_HISTORY` are dropped.

### `handleDeleteHistoryEntry(id) -> void`

Removes the entry from `runHistory` by `id`.

### `handleClearHistory() -> void`

Shows a `window.confirm` dialog, then resets `runHistory` to `[]` if confirmed.
The currently displayed result and the live model are not affected.

### `handleToggleComparison(id, inComparison) -> void`

Toggles whether an entry is included in the Comparison sub-tab.

---

## Scenario handlers

### `captureCurrentScenario(overrides?) -> ScenarioPreset`

Builds a `ScenarioPreset` from the current live slider state (snapshot window,
weights, carbon price, constraints, pathway, rolling config). Used by
`handleCreateScenarioFromCurrent` and `handleUpdateActiveScenarioFromCurrent`.

### `applyScenarioPreset(scenario) -> void`

Applies a `ScenarioPreset` to all live sliders. Clamps the snapshot window to
the current `maxSnapshots`. Shows a toast. Used when the user picks a scenario
from the dropdown.

### `handleSelectScenario(scenarioId) -> void`

Looks up the scenario by id and calls `applyScenarioPreset`.

### `handleCreateScenarioFromCurrent() -> void`

Calls `captureCurrentScenario` and appends the result to the catalog.

### `handleDuplicateScenario() -> void`

Clones the active scenario (new id, label suffixed " copy") and appends it.

### `handleUpdateActiveScenarioFromCurrent() -> void`

Overwrites the active scenario's fields with the current live state while
preserving its id, label, and notes.

### `handleDeleteScenario() -> void`

Removes the active scenario. No-op if only one scenario remains. Activates the
first remaining scenario.

### `handleRenameScenario(scenarioId, label) -> void`

Updates the label in-place; falls back to the existing label if `label.trim()`
is empty.

### `handleScenarioNotesChange(scenarioId, notes) -> void`

Updates the `notes` field on the named scenario.

---

## useMemo-derived values

### `displayResults`

**Type:** `RunResults | null`

The processed result fed to all analytics components. Derived from `results`,
`analyticsModel`, and frozen derivation context. Two paths:

- Non-pathway: calls `withDerivedAssetDetails(analyticsModel, results, currencySymbol)`.
- Pathway: calls `deriveRunResults(analyticsModel, outputs, {carbonPrice, currencySymbol, discountRate, snapshotWeight, selectedPeriod, pathway, rolling})` and merges its output with raw pathway/rolling/plugin analytics from `results`.

Recomputes when `results`, `analyticsModel`, currency, carbon price, discount
rate, snapshot weight, or `pathwayConfig` change.

### `analyticsModel`

**Type:** `WorkbookModel`

`resultsModel ?? model`. The topology that owns the currently displayed results.
Analytics (map geometry, asset derivation) always use this, not the live
editable model, so a user can edit buses without corrupting the active result
display.

### `bounds` / `busIndex`

Geographic bounding box and name-to-row lookup derived from `model.buses`.
Analogues `analyticsBounds` / `analyticsBusIndex` are derived from
`analyticsModel.buses`.

### `activeScenario`

The `ScenarioPreset` whose `id` matches `scenarioCatalog.activeScenarioId`, or
`null`.

### `scenarioDirty`

`boolean`. True when the live slider state differs from `activeScenario`
(JSON comparison via `captureCurrentScenario`).

---

## Plugin host wiring

`App.tsx` calls `useFrontendPlugins()` once at the root level and stores the
result in `frontendPlugins`. This value is passed as `host` to `PluginsView`,
which passes it to `PluginDetail`. All plugin installs, uninstalls, config
reads, and config writes go through `host`; none of them touch the Ragnarok
backend.

There are no App-level plugin handler functions — `PluginsView` calls
`host.install`, `host.uninstall`, `host.setConfigField`, etc. directly via the
`FrontendPluginHost` it receives.

---

## Internal helpers

### `prepareModelForBackend(source) -> WorkbookModel`

Deep-clones `source` and applies `normalizeInputDatesToIso` with the current
`settings.dateFormat`. Called before every backend POST to ensure canonical ISO
timestamps reach the solver.

### `resetForNewModel(nextModel, name?) -> void`

Single choke-point for all model-load paths (open, import, import project,
demo, plugin preview, history restore). Actions:
1. Normalises input dates to ISO.
2. Reads snapshot range, pathway config, rolling config, scenario catalog from the model.
3. Resets `results`, `resultsModel`, `resultsContext`, `runStatus`,
   `chartSections`, `validateResult`, `analyticsFocus`, `projectProvenance`.
4. Does NOT clear `runHistory` — prior runs remain for comparison.
5. Applies the active imported scenario (or a default) to live sliders.

### `stopPolling() -> void`

Clears the polling timer (`pollTimerRef.current`). Called before cancel and on
unmount.

### `handleImportTsSheet(sheet, rows) -> void`

Canonicalises rows via `canonicalizeTemporalRows` and replaces `model[sheet]`
in place. Used by both `BuildView` and `ModelView` for per-sheet CSV imports.
