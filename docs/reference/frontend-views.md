# frontend-views.md

Function reference for `frontend/Ragnarok_default/src/views/`.

Views are thin shell components. They own layout and local selection state;
all data mutations are delegated to callbacks received as props from `App.tsx`.

---

## `views/ModelView.tsx`

### `ModelView`

The workbook input editor. Three resizable columns: `SheetTree` (left),
`TablesPane` (centre), `MapPane` (right). `FileToolbar` sits above the columns.

`ModelView` owns only one piece of local state: `sel: TableSel`, the currently
selected sheet and kind (`'static'` or `'temporal'`). All other state is held
in `App.tsx` and passed down.

**Key props** (extends `FileToolbarProps`):

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
| `onOpen` | `() => void` | Open workbook |
| `onSave` | `() => void` | Save workbook |
| `onSaveAs` | `() => void` | Save As workbook |
| `onImportProject` | `() => void` | Trigger project import input |
| `onExportProject` | `() => void` | Export project |
| `onExportResult` | `() => void` | Export result workbook |
| `onImportCsvFolder` | `() => void` | Trigger CSV zip import input |
| `onExportCsvFolder` | `() => void` | Export CSV zip |
| `onImportNetcdf` | `() => void` | Trigger netCDF import input |
| `onExportNetcdf` | `() => void` | Export netCDF |
| `onImportHdf5` | `() => void` | Trigger HDF5 import input |
| `onExportHdf5` | `() => void` | Export HDF5 |

**Notes:** The view is a layout shell. It delegates to `FileToolbar` for file
operations, `SheetTree` for navigation, `TablesPane` for editing, and
`MapPane` for the topology preview. Column widths are managed by
`ResizablePanels` with initial sizes `[20, 40, 40]`.

---

## `views/ModelView.features/FileToolbar.tsx`

### `FileToolbar`

The file-operation toolbar that sits at the top of `ModelView`. This is the
only place file-op buttons exist in the entire UI.

**Key props** (`FileToolbarProps`):

| Prop | Type | Meaning |
|---|---|---|
| `hasResults` | `boolean` | If false, disables the Export Result button |
| `onOpen` | `() => void` | Open an `.xlsx` workbook |
| `onSave` | `() => void` | Save current workbook |
| `onSaveAs` | `() => void` | Save As (always prompts for a path) |
| `onImportProject` | `() => void` | Import a project `.xlsx` |
| `onExportProject` | `() => void` | Export the current run as a project |
| `onExportResult` | `() => void` | Export the result workbook |
| `onImportCsvFolder` | `() => void` | Import a PyPSA CSV folder `.zip` |
| `onExportCsvFolder` | `() => void` | Export a PyPSA CSV folder `.zip` |
| `onImportNetcdf` | `() => void` | Import a `.nc` file via the backend |
| `onExportNetcdf` | `() => void` | Export a `.nc` file via the backend |
| `onImportHdf5` | `() => void` | Import a `.h5` / `.hdf5` file via the backend |
| `onExportHdf5` | `() => void` | Export a `.h5` file via the backend |

**Notes:** The less-common formats (CSV folder, netCDF, HDF5) are grouped
under a `<details>` disclosure element labelled "More formats…" to keep the
primary toolbar uncluttered.

---

## `views/ModelView.features/SheetTree.tsx`

### `SheetTree`

Left-column component navigator. Shows only groups where the static sheet or
at least one temporal sheet has data. Supports a text filter (search box)
and collapsible groups.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `model` | `WorkbookModel` | Used to check which sheets have data |
| `issues` | `ModelIssue[]` | Per-sheet error/warning badge counts |
| `sel` | `TableSel` | Currently selected sheet |
| `onSelChange` | `(sel) => void` | Selection change callback |

**Internal state:**
- `navSearch` — filter text; groups not matching are hidden.
- `collapsed` — set of group sheet names that are folded.

**Notes:** Issue badge counts are memoized from `ModelIssue[]`. Groups are
defined by `TABLE_GROUPS` from `constants/index.ts`.

---

## `views/AnalyticsView.tsx`

### `AnalyticsView`

Results and validation dashboard with four sub-tabs: Validation, Result,
Analytics, Comparison. The view owns no local state; sub-tab routing is driven
by `analyticsSubTab` from `App.tsx`.

