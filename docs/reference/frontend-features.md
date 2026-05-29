# frontend-features.md

Function reference for `frontend/Ragnarok_default/src/features/`.

Each feature folder owns one logical concern. Components receive callbacks from
`App.tsx` and do not mutate shared state directly.

---

## `features/run/RunDialog.tsx`

### `RunDialog`

Modal dialog for configuring and triggering a solve. Renders as an overlay
when `open` is true; returns `null` otherwise. Clicking the backdrop calls
`onClose`.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `open` | `boolean` | Whether the dialog is visible |
| `onClose` | `() => void` | Called on backdrop click or Cancel button |
| `forceLp` | `boolean` | Current Force LP toggle state |
| `dryRun` | `boolean` | Current Dry Run toggle state |
| `activeScenarioLabel` | `string \| null` | Label of the active scenario, shown in Planning summary |
| `activeConstraintCount` | `number` | Number of enabled constraints, shown in Planning summary |
| `snapshotStart` | `number` | Snapshot window start index |
| `snapshotEnd` | `number` | Snapshot window end index |
| `snapshotWeight` | `number` | Snapshot weight (hours per snapshot) |
| `pathwayConfig` | `PathwayConfig` | Used to decide whether to show "N pathway periods" |
| `rollingConfig` | `RollingHorizonConfig` | Used to show rolling horizon summary |
| `onForceLpChange` | `(v: boolean) => void` | Toggle Force LP |
| `onDryRunChange` | `(v: boolean) => void` | Toggle Dry Run |
| `onRun` | `() => void` | Called when "Run model" / "Validate" is clicked |

**Notes:** The primary action button label switches to `'Validate'` when
`dryRun` is true. The dialog does not own any state beyond the button and
field bindings it receives via props.

---

## `features/run-history/`

### `RunHistoryList`

Renders a vertical list of `RunHistoryCard` components, one per entry in
`runHistory`.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `runHistory` | `RunHistoryEntry[]` | Entries to display |
| `onRestoreRun` | `(entry) => void` | Called when "View results" is clicked |
| `onRenameHistoryEntry` | `(id, label) => void` | Commit a rename |
| `onPinHistoryEntry` | `(id, pinned) => void` | Pin/unpin an entry |
| `onDeleteHistoryEntry` | `(id) => void` | Delete an entry |
| `onToggleComparison` | `(id, inComparison) => void` | Toggle inclusion in Comparison tab |
| `currencySymbol` | `string` | Display symbol for carbon price KPI |

### `RunHistoryCard`

Single card displaying one `RunHistoryEntry`. Manages its own internal state
for inline label editing and delete confirmation.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `entry` | `RunHistoryEntry` | The run to display |
| `onView` | `() => void` | Restore this run |
| `onRename` | `(label) => void` | Commit edited label |
| `onPin` | `(pinned) => void` | Toggle pin |
| `onDelete` | `() => void` | Delete after confirming |
| `onToggleComparison` | `(inComparison) => void` | Comparison checkbox |
| `currencySymbol` | `string` | For carbon price display |

**Notes:** Label editing is inline — clicking the label text switches to an
`<input>` that commits on blur or Enter. Delete requires a two-step confirm.
Displays KPI summary items 3 (peak price) and 4 (system emissions) from
`entry.results.summary`.

### `RunComparisonTable`

Side-by-side comparison table for all entries in `runHistory` where
`inComparison === true`. Returns `null` when fewer than two entries exist.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `runHistory` | `RunHistoryEntry[]` | All history entries (filtered internally to `inComparison`) |
| `activeResults` | `RunResults` | The currently displayed run (marked "active") |
| `onToggleComparison` | `(id, inComparison) => void` | Remove a column from the table |
| `currencySymbol` | `string` | For carbon price row |

**Notes:** Entries are sorted newest-first. Each non-active column shows a
percentage-delta badge relative to the active run for every numeric KPI row.
Internal `parseNum` strips units/commas before computing deltas; internal
`delta(base, target)` returns `{text, dir}`.

