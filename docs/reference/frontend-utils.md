# frontend-utils.md

Function reference for `frontend/Ragnarok_default/src/shared/utils/`.

---

## `workbook.ts`

Handles all XLSX read/write and the project round-trip format. Every temporal
sheet is canonicalised on entry (ISO-8601 `T`-separated snapshot values, with
`period?` then `snapshot` as leading columns) regardless of the path it came
in through.

### Sheet name constants (exported)

`RESULT_META_SHEET`, `PLUGIN_ANALYTICS_SHEET`, `SETTINGS_SHEET`,
`CONSTRAINTS_SHEET`, `RUN_STATE_SHEET`, `RUN_HISTORY_SHEET`,
`PROVENANCE_SHEET` — names of Ragnarok-private metadata sheets appended to
project workbooks.

### `normalizeCell(value) -> Primitive`

Converts a raw SheetJS cell value (`unknown`) to a `Primitive`. Handles
`number`, `boolean`, `string`, and JavaScript `Date` objects (produced by
SheetJS when `cellDates: true`; emitted as ISO `YYYY-MM-DDThh:mm:ss`). Falls
back to `String(value)`.

### `hasSnapshotColumn(rows) -> boolean`

Returns `true` if any row in `rows` has a key named `'snapshot'`. Used to
self-gate temporal canonicalisation — sheets without a `snapshot` column are
never mutated.

### `orderTemporalRow(row) -> GridRow`

Returns a copy of `row` with `period` (if present) then `snapshot` as the
first two keys, followed by the remaining keys in original order. Produces
stable PyPSA-conventional column ordering for SheetJS export.

### `canonicalizeTemporalRows(rows, fmt) -> GridRow[]`

**Params:** `rows` — `GridRow[]`; `fmt` — `DateFormat`.

Returns a new array. For each row, converts `snapshot` from string, JS `Date`,
or Excel serial number to ISO `YYYY-MM-DDThh:mm:ss`, then re-orders columns
via `orderTemporalRow`. Rows without a `snapshot` key are returned unchanged.
Idempotent: already-canonical values pass through as-is.

`prepareTemporalRowsForExport` is an alias exported for back-compat.

### `canonicalizeTemporalSheets(sheets, fmt) -> void`

**Params:** `sheets` — `Record<string, GridRow[] | undefined>`; `fmt` — `DateFormat`.

Applies `canonicalizeTemporalRows` in place to every sheet that has a `snapshot`
column. Static sheets are untouched. Idempotent.

### `canonicalizeOutputSeries(series, fmt) -> void`

**Params:** `series` — `Record<string, GridRow[]>`; `fmt` — `DateFormat`.

Thin wrapper around `canonicalizeTemporalSheets` scoped to `outputs.series`.
Called after every backend run result and project import.

### `normalizeInputDatesToIso(model, fmt) -> void`

**Params:** `model` — `WorkbookModel`; `fmt` — `DateFormat`.

Applies `canonicalizeTemporalSheets` to the whole model in place. Called at
every model-load boundary (`handleOpenWorkbook`, `handleImportProject`,
`resetForNewModel`, CSV/netCDF/HDF5 import).

### `temporalHeader(rows) -> string[]`

Returns the stable column header for temporal export: `['period'?,'snapshot', ...rest]`.
Used by `temporalSheetToWorksheet` to fix column order before passing to SheetJS.

### `createEmptyWorkbook() -> WorkbookModel`

Returns a `WorkbookModel` with every known sheet key (`SHEETS`, `TS_SHEETS`,
pathway, rolling, scenario internal sheets) initialised to `[]`.

### `parseSheets(workbook) -> WorkbookModel`

**Params:** `workbook` — SheetJS workbook object.

Iterates all sheet names, normalises each name via `normalizeSheetName`, and
converts rows to `GridRow[]` via `normalizeCell`. Returns a `WorkbookModel`.

### `parseWorkbook(file) -> Promise<WorkbookModel>`

Reads a `File` as `ArrayBuffer` via `FileReader`, calls `XLSX.read` with
`cellDates: true`, and delegates to `parseSheets`. Rejects on read error or
parse failure.

