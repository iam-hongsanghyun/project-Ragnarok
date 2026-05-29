# Ragnarok — Process Logic

This document traces each major end-to-end process in Ragnarok, naming the actual
functions and files that carry out each step. It is written for a developer who wants to
follow the code, not just the architecture.

---

## 1. Opening / Parsing a Workbook (xlsx to WorkbookModel)

**Entry point:** `handleOpenWorkbook` in
`frontend/Ragnarok_default/src/App.tsx`

1. The user clicks "Open". On Chromium the File System Access API
   `showOpenFilePicker` is called and returns a `FileSystemFileHandle`. On other
   browsers the hidden `<input type="file">` (`fileInputRef`) is clicked instead,
   which fires `handleImport`.
2. Either path calls `parseWorkbook(file)` in
   `frontend/Ragnarok_default/src/shared/utils/workbook.ts`. This reads the file as
   an `ArrayBuffer` via `FileReader.readAsArrayBuffer`, then passes it to SheetJS
   `XLSX.read(arrayBuffer, { type: 'array', cellDates: true })`.
3. `parseSheets(workbook)` iterates every sheet name, calls
   `normalizeSheetName(sheetName)` (from `constants/pypsa_schema`) to map
   case-insensitive or aliased names to canonical keys, then
   `XLSX.utils.sheet_to_json` with `defval: null`. Each cell value passes through
   `normalizeCell(value)`, which converts `Date` objects to ISO-8601 strings,
   coerces numbers and booleans, and stringifies anything else.
4. The result is a `WorkbookModel` — a plain object keyed by sheet name, where each
   value is `GridRow[]`.
