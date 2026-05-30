# Ragnarok — User Manual

Ragnarok is a browser-based graphical interface for building, configuring, and running PyPSA power-system optimization models without writing Python.

---

## Contents

1. [What you can do with Ragnarok](#1-what-you-can-do-with-ragnarok)
2. [Prerequisites and starting the application](#2-prerequisites-and-starting-the-application)
3. [Workspace tour](#3-workspace-tour)
4. [Building or opening a model](#4-building-or-opening-a-model)
5. [Configuring and running a study](#5-configuring-and-running-a-study)
6. [Reading results in the Analytics view](#6-reading-results-in-the-analytics-view)
7. [Run history](#7-run-history)
8. [Exporting your work](#8-exporting-your-work)
9. [Settings](#9-settings)
10. [Plugins](#10-plugins)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. What you can do with Ragnarok

- Open or build a PyPSA network model expressed as an Excel workbook — one sheet per component type (buses, generators, loads, lines, links, stores, storage units, transformers, carriers, global constraints, time-series profiles).
- Edit every component attribute in a spreadsheet grid, or place and connect buses directly on a map.
- Set economic parameters (carbon price, discount rate, simulation window, solver options) in a dedicated Settings panel.
- Submit the model to a local PyPSA/HiGHS solver and see dispatch, price, emissions, storage, and line-loading results in an interactive analytics dashboard.
- Compare multiple runs side by side, restore a previous run's inputs to continue working from it, and export results in several formats.

---

## 2. Prerequisites and starting the application

### What you need

| Requirement | Notes |
|---|---|
| A modern Chromium-based browser (Chrome, Edge, Arc) | Recommended. Firefox works but the save-file picker falls back to a plain download. |
| The local FastAPI backend running at `http://127.0.0.1:8000` | Required for running the solver, validating the model, and the netCDF / HDF5 import/export paths. |
| An Excel workbook (.xlsx) describing your PyPSA network | Optional at startup — you can start from a blank model. |

### Starting the backend

The backend must be running before you attempt any solve or validation. Check your project's start-up instructions; the typical command from the repo root is:

```
uv run python -m ragnarok_backend
```

or whatever the project provides. Confirm it is up by visiting `http://127.0.0.1:8000/docs` in your browser. You should see the FastAPI automatic docs page.

### Opening the UI

Open the Ragnarok URL in your browser (for example `http://localhost:5173` when running the Vite dev server). The interface loads with an empty model. The status bar on the top right reads "Ready. Open a workbook or import a project."

---

## 3. Workspace tour

### Top bar

The top bar runs the full width of the window.

- **Ragnarok** (brand label, left) — identifies the application.
- **Run** button — opens the Run dialog. Disabled while a solve is in progress.
- **Clear** button — discards the loaded model and starts from an empty workbook. Prompts for confirmation.
- Elapsed timer and **Cancel** button — visible only while a solve is running.
- Filename, snapshot count, and status message — displayed on the right side.

### Activity bar

The narrow vertical strip on the far left is the only way to switch views. Each button shows a single letter and reveals its full name in a tooltip.

| Letter | View | Purpose |
|---|---|---|
| B | Build | Guided wizard for constructing a model from scratch on a map. |
| M | Model | Spreadsheet editor for all component sheets plus a read-only topology map. |
| S | Settings | Scenario presets, simulation window, carbon price, planning mode, solver options, appearance, and project defaults. |
| A | Analytics | Results dashboard, validation report, and run comparison. |
| P | Plugins | Module manager for installing and enabling backend plugins. |

The Analytics button shows a badge with an error count if validation has been run and found issues. The Plugins button shows a badge with the count of currently enabled modules.

---

## 4. Building or opening a model

### Opening an existing workbook

1. Click **M** in the activity bar to go to the Model view.
2. Click **Open** in the file toolbar at the top of the view.
3. A file-picker dialog opens. Select an `.xlsx` workbook.
4. The workbook loads into the spreadsheet editor. The status bar confirms "Opened `<filename>`".

If your browser does not support the File System Access API (non-Chromium browsers), the picker falls back to a standard `<input type="file">` dialog. In that case, **Save** always prompts for a filename rather than writing in place.

### Importing a project workbook

A project workbook contains both input sheets and solved output sheets in one file. Use **Import Project** (in the Model view file toolbar) instead of **Open** when you have a file previously exported from Ragnarok via **Export Project**. The full run state (inputs, results, run settings) is restored, and a history entry is added to the current session's run history.

### Editing the model in the Model view

The Model view has three resizable columns:

- **Sheet tree** (left) — lists every component type grouped by category (static sheets and time-series sheets). Click a sheet name to load it in the table. Error and warning indicators appear next to sheets with validation issues.
- **Table editor** (center) — a spreadsheet grid for the selected sheet. Click any cell to edit it in place. Each column header matches a PyPSA attribute name.
- **Topology map** (right) — a read-only Leaflet map showing bus positions and branch connections. This map reflects the live model.

#### Adding and removing rows

- To add a row: click the **+ Add row** button below the table, or paste multiple rows from a spreadsheet (Ctrl+V / Cmd+V).
- To delete a row: click the delete control on the left side of the row.
- To move a row: use the up/down arrows on the row's left edge (where present).

#### Adding, renaming, and removing columns

- Right-click a column header (or use the column header menu if one is present) to rename or delete a column.
- To add a custom column: use the **+ Add column** action available in the column header area.

#### Undoing and redoing edits

Ctrl+Z (Cmd+Z on macOS) undoes the last model edit while you are in the Model or Build view and no text input is focused. Ctrl+Shift+Z or Ctrl+Y redoes. The undo stack holds up to 50 operations per session.

### Building a model from scratch (Build view)

Click **B** in the activity bar. The Build view guides you through the model in dependency order: Network, Carriers, Buses, Generators, Loads, Storage, Lines/Links, and a Review step.

Each step shows:

- A table editor scoped to that step's sheet on the left.
- A schema and issue detail pane on the right.
- An interactive map in the center for geo-aware sheets (buses, lines, links, transformers). You can click on the map to drop a new bus and then drag it to position it. Click two buses to draw a line or link between them.

The Build view writes directly into the same underlying model as the Model view. Switching from Build to Model at any point shows the same data.

#### Placing buses on the map

1. In the Build view, navigate to the **Buses** step.
2. Click anywhere on the map to create a new bus at that location. Ragnarok assigns an auto-generated name (e.g. `bus_1`).
3. Drag an existing bus marker to update its `x` and `y` coordinates.

#### Connecting buses (lines and links)

1. Navigate to the **Lines** or **Links** step.
2. Click the source bus marker, then click the destination bus marker. A branch row is added to the sheet with `bus0` and `bus1` set automatically.

### Loading time-series data

Time-series data (generator availability profiles, load profiles) lives on separate sheets such as `generators-p_max_pu` and `loads-p_set`. You can:

- Type or paste values directly into the time-series table in the Model or Build view.
- Import a CSV file: in the time-series sheet view, use the **Import CSV** action to load a `.csv` file. The first column must contain the snapshot timestamps; subsequent columns must be named after the component they profile.

---

## 5. Configuring and running a study

### Opening the Run dialog

Click the **Run** button in the top bar. The Run dialog opens with a summary of the current configuration and two toggle options.

### Run dialog contents

**Planning summary** — shows read-only:

- Which scenario preset is active (or "ad hoc" if no preset is selected).
- Whether the solve is single-period or a multi-year pathway.
- Whether rolling-horizon mode is enabled, and its horizon/overlap window.
- The snapshot range (`start → end`) and resolution (e.g. "1h resolution").
- The number of active custom constraints.

**Optimisation settings** — two toggles:

- **Force LP**: when active, forces a linear programming relaxation even if the model contains integer variables. Useful for debugging or speeding up large models that do not require unit commitment.
- **Dry run**: when active, the button changes label to "Validate". Clicking it sends the model to the backend's validation endpoint instead of the solver. Results appear in the Analytics view under the Validation sub-tab.

**Action buttons**:

- **Cancel** — closes the dialog without running.
- **Run model** (or **Validate** when Dry run is active) — submits the job.

### Configuring the simulation window and resolution

Before running, go to Settings (S) and select **Simulation window** from the Setup group.

- Use the dual-range slider to set the start and end snapshot index. The label shows how many of the total available snapshots are selected.
- Click a resolution button to choose how many hours each snapshot represents: 1h, 2h, 3h, 4h, 6h, 8h, 12h, or 24h. A weight of 1h means each snapshot is treated as one hour; 24h treats each snapshot as one day.

If pathway mode is enabled, the slider is hidden because the solver uses the full horizon defined by the pathway periods.

### Multi-year pathway runs

Go to Settings > **Multi-year planning** to switch between Single period and Pathway mode. In Pathway mode, you define investment periods (e.g. 2030, 2040) each with an objective weight and years weight. The solver jointly optimizes investment decisions and dispatch across all periods.

### Rolling horizon

Go to Settings > **Rolling horizon** to enable rolling-horizon dispatch. Set the horizon length (number of snapshots solved in each window) and the overlap. Rolling horizon is useful for long time series that would otherwise be too large for a single solve.

### Carbon price

Go to Settings > **Carbon price** to apply an economy-wide carbon cost.

- Set the scalar price (currency per tonne CO2) to apply a flat rate to all snapshots. The price is added to each generator's marginal cost proportional to its carrier's `co2_emissions` factor.
- Add schedule rows to ramp the carbon price across years. When a schedule is active, the scalar input is disabled. Each snapshot uses the price from the most-recent schedule row whose year is at or before the snapshot's year.

### Monitoring a run

While a solve is in progress, the top bar shows an elapsed timer (minutes and seconds) and a **Cancel** button. The backend job runs independently; a brief network interruption retries polling silently and does not kill the solve. If the backend restarts during a solve, Ragnarok reports "Run disconnected — server restarted" and you must run again.

---

## 6. Reading results in the Analytics view

Click **A** in the activity bar after a successful run. The Analytics view has four sub-tabs:

### Validation sub-tab

Shows structural issues detected in the model. Issues are grouped into errors (block the solve), warnings (may degrade results), and notes. Clicking an issue row navigates you to the relevant row in the Model table.

You can trigger validation without running the full solver by opening the Run dialog, enabling **Dry run**, and clicking **Validate**.

### Result sub-tab

A curated dashboard of the most important charts and KPIs for the current run. The layout is saved in your browser's local storage and persists between sessions (key: `ragnarok:dashboard:result:v1`).

**KPI strip** — nine headline metrics across the top:

| KPI | Unit |
|---|---|
| Total cost | Currency |
| Dispatch | MWh |
| Avg price | Currency/MWh |
| Min / Max price | Currency/MWh |
| Peak load | MW |
| Load factor | % |
| Renewables share | % |
| Emissions | tCO2 (or as reported) |
| Snapshots | count x weight |

### Analytics sub-tab

A free-form dashboard where you can add, remove, resize, and rearrange chart cards. Click **Presets** to load one of fifteen built-in layouts:

- At a glance, Operations log, Daily digest, Supply mix, Market & price, Storage cycle, Emissions tracker, Trader board (3x3), Briefing, Map operations, Generator fleet, Nodal view, Storage fleet, Branch loading, Blank.

Each chart card has a settings gear that lets you change the metric, chart type (line, area, bar, donut), time aggregation (hourly or daily), and whether to stack series.

**Available metrics (system focus):** dispatch (by carrier), dispatch by generator, load, system price, system emissions, storage state of charge, storage charge/discharge power.

**Per-asset focus:** click any bus, generator, storage unit, or branch on the analytics map to switch focus to that asset. Charts in per-asset focus mode show only data for the selected asset or the full fleet if no specific asset is selected.

### Map

The analytics map shows bus positions, line loading (thickness), and bus nodal prices (color). Clicking an asset on this map switches the analytics focus to that asset and opens the per-asset detail card.

### Comparison sub-tab

Displays a side-by-side table of all runs currently included in the comparison list. Use the checkboxes on each run history card in the right-hand rail to include or exclude runs.

---

## 7. Run history

After each successful run, Ragnarok adds an entry to the run history rail on the right side of the Analytics view. The run history is session-scoped: it survives opening a new model or importing a project within the same browser tab, but is lost when you close or reload the tab.

Up to five unpinned entries are retained automatically. Pinned entries are never auto-removed.

### What each history card shows

- The run label (editable, defaults to "Run 1", "Run 2", …).
- The relative time it was saved and the source filename.
- Snapshot count, snapshot weight, carbon price (if non-zero), and active constraints.
- Two headline KPIs: system emissions and system price.

### Actions on a history card

| Action | How |
|---|---|
| View results | Click **View results** to restore this run's results and inputs as the active state. |
| Rename | Click the label text to edit it in place. Press Enter or click away to confirm. |
| Pin / Unpin | Click **Pin** to protect the entry from auto-expiry. Click **Unpin** to remove the protection. |
| Include / exclude from Comparison | Check or uncheck the checkbox in the top-left of the card. |
| Delete | Click **Delete**, then confirm with **Yes** in the inline confirmation. |
| Clear all | Click **Clear all** in the rail header to remove every entry (including pinned ones). Prompts for confirmation. This does not affect the live model or the currently displayed result. |

### What "View results" does

Clicking **View results** on a history card:

1. Loads that run's input model back into the live editable state (visible in the Model and Build views and used by any subsequent export).
2. Displays that run's results in the Analytics view.
3. Restores the run's snapshot range, snapshot weight, and carbon price to the live sliders.
4. Keeps you on whichever view and sub-tab you are currently on — it does not jump to a different tab.
5. The previous live model is pushed onto the undo stack so you can undo the restore with Ctrl+Z.

---

## 8. Exporting your work

All export actions are in the file toolbar at the top of the Model view. Open **M** to access them.

### Export Project

Exports a single `.xlsx` workbook containing both the model inputs and the solved outputs (if a run has been completed). This is the recommended archive format because it can be re-imported with full state restoration.

- If no run has been completed, only the inputs are written (the file is still valid as input for the next session).
- The export always reflects the run you are currently viewing. To export a different run, restore it from the run history rail first, then export.

**Steps:**

1. In the Model view, click **Export Project**.
2. A save dialog opens (File System Access API on Chromium, fallback download on other browsers).
3. Choose a folder and filename. The suggested name is `<current_filename>_project.xlsx`.
4. Click Save.

### Export Result

Exports a dedicated results workbook `.xlsx` containing only the solved output sheets (dispatch, price, emissions, capacity, etc.). This button is disabled until a run has been completed.

**Steps:**

1. Click **Export Result**.
2. Save dialog opens. Suggested name: `<current_filename>_results.xlsx`.
3. Click Save.

### More formats (under "More formats...")

Click **More formats...** in the file toolbar to expand additional import/export options:

| Action | Format | Notes |
|---|---|---|
| Import CSV folder | `.zip` of CSVs | Zip archive in PyPSA CSV-folder layout. Unknown files are skipped. |
| Import netCDF | `.nc` | Requires the backend to be running. |
| Import HDF5 | `.h5` / `.hdf5` | Requires the backend to be running. |
| Export CSV folder | `.zip` of CSVs | Exports the current model (inputs only) as a PyPSA CSV folder archive. |
| Export netCDF | `.nc` | Requires the backend to be running. Exports current model inputs. |
| Export HDF5 | `.h5` | Requires the backend to be running. Exports current model inputs. |

### Save and Save As

**Save** writes the model inputs back to the file you opened (Chromium only, using the stored file handle). If no handle is available — for example after importing from a project file or using a browser without File System Access API — Save falls back to Save As.

**Save As** always opens a save dialog and lets you choose a new name and location.

---

## 9. Settings

Click **S** in the activity bar. The Settings view has a left navigation panel grouped into four sections: Setup, Policy, Solve, and App.

### Setup

**Scenarios** — a scenario preset captures the full set of run parameters (simulation window, carbon price, pathway configuration, rolling-horizon configuration, constraints, discount rate, load-shedding settings) under a named label. Use scenarios to switch quickly between different study configurations.

- **New from current**: creates a new preset from the current parameter values.
- **Update active**: overwrites the active preset with the current values (button is highlighted when the active preset differs from the current sliders).
- **Duplicate**: creates a copy of the active preset.
- **Delete**: removes the active preset (disabled when only one preset remains).
- Click a preset label pill to activate it and apply its values.

**Simulation window** — dual-range slider for selecting the start and end snapshot indices. Resolution buttons: 1h, 2h, 3h, 4h, 6h, 8h, 12h, 24h. Selecting 24h treats each row of your time-series data as one day.

**Multi-year planning** — toggle between Single period and Pathway mode. In Pathway mode, add investment period rows (year, objective weight, years weight).

**Rolling horizon** — enable and configure rolling-horizon dispatch (horizon length, overlap, step size).

### Policy

**Carbon price** — scalar carbon cost (currency/tCO2) or a year-indexed schedule. See [section 5](#5-configuring-and-running-a-study) for details.

**Constraints** — custom global constraints added on top of the standard PyPSA constraints. Each row has an enabled toggle, a label, and the constraint parameters. These are separate from the `global_constraints` sheet in the model workbook, which holds PyPSA-native constraints (such as CO2 budget limits).

### Solve

**Stochastic** — configure stochastic scenario generation for uncertainty analysis.

**Security-constrained (SCLOPF)** — enable security-constrained linear optimal power flow.

**Solver** — HiGHS configuration:

- **Threads**: 0 (auto, uses all available cores), 1, 2, 4, or 8.
- **Algorithm**: Simplex or IPM (interior point). IPM is often faster for large LP models. Use Simplex for MIP or unit-commitment runs.

### App

**Appearance** — per-carrier color swatches. Click the color input for a carrier to change its color across all maps, legends, and charts. Use the up/down arrows to reorder carriers (the order affects legend and chart stacking order).

**Project defaults** — settings that affect parsing and display across all sessions:

| Setting | Options | Default | Effect |
|---|---|---|---|
| Date format | Auto-detect, YYYY-MM-DD, DD-MM-YYYY, MM-DD-YYYY | Auto-detect | Declares the format of snapshot timestamps in the input workbook. Display is always canonical ISO. |
| Currency | Dropdown of common currencies | USD ($) | Sets the currency symbol shown in the KPI strip, carbon price fields, and chart labels. |
| Discount rate | 0–1 (fraction) | 0.05 | Used to annualize capital costs for extendable assets. 0.05 = 5% WACC. |
| Load shedding | Off / On | Off | When On, unmet demand is absorbed at the Value of Lost Load (VOLL) rather than causing solver infeasibility. |
| Value of lost load | Number (currency/MWh) | 2000 | Visible only when Load shedding is On. |

---

## 10. Plugins

Click **P** in the activity bar. The Plugins view has a rail on the left to install and switch between plugins, and a panel on the right showing the selected plugin's GUI (Description / Input / Output). Plugins run in the browser and never contact the Ragnarok backend.

### Installing a plugin

1. Click **Install plugin** and select a plugin `.zip` (a `module.json` manifest plus a JS entry).
2. The plugin appears in the rail and its GUI renders from the manifest.

There is no enable/disable switch — a plugin is simply installed or not.

### Using a plugin

Select the plugin in the rail, fill in its **Input** form, and use its action buttons (for example, an importer's **Send model to Ragnarok**). A plugin can replace the workbook, contribute sheets and constraints, or read run output in its **Output** tab. Constraints a plugin produces appear in **Settings → Advanced Constraints** and are applied on the next **Run**.

### Plugin servers

Some plugins do heavy work in their own local server. Register that server in the project's `plugins.env` (the plugin's **Server setup** panel shows the exact line); Ragnarok's `run.command` launches it on startup. The plugin then connects to it over `localhost`.

### Uninstalling a plugin

Click **Uninstall** next to a plugin in the rail to remove it.

For authoring your own plugins, see [PLUGIN_AUTHORING.md](PLUGIN_AUTHORING.md).

---

## 11. Troubleshooting

### Error: "Failed to start run" or run button appears to do nothing

**Cause**: The local FastAPI backend is not running or is not reachable at `http://127.0.0.1:8000`.

**Fix**: Start the backend server (see [section 2](#2-prerequisites-and-starting-the-application)). Confirm it is responding by visiting `http://127.0.0.1:8000/docs`. Then click Run again.

### Run fails with "objective function could not be created" or "ValueError: objective function empty"

**Cause**: The model has no generator or storage component with a non-zero cost (capital cost or marginal cost). PyPSA requires at least one cost term to form an objective function.

**Fix**: Add `marginal_cost` or `capital_cost` values to at least one generator or storage unit in your model. Even a small marginal cost (e.g. 0.01) on a dispatchable generator is sufficient.

### Run fails with "INFEASIBLE" solver status

**Cause**: One or more constraints conflict and the model has no feasible solution. Common causes: load exceeds available generation capacity for some snapshots; a CO2 budget constraint in `global_constraints` is too tight; or a custom constraint contradicts the model data.

**Fix**: Enable **Load shedding** in Settings > Project defaults as a temporary diagnostic. If the model solves with load shedding, find the snapshots with non-zero shed load and review the capacity and availability data for those periods. Check `global_constraints` for budget limits that may be infeasible given the installed capacity.

### "Export Result" button is greyed out

**Cause**: No run has been completed in the current session or after the last history restore.

**Fix**: Run the model first. The button enables as soon as results are available.

### Export does nothing (no save dialog, no download)

**Cause**: Some browsers block file-save dialogs triggered outside a direct user interaction (e.g. when called from certain async contexts). This is rare.

**Fix**: Try using a Chromium-based browser (Chrome or Edge). If the issue persists, use the CSV folder export which triggers a standard download without the File System Access API.

### netCDF or HDF5 import/export fails

**Cause**: These operations route through the backend. The backend must be running at `http://127.0.0.1:8000`.

**Fix**: Confirm the backend is running. Check the backend terminal output for error details.

### Run history is empty after refreshing the page

**Cause**: Run history is stored only in browser memory (React state). It is not persisted to disk or local storage. Reloading the tab clears it.

**Fix**: Before closing or reloading, export the run you want to keep using **Export Project**. The exported project file can be re-imported in a future session via **Import Project**, which adds an entry back to the history rail.

### "Run disconnected — server restarted"

**Cause**: The backend process stopped and restarted while a solve was in progress. The job was lost.

**Fix**: Confirm the backend is stable, then click Run again.

### Validation badge appears on the Analytics button but the model looks correct

**Cause**: The badge reflects either the last explicit validation run (via Dry run) or live structural issues detected by the client-side validator (`useModelIssues`). The client-side check catches things like buses referenced in generators that do not exist.

**Fix**: Click **A** to open Analytics, then the **Validation** sub-tab. Review the errors and warnings listed. Click any issue row to navigate to the relevant sheet and row in the Model view.

### Date parsing produces unexpected snapshot order

**Cause**: Ambiguous date formats (e.g. `01-02-2030` could be January 2 or February 1 depending on locale).

**Fix**: Set the **Date format** in Settings > Project defaults to the explicit format your input file uses (YYYY-MM-DD, DD-MM-YYYY, or MM-DD-YYYY). "Auto-detect" works for ISO dates but can misparse ambiguous formats.
