# Ragnarok — User Manual

Ragnarok is a local web application for building, editing, and solving PyPSA
power-system optimization models without writing Python. A React/TypeScript
frontend communicates with a FastAPI backend that uses PyPSA and linopy to
formulate and solve linear programs with the HiGHS solver. Everything runs on
your own machine; no data leaves your computer.

This manual is the single reference for everything a user needs to know to
operate the application. For how the system is architected internally, see
[docs/architecture/ARCHITECTURE.md](architecture.md). For writing
your own plugins, see [docs/guides/PLUGIN_AUTHORING.md](plugin.md).

---

## Table of contents

1. [Prerequisites and launching](#1-prerequisites-and-launching)
2. [Workspace tour](#2-workspace-tour)
3. [Model view — opening, editing, and saving](#3-model-view--opening-editing-and-saving)
4. [Build view — guided model construction](#4-build-view--guided-model-construction)
5. [Settings view](#5-settings-view)
   - 5.1 [Setup group](#51-setup-group)
   - 5.2 [Policy group](#52-policy-group)
   - 5.3 [Solve group](#53-solve-group)
   - 5.4 [App group](#54-app-group)
6. [Running a model](#6-running-a-model)
7. [Analytics view](#7-analytics-view)
   - 7.1 [Validation sub-tab](#71-validation-sub-tab)
   - 7.2 [Result sub-tab](#72-result-sub-tab)
   - 7.3 [Analytics sub-tab](#73-analytics-sub-tab)
   - 7.4 [Comparison sub-tab](#74-comparison-sub-tab)
8. [Run history](#8-run-history)
9. [Exporting your work](#9-exporting-your-work)
10. [Plugins](#10-plugins)
11. [Capabilities and limitations](#11-capabilities-and-limitations)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Prerequisites and launching

### What you need

| Requirement | Notes |
|---|---|
| Node.js (includes npm) | Builds and serves the frontend |
| git | Required by the PyPSA pip dependency |
| Python 3.11 or later | Runs the FastAPI backend |
| A modern Chromium-based browser (Chrome, Edge, Arc) | Recommended. Firefox works but the save-file picker falls back to a plain download. |

`run.command` checks for npm, git, and Python 3.11+ on every startup and prints
a download URL if any are missing.

### Launching the application

From the project root, run:

```bash
bash run.command
```

On macOS you can also double-click `run.command` in Finder.

The script performs the following steps in order:

1. Checks that `npm`, `git`, and Python 3.11+ are available.
2. Creates a `.venv-pypsa` virtual environment (first run only).
3. Installs backend Python dependencies (skipped when unchanged since last launch).
4. Installs frontend npm packages in the `node_modules/` directory (first run only).
5. Frees ports 3000 and 8000, killing any stale processes on those ports.
6. Starts the FastAPI backend (`uvicorn`) on `127.0.0.1:8000`.
7. Polls `http://127.0.0.1:8000/api/health` until the backend is ready.
8. Reads `plugins.env` (if present) and starts any registered plugin servers.
9. Starts the React frontend on port 3000 and opens it in your default browser.

The first launch is slower because it downloads Python packages and npm modules.
Subsequent launches typically start in a few seconds.

All processes — backend, plugin servers, and frontend — shut down cleanly when
you close the terminal or press Ctrl+C.

### Confirming the backend is running

Visit `http://127.0.0.1:8000/docs` in your browser after launch. If the FastAPI
automatic documentation page loads, the backend is ready.

---

## 2. Workspace tour

### Top bar

The top bar runs the full width of the window.

- **Ragnarok** (brand label, left) — identifies the application.
- **Run** button — opens the Run dialog. Disabled while a solve is in progress.
- **Clear** button — discards the loaded model and starts from an empty workbook. Prompts for confirmation.
- **Elapsed timer** and **Cancel** button — visible only while a solve is running.
- Filename, snapshot count, and status message — displayed on the right side.

The status bar displays "Ready. Open a workbook or import a project." when no
model is loaded.

### Activity bar

The narrow vertical strip on the far left is the only navigation between views.
Each button shows a single letter and its full name as a tooltip.

| Letter | View | Purpose |
|---|---|---|
| B | Build | Guided step-by-step wizard for authoring a model from scratch on a map. |
| M | Model | Spreadsheet editor for all component sheets plus a read-only topology map. |
| S | Settings | Scenario presets, simulation window, carbon price, planning modes, constraints, solver options, and appearance. |
| A | Analytics | Results dashboard, validation report, KPI strip, and run comparison. |
| P | Plugins | Install, use, and uninstall plugins (frontend and backend). |

The Analytics button shows a badge with the count of validation errors and
warnings when validation has been run and found issues. The Plugins button shows
a badge with the count of installed plugins.

---

## 3. Model view — opening, editing, and saving

Click **M** in the activity bar to open the Model view. This is the primary
editing surface. It has three resizable columns: sheet tree on the left, table
editor in the center, and a read-only topology map on the right.

### Opening an existing workbook

1. Click **Open** in the file toolbar at the top of the Model view.
2. Select an `.xlsx` PyPSA workbook in the file picker.
3. The workbook loads into the table editor. The status bar confirms the filename.

If your browser does not support the File System Access API (non-Chromium
browsers), the picker falls back to a standard file dialog. In that case,
**Save** always prompts for a filename rather than writing in place.

### Importing a project

A project file contains both model inputs and solved outputs in one `.xlsx` file.
Use **Import Project** (in the file toolbar) when you have a file previously
exported with **Export Project**. The full run state — inputs, results, and run
settings — is restored, and a history entry is added to the run history rail.

### Sheet tree

The left column lists every component sheet grouped by category:

- **Static sheets**: network, carriers, buses, generators, loads, lines, links,
  storage units, stores, transformers, shunt impedances, processes, global
  constraints, line types, transformer types, snapshots.
- **Time-series sheets**: generators-p_max_pu, loads-p_set, and other per-component
  time-series profiles.

Click any sheet name to load it in the table editor. Sheets with validation
errors or warnings show a colored indicator next to their name.

### Table editor

The center column is a spreadsheet grid. Each column header matches a PyPSA
attribute name.

**Editing cells** — click any cell to edit it in place. Press Enter or Tab to
move to the next cell. Changes are applied immediately to the live model.

**Adding rows** — click the **+ Add row** button below the table, or paste
multiple rows from a spreadsheet using Ctrl+V (Cmd+V on macOS).

**Deleting rows** — click the delete control on the left side of the row.

**Adding columns** — use the **+ Add column** action in the column header area
to add a custom attribute column.

**Renaming and deleting columns** — right-click a column header to rename or
delete it.

**Importing time-series CSV** — when a time-series sheet is active, use the
**Import CSV** action to load a `.csv` file. The first column must contain
snapshot timestamps; subsequent columns must be named after the components they
profile.

**Undo and redo** — Ctrl+Z (Cmd+Z on macOS) undoes the last model edit. Ctrl+Shift+Z
or Ctrl+Y redoes. The undo stack holds up to 50 operations per session.

### Topology map

The right column shows a read-only Leaflet map with bus positions, branch
connections, and component markers colored by carrier. This map updates live as
you edit the model. It is for reference only; editing is done in the table.

### File operations

All file operations are in the file toolbar at the top of the Model view.

| Action | Description |
|---|---|
| Open | Load a `.xlsx` workbook (inputs only). |
| Save | Write inputs back to the open file handle (Chromium only). Falls back to Save As if no handle is available. |
| Save As | Open a save dialog and choose a new name and location. |
| Import Project | Restore a previously exported project file (inputs + results + settings). |
| Export Project | Save a `.xlsx` containing inputs, solved outputs, and run metadata. |
| Export Result | Save a results-only `.xlsx` (disabled until a run completes). |
| More formats... | Expand additional import/export options (see [Exporting your work](#9-exporting-your-work)). |

---

## 4. Build view — guided model construction

Click **B** in the activity bar. The Build view is a step-by-step wizard that
guides you through authoring a model in PyPSA dependency order. It writes
directly into the same underlying model as the Model view; switching between the
two views at any point shows the same data.

### Build steps

The wizard has the following steps:

| Step | Primary sheet | Description |
|---|---|---|
| Network | network | Project metadata: name, coordinate reference system, base year. |
| Carriers | carriers | Energy carriers (electricity, gas, heat, etc.) and their CO2 emission factors. |
| Buses | buses | Network nodes. Every generator, load, and line attaches to a bus. |
| Generators | generators, generators-p_max_pu | Dispatchable and variable generation. Costs and capacity feed the optimization. |
| Loads | loads, loads-p_set | Demand at each bus, either as a static p_set or a time-series profile. |
| Storage | storage_units, stores | Storage units and stores. This step is optional. |
| Lines | lines | AC transmission lines between buses. |
| Links | links, transformers | Controllable links (HVDC, converters) and transformers. |
| Processes | processes | Sector-coupling conversion processes. Optional. |
| Constraints | global_constraints | Global constraints such as CO2 caps and expansion limits. |
| Review | network | Validate the model before solving. |

Each step shows a table editor scoped to that step's sheet on the left and an
issue detail pane on the right.

### Placing buses on the map

The center of the Build view is an interactive map for geo-aware sheets (buses,
lines, links, transformers).

1. Navigate to the **Buses** step.
2. Click anywhere on the map to drop a new bus at that location. Ragnarok assigns
   an auto-generated name such as `bus_1`.
3. Drag an existing bus marker to update its `x` and `y` coordinates in the table.

### Drawing lines and links on the map

1. Navigate to the **Lines** or **Links** step.
2. Click the source bus marker, then click the destination bus marker. A branch
   row is added to the sheet with `bus0` and `bus1` set automatically.

---

## 5. Settings view

Click **S** in the activity bar. The Settings view has a left navigation panel
organized into four groups: **Setup**, **Policy**, **Solve**, and **App**. Click
any item in the nav to open that section.

---

### 5.1 Setup group

#### Scenarios

A scenario preset captures the full set of run parameters — simulation window,
carbon price, pathway configuration, rolling-horizon configuration, constraints,
discount rate, and load-shedding settings — under a named label. Switching
between presets instantly applies all saved parameters.

**Actions:**

| Button | Effect |
|---|---|
| New from current | Create a new preset from the current parameter values. |
| Update active | Overwrite the active preset with the current values. The button is highlighted when the current controls differ from the saved preset. |
| Duplicate | Create a copy of the active preset. |
| Delete | Remove the active preset. Disabled when only one preset remains. |
| Preset label pill | Click to activate a preset and apply its values. |

Each preset also has an editable **label** and a free-text **Notes** field,
useful for recording the intent of a configuration.

A status indicator next to the action buttons shows whether the current controls
match the active scenario ("Current controls match the active scenario") or have
been modified since the last save ("Current controls differ from the active scenario").

#### Simulation window

Controls which portion of the snapshot index is submitted to the solver.

- **Dual-range slider** — drag the left handle to set the start snapshot index
  and the right handle to set the end index. The label shows how many of the
  total available snapshots are selected.
- **Resolution buttons** — choose how many hours each snapshot represents: 1h,
  2h, 3h, 4h, 6h, 8h, 12h, or 24h. A weight of 24h treats each row of your
  time-series data as one day.

When pathway mode is enabled, the slider is hidden because the solver uses the
full horizon defined by the pathway periods.

#### Multi-year planning

Toggles between **Single period** and **Pathway** mode.

In **Single period** mode (the default), one optimization covers the full
snapshot window, optimizing dispatch and — when assets are marked
`p_nom_extendable` — capacity simultaneously.

In **Pathway** mode, you define a table of investment periods. Each row has:

| Column | Description |
|---|---|
| Period | The investment year (e.g. 2030, 2040). |
| Obj. weight | Relative weight of this period in the objective function. |
| Years | Duration of the period in years. PyPSA uses this to annuitize capital costs. |

Add periods with **Add period** and remove them with the × button on each row.

You also choose how snapshots are mapped to periods:

- **Use snapshots.period column** — your `snapshots` sheet must have a `period`
  column assigning each snapshot to an investment period.
- **Repeat all snapshots for each period** — the full snapshot window is used for
  every period.

#### Rolling horizon

Enables rolling-horizon dispatch, which solves a sequence of overlapping windows
across the snapshot timeline. This is useful for long time series that exceed
practical LP memory limits. Storage state is forwarded between windows by the
backend.

**Parameters:**

| Parameter | Description |
|---|---|
| Chunks | Number of solve windows to divide the snapshot range into. Minimum 2. |
| Overlap (snapshots) | Number of snapshots that adjacent windows share. A higher overlap improves accuracy at the boundary between windows. Maximum is step size minus 1. |

A rolling-horizon timeline diagram below the inputs shows each window's start
and end timestamps, with overlap regions highlighted. The summary line displays
total windows, horizon length, and step size.

Rolling horizon cannot be combined with stochastic mode or SCLOPF.

---

### 5.2 Policy group

#### Carbon price

Applies an economy-wide carbon cost to all generators proportional to their
carrier's `co2_emissions` factor. The cost is added to each generator's marginal
cost at build time and reported as a separate "Carbon cost" line in the results.

**Scalar price** — enter a flat rate in currency per tonne CO2. This value is
applied to every snapshot when no schedule is defined.

**Schedule** — add year-indexed rows to ramp the carbon price over time. When a
schedule is active, the scalar price input is disabled. Each snapshot uses the
price from the most-recent schedule entry whose year is at or before the
snapshot's year. For pathway runs, the investment period year is used; for
single-period runs, the snapshot timestamp year is used. Schedule rows are
automatically kept in ascending year order.

The carbon price is a flat per-tonne adder. There is no ETS permit curve, permit
banking, or endogenous carbon market clearing.

#### Standard Constraints

This section contains two editors side by side:

**Custom solver constraints** — a table of UI-authored linopy constraints applied
via `extra_functionality`. Each row has an enabled toggle, a label, and constraint
parameters. Supported metrics:

| Metric | Description |
|---|---|
| `co2_cap` | CO2 emission intensity cap (kg CO2e/MWh system average). |
| `max_load_shed` | Total load shedding cap (MWh over the modelled window). |
| `carrier_max_gen` | Generation cap for a named carrier (MWh). |
| `carrier_min_gen` | Generation floor for a named carrier (MWh). |
| `carrier_max_share` | Dispatch share cap for a named carrier (%). |
| `carrier_min_share` | Dispatch share floor for a named carrier (%). |
| `carrier_max_cf` | Capacity factor cap for a named carrier (fraction 0–1). |
| `carrier_min_cf` | Capacity factor floor for a named carrier (fraction 0–1). |

**PyPSA global_constraints sheet** — a table editor for the native PyPSA
`global_constraints` workbook sheet. Changes here persist directly into the
workbook and are included in any subsequent export. Use this for PyPSA-native
system-wide constraints such as CO2 budget limits and primary energy limits.

#### Advanced Constraints

A free-text editor for a custom DSL (domain-specific language). Write one
constraint per line; `#` starts a comment.

**DSL grammar and examples:**

| Expression | Meaning |
|---|---|
| `gen(carrier)` | Total energy dispatched by a carrier (MWh). Bare `gen` = all supply. |
| `cap(carrier)` | Installed capacity (MW). Bare `cap` = all supply. |
| `emissions(carrier)` | Total CO2 emissions (tCO2). Bare `emissions` = system total. |
| `load_shed` | Unserved energy (MWh). |
| `cf(carrier)` | Capacity factor for a carrier (fraction 0–1). |
| `gen(solar & wind)` | Union selector: sums over carrier `solar` *or* `wind`. Works in `gen`/`cap`/`cf`/`emissions`. |
| `cap(type, solar & wind)` | Column selector: sums over generators whose `type` column is `solar` or `wind` — any generator column works, e.g. a joint 100 GW VRE cap: `cap(type, solar & wind) <= 100000`. |

Combine terms with `+`, `-`, and `*` with a scalar constant, and close with `<=`,
`>=`, or `=` and a right-hand-side value.

```
# Require coal dispatch to stay below 200 GWh
gen(coal) <= 200000

# Cap nuclear capacity factor
cf(nuclear) <= 0.85

# Require combined solar + wind to supply at least 5 GWh
gen(solar) + gen(wind) >= 5000

# Emission intensity cap: average emissions per MWh <= 0.4 tCO2
emissions <= 0.4 * gen
```

After each run, the **Applied constraints (last run)** list below the editor
shows every constraint that was active — from the custom table, DSL, or
installed plugins — along with its source badge and, where available, its dual
variable (shadow price, labelled λ).

---

### 5.3 Solve group

#### Stochastic

Configures two-stage stochastic scenario planning. Investment (capacity)
decisions are shared across all scenarios; dispatch is scenario-specific. At
least two scenarios are required.

**Enabling** — click **On**. The button is disabled when rolling horizon is
active; disable rolling horizon first.

Each scenario row has:

| Field | Description |
|---|---|
| Name | A label for the scenario (e.g. `high_demand`, `low_wind`). |
| Weight | Relative probability weight. Weights are normalized to sum to 1 at solve time. |
| Advanced overrides | Per-cell value overrides for any sheet column (for creating variant input data per scenario). |

Add scenarios with **+ Add scenario** and remove them with the delete button on
each row.

Stochastic mode cannot be combined with rolling horizon or SCLOPF.

#### Security-constrained (SCLOPF)

Enables N-1 security-constrained linear optimal power flow. Every dispatch
decision must remain feasible under the outage of any single passive branch
(line or transformer) in the network.

**Enabling** — click **On**. The button is disabled if rolling horizon,
stochastic mode, or pathway mode is active; disable those modes first.

When enabled, the section shows the count of branches in N-1 coverage, broken
down by lines and transformers.

SCLOPF cannot be combined with rolling horizon, stochastic mode, or multi-period
pathway.

#### Solver

HiGHS configuration for the optimization step.

| Setting | Options | Default | Notes |
|---|---|---|---|
| Threads | auto, 1, 2, 4, 8 | auto | `auto` lets HiGHS use all available cores. |
| Algorithm | Simplex, IPM | Simplex | IPM (interior point method) is often faster for large LP models. Use Simplex for MIP or unit-commitment runs. |

---

### 5.4 App group

#### Appearance

A list of every carrier defined in the model with a color swatch for each. Click
a swatch to open the color picker and change that carrier's color across all
maps, legends, and charts. Drag a row by its grip handle to reorder carriers;
the order controls legend and chart stacking order throughout the application.

#### Project defaults

Settings that affect parsing and display across all sessions.

| Setting | Options | Default | Effect |
|---|---|---|---|
| Date format | Auto-detect, YYYY-MM-DD (ISO), DD-MM-YYYY, MM-DD-YYYY | Auto-detect | Declares the format of snapshot timestamps in the input workbook so the parser can resolve ambiguous strings. Display is always canonical ISO. |
| Currency | Dropdown of common currencies | USD ($) | Sets the symbol shown in KPI strips, carbon price fields, and chart labels. |
| Discount rate | Fraction (0–1) | 0.05 | Used to annuitize capital costs for extendable assets. 0.05 equals a 5% WACC. |
| Load shedding | Off / On | Off | When On, unmet demand is absorbed by a VOLL (value of lost load) backstop generator at each bus rather than causing solver infeasibility. |
| Value of lost load | Currency/MWh | 2000 | Visible only when load shedding is On. Sets the penalty cost for unserved energy. |

---

## 6. Running a model

### Opening the Run dialog

Click the **Run** button in the top bar. The Run dialog opens.

### Run dialog contents

**Planning summary** (read-only) — shows:

- Which scenario preset is active, or "ad hoc" if no preset is selected.
- Whether the solve is single-period or a multi-year pathway, and how many periods.
- Whether rolling-horizon mode is enabled, and its horizon and overlap.
- The snapshot range (`start → end`) and resolution (e.g. "1h resolution").
- The number of active custom constraints.

**Optimization settings** — two toggles:

- **Force LP** — when active, forces a linear programming relaxation even if the
  model contains generators with `committable = True`. Useful for debugging or
  speeding up large models that do not require unit commitment.
- **Dry run** — when active, the action button label changes to **Validate**.
  Clicking it sends the model to the backend's validation endpoint instead of
  the solver. Results appear in the Analytics view under the Validation sub-tab.

**Action buttons** — **Cancel** closes the dialog without running. **Run model**
(or **Validate** in dry-run mode) submits the job.

### Monitoring a run

While a solve is in progress, the top bar shows an elapsed timer (minutes and
seconds) and a **Cancel** button. The backend job runs independently; a brief
network interruption retries polling silently and does not kill the solve. If the
backend restarts during a solve, Ragnarok reports "Run disconnected — server
restarted" and you must run again.

When the solve completes, click **A** in the activity bar to open Analytics.

---

## 7. Analytics view

Click **A** in the activity bar after a run. The Analytics view has four
sub-tabs across the top: **Validation**, **Result**, **Analytics**, and
**Comparison**. A run history rail occupies the right side of the view.

---

### 7.1 Validation sub-tab

Shows structural issues detected in the model. Issues are grouped into:

- **Errors** — block the solve or indicate invalid data.
- **Warnings** — may degrade results but do not prevent running.
- **Notes** — informational items.

Click any issue row to navigate directly to the relevant sheet and row in the
Model view.

You can trigger validation without running the full solver by opening the Run
dialog, enabling **Dry run**, and clicking **Validate**. The Validation sub-tab
button shows a badge with the total error count when issues are present, and an
"ok" badge when validation passed cleanly.

---

### 7.2 Result sub-tab

A curated KPI dashboard for the current run.

**KPI strip** — nine headline metrics across the top:

| KPI | Unit |
|---|---|
| Total cost | Currency |
| Dispatch | MWh |
| Avg price | Currency/MWh |
| Min price | Currency/MWh |
| Max price | Currency/MWh |
| Peak load | MW |
| Load factor | % |
| Renewables share | % |
| Emissions | tCO2 |
| Snapshots | count × weight |

The full Result dashboard below the KPI strip shows an overview of the run in a
fixed layout. The layout is saved in your browser's local storage and persists
between sessions.

---

### 7.3 Analytics sub-tab

A free-form dashboard where you add, remove, resize, and rearrange chart cards
to build custom views of the results.

#### Adding and arranging cards

Click **+ Add card** (or use a preset) to add a chart card to the dashboard.
Each card occupies a resizable cell in a row layout. Drag cards to rearrange
them. Resize rows by dragging the row's bottom edge.

#### Chart card settings

Each chart card has a gear icon. Click it to configure:

| Setting | Options |
|---|---|
| Metric | See metric list below. |
| Chart type | Line, area, bar, donut (donut is available only for metrics that support it). |
| Time aggregation | Hourly or daily. |
| Stacked | Whether to stack series. |
| Focus | System (all assets) or a specific asset type and selection. |
| Group by | Carrier or individual asset name (for multi-asset metrics). |
| Bus filter | Narrow generator or storage metrics to assets attached to specific buses. |
| Carrier filter | Narrow generator metrics to specific carriers. |

#### Available metrics

**System focus** (all assets):

| Metric key | Label | Unit |
|---|---|---|
| dispatch | Dispatch by carrier | MW |
| dispatch_by_gen | Dispatch by generator | MW |
| load | Total load | MW |
| system_price | System marginal price | Currency/MWh |
| system_emissions | System emissions | tCO2e |
| storage_power | Storage power (charge/discharge) | MW |
| storage_state | Storage state of charge | MWh |

**Generator focus** (single or all generators):

| Metric key | Label | Unit |
|---|---|---|
| output | Output | MW |
| available | Available output | MW |
| curtailment | Curtailment | MW |
| emissions | Emissions | tCO2e |

**Bus focus** (single or all buses):

| Metric key | Label | Unit |
|---|---|---|
| load | Load | MW |
| generation | Generation | MW |
| smp | SMP (nodal marginal price) | Currency/MWh |
| emissions | Emissions | tCO2e |
| v_mag_pu | Voltage magnitude | p.u. (shown only when data is present) |
| v_ang | Voltage angle | deg/rad (shown only when data is present) |
| gen_output_by_bus | Generator output by bus | MW |
| gen_available_by_bus | Generator available by bus | MW |
| gen_curtailment_by_bus | Generator curtailment by bus | MW |
| gen_emissions_by_bus | Generator emissions by bus | tCO2e |

**Storage unit focus**:

| Metric key | Label | Unit |
|---|---|---|
| dispatch | Dispatch | MW |
| storage_power | Storage power (charge/discharge) | MW |
| state | State of charge | MWh |

**Store focus**:

| Metric key | Label | Unit |
|---|---|---|
| energy | Energy | MWh |
| power | Power | MW |

**Branch focus** (lines, links, transformers):

| Metric key | Label | Unit |
|---|---|---|
| terminal_flows | Terminal flows (P0, P1) | MW |
| loading | Loading | % |
| losses | Losses | MW |

**Process focus**:

| Metric key | Label | Unit |
|---|---|---|
| throughput | Throughput | MW |
| terminal_flows | Terminal flows (P0, P1) | MW |

**Shunt impedance focus**:

| Metric key | Label | Unit |
|---|---|---|
| active_power | Active power | MW |
| reactive_power | Reactive power | MVar |

#### Dashboard presets

Click **Presets** to load one of fifteen built-in layouts. Loading a preset
replaces the current layout; you can then resize, rearrange, and modify cards.

| Preset | Description |
|---|---|
| At a glance | Three energy/generator/storage mix donuts; one hero dispatch chart; load and price side-by-side. |
| Operations log | Four full-width time series: dispatch, load, price, emissions. |
| Daily digest | Daily-aggregated bars in a 2x2 grid, then hourly dispatch. |
| Supply mix | Dispatch stacked by carrier and by individual generator, with donuts. |
| Market & price | Price front-and-centre with daily summary, load, and energy-mix context. |
| Storage cycle | State of charge, charge/discharge power, then dispatch and load. |
| Emissions tracker | Hourly emissions, daily bar comparison, dispatch mix. |
| Trader board (3x3) | Nine compact tiles: load, price, emissions; dispatch views and donut; storage and notes. |
| Briefing | Run notes at top, then hero dispatch, then load and price. Good for screenshots. |
| Map operations | Hero map with line loadings; fleet-wide generator charts. |
| Generator fleet | Whole generator fleet output, curtailment, emissions, and availability. |
| Nodal view | Per-bus marginal price and load with a nodal map. |
| Storage fleet | Per-storage state, dispatch, and power across the whole fleet. |
| Branch loading | Line/link/transformer loading and losses with dispatch context. |
| Blank | One empty chart card for starting from scratch. |

#### Analytics map

The analytics map shows bus positions, line loading (line thickness), and bus
nodal prices (bus color). Click any bus, generator, storage unit, or branch on
the map to switch chart focus to that asset. Charts configured for per-asset
focus update to show data for the selected asset. Clicking an asset also opens
its per-asset detail card.

#### Notes card

The Trader board and Briefing presets include a Notes card, which is a free-text
field for recording observations about the run. Notes are stored with the run
history entry.

---

### 7.4 Comparison sub-tab

Shows a side-by-side KPI table for all runs currently included in the comparison
list. Use the checkboxes on run history cards in the right-hand rail to include
or exclude individual runs from the comparison.

---

## 8. Run history

After each successful run, Ragnarok adds an entry to the run history rail on the
right side of the Analytics view. The run history is session-scoped: it survives
opening a new model or importing a project within the same browser tab, but is
cleared when you close or reload the tab.

Up to five unpinned entries are kept automatically. Pinned entries are never
auto-removed.

### What each history card shows

- Run label (editable; defaults to "Run 1", "Run 2", ...).
- Relative time saved and source filename.
- Snapshot count, snapshot weight, carbon price (if non-zero), and number of
  active constraints.
- Two headline KPIs: system emissions and system price.
- A checkbox to include or exclude this run from the Comparison sub-tab.

### Actions on a history card

| Action | How |
|---|---|
| View results | Click **View results** to restore this run's inputs and results as the active state. |
| Rename | Click the label text to edit it in place. Press Enter or click away to confirm. |
| Pin / Unpin | Click **Pin** to protect the entry from auto-expiry. Click **Unpin** to remove the protection. |
| Include in Comparison | Check or uncheck the checkbox in the top-left of the card. |
| Delete | Click **Delete**, then confirm with **Yes** in the inline confirmation. |
| Clear all | Click **Clear all** in the rail header to remove every entry, including pinned ones. Prompts for confirmation. Does not affect the live model or the currently displayed result. |

### What "View results" does

Clicking **View results** on a history card:

1. Loads that run's input model back into the live editable state (visible in the
   Model and Build views and used by any subsequent export).
2. Displays that run's results in the Analytics view.
3. Restores the run's snapshot range, snapshot weight, and carbon price to the
   live settings.
4. Keeps you on your current view and sub-tab.
5. Pushes the previous live model onto the undo stack so you can undo the restore
   with Ctrl+Z.

---

## 9. Exporting your work

All export actions are in the file toolbar at the top of the Model view (click
**M** to reach it).

### Export Project

Saves a single `.xlsx` workbook containing both model inputs and solved outputs
(if a run has been completed). This is the recommended archive format because it
can be re-imported with full state restoration via **Import Project**.

If no run has been completed, only the inputs are written; the file is still
valid for the next session.

The export always reflects the run you are currently viewing. To export a
different run, restore it from the run history rail first, then export.

**Steps:**

1. In the Model view, click **Export Project**.
2. A save dialog opens (File System Access API on Chromium, fallback download on
   other browsers).
3. Choose a folder and filename. The suggested name is `<filename>_project.xlsx`.
4. Click Save.

### Export Result

Saves a results-only `.xlsx` containing the solved output sheets (dispatch,
price, emissions, capacity, etc.). This button is disabled until a run has been
completed.

Suggested name: `<filename>_results.xlsx`.

### More formats

Click **More formats...** in the file toolbar to expand additional options:

| Action | Format | Notes |
|---|---|---|
| Import CSV folder | `.zip` of CSVs | PyPSA CSV-folder layout. Unknown files are skipped. Frontend-side; no backend call. |
| Import netCDF | `.nc` | Backend conversion via PyPSA. Backend must be running. |
| Import HDF5 | `.h5` / `.hdf5` | Backend conversion via PyPSA. Backend must be running. |
| Export CSV folder | `.zip` of CSVs | Inputs only, PyPSA-native. Frontend-side; no backend call. |
| Export netCDF | `.nc` | Inputs only. Backend must be running. |
| Export HDF5 | `.h5` | Inputs only. Backend must be running. |

---

## 10. Plugins

Click **P** in the activity bar. The Plugins view has a left rail for managing
installed plugins and a main panel showing the selected plugin's interface.

There are two kinds of plugin. Ragnarok ships neither — plugins are 3rd-party
and you install them yourself:

- **Frontend plugins** run in the browser. They never contact the Ragnarok
  backend (a plugin that needs server-side computation runs its *own* local
  server — see [Plugin servers](#plugin-servers) below).
- **Backend plugins** run inside the Ragnarok backend process. Their build
  output is written straight into the server-side session, so large models
  never pass through the browser. They appear in the rail under a
  **Backend (server-side)** group.

> **Trust note:** installing a backend plugin means the server runs that
> plugin's Python code. Only install plugins you trust.

### Installing a plugin

1. Click **Install plugin...** in the left rail.
2. Select a plugin `.zip` file. The kind is detected automatically: a zip with
   `module.json` + a JavaScript entry file installs as a frontend plugin (into
   the browser); a zip with `manifest.json` + `plugin.py` uploads to the server
   as a backend plugin.
3. The plugin appears in the rail and its interface renders immediately.
   Re-installing a zip with the same id replaces the existing plugin.

There is no enable/disable toggle. A plugin is simply installed or not.

### Using a plugin

Select the plugin in the rail. The main panel shows the plugin's interface,
typically organized into tabs such as **Description**, **Input**, and **Output**.

- Fill in the plugin's **Input** form and use its action buttons (for example,
  an importer's "Send model to Ragnarok" button).
- A plugin can replace the entire workbook model, merge additional sheets, or
  append custom DSL constraint lines. Constraints contributed by a plugin appear
  in **Settings > Advanced Constraints** and are applied on the next **Run**.
- After a solve, the plugin's **Output** tab may display post-solve analysis
  rendered by the plugin's `analyze(result, config)` hook.

For a **backend plugin**, heavy input files (e.g. a model workbook) are
uploaded once into the plugin's server-side file store via its file picker and
referenced by name afterwards — the file never lives in the browser. Apply
actions run on the server and the editor refreshes from the session when they
finish. Whatever a plugin does, only the model it *returns* is applied — a
plugin cannot change your session as a side effect.

### Plugin servers

Some plugins do heavy work in their own local server (for example, a custom
data-import backend or a PyPSA variant). Such a server is not the Ragnarok
backend; it is a separate process that the plugin connects to over `localhost`.

To have `run.command` launch a plugin server automatically:

1. Copy the example file: `cp plugins.env.example plugins.env`
2. Open `plugins.env` and add one line per server in the format:

   ```
   <absolute path to server directory>|<run command>
   ```

   Example:

   ```
   /Users/you/my-plugin/backend|python server.py --port 8765
   ```

   Blank lines and lines starting with `#` are ignored.
3. The plugin's **Server setup** panel (if present) shows the exact line to add.
4. On the next `run.command` launch, Ragnarok starts each registered server
   using the server directory's own `.venv` if one exists, so plugin dependencies
   stay isolated from Ragnarok's Python environment.

### Uninstalling a plugin

Click the **x** button next to the plugin's name in the rail. The plugin is
removed immediately. Uninstalling a backend plugin also deletes its uploaded
data files from the server.

For authoring your own plugins, see
[docs/guides/PLUGIN_AUTHORING.md](plugin.md).

---

## 11. Capabilities and limitations

### Supported components

Every component below is editable in the Model and Build views. The schema is
generated from PyPSA's own component registry.

| Component | Sheet | Map marker |
|---|---|:---:|
| Bus | buses | Yes |
| Carrier | carriers | — |
| Generator | generators | Yes |
| Load | loads | — |
| Line | lines | Yes |
| Link | links | Yes |
| StorageUnit | storage_units | Yes |
| Store | stores | Yes |
| Transformer | transformers | Yes |
| ShuntImpedance | shunt_impedances | — |
| Process | processes | — |
| GlobalConstraint | global_constraints | — |
| LineType | line_types | — |
| TransformerType | transformer_types | — |
| Snapshots | snapshots | — |

### Supported study modes

All modes call `network.optimize()` (LOPF) via HiGHS.

| Mode | Description | Incompatible with |
|---|---|---|
| Single-period | One optimization over the full snapshot window. | — |
| Multi-period pathway | Joint investment + dispatch across defined periods. | SCLOPF |
| Rolling horizon | Sequence of overlapping window solves. | Stochastic, SCLOPF |
| Two-stage stochastic | Shared capacity, scenario-specific dispatch. | Rolling horizon, SCLOPF |
| Security-constrained (SCLOPF, N-1) | Dispatch feasible under any single branch outage. | Rolling horizon, Stochastic, Pathway |

Combining incompatible modes returns a 400 error from the backend.

### Capability matrix

| Feature | Supported | Notes |
|---|:---:|---|
| Single-period LOPF | Yes | |
| Multi-period pathway | Yes | |
| Rolling-horizon dispatch | Yes | Cannot combine with stochastic or SCLOPF |
| Two-stage stochastic | Yes | Cannot combine with rolling horizon or SCLOPF |
| Security-constrained LOPF (N-1) | Yes | Cannot combine with rolling, stochastic, or pathway |
| Unit commitment (MIP) | Yes | Per-generator `committable` flag; Force-LP override available |
| Power-flow only (PF/LPF) | No | Roadmapped |
| Custom linopy constraints (table) | Yes | 8 metric types |
| Custom DSL constraints | Yes | Free-text; `gen`, `cap`, `emissions`, `load_shed`, `cf` |
| Native global_constraints | Yes | |
| Carbon price (flat adder) | Yes | Scalar or year-indexed schedule; no ETS curve or banking |
| Load shedding (VOLL backstop) | Yes | Configurable cost; per-bus |
| Annuitised CAPEX (expansion) | Yes | |
| HiGHS solver | Yes | Simplex or IPM; thread count configurable |
| Other solvers (Gurobi, GLPK, CPLEX) | No | HiGHS only |
| Map-based network visualization | Yes | Leaflet |
| Dispatch / price / emissions charts | Yes | Recharts |
| Per-asset detail card | Yes | Generators, buses, lines, links, storage, processes, shunt impedances |
| LMP (nodal marginal prices) | Yes | Per-bus time series |
| Session run history | Yes | Every solved run is persisted server-side and listed in History |
| Persisted scenario manager (cross-session) | No | |
| Open / Save workbook (.xlsx) | Yes | Inputs only |
| Import / Export Project (.xlsx) | Yes | Inputs + solved outputs + metadata |
| Export Result workbook (.xlsx) | Yes | Full output dataset |
| CSV folder (import + export) | Yes | PyPSA-native; zipped; frontend-side |
| netCDF (import + export) | Yes | Backend-side conversion |
| HDF5 (import + export) | Yes | Backend-side conversion |
| Frontend plugin system | Yes | .zip install; JS hooks in browser; optional local server |
| Backend plugin system | Yes | .zip install; Python hooks in the backend process; server-side file store |
| Cloud / multi-user deployment | No | Local only; no authentication |
| Time-series data fetching | No | User must supply all time-series sheets |

### Current limitations

**No standalone power-flow study.** Every run is an optimization (LOPF).
Power-flow-only modes are roadmapped but not yet implemented.

**HiGHS only.** There is no UI mechanism to switch solvers. Gurobi, GLPK, CPLEX,
and other solvers are not exposed.

**Local backend only.** The FastAPI process runs at `http://127.0.0.1:8000`. There
is no authentication layer, cloud deployment, or multi-user session management.
Ragnarok is not intended for public network exposure as shipped.

**Session-scoped run history.** The run history list lives in browser memory. It
survives model swaps within the same browser session but is cleared on page reload
or "Clear all". There is no database-backed scenario store and no export of the
full run history list.

**Copper-plate unless impedances and limits are provided.** A network with buses
but no lines (or lines with `s_nom = 0` and no resistance/reactance) behaves as
a copper-plate system. Transmission constraints and nodal price separation are
only active when line impedances and `s_nom` limits are provided.

**Carbon price is a flat per-tonne adder.** There is no ETS permit curve, no
permit banking or borrowing between periods, and no endogenous carbon market
clearing.

**No built-in time-series generation.** Load profiles, renewable capacity factors,
and price series must be supplied by the user in the corresponding time-series
sheets. Ragnarok does not fetch weather data, ENTSO-E profiles, or any external
time-series source.

**Plugin UI is manifest-driven, not arbitrary React.** Plugins cannot inject
custom React components, register new sidebar panels, or add workbook sheets
dynamically at runtime. There is no remote plugin registry.

---

## 12. Troubleshooting

### Error: "Failed to start run" or the Run button appears to do nothing

**Cause**: The local FastAPI backend is not running or is not reachable at
`http://127.0.0.1:8000`.

**Fix**: Confirm the backend is up by visiting `http://127.0.0.1:8000/docs`. If
the page does not load, restart the application with `bash run.command`. Then
click Run again.

### Run fails with "objective function could not be created" or "ValueError: objective function empty"

**Cause**: The model has no generator or storage component with a non-zero cost.
PyPSA requires at least one cost term to form an objective function.

**Fix**: Add `marginal_cost` or `capital_cost` values to at least one generator
or storage unit. Even a small marginal cost (e.g. 0.01) on a dispatchable
generator is sufficient.

### Run fails with "INFEASIBLE" solver status

**Cause**: One or more constraints conflict and the model has no feasible solution.
Common causes: load exceeds available generation capacity for some snapshots; a
CO2 budget constraint in `global_constraints` is too tight; or a custom constraint
contradicts the model data.

**Fix**: Enable **Load shedding** in **Settings > Project defaults** as a
temporary diagnostic. If the model solves with load shedding on, find the
snapshots with non-zero shed load and review the capacity and availability data
for those periods. Check `global_constraints` for budget limits that may be
infeasible given the installed capacity.

### Incompatible modes error (400 from backend)

**Cause**: You have enabled a combination of study modes that cannot run together:
stochastic + rolling horizon, SCLOPF + rolling horizon, SCLOPF + stochastic, or
SCLOPF + pathway.

**Fix**: Go to **Settings** and disable the conflicting mode before running. The
SCLOPF and Stochastic section headers show a warning message identifying the
blocking mode.

### "Export Result" button is greyed out

**Cause**: No run has been completed in the current session, or no results are
associated with the currently viewed run.

**Fix**: Run the model first. The button enables as soon as results are available.

### Export does nothing — no save dialog, no download

**Cause**: Some browsers block file-save dialogs triggered outside a direct user
interaction. This is rare.

**Fix**: Use a Chromium-based browser (Chrome or Edge). If the issue persists,
use the CSV folder export, which triggers a standard download without the File
System Access API.

### netCDF or HDF5 import/export fails

**Cause**: These operations route through the backend. The backend must be running.

**Fix**: Confirm the backend is running at `http://127.0.0.1:8000`. Check the
backend terminal output for error details.

### Run history is empty after refreshing the page

**Cause**: Run history is stored only in browser memory. Reloading the tab clears it.

**Fix**: Before closing or reloading, export the runs you want to keep using
**Export Project**. Re-import the file in a future session with **Import Project**
to restore that run as an entry in the history rail.

### "Run disconnected — server restarted"

**Cause**: The backend process stopped and restarted while a solve was in progress.
The job was lost.

**Fix**: Confirm the backend is stable, then click Run again.

### Validation badge appears on the Analytics button but the model looks correct

**Cause**: The badge reflects live structural issues detected by the client-side
validator (for example, a bus name referenced in a generator that does not exist
in the buses sheet).

**Fix**: Click **A** to open Analytics, then the **Validation** sub-tab. Review
the listed issues. Click any issue row to navigate to the relevant sheet and row
in the Model view.

### Date parsing produces unexpected snapshot order

**Cause**: Ambiguous date formats (e.g. `01-02-2030` could be January 2 or
February 1 depending on locale).

**Fix**: Set the **Date format** in **Settings > Project defaults** to the
explicit format your input file uses: YYYY-MM-DD, DD-MM-YYYY, or MM-DD-YYYY.
"Auto-detect" works for unambiguous ISO dates but can misparse ambiguous strings.

### A plugin's server is not starting

**Cause**: The plugin server line in `plugins.env` may be missing or malformed,
or the referenced directory does not exist.

**Fix**: Check that the line in `plugins.env` follows the format
`<absolute path>|<run command>` with no leading or trailing spaces. Verify the
directory path is correct and that the run command works if you execute it
manually in that directory. Restart `run.command` after making changes.