### `buildWorkbook(model, dateFormat?) -> XLSX.WorkBook`

**Params:** `model` — `WorkbookModel`; `dateFormat` — `DateFormat` (default `'auto'`).

Constructs a SheetJS workbook from the model:
- Static sheets (`SHEETS`): strips output-static attributes, skips empty sheets.
- Time-series sheets (`TS_SHEETS` + any dynamic temporal sheets): prepares with
  `prepareTemporalRowsForExport`.
- Internal Ragnarok sheets (pathway, rolling, scenarios): appended as-is.

### `exportWorkbook(model, filename?, dateFormat?) -> void`

Calls `buildWorkbook` then `XLSX.writeFile`. Triggers a browser download.

### `workbookToArrayBuffer(model, dateFormat?) -> ArrayBuffer`

Calls `buildWorkbook` then `XLSX.write` with `{bookType: 'xlsx', type: 'array'}`.
Returns the raw bytes. Used by `saveWorkbook` / `saveAsWorkbook` to write via
the File System Access API.

### `parseDelimitedTextToGridRows(text) -> GridRow[]`

Parses a CSV or TSV string via SheetJS. Column 0 is kept as `string` (snapshot
label); all other columns are cast to `number` where parseable, otherwise kept
as `string`. Handles BOM and auto-detects delimiter.

### `parseCsvToGridRows(file) -> Promise<GridRow[]>`

Reads a `File` as text and calls `parseDelimitedTextToGridRows`.

### `buildProjectWorkbook(model, outputs?, metadata?) -> XLSX.WorkBook`

**Params:**
- `model` — `WorkbookModel`: input data.
- `outputs` — `ProjectOutputs`: solver outputs to embed (`static` + `series`).
- `metadata` — `ProjectMetadata`: settings, constraints, run state, provenance.

Builds the full project `.xlsx`:
1. Static component sheets: input columns merged with output-static columns
   (`p_nom_opt` etc.) per component name. Components present in outputs but
   not inputs (e.g. auto-added load-shedding generators) are appended as extra
   rows.
2. Input time-series sheets.
3. Output time-series sheets.
4. Internal config sheets (pathway, rolling, scenarios).
5. Metadata sheets: `RAGNAROK_ResultMeta`, `RAGNAROK_PluginAnalytics`,
   `RAGNAROK_Settings`, `RAGNAROK_Constraints`, `RAGNAROK_RunState`,
   `RAGNAROK_Provenance`. Long JSON values are chunked across rows to respect
   Excel's 32 767-character cell limit.

### `projectWorkbookToArrayBuffer(model, outputs, metadata) -> ArrayBuffer`

Calls `buildProjectWorkbook` and serialises to bytes. The `outputs` and
`metadata` arguments are nullable; `null` falls back to empty objects.

### `parseProjectWorkbook(arrayBuffer) -> {model, outputs, metadata}`

**Params:** `arrayBuffer` — `ArrayBuffer`.

Reverses `buildProjectWorkbook`:
- Output time-series sheets (matching `<list>-<output_attr>`) are routed to
  `outputs.series`.
- Component sheets: output-static columns are split into `outputs.static`;
  input columns remain in `model`.
- Metadata sheets are parsed back into typed `ProjectMetadata` fields.
  Multi-chunk JSON values are reassembled in `part` order.

### `parseProjectFile(file) -> Promise<{model, outputs, metadata}>`

Async wrapper around `parseProjectWorkbook` using `FileReader`.

---

## `exportResults.ts`

Builds the standalone "result workbook" exported via the Export Result button.
All column widths are auto-fitted (capped at 40 chars).

### `buildFullResultsWorkbook(model, results) -> XLSX.WorkBook`

**Params:** `model` — `WorkbookModel`; `results` — `RunResults`.

Starts from `buildWorkbook(model)` (so all input sheets are included) then
appends `OUT_*` sheets:

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

### `fullResultsArrayBuffer(model, results) -> ArrayBuffer`