The layout has a left sidebar with `RunHistoryList` and a main area with the
active sub-tab body and `AnalyticsSubnav`.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `analyticsSubTab` | `AnalyticsSubTab` | Active sub-tab |
| `onAnalyticsSubTabChange` | `(s) => void` | Sub-tab switch |
| `validateResult` | `ValidationResult \| null` | Backend dry-run result |
| `modelIssues` | `ModelIssue[]` | Client-side issues for Validation tab |
| `onValidate` | `() => void` | Trigger dry run |
| `onRun` | `() => void` | Open run dialog |
| `onNavigateToTable` | `(sheet, rowIndex) => void` | Jump to Model tab row |
| `displayResults` | `RunResults \| null` | Derived results |
| `filename` | `string` | Current workbook filename |
| `model` | `WorkbookModel` | Results-owning topology |
| `bounds` | `LatLngBoundsExpression \| null` | Analytics map bounds |
| `busIndex` | `Record<string, GridRow>` | Bus lookup for analytics map |
| `analyticsFocus` | `AnalyticsFocus` | Focused asset |
| `setAnalyticsFocus` | `(focus) => void` | Focus change |
| `chartSections` | `ChartSectionConfig[]` | Dashboard chart layout |
| `setChartSections` | `Dispatch<...>` | Update layout |
| `dispatchRows` | `TimeSeriesRow[]` | Carrier dispatch series |
| `dispatchSeries` | `TimeSeriesSeries[]` | Chart series metadata |
| `systemLoadRows` | `TimeSeriesRow[]` | Load series |
| `systemPriceRows` | `TimeSeriesRow[]` | Price series |
| `storageRows` | `TimeSeriesRow[]` | Storage series |
| `runHistory` | `RunHistoryEntry[]` | All history entries |
| `currencySymbol` | `string` | Display currency |
| `pathwayConfig` | `PathwayConfig` | Period selector state |
| `onSelectedPeriodChange` | `(period) => void` | Period pill click |
| `onExportAll` | `() => void` | Export result workbook |
| `onToggleComparison` | `(id, inComparison) => void` | Comparison checkbox |
| `onRestoreRun` | `(entry) => void` | View a past run |
| `onRenameHistoryEntry` | `(id, label) => void` | Rename history entry |
| `onPinHistoryEntry` | `(id, pinned) => void` | Pin/unpin |
| `onDeleteHistoryEntry` | `(id) => void` | Delete entry |
| `onClearHistory` | `() => void` | Clear all history |

**Sub-tab routing:**
- `'Validation'` → `ValidationPane`
- `'Result'` → `AnalyticsPane` (or `EmptyAnalytics` when no results)
- `'Analytics'` → `AnalyticsDashboard` (custom drag/drop dashboard)
- `'Comparison'` → `ComparisonPane`

---

## `views/AnalyticsView.features/AnalyticsSubnav.tsx`

### `AnalyticsSubnav`

Horizontal sub-tab navigation bar rendered above the analytics main area.
Displays the four sub-tab labels with optional issue/validation badges.

---

## `views/AnalyticsView.features/Dashboard/AnalyticsDashboard.tsx`

### `AnalyticsDashboard`

Drag-and-drop dashboard for the Analytics sub-tab. Manages a grid layout of
chart cards (capacity, dispatch, price, emissions, merit order, etc.). Users
can add, remove, and reorder cards.

---

## `views/AnalyticsView.features/Dashboard/Dashboard.tsx`

### `Dashboard`

Core drag-and-drop grid container. Renders `DashboardCard` items in a CSS grid
and handles drop events to reorder cards.

---

## `views/AnalyticsView.features/Dashboard/useDashboardLayout.ts`

### `useDashboardLayout(storageKey, defaultLayout) -> [layout, setLayout, resetLayout]`

**Params:** `storageKey` — `string`; `defaultLayout` — initial card configuration.

Hook that persists the dashboard card layout to `localStorage`. Returns the
current layout, a setter, and a reset-to-default function.

---

## `views/AnalyticsView.features/Dashboard/presets.ts`

Exports `PRESETS`: an array of named dashboard preset configurations (e.g.
"Overview", "Capacity", "Dispatch"). Each preset is a list of card descriptors
that `useDashboardLayout` can restore.

---

## `views/AnalyticsView.features/Dashboard/result-preset.ts`

### `buildResultPreset(results) -> DashboardPreset`

**Params:** `results` — `RunResults`.

Builds a dashboard preset tailored to the specific results: includes capacity
expansion cards only when extendable assets exist, pathway cards only for
multi-period solves, etc.

---

## `views/SettingsView.tsx`

### `SettingsView`

Left section-nav + active section editor for all solver configuration. The
view owns only one piece of local state: `activeSection: SectionId` (the
currently visible section). Each section is a separate component under
`SettingsView.sections/`.

**Section groups and IDs:**

| Group | Sections |
|---|---|
| Setup | `scenarios`, `window` |
| Policy | `carbon`, `planning`, `rolling`, `stochastic`, `sclopf`, `constraints` |
| Solve | `solver` |
| App | `appearance`, `projectDefaults` |

**Key props (representative selection):**