---

## `features/analytics/AnalyticsPane.tsx`

### `AnalyticsPane`

Main analytics result panel rendered when `subTab === 'Result'` in
`AnalyticsView`. Hosts the `AnalyticsDashboard` and optionally a pathway period
selector strip.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `results` | `RunResults` | Derived results to display |
| `model` | `WorkbookModel` | Results-owning topology |
| `bounds` | `LatLngBoundsExpression \| null` | Map bounds for the analytics map |
| `busIndex` | `Record<string, GridRow>` | Bus name lookup for the analytics map |
| `analyticsFocus` | `AnalyticsFocus` | Currently focused asset or 'system' |
| `setAnalyticsFocus` | `(focus) => void` | Change the focused asset |
| `chartSections` | `ChartSectionConfig[]` | Dashboard chart layout |
| `setChartSections` | `Dispatch<SetStateAction<ChartSectionConfig[]>>` | Update chart layout |
| `dispatchRows` | `TimeSeriesRow[]` | Carrier dispatch series rows |
| `dispatchSeries` | `TimeSeriesSeries[]` | Series metadata for dispatch chart |
| `systemLoadRows` | `TimeSeriesRow[]` | Load time series |
| `systemPriceRows` | `TimeSeriesRow[]` | System price time series |
| `storageRows` | `TimeSeriesRow[]` | Aggregate storage series |
| `subTab` | `AnalyticsSubTab` | Controls which pane is visible |
| `currencySymbol` | `string` | Display currency |
| `pathwayConfig` | `PathwayConfig \| undefined` | Active pathway settings |
| `onSelectedPeriodChange` | `(period: number) => void \| undefined` | Called when a period pill is clicked |

### `EmptyAnalytics`

Simple placeholder component returned when no results exist yet. Renders a
heading and short instructions asking the user to run the model.

---

## `features/analytics/ComparisonPane.tsx`

Renders `RunComparisonTable` wrapped in a pane container. Receives the same
run history props as `AnalyticsView`.

---

## `features/analytics/useMetricOptions.ts`

### `useMetricOptions(results, ...) -> MetricOption[]`

Hook that derives the list of metric options (dispatch, price, storage, load,
emissions) available for the interactive chart cards. Returns memoized options
based on current results and dispatch rows.

---

## `features/build/BuildView.tsx`

### `BuildView`

Guided wizard for constructing a PyPSA model from scratch. Renders a horizontal
step strip, a `TablesPane` scoped to the active step's sheet, a schema/issue
detail pane, and a `BuildNetworkMap`.

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
| `currencySymbol` | `string` | For CAPEX/cost columns |
| `dateFormat` | `DateFormat` | For snapshot parsing |
| `onOpenRunSetup` | `() => void \| undefined` | Open the run dialog |

**Notes:** Each build step (defined in `steps.ts`) maps to one or two schema
sheets in dependency order: Network → Carriers → Buses → Generators →
Loads → Storage → Lines → Links → Transformers → Snapshots → Review.
Switching steps does not reset the model. An auto-naming helper generates
default names like `bus1`, `gen2` when a new row is added on the map.

### `BUILD_STEPS` (from `steps.ts`)

Array of `BuildStep` objects defining the build wizard order. Each step has
`id`, `label`, `sheets`, `description`, and `helpText`.

### `getStepIssues(step, modelIssues) -> ModelIssue[]`

Filters `modelIssues` to only those belonging to the step's sheets.

---

## `features/build/BuildNetworkMap.tsx`

### `BuildNetworkMap`