Calls `buildFullResultsWorkbook` and serialises to bytes for `saveFileWithPicker`.

---

## `csvFolder.ts`

PyPSA-native CSV folder import/export. Round-trips with
`pypsa.Network.import_from_csv_folder` / `export_to_csv_folder`. The zip
structure is `<archiveName>/<sheetName>.csv`.

### `exportModelAsCsvFolderBytes(model, archiveName) -> Uint8Array`

**Params:** `model` — `WorkbookModel`; `archiveName` — `string`.

Converts every known non-empty model sheet to CSV (via the internal `rowsToCsv`
function) and packs them into a deflated zip using `fflate.zipSync`. Only sheets
present in the known PyPSA name set are included; Ragnarok-private metadata
sheets are skipped.

### `exportModelAsCsvFolderZip(model, archiveName) -> Blob`

Calls `exportModelAsCsvFolderBytes` and wraps the bytes in a `Blob` of type
`application/zip`. Used by `handleExportCsvFolder` in `App.tsx`.

### `importCsvFolderZip(file) -> Promise<CsvFolderImportResult>`

**Params:** `file` — `File | Blob | ArrayBuffer | Uint8Array`.

Decompresses the zip via `fflate.unzipSync`. For each `.csv` entry whose base
name matches a known PyPSA sheet, parses the CSV via SheetJS and stores the
rows in a fresh `WorkbookModel`. Unknown files are collected in `unknownFiles`.

**Returns:** `{model, unknownFiles, importedSheets}` where `importedSheets` is
the list of sheet names successfully loaded.

---

## `helpers.ts`

General-purpose value coercions, colour utilities, and geometry helpers.

### `numberValue(value) -> number`

**Params:** `value` — `Primitive | string | number | undefined`.

Coerces to a finite `number`. Returns `0` for non-finite, `null`, `undefined`,
and non-numeric strings. `boolean` maps to `1` / `0`.

### `stringValue(value) -> string`

**Params:** `value` — `Primitive | undefined`.

Returns `''` for `null`/`undefined`; otherwise `String(value)`.

### `hashColor(value) -> string`

Returns a deterministic `hsl(H 65% 46%)` colour for a string. Used as a
last-resort colour when no palette or override applies.

### `setCarrierColorOverrides(rows) -> void`

**Params:** `rows` — `GridRow[]` (the `carriers` sheet).

Rebuilds the module-level `carrierColorOverrides` map from `{name, color}` rows.
Called whenever `model.carriers` changes.

### `carrierColor(carrier) -> string`

**Params:** `carrier` — `string`.

Returns the display colour for a carrier. Resolution order:
1. User-defined override (`setCarrierColorOverrides`).
2. Deterministic palette slot derived from the carrier name.

Returns `'#94a3b8'` for empty/blank carriers.

### `resolvedColor(explicitColor, carrier?) -> string`

**Params:** `explicitColor` — `Primitive | undefined`; `carrier` — `Primitive | undefined`.

Returns the explicit hex color if valid; otherwise falls back to `carrierColor(carrier)`.
Used for map markers and chart elements where a per-row color override may exist.

### `clamp(value, min, max) -> number`

Standard numeric clamp.

### `inferInputValue(raw, current) -> Primitive`

**Params:** `raw` — `string` (user-typed text); `current` — `Primitive` (existing
cell value).

Infers the correct `Primitive` type: preserves `number` type if `current` is
numeric, casts `'true'`/`'false'` to boolean, parses integers/floats, otherwise
returns `raw` as string.

### `getColumns(rows, sheet) -> string[]`

**Params:** `rows` — `GridRow[]`; `sheet` — `SheetName`.

Returns the union of schema default columns and all keys present in `rows`,
with `'name'` pinned as the first column.

### `getTsFirstCol(rows) -> string`

**Params:** `rows` — `GridRow[]`.

Returns the first timestamp-like column name (`'snapshot'`, `'datetime'`, etc.)
found in `rows[0]`. Falls back to the first key, then `'snapshot'`.

### `orderByCarrierRows(carrierRows, keys) -> string[]`