| Prop | Type | Meaning |
|---|---|---|
| `model` | `WorkbookModel` | Read-only access for carrier rows and component counts |
| `scenarioCatalog` | `ScenarioCatalog` | Scenario list |
| `activeScenarioLabel` | `string \| null` | Label of the active scenario |
| `scenarioDirty` | `boolean` | Whether live state differs from the active scenario |
| `pathwayConfig` | `PathwayConfig` | Multi-period settings |
| `rollingConfig` | `RollingHorizonConfig` | Rolling horizon settings |
| `stochasticConfig` | `StochasticConfig` | Stochastic scenario settings |
| `sclopfConfig` | `SecurityConstrainedConfig` | SCLOPF settings |
| `maxSnapshots` | `number` | Upper bound for snapshot sliders |
| `snapshotStart/End/Weight` | `number` | Run window sliders |
| `carbonPrice` | `number` | Carbon price slider |
| `carbonPriceSchedule` | `CarbonPriceScheduleEntry[]` | Per-period carbon prices |
| `constraints` | `CustomConstraint[]` | Custom constraint rows |
| `dateFormat` | `DateFormat` | Date format selector |
| `currencyCode/Symbol` | `string` | Currency selector |
| `discountRate` | `number` | CAPEX annualisation rate |
| `enableLoadShedding` | `boolean` | Load shedding toggle |
| `loadSheddingCost` | `number` | VOLL |
| `solverThreads` | `number` | HiGHS thread count |
| `solverType` | `SolverType` | `'simplex' \| 'ipm'` |
| `onSelectScenario` | `(id) => void` | Apply a scenario by id |
| `onCreateScenarioFromCurrent` | `() => void` | Save current state as new scenario |
| `onDuplicateScenario` | `() => void` | Clone active scenario |
| `onUpdateActiveScenarioFromCurrent` | `() => void` | Overwrite active scenario from current state |
| `onDeleteScenario` | `() => void` | Delete active scenario |
| `onRenameScenario` | `(id, label) => void` | Rename scenario |
| `onScenarioNotesChange` | `(id, notes) => void` | Edit scenario notes |

**Notes:** The view is a pure layout shell. All settings mutations go through
the callbacks, which live in `App.tsx` and apply to the shared state.
`SettingsView` never calls `setModel` directly.

---

## `views/SettingsView.sections/`

Each section is a self-contained form component receiving its relevant slice
of props from `SettingsView`. Sections do not communicate with each other.

| File | Section | Purpose |
|---|---|---|
| `Scenarios.tsx` | scenarios | Scenario catalog management |
| `Window.tsx` | window | Snapshot range and weight sliders |
| `Carbon.tsx` | carbon | Carbon price and per-period schedule |
| `Planning.tsx` | planning | Pathway period table and mapping mode |
| `Rolling.tsx` | rolling | Rolling horizon toggle and window parameters |
| `Stochastic/Stochastic.tsx` | stochastic | Stochastic scenario enable + scenario rows |
| `Sclopf.tsx` | sclopf | Security-constrained LP/OPF toggle |
| `Constraints.tsx` | constraints | Custom constraint table |
| `Solver.tsx` | solver | Solver type, thread count |
| `Appearance.tsx` | appearance | Currency and carrier colour overrides |
| `ProjectDefaults.tsx` | projectDefaults | Date format and load shedding defaults |

---

## `views/PluginsView.tsx`

### `PluginsView`

Two-column view: an install/select rail on the left and `PluginDetail` in the
main area. When no plugins are installed, shows a placeholder message with
instructions. Plugins run entirely in the browser and never contact the
Ragnarok backend.

**Key props:**

| Prop | Type | Meaning |
|---|---|---|
| `host` | `FrontendPluginHost` | Plugin host from `useFrontendPlugins()` |
| `model` | `WorkbookModel` | Live workbook — passed through to `PluginDetail` |
| `onReplaceModel` | `(next: WorkbookModel) => void` | Called when a plugin replaces the workbook |
| `onMergeSheets` | `(sheets) => void` | Called when a plugin contributes sheets |
| `customDsl` | `string` | Current constraint DSL text |
| `onCustomDslChange` | `(text: string) => void` | Called when a plugin appends constraint lines |
| `results` | `unknown` | Last run results — passed to the plugin `analyze` hook |

**Left rail behaviour:**
- An "Install plugin…" button opens a hidden `<input type="file" accept=".zip">`.
  On selection, calls `host.install(file)`. Success toasts with the installed id;
  the new plugin is selected automatically.
- Each installed plugin appears as a button. Clicking selects it; the `x`
  button calls `host.uninstall(id)` and clears the selection if it was active.
- There is no enable/disable toggle — every installed plugin is immediately
  available.

**Notes:** `host.installed` is the sole source of truth for the list. The view
owns only one piece of local state: `selectedId`, the id of the plugin whose
`PluginDetail` is shown in the main area.