Interactive Leaflet map for the Build wizard. Displays buses, generators,
loads, storage units, stores, lines, links, and transformers. The active step's
layer is fully interactive; all other layers render as faint context.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `model` | `WorkbookModel` | Current topology |
| `activeSheet` | `string` | Sheet being edited in the current build step |
| `selectedRowIndex` | `number \| null` | Highlighted row |
| `onSelectRow` | `(rowIndex: number) => void` | Row selection callback |
| `onPlaceComponent` | `(lat, lng) => void` | Right-click to place a new component |
| `onUpdateCoords` | `(sheet, rowIndex, x, y) => void` | Drag a marker to update x/y |
| `onLinkToBus` | `(rowIndex, busName) => void` | Link mode — attach component to bus |
| `linkMode` | `LinkMode` | Whether link-to-bus mode is active |
| `onLinkModeChange` | `(mode: LinkMode) => void` | Toggle link mode |

**Exported constants:**
- `BRANCH_SHEETS` — `Set<string>`: `{'lines', 'links', 'transformers'}`.
- `isGeoSheet(sheet) -> boolean` — true for sheets that support map placement.
- `LinkMode` — `'off' | 'active'`.

**Notes:** Component placement works by right-click on the map. Dragging a
marker fires `onUpdateCoords` with the new lat/lng (stored as `y`/`x` on the
row). Branch (line/link/transformer) placement is from bus to bus. Dashed
connectors appear between a point component and its bus once a bus reference
is set. Unlike the analytics map, this component is results-agnostic — it
only reads the `WorkbookModel`.

---

## `features/build/BuildDetailPane.tsx`

Displays schema documentation and validation issues for the active build step.
No significant exported logic; purely presentational.

---

## `features/build/BuildAttributeForm.tsx`

Inline attribute form shown when a row is selected on the build map. Renders
schema-driven field inputs for the selected row. No significant exported logic.

---

## `features/constraints/GlobalConstraintsSection.tsx`

Renders a table for adding and editing `CustomConstraint` rows (metric, carrier,
value, unit, enabled toggle). Lifted into `SettingsView` for the Constraints
section.

---

## `features/input/TablesPane.tsx`

### `TablesPane`

The central table editor. Renders a component-level navigation rail (sheet
selector) on the left and a `DataGrid` for the selected sheet on the right,
wrapped in `ResizablePanels`. For temporal sheets, also renders an
`InputAnalyser` above the grid.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `model` | `WorkbookModel` | Full model for row data and TS lookup |
| `sel` | `TableSel` | Currently selected sheet and kind (`static` / `temporal`) |
| `onSelChange` | `(sel) => void` | Sheet selection change |
| `onUpdate` | `(sheet, rowIndex, col, val) => void` | Cell edit |
| `onAddRow` | `(sheet) => void` | Add row |
| `onDeleteRow` | `(sheet, rowIndex) => void` | Delete row |
| `onAddColumn` | `(sheet, col, defaultValue) => void` | Add column |
| `onDeleteColumn` | `(sheet, col) => void` | Delete column |
| `onRenameColumn` | `(sheet, oldCol, newCol) => void` | Rename column |
| `onClearTable` | `(sheet) => void` | Clear all rows |
| `onImportTsSheet` | `(sheet, rows) => void` | CSV import |
| `onBulkPaste` | `(sheet, edits, extraRows) => void` | Multi-cell paste |
| `modelIssues` | `ModelIssue[]` | Highlighted cells |
| `jumpTo` | `{sheet, rowIndex} \| null` | Scroll to a specific row |
| `currencySymbol` | `string` | For cost column display |
| `dateFormat` | `DateFormat` | For snapshot parsing |

**Notes:** `mergeTypeNames` (internal) merges user-defined `line_types` and
`transformer_types` rows with the PyPSA standard catalogue to seed
`<datalist>` autocomplete for the `type` column.

---

## `features/input/grid/DataGrid.tsx`

### `DataGrid`

Low-level spreadsheet grid. Renders rows and columns as a styled `<table>`.
Handles single-cell edits, keyboard navigation, multi-cell selection, and
clipboard paste (parsed via `tsv.ts`). Highlights cells with model issues.