**Params:** `carrierRows` — `GridRow[]`; `keys` — `string[]`.

Returns `keys` sorted so that carriers defined in the `carriers` sheet come
first (in their user-defined order), then any unlisted carriers follow. Used to
sort dispatch chart stack keys.

### `priceColor(value, min, max) -> string`

Returns an interpolated colour on a teal → light-grey → red scale. `value` at
`min` maps to `#0f766e` (teal, cheap); at `max` maps to `#dc2626` (red,
expensive). Used for nodal price choropleth maps.

### `loadingColor(pct) -> string`

**Params:** `pct` — line loading percentage 0–100+.

Returns an interpolated colour: green (`#22c55e`) at 0 %, yellow (`#f59e0b`)
at 50 %, red (`#dc2626`) at 100 %.

### `rowCoords(row) -> [number, number] | null`

**Params:** `row` — `GridRow` with `x` and `y` fields.

Returns `[lat, lng]` (note: `y` → lat, `x` → lng) if both fields are non-empty;
otherwise `null`.

### `getBounds(model) -> LatLngBoundsExpression | null`

**Params:** `model` — `WorkbookModel`.

Returns the array of `[lat, lng]` pairs for buses and generators that have
explicit coordinates. Returns `null` when no coordinates are present.

### `getBusIndex(model) -> Record<string, GridRow>`

**Params:** `model` — `WorkbookModel`.

Returns a `name -> row` lookup over `model.buses`. Used to resolve bus
coordinates for component markers on the map.

### `isoDate(d) -> string`

Returns `'YYYY-MM-DD'` using local (not UTC) date components.

### `isoTime(d) -> string`

Returns `'HH:MM'` using local date components.

### `formatTimestamp(raw?) -> string`

Parses an ISO string and formats as `'YYYY-MM-DD HH:MM'`. Returns `raw`
unchanged if unparseable.

### `normalizeDateToIso(raw, fmt?) -> string`

**Params:** `raw` — `string`; `fmt` — `DateFormat` (default `'auto'`).

Converts a date string in the user's declared input format to ISO `YYYY-MM-DD`
(or `YYYY-MM-DDThh:mm:ss` when a time part is present). A four-digit leading
component overrides `fmt` and is treated as the year. Non-date strings pass
through unchanged.

### `snapshotMaxFromWorkbook(rows) -> number`

**Params:** `rows` — `GridRow[]` (the `snapshots` sheet).

Returns the number of rows, or `1` for empty/single-entry tables. Used to
derive the snapshot range for the run window slider.

---

## `analytics.ts`

Utility functions for chart data preparation and aggregation.

### `normalizeSeriesPoint(point) -> TimeSeriesRow`

**Params:** `point` — `SeriesPoint`.

Flattens a `SeriesPoint` (which may store values in a nested `values` map or as
flat numeric keys) into a `TimeSeriesRow`. Used by `App.tsx` to prepare
`systemDispatchRows`.

### `buildRowsFromGeneratorDetails(generators, mode) -> TimeSeriesRow[]`

**Params:** `generators` — map of generator detail objects; `mode` — `'generator' | 'carrier'`.

Aggregates per-generator output series into time-keyed rows, bucketed by either
the individual generator name or its carrier. Output is sorted by timestamp.
Used as a fallback when the backend dispatch series is empty.

### `buildSystemLoadRows(results) -> TimeSeriesRow[]`

**Params:** `results` — `RunResults | null`.

Returns load time-series rows. First attempts to use the `total` field from
`dispatchSeries`; if all totals are zero, aggregates `netSeries.load` across
all buses from `assetDetails`.

### `aggregateValues(values, reducer) -> number`

**Params:** `values` — `number[]`; `reducer` — `'sum' | 'mean' | 'last'`.

Returns the aggregate value for the given reducer. Returns `0` for empty arrays.

### `getTimeBucket(timestamp, timeframe) -> string`

**Params:** `timestamp` — `string | undefined`; `timeframe` — `TimeframeOption`.