5. Back in `App.tsx`, `normalizeInputDatesToIso(nextModel, settings.dateFormat)` is
   called. This calls `canonicalizeTemporalSheets` in `workbook.ts`, which walks
   every sheet, and for any sheet that contains a `snapshot` column it calls
   `canonicalizeTemporalRows`: snapshot strings are parsed via
   `normalizeSnapshotIso` (respecting the user's date format setting), Excel date
   serials are converted via `excelSerialToDate`, and `Date` objects use
   `isoFromDate`. The result is a uniform `YYYY-MM-DDTHH:MM:SS` representation.
   Columns are reordered so `period` (when present) precedes `snapshot` (via
   `orderTemporalRow`).
6. `resetForNewModel(nextModel, file.name)` is called. This is the single choke
   point for loading any model into live state. It reads embedded pathway, rolling,
   and scenario config from the model via `readPathwayConfigFromModel`,
   `readRollingConfigFromModel`, and `readScenarioCatalogFromModel`, applies the
   active scenario's parameters to the React state sliders, clears `results`,
   `resultsModel`, and `resultsContext`, and resets `runStatus` to `'idle'`.
7. The `fileHandle` ref is stored so subsequent "Save" calls can write back to the
   same file without a second picker.

**Project import** (`handleImportProject`) follows the same path but calls
`parseProjectFile(file)` instead, which calls `parseProjectWorkbook`. This function
splits each static component sheet into input columns (fed to `model`) and output
static columns (fed to `outputs.static`) using `outputStaticAttrSet` from the
schema. Sheets whose name matches `<listname>-<output_attr>` are routed to
`outputs.series`. Private sheets prefixed `RAGNAROK_` carry settings, constraints,
run-state, provenance, and plugin analytics, each decoded by its own branch in
`parseProjectWorkbook`. JSON payloads longer than 30,000 characters are stored as
chunked rows (with a `part` index) and reassembled by concatenating the `json`
strings in order.

---

## 2. Editing the Model (In-Memory State, Undo/Redo)

All model state lives in a single `model: WorkbookModel` React state value in
`App.tsx`. Every mutation produces a new object; the old one is never mutated.

- `pushHistory()` snapshots the current `model` onto `undoStack` (capped at 50
  entries) and clears `redoStack`.
- `undo()` pops from `undoStack`, pushes the current model onto `redoStack`, and
  calls `setModel`.
- `redo()` is the reverse.
- Keyboard shortcuts (`Ctrl/Cmd+Z`, `Ctrl+Shift+Z`, `Ctrl+Y`) are wired in a
  `keydown` listener that is active only on the `Model` and `Build` tabs, and is
  suppressed when a text input or contentEditable has focus.

The mutation helpers are:

| Function | What it does |
|---|---|
| `updateRowValue(sheet, rowIndex, key, value)` | Single-cell edit |
| `bulkPaste(sheet, edits, extraRows)` | Multi-cell Excel paste as one undoable operation |
| `addRow(sheet)` | Appends a row seeded from `getDefaultRowForSheet` |
| `deleteRow(sheet, rowIndex)` | Removes row by index |
| `moveRow(sheet, rowIndex, direction)` | Swaps row with its neighbour |
| `addColumn(sheet, col, defaultValue)` | Adds a column to every row if absent |
| `deleteColumn(sheet, col)` | Removes a key from every row |
| `renameColumn(sheet, oldCol, newCol)` | Renames a key across every row |
| `clearSheet(sheet)` | Replaces the array with `[]` |

Time-series CSV imports go through `handleImportTsSheet`, which calls
`canonicalizeTemporalRows` before writing the rows into the model.

Pathway config, rolling config, and scenario catalog are stored separately in their
own React state values. Three `useEffect` hooks keep the model's embedded config
sheets (`RAGNAROK_PathwayConfig`, `RAGNAROK_RollingConfig`, `RAGNAROK_Scenarios`) in
sync via `writePathwayConfigToModel`, `writeRollingConfigToModel`, and
`writeScenarioCatalogToModel` — but only when the round-trip read back via the
corresponding reader detects an actual change, preventing re-render loops.

---

## 3. Validation (Dry Run)

1. The user opens the Run dialog (`RunDialog` in
   `frontend/Ragnarok_default/src/features/run/RunDialog.tsx`) and toggles "Dry
   run" on, then clicks "Validate".
2. `handleRunModel` in `App.tsx` detects `dryRun === true`. It calls
   `prepareModelForBackend(model)`, which deep-clones the model and calls
   `normalizeInputDatesToIso` to guarantee canonical timestamps before the POST.
3. A `POST /api/validate` request is made with body
   `{ model, scenario, options }`.
4. In `backend/app/main.py`, the `validate_case` route handler calls
   `validate_model(payload)` from
   `backend/pypsa/network/validators.py` (re-exported via
   `backend/pypsa/network/__init__.py`).
5. `validate_model` performs a series of schema-driven checks without building a
   `pypsa.Network`:
   - Unknown or output-only sheets are flagged.
   - `_effective_snapshot_count` deduplicates snapshot labels for single-period
     interpretation.
   - Pathway checks: periods must be unique ascending integers; if
     `snapshot_mapping_mode == "explicit_period_column"` every snapshot row must
     carry a `period` value matching the configured list.
   - Rolling checks: horizon, overlap, and step are validated for
     internal consistency.
   - Every static sheet goes through `_check_duplicate_names`,
     `_check_required_fields`, `_check_bus_refs`, `_check_numeric_sanity`, and
     `_check_carrier_refs`.
   - `_check_ts_sheets` verifies that time-series sheets have a snapshot-label
     column, that column counts match the snapshot count, and that column names
     correspond to components in the matching static sheet.
   - Returns `{ valid, errors, warnings, notes, snapshotCount, networkSummary }`.
6. The response is stored in `validateResult` state. The app switches to the
   Analytics tab, Validation sub-tab. If `valid` is false, the errors list is
   rendered; clicking an error can call `onNavigateToTable` to jump to the
   offending sheet row in the Model tab.

---

## 4. The Run Lifecycle

### 4a. Options Assembly (Frontend)

`handleRunModel` in `App.tsx` assembles:

- `scenario`: `{ constraints: enabled[], carbonPrice, discountRate }`
- `options`: snapshot window (`snapshotStart`, `snapshotCount`, `snapshotWeight`),
  solver settings (`solverThreads`, `solverType`), feature flags (`forceLp`,
  `enableLoadShedding`, `loadSheddingCost`), backend selector
  (`backend: 'pypsa'`), `enabledModules`, `moduleConfigs`,
  `pathwayConfig`, `rollingConfig`, `stochasticConfig`,
  `securityConstrainedConfig`, `carbonPriceSchedule`.

The model is deep-cloned and ISO-normalised via `prepareModelForBackend`.

### 4b. Starting the Job (POST /api/run)

1. `POST /api/run` in `backend/app/main.py` receives `RunPayload`.
2. The backend validates the requested backend name via `get_backend`; a 400 is
   returned immediately on an unknown backend.
3. Stale completed/cancelled jobs are pruned from the `_jobs` dict.
4. A UUID `job_id` is generated. A multiprocessing `Queue` and a `Process` are
   created using `mp.get_context("spawn")` so the worker imports cleanly in a
   fresh interpreter. The target function is `_solve_worker`.
5. `_solve_worker` runs in the child process. It calls `get_backend(options["backend"])` to
   retrieve the backend — currently always `PypsaBackend` from
   `backend/pypsa/adapter.py` — then calls `backend.run(model, scenario, options)`,
   which calls `run_pypsa` from `backend/pypsa/results/__init__.py`. On completion
   it puts `("ok", result)` or `("err", message)` into the queue.
6. An asyncio task `_collect_job(job_id)` is created. It polls the queue every 0.5 s
   and updates `job.status` and `job.result` when the worker finishes or the
   process dies.
7. `{ jobId, status: "running" }` is returned synchronously to the frontend.
8. The frontend stores `jobId` in `jobIdRef` and `sessionStorage`.

### 4c. Polling (GET /api/run/{job_id})

The frontend schedules the first poll after `RUN_POLLING.initialDelayMs`
(defined in `constants`). The `poll` async function in `App.tsx`:

1. Fetches `GET /api/run/{jobId}`.
2. A `404` means the server restarted and lost the job; the UI transitions to
   `'error'` and asks the user to re-run.
3. A non-200 response transitions to `'error'` with the response body.
4. A network error (catch block) schedules a retry after
   `RUN_POLLING.retryDelayMs` — a brief network hiccup does not kill the solve.
5. If `data.status === 'running'`, schedules the next poll after
   `RUN_POLLING.runningDelayMs`.
6. When `data.status === 'done'`, calls `applyResult(data.result)`.

The poll timer is stored in `pollTimerRef`. `stopPolling` clears it. Cancel
(`handleCancelRun`) calls `stopPolling`, then `DELETE /api/run/{jobId}`, which
terminates the child process via `proc.terminate()` and `proc.join(3)`.

On the backend `poll_run`, the job is removed from `_jobs` immediately on delivery
of a `done` result so memory is freed after the first successful poll.

### 4d. Applying the Result (Frontend)

`applyResult(rawResults)` in `App.tsx`:

1. Calls `canonicalizeOutputSeries(rawResults.outputs.series, settings.dateFormat)`
   to normalise backend output timestamps.
2. Updates `pathwayConfig` and `rollingConfig` from the returned metadata.
3. Calls `setResults(rawResults)`.
4. Calls `setResultsModel(structuredClone(modelForRun))` — freezes the exact
   topology that was submitted, so later edits do not corrupt analytics for this
   run.
5. Calls `setResultsContext({ carbonPrice, snapshotWeight, discountRate })` —
   freezes derivation inputs so pathway KPIs stay stable even if the user moves the
   live sliders afterwards.
6. Sets `runStatus` to `'done'`.
7. Appends a `RunHistoryEntry` to `runHistory`, containing the raw results and a
   deep clone of `modelForRun`.

---

## 5. Network Build: `build_network`

`build_network(model, scenario, options)` in
`backend/pypsa/network/__init__.py` returns `(network, notes)`.

1. **Parse options.** `parse_pathway_config` (`backend/pypsa/pathway.py`) and
   `parse_stochastic_config` (`backend/pypsa/stochastic.py`) build typed config
   objects from the options dict.
2. **Create the network.** `pypsa.Network()` is instantiated. `_apply_network_sheet`
   (`backend/pypsa/network/network_sheet.py`) applies the optional `network` sheet
   (name, CRS).
3. **Build the snapshot index.** `_snapshots_index(model, pathway)`
   (`backend/pypsa/network/snapshots.py`) reads the `snapshots` sheet. For
   pathway mode with `explicit_period_column`, it constructs a
   `pd.MultiIndex(["period", "timestep"])` named `"snapshot"`. For single-period
   mode it deduplicates labels and calls `pd.to_datetime`. The result is passed to
   `network.set_snapshots`. `_apply_pathway_config` then calls
   `network.set_investment_periods` and populates
   `investment_period_weightings` from the pathway period objects.
4. **Add components.** `_ordered_component_sheets(network)` returns all component
   sheet names in dependency-safe order (carriers first, then buses, then
   everything else, preserving PyPSA's registry order). For each sheet:
   - Rows without a `name` are dropped by `_has_name`.
   - A DataFrame is built and `_strip_blank_columns` removes all-null columns so
     PyPSA defaults apply.
   - Columns are filtered to `input_static_attributes(sheet_name)` (schema-driven).
   - `_drop_broken_bus_refs` removes rows with invalid bus references; the schema
     determines which bus-ref columns are required.
   - `_ensure_carriers` auto-adds any referenced carrier not already in
     `network.carriers`.
   - `network.add(cls, names, **kwargs)` bulk-inserts the components.
5. **Attach time-series sheets.** Every key in `model` containing `-` is checked:
   `list_name` and `attr` are split on the first hyphen. The sheet is skipped if
   `attr` is not in PyPSA's defaults for that component class, or if it is not
   marked `varying=True`. `_apply_ts_sheet` converts the rows to a DataFrame,
   detects the snapshot-label column, coerces numerics, aligns the index to
   `network.snapshots` (including period-broadcast for pathway mode), and stitches
   the result onto `network.<list_name>_t.<attr>` via `pd.concat`.
   `_normalize_dynamic_snapshot_index_names` ensures every dynamic frame index is
   named `"snapshot"`.
6. **Snapshot windowing.** The `snapshotStart` / `snapshotCount` / `snapshotWeight`
   options slice and downsample `network.snapshots`. For pathway mode the full
   snapshot set is kept; only the step size is applied across all periods.
   `network.snapshot_weightings` columns `objective`, `stores`, `generators` are
   set to `float(step)`.
7. **Period-factor scaling.** Annual energy caps (`*_sum_min`, `*_sum_max`) on
   generators, storage units, and stores are scaled by
   `min(modelled_hours / 8760, 1.0)` so they are proportional to the modelled
   window rather than a full year.
8. **Carbon price.** `parse_carbon_price_config` (`backend/pypsa/carbon_price.py`)
   builds a `CarbonPriceConfig` from the scalar `carbonPrice` and the optional
   `carbonPriceSchedule` array. `apply_carbon_price` constructs a per-snapshot
   `Series` via `build_price_series` (step-function lookup by snapshot year), then
   adds `price × emission_factor` to each emitting generator's marginal cost in
   both static and `_t` frames. A varying schedule is always written to `_t`.
9. **CAPEX annuitisation.** For each of `generators`, `storage_units`, `stores`,
   `lines`, `links`: extendable components have their `capital_cost` multiplied by
   `annuity_factor(discount_rate, lifetime)` from
   `backend/pypsa/utils/annuity.py`. Lifetime defaults to 20 years when absent.
10. **Force-LP.** If `options["forceLp"]` is true, all `committable=True` flags on
    generators are set to `False`.
11. **Load shedding.** `add_load_shedding`
    (`backend/pypsa/network/load_shedding.py`) adds a `Generator` named
    `load_shedding_{bus}` per bus when `enableLoadShedding` is true. `p_nom` is set
    to the system-wide peak demand; `marginal_cost` is the user-configured VOLL.
12. **Stochastic expansion.** If stochastic mode is enabled,
    `apply_scenarios(network, stochastic)` (`backend/pypsa/stochastic.py`) calls
    `network.set_scenarios(weights)` to expand all frames to a `(scenario, name)`
    MultiIndex, then applies per-scenario `ScenarioOverride` objects to both static
    and dynamic frames.

---

## 6. Solving: Branch Logic in `run_pypsa`

`run_pypsa(model, scenario, options)` in
`backend/pypsa/results/__init__.py` orchestrates the solve after `build_network`
completes.

**Mode selection and mutual-exclusion checks** happen first. The function raises
HTTP 400 if stochastic + rolling, or SCLOPF + rolling/stochastic/pathway are
combined.

**`extra_functionality(n, snapshots)`** is a closure passed into every solve call.
It calls `apply_custom_constraints` (`backend/pypsa/network/custom_constraints.py`)
and then `execute_plugins_at_stage("in-solve", ...)`. Custom constraints are added
to `n.model` (the linopy model) inside this callback so they are registered before
the solver runs. See section 7 for plugin details.

**Solve branches:**

| Mode | PyPSA call |
|---|---|
| Rolling horizon | `network.optimize.optimize_with_rolling_horizon(horizon, overlap, multi_investment_periods, ...)` |
| Security-constrained (SCLOPF) | `network.optimize.optimize_security_constrained(...)` |
| Single-period or pathway | `network.optimize(multi_investment_periods=pathway.enabled, ...)` |

All three receive `solver_name="highs"`, the assembled `solver_options` dict (threads, simplex/IPM), and `extra_functionality`.

**Rolling windows:** `_rolling_window_summaries`
(`backend/pypsa/results/summaries.py`) pre-computes window metadata (solved range,
accepted range, period list) before the solve so the result payload carries it even
if the solve raises.

**Stochastic post-processing:** After a stochastic solve, `per_scenario_summaries`
computes per-scenario energy/emissions/cost totals, then
`collapse_to_representative_scenario` slices all static and dynamic frames to the
highest-weight scenario, restoring the deterministic shape that all downstream
extraction code expects.

**Pathway multi-period:** `network.optimize(multi_investment_periods=True)` lets
PyPSA handle investment-period coupling natively. `_pathway_period_summaries` in
`summaries.py` computes per-period KPIs (total dispatch, emissions, average price,
peak load, objective weight) by grouping the snapshot MultiIndex by `period`.

---

## 7. Plugin Execution Stages

`execute_plugins_at_stage(stage, enabled_ids, **kwargs)` in
`backend/app/module_host.py`.

Plugins are Python modules installed into the managed root directory
(default: `.ragnarok/modules/`). Each has a `module.json` manifest declaring `id`,
`stage`, and `hook` (function name, default `"run"`).

**Stage contracts** (the keyword arguments each hook receives):

| Stage | Arguments |
|---|---|
| `pre-build` | `model, scenario, options` |
| `post-build` | `network, scenario, options` |
| `in-solve` | `network, model, scenario, options` |
| `post-solve` | `network, results, scenario, options` |

**Execution flow for each enabled module:**

1. `_load_module_entry(module_id)` reads `module.json`, locates the `entry` file,
   and imports it via `importlib.util.spec_from_file_location`. Returns
   `(module_object, manifest)` or `(None, None)` on failure.
2. The manifest `stage` is compared to the requested stage; mismatches are skipped.
3. `getattr(mod, hook_name)` retrieves the callable.
4. Only the kwargs defined in `_STAGE_KWARGS[stage]` are passed. The module's own
   config (from `options["moduleConfigs"][module_id]`) is injected as
   `options["moduleConfig"]` so the plugin does not need to know its own id.
5. Errors are caught, logged, and stored as `{"error": "..."}` in the return dict —
   except at `in-solve`, where exceptions re-raise immediately because swallowing a
   constraint-registration failure would silently produce wrong solver results.

**How stages connect to `run_pypsa`:**

- `pre-build`: runs before `build_network`. Any plugin returning a non-error dict
  replaces `model` (last-writer-wins).
- `post-build`: runs after `build_network`. Return value is ignored; plugins modify
  `network` in place.
- `in-solve`: runs inside `extra_functionality`, which PyPSA calls once before
  handing the model to the solver. Plugins register additional linopy constraints
  here.
- `post-solve`: runs after the solve and stochastic collapse. Return values are
  enriched with display metadata from `get_module_metadata` (reading `name` and `ui`
  hints from `module.json`) and stored in `plugin_analytics[module_id]`, which is
  returned inside `RunResults`.

`execute_module_action` is a single-module variant used by the
`POST /api/modules/{module_id}/preview` endpoint for action-button previews. It
bypasses the stage filter and calls the named hook directly.

---

## 8. Result Extraction: `run_pypsa` to `RunResults`

After the solve, `run_pypsa` assembles the `RunResults` dict that the frontend
stores as `results` state. The extraction is done entirely in the backend worker
process before the result is placed in the multiprocessing queue.

**Key extraction calls:**

| Output field | Source |
|---|---|
| `dispatchSeries`, `generatorDispatchSeries` | `build_dispatch_series` in `backend/pypsa/results/dispatch.py` |
| `systemPriceSeries`, `systemEmissionsSeries` | `build_price_emissions_series` in `dispatch.py` |
| `storageSeries` | `build_storage_series` in `dispatch.py` |
| `carrierMix` | `dispatch_by_carrier` groups `generators_t.p` by carrier; `weighted_sum` with `snapshot_weightings["generators"]` |
| `costBreakdown` | Fuel cost, carbon cost, load-shedding cost split per generator using `get_switchable_as_dense` for marginal cost; expansion CAPEX from `build_expansion_results` |
| `nodalBalance` | Per-bus average load and generation from static `loads_t.p_set` and dispatch frame |
| `lineLoading` | Peak `|p0| / s_nom * 100` for lines, links, transformers |
| `meritOrder` | `build_merit_order` in `backend/pypsa/results/market.py` |
| `co2Shadow` | `build_co2_shadow` in `market.py` |
| `emissionsBreakdown` | `build_emissions_breakdown` in `backend/pypsa/results/emissions.py` |
| `expansionResults` | `build_expansion_results` in `backend/pypsa/results/expansion.py` |
| `pathway.summaries` | `_pathway_period_summaries` in `backend/pypsa/results/summaries.py` |
| `pluginAnalytics` | `execute_plugins_at_stage("post-solve", ...)` enriched with manifest metadata |
| `outputs` | `build_full_outputs(network)` in `backend/pypsa/results/full_outputs.py` |

**`build_full_outputs`** (`backend/pypsa/results/full_outputs.py`) is the
schema-driven full extraction pass. It walks every component in
`load_pypsa_schema()`, calls `_component_output_attrs(sheet_name)` to split output
attributes into static vs series categories, then:

- Extracts static output attributes (e.g. `p_nom_opt`, `mu_upper`) from
  `comp.static` into `static_out[list_name][component_name][attr]`.
- Extracts time-series output attributes (e.g. `p`, `state_of_charge`,
  `marginal_price`) from `network.<list_name>_t.<attr>` (falling back to
  `comp.dynamic`) into `series_out["<list_name>-<attr>"]`. Each row is
  `{"snapshot": iso_str, component_name: value, ...}` with `_series_snapshot_row`
  handling the pathway `(period, timestep)` tuple.

The shape mirrors the input model format so the same workbook parser handles
project export/import round-trips.

**`summary`** is a six-item list of human-readable KPIs (installed capacity, peak
demand, reserve position, peak price, system emissions, transmission stress).

**`runMeta`** carries `snapshotCount`, `snapshotWeight`, `modeledHours`,
`planningMode`, `investmentPeriods`, and embedded rolling/pathway descriptors.

---

## 9. Rendering Results in the Frontend

**`displayResults` memo** in `App.tsx` (lines 176-217) is the single transformation
point from raw `results` to display-ready data. It runs on every change to
`results`, `analyticsModel`, or any of the three frozen context values.

- For non-pathway results: calls `withDerivedAssetDetails(analyticsModel, results,
  currencySymbol)` from
  `frontend/Ragnarok_default/src/shared/utils/deriveAssetDetails.ts`, which walks
  `results.outputs` to build `assetDetails.generators`,
  `assetDetails.storageUnits`, `assetDetails.buses`, `assetDetails.branches`, and
  `assetDetails.stores` records with per-asset output series attached.
- For pathway results: calls `deriveRunResults(analyticsModel, results.outputs,
  derivationContext)` from
  `frontend/Ragnarok_default/src/shared/utils/deriveRunResults.ts`. This
  re-derives carrier mix, cost breakdown, dispatch series, nodal balance, and all
  other KPIs from `outputs.static` and `outputs.series` for the selected pathway
  period, applying the frozen `carbonPrice`, `snapshotWeight`, and `discountRate`
  values. The result is merged with fields that are period-independent (`meritOrder`,
  `co2Shadow`, `emissionsBreakdown`, `pluginAnalytics`, `outputs`).

**`analyticsModel`** is `resultsModel ?? model`. When `resultsModel` is set (i.e.
after a run or after restoring a history entry), analytics use the frozen topology
snapshot rather than the live editable model.

The memo output is passed directly to `AnalyticsView`, which renders whichever
sub-tab the user has selected (`Result`, `Validation`, `Comparison`, etc.).

Derived time-series for charts (`systemDispatchRows`, `systemPriceRows`,
`storageRows`, `systemLoadRows`) are built from `displayResults` using helpers in
`frontend/Ragnarok_default/src/shared/utils/analytics.ts` and passed down to chart
components.

---

## 10. Run History

**Snapshotting a run.** At the end of `applyResult` in `App.tsx`, a
`RunHistoryEntry` is prepended to `runHistory` state. The entry stores:

- `results`: the full raw `RunResults` returned by the backend.
- `model`: `structuredClone(modelForRun)` — the exact topology submitted to the
  backend, which may differ from the current live model if the user has since made
  edits.
- `carbonPrice`, `discountRate`, `snapshotStart`, `snapshotEnd`, `snapshotWeight`,
  `activeConstraints`, `componentCounts`, `scenarioLabel`.

Pinned entries are retained indefinitely. Unpinned entries are trimmed to
`MAX_UNPINNED_HISTORY` (defined in `constants`). Run history is session-scoped
in-memory React state — it is never written to disk and does not survive a page
reload.

**Restoring a run.** `handleRestoreRun(entry)` in `App.tsx`:

1. Calls `canonicalizeOutputSeries` on `entry.results.outputs.series` to normalise
   any legacy timestamps.
2. Calls `setResults(entry.results)` to display the stored results.
3. Sets `resultsModel` to `entry.model ?? null`, pinning analytics to the stored
   topology.
4. Sets `resultsContext` to the stored `carbonPrice`, `snapshotWeight`, and
   `discountRate` so pathway derivation uses this run's values, not the live
   sliders.
5. If `entry.model` is present, pushes the current live model onto the undo stack,
   calls `setModel(structuredClone(entry.model))`, and restores `maxSnapshots`,
   `snapshotStart`, `snapshotEnd`. This makes the Model and Build tabs, and any
   export, reflect the run's input topology rather than whatever the user last edited.
6. Restores `pathwayConfig` and `rollingConfig` from the entry's results metadata.
7. Does not switch tabs — the user stays on their current view.

The comparison table in `RunHistoryList` / `RunComparisonTable`
(`frontend/Ragnarok_default/src/features/run-history/`) reads `inComparison` from
each entry. Toggling `inComparison` via `handleToggleComparison` is the only state
change; no re-derivation occurs.

---

## 11. Export Pipelines

All exports that produce a file use `saveFileWithPicker` in `App.tsx`. This helper
opens `showSaveFilePicker` (File System Access API, Chromium only), letting the user
choose the directory and file name. On other browsers it falls back to creating an
`<a>` element with a `download` attribute and clicking it programmatically. The
heavy serialisation (`buildData`) is called lazily after the picker resolves so the
transient user-activation window is preserved.

### Export Project (inputs + outputs as one xlsx)

`handleExportProject` calls `saveFileWithPicker` with
`buildData: () => projectWorkbookToArrayBuffer(analyticsModel, results?.outputs, metadata)`.

`projectWorkbookToArrayBuffer` calls `buildProjectWorkbook`
(`frontend/Ragnarok_default/src/shared/utils/workbook.ts`), which:

1. Writes every static component sheet as input columns merged with solved output
   static columns from `outputs.static`. Components that exist only in
   `outputs.static` (e.g. auto-added load-shedding generators) are appended as
   extra rows.
2. Writes all input time-series sheets from the model.
3. Writes all output time-series sheets from `outputs.series`.
4. Writes embedded config sheets (`RAGNAROK_PathwayConfig`, `RAGNAROK_RollingConfig`,
   `RAGNAROK_Scenarios`).
5. Writes private metadata sheets: `RAGNAROK_ResultMeta` (JSON-chunked `runMeta`,
   `pathway`, `rolling`, `co2Shadow`, `narrative`), `RAGNAROK_PluginAnalytics`
   (JSON-chunked per-module data), `RAGNAROK_Settings`, `RAGNAROK_Constraints`,
   `RAGNAROK_RunState`, `RAGNAROK_Provenance`.

The file is an ordinary `.xlsx` that PyPSA can import natively (it reads the same
sheet names). Run history is intentionally not exported.

### Export Result Workbook

`handleExportResultWorkbook` calls
`fullResultsArrayBuffer(analyticsModel, displayResults)` from
`frontend/Ragnarok_default/src/shared/utils/exportResults.ts`.

`buildFullResultsWorkbook` starts from `buildWorkbook(model)` (all input sheets)
and appends `OUT_*` sheets for every result category: `OUT_Summary`,
`OUT_Dispatch`, `OUT_GenDispatch`, `OUT_SysPrice`, `OUT_Emissions`, `OUT_Storage`,
`OUT_CarrierMix`, `OUT_CostBreakdown`, `OUT_NodalBalance`, `OUT_LineLoading`,
`OUT_GenDetail`, `OUT_StorageDetail`, `OUT_BranchFlow`, and conditionally
`OUT_MeritOrder`, `OUT_Expansion`, `OUT_EmissionsByGen`, `OUT_EmissionsByCarrier`,
`OUT_CO2Shadow`. Column widths are auto-fitted via `autoFitCols`.

### Export / Import CSV Folder

`handleExportCsvFolder` dynamically imports `exportModelAsCsvFolderZip` from
`frontend/Ragnarok_default/src/shared/utils/csvFolder.ts`, which writes each sheet
as a separate CSV into a zip archive using a download-fallback (no picker).

`handleImportCsvFolder` imports `importCsvFolderZip` from the same module, then
calls `normalizeInputDatesToIso` and `resetForNewModel`.

### Export / Import netCDF and HDF5

Both formats require a backend round-trip because the browser has no native
parser.

**Export:** `exportViaBackend('/api/export/netcdf', ...)` or
`exportViaBackend('/api/export/hdf5', ...)` in `App.tsx`. The current model is
POSTed as JSON. In `backend/app/main.py`, `_model_payload_to_network` calls
`build_network` (no solve), then `network.export_to_netcdf(path)` or
`network.export_to_hdf5(path)`. The file bytes are returned as a `Response` and
the frontend triggers a download via the `<a>` fallback (no picker for these
formats).

**Import:** A file upload via a hidden `<input>` fires `handleImportNetcdf` or
`handleImportHdf5`, which call `importViaBackend('/api/import/netcdf', file)` or
`importViaBackend('/api/import/hdf5', file)`. The backend endpoint reads the file
into a temporary path, calls `pypsa.Network().import_from_netcdf(path)` or
`import_from_hdf5(path)`, then passes the result through `_network_to_model_json`,
which walks the schema-known component list and serialises static columns and
`*_t` frames into the `{sheet: rows[]}` format the frontend understands. The JSON
model is returned in the response body; the frontend calls `normalizeInputDatesToIso`
and `resetForNewModel`.