---

## `features/input/grid/range.ts`

### Exported functions

- `parseRange(sel) -> {start, end}` — parses a selection range object.
- `selectionToEdits(selection, parsedTsv, sheet, rows, columns) -> {rowIndex, col, val}[]` — maps a clipboard paste onto the correct grid cells, expanding the selection.

---

## `features/input/tsv.ts`

### `parseTsv(text) -> string[][]`

Parses a tab-separated value string (e.g. from clipboard) into a 2D array.
Handles quoted fields with embedded tabs and newlines.

---

## `features/map/MapPane.tsx`

### `MapPane`

Read-only Leaflet map displaying the model topology from the input workbook.
Shows buses as circle markers, generators and loads as smaller markers, and
lines/links/transformers as polylines. Togglable layers per component type.
No results required.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `model` | `WorkbookModel` | Topology to render |
| `bounds` | `LatLngBoundsExpression \| null` | Auto-fit viewport |
| `busIndex` | `Record<string, GridRow>` | Bus coordinate lookup |

**Internal helpers:**
- `ownCoords(row)` — extracts `[lat, lng]` from a row's `x`/`y` fields.
- `resolveCoords(row, bus, offset?)` — component coordinates: own first, then
  bus coords plus a small offset so stacked components don't overlap.

---

## `features/map/FitToBounds.tsx`

### `FitToBounds`

Leaflet child component that calls `map.fitBounds(bounds)` whenever `bounds`
changes. Prevents zoom animation via `NoZoomAnimation`.

---

## `features/map/MapLegend.tsx`

### `MapLegend`

Static legend overlay for the model topology map. Labels each component type
with its colour.

---

## `features/map/NoZoomAnimation.tsx`

### `NoZoomAnimation`

Disables Leaflet's CSS zoom animation (`zoomAnimation: false`) for the map
instance. Prevents jarring tile flicker during programmatic bounds fitting.

---

## `features/modules/useModuleHost.ts`

### `useModuleHost() -> ModuleHost`

Hook that manages the pluggable module system. On mount, fetches the module
inventory from `/api/modules` and pruning enabled IDs that are no longer
eligible.

**Returned object:**

| Field | Type | Meaning |
|---|---|---|
| `inventory` | `ModuleHostInventory \| null` | Raw inventory from the backend |
| `modules` | `ModuleDescriptor[]` | All discovered modules |
| `loading` | `boolean` | Inventory fetch in progress |
| `error` | `string \| null` | Last fetch error message |
| `enabledIds` | `string[]` | IDs of enabled + eligible modules |
| `moduleConfigs` | `Record<string, Record<string, unknown>>` | Per-module config values |
| `isEnabled(moduleId)` | `(string) => boolean` | Whether a module is in the enabled set |
| `isEnableEligible(module)` | `(ModuleDescriptor) => boolean` | `status === 'ready' && valid && compatible && entryExists` |
| `toggleEnabled(moduleId, enabled)` | `(string, boolean) => void` | Enable/disable a module; persists to `localStorage` |
| `setModuleConfig(moduleId, key, value)` | `(string, string, unknown) => void` | Update one config field; persists non-File values to `localStorage` |
| `installFromFile(file)` | `(File) => Promise<{ok, error?, moduleId?}>` | POST a zip to `/api/modules/install`; refreshes inventory on success |
| `uninstall(moduleId)` | `(string) => Promise<{ok, error?}>` | DELETE `/api/modules/:id`; removes from enabled set and refreshes inventory |

**Notes:** Module configs with `File` values are stripped before persisting to
`localStorage` so large binary blobs are never stored. Enabled IDs that fail
the `isEnableEligible` check are automatically removed when the inventory is
refreshed.

---

## `features/modules/ModuleManagerSection.tsx`

### `ModuleManagerSection`