Maps an ISO timestamp to a bucket label for the given aggregation level:
`'hourly'` (identity), `'daily'` (`YYYY-MM-DD`), `'weekly'` (`YYYY-W MM-DD`),
`'monthly'` (`YYYY-MM`), `'yearly'` (`YYYY`), `'aggregated'` (literal
`'aggregated'`).

### `aggregateMetricRows(metric, startIndex, endIndex, timeframe) -> TimeSeriesRow[]`

**Params:** `metric` — `MetricOption`; `startIndex`, `endIndex` — `number`;
`timeframe` — `TimeframeOption`.

Slices `metric.rows[startIndex..endIndex]`, groups by time bucket, and applies
`aggregateValues` to each series key. Returns one row per bucket. Returns the
raw slice for `'hourly'`, a single aggregated row for `'aggregated'`.

### `buildDonutFromMetric(metric, startIndex, endIndex) -> Array<{label, value, color}>`

**Params:** `metric` — `MetricOption`; `startIndex`, `endIndex` — `number`.

Aggregates the metric to a single total per series key, filters out zeros, and
sorts descending by value. Used to populate donut chart segments.

---

## `deriveRunResults.ts`

Derives a full `RunResults` object from `(model, outputs)` without a backend
call. Used on the project-import path to restore analytics immediately.

### `deriveRunResults(model, outputs, options?) -> RunResults`

**Params:**
- `model` — `WorkbookModel`: input topology (generators, buses, loads, lines, …).
- `outputs` — `{static, series}`: raw PyPSA output from the backend or imported project.
- `options` — `DeriveRunResultsOptions`: optional overrides for `carbonPrice`,
  `currencySymbol`, `discountRate`, `snapshotWeight`, `narrative`,
  `selectedPeriod`, `pathway`, `rolling`.

**Returns:** Complete `RunResults` including:
- `dispatchSeries`, `generatorDispatchSeries`, `systemPriceSeries`,
  `systemEmissionsSeries`, `storageSeries`, `nodalPriceSeries`
- `carrierMix`, `costBreakdown`, `nodalBalance`, `lineLoading`
- `expansionResults` (from `p_nom_extendable` / `s_nom_extendable` / `e_nom_extendable` flags)
- `meritOrder` (sorted by marginal cost, cumulative capacity prefix-summed)
- `emissionsBreakdown.byGenerator`, `.byCarrier`
- `co2Shadow` (always `found: false` — duals are only available from a fresh solve)
- `assetDetails` (delegated to `deriveAssetDetails`)
- `runMeta`, `pathway`, `rolling`

Multi-period / pathway runs filter `outputs.series` to the `activePeriod` before
all derivation. `annuityFactor(rate, lifetime)` is used for CAPEX annualisation
(same formula as the backend Python `annuity_factor`).

---

## `deriveAssetDetails.ts`

Derives per-asset UI records from `(model, outputs)`.

### `withDerivedAssetDetails(model, results, currencySymbol?) -> RunResults`

**Params:** `model` — `WorkbookModel`; `results` — `RunResults`; `currencySymbol` — `string`.

Returns a new `RunResults` with `assetDetails` populated by calling
`deriveAssetDetails`. Used on the non-pathway run path in `App.tsx`.

### `deriveAssetDetails(model, outputs, currencySymbol?, snapshotWeight?) -> AssetDetails`

Builds `{generators, buses, storageUnits, stores, branches, processes, shuntImpedances}`
maps from the output series and static data. Each entry carries a `name`,
`outputSeries` / `netSeries` / `flowSeries` / `stateSeries` array, KPI
scalars (total energy, average output, capital cost, etc.), and display
metadata (carrier, bus, color).

---

## `exportChart.ts`

Chart-level export utilities.

### `svgToPng(svgEl) -> Promise<string | null>`

**Params:** `svgEl` — `SVGElement`.

Serialises the SVG to a PNG base64 string (no `data:` prefix) via an
off-screen `Canvas` at 2× resolution for retina sharpness. Returns `null` on
any error.

### `exportChartToExcel(title, headers, rows, containerEl, filename?) -> Promise<void>`