Sidebar section listing all discovered modules with enable/disable toggles,
install button, and per-module uninstall. Delegates all mutations to callbacks
from `useModuleHost`.

### `ConfigFieldRow`

Renders a single module config field row (text, number, boolean toggle, file
picker, or action button). Exported so `PluginPanel` can reuse it.

---

## `features/plugins/PluginPanel.tsx`

### `PluginPanel`

Main panel area for enabled plugin modules. Renders one tabbed card per enabled
module. Each card has Description / Input / Output inner tabs. The Output tab
renders plugin analytics using `PluginFieldHint` metadata for chart types.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `modules` | `ModuleDescriptor[]` | Enabled modules to render |
| `moduleConfigs` | `Record<string, Record<string, unknown>>` | Config values per module |
| `onModuleConfigChange` | `(moduleId, key, value) => void` | Config field change |
| `onModuleAction` | `(moduleId, fieldKey, field) => Promise<void>` | Action button handler |
| `displayResults` | `RunResults \| null` | Passed through for plugin output rendering |

---

## `features/settings/useSettings.ts`

### `useSettings() -> [AppSettings, (patch: Partial<AppSettings>) => void]`

Hook that loads `AppSettings` from `localStorage` on mount and provides a
stable `updateSettings` callback. Settings are persisted on every update.

`AppSettings` fields:

| Field | Type | Default |
|---|---|---|
| `dateFormat` | `DateFormat` | `'auto'` |
| `solverThreads` | `number` | `0` (let HiGHS decide) |
| `solverType` | `SolverType` | `'simplex'` |
| `currencyCode` | `string` | `'USD'` |
| `currencySymbol` | `string` | `'$'` |
| `enableLoadShedding` | `boolean` | `false` |
| `loadSheddingCost` | `number` | VOLL in selected currency per MWh |
| `discountRate` | `number` | 0.05 |

---

## `features/validation/ValidationPane.tsx`

### `ValidationPane`

Displays model issues from `useModelIssues` and optionally a backend validation
result. Issues are shown as a scrollable list (truncated to 20 by default, with
a "Show all" toggle). Each issue item is a clickable link that navigates to the
relevant sheet and row via `onNavigate`.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `validateResult` | `ValidationResult \| null` | Backend dry-run result |
| `issues` | `ModelIssue[]` | Client-side model issues from `useModelIssues` |
| `onValidate` | `() => void` | Trigger a dry run |
| `onRun` | `() => void` | Open the run dialog |
| `onNavigate` | `(sheet, rowIndex) => void` | Navigate Model tab to a row |

---

## `features/validation/useModelIssues.ts`

### `useModelIssues(model) -> ModelIssue[]`

**Params:** `model` — `WorkbookModel`.

Returns a memoized array of `ModelIssue` objects. Runs a suite of schema-driven
checks on every update to `model`:

- **Duplicate names** — error if two rows in the same sheet share a `name`.
- **Required fields** — error if a required attribute is blank.
- **Bus references** — error if `bus`, `bus0`, `bus1`, etc. name a bus that
  does not exist in the `buses` sheet.
- **Type references** — warning if `lines.type` or `transformers.type` is not
  in the combined user-defined + PyPSA standard type catalogue.
- **Non-negative attributes** — error if `p_nom`, `capital_cost`, etc. are
  negative.
- **Per-unit range** — warning if `*_pu` attributes fall outside `[0, 1]`.
- **Efficiency range** — warning if `efficiency > 5` (likely in % not ratio).
- **CO2 emissions magnitude** — warning if `co2_emissions > 5` (likely wrong
  units).
- **Carrier cross-reference** — warning if a `carrier` field names a carrier
  absent from the `carriers` sheet.
- **Temporal sheet checks** — row count vs snapshot count mismatch, missing
  snapshot label column, unknown component column names, out-of-range per-unit
  or load values.

`ModelIssue` shape: `{sheet, rowIndex, col?, severity: 'error'|'warning', message}`.