**Params:**
- `title` — chart title used as the default filename prefix.
- `headers` — ordered column names.
- `rows` — data rows keyed by headers.
- `containerEl` — DOM element; the first `<svg>` child is used for the chart image.
- `filename` — override filename (default `<title>_<date>.xlsx`).

Writes an ExcelJS workbook with a `Data` sheet (bold header row, auto-width
columns) and a `Chart` sheet (embedded PNG if the SVG render succeeded).
Triggers a `<a download>` browser download.

---

## `formatRelTime.ts`

### `formatRelTime(iso) -> string`

**Params:** `iso` — ISO 8601 timestamp string.

Returns a human relative time label: `'just now'` (< 1 min), `'Nm ago'`
(< 1 h), `'Nh ago'` (< 1 day), `'Nd ago'` (otherwise). Used in
`RunHistoryCard`.

---

## `pathway.ts`

Pathway (multi-period investment) config serialisation.

### `defaultPathwayConfig() -> PathwayConfig`

Returns a `PathwayConfig` with `enabled: false`, `planningMode: 'single_period'`,
empty periods, and `snapshotMappingMode: 'explicit_period_column'`.

### `readPathwayConfigFromModel(model) -> PathwayConfig`

Reads `RAGNAROK_Pathway` (first row) and `RAGNAROK_PathwayPeriods` from the
model, producing a typed `PathwayConfig`. Periods are sorted ascending by period
number.

### `writePathwayConfigToModel(model, config) -> WorkbookModel`

Returns a new model with `RAGNAROK_Pathway` and `RAGNAROK_PathwayPeriods`
overwritten from `config`.

### `samePathwayConfig(a, b) -> boolean`

JSON-equality check used to skip redundant `setModel` calls in the sync effect.

### `getDefaultSelectedPeriod(config) -> number | null`

Returns `config.selectedPeriod` if set and present in `config.periods`, else
the first period, else `null`.

---

## `rolling.ts`

Rolling-horizon config serialisation.

### `defaultRollingConfig() -> RollingHorizonConfig`

Returns defaults: `enabled: false`, `horizonSnapshots: 168`,
`overlapSnapshots: 24`, `stepSnapshots: 144`, `preserveTerminalState: true`,
`selectedWindow: null`.

### `readRollingConfigFromModel(model) -> RollingHorizonConfig`

Reads `RAGNAROK_Rolling` (first row) from the model.

### `writeRollingConfigToModel(model, config) -> WorkbookModel`

Returns a new model with `RAGNAROK_Rolling` overwritten.

### `normalizeRollingConfig(config) -> RollingHorizonConfig`

Clamps `horizonSnapshots`, `overlapSnapshots`, and `stepSnapshots` to positive
integers; computes `stepSnapshots` from `horizon - overlap` when
`stepPolicy === 'derived'`.

### `sameRollingConfig(a, b) -> boolean`

JSON-equality check.

---

## `scenarios.ts`

Scenario catalog serialisation.

### `createScenarioId() -> string`

Returns a unique string id (`scenario-<timestamp>-<random>`).

### `buildScenarioPreset(input) -> ScenarioPreset`

Constructs a `ScenarioPreset` from the provided fields, generating a new id if
none is provided and deep-cloning `pathwayConfig`, `rollingConfig`, and
`constraints`.

### `defaultScenarioCatalog(params) -> ScenarioCatalog`

Returns a `ScenarioCatalog` with a single default scenario built from `params`
(snapshot window, weights, carbon price, discount rate, constraints, pathway,
rolling).

### `readScenarioCatalogFromModel(model) -> ScenarioCatalog`

Reads `RAGNAROK_Scenarios` from the model. Each row stores the full scenario
JSON. Returns `{scenarios: [], activeScenarioId: null}` on empty or missing sheet.

### `writeScenarioCatalogToModel(model, catalog) -> WorkbookModel`

Returns a new model with `RAGNAROK_Scenarios` overwritten.

### `sameScenarioCatalog(a, b) -> boolean`

JSON-equality check.
