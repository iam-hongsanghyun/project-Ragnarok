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
13. [P2X module — power-to-X chains, RFNBO matching, LCOH](#13-p2x-module--power-to-x-chains-rfnbo-matching-lcoh)
14. [Screening and siting](#14-screening-and-siting)
15. [Training — the power-market modelling course](#15-training--the-power-market-modelling-course)

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

### Piecewise cost and efficiency curves

A `marginal_cost`, `capital_cost` or `efficiency` can be a piecewise-linear curve instead of one
number (PyPSA 1.3+). Open **Forge → Marginal cost curve → Piecewise breakpoints**, choose the component
(generators, links, processes, storage units, stores) and the curve, narrow the rows with filters,
and type the breakpoints (x, y). The editor checks the curve as you type: x must be strictly
increasing, start at 0 and (per-unit curves) end at 1, and per-unit curves need a fixed capacity.
It also tells you whether the curve is **convex** (solved as an LP) or **non-convex** (PyPSA adds
binaries and the run becomes a MIP). **Apply** writes the curve to a
`<component>-<attribute>-pw` sheet for every matched row; **Clear** removes it. A curve replaces the
scalar value of the same attribute on that row.

The sheet layout (one row per breakpoint, and what y means for each attribute) is in
[backend.md §5.7](backend.md#57-piecewisepy--piecewise-linear-curves). `capital_cost`
curves use absolute `p_nom` / `e_nom` / `s_nom` on the x axis and PERIODISED prices (per modelled
horizon, like `capital_cost`); PyPSA takes them as written and refuses a curve on a row that also has an `overnight_cost`. After a solve, the **Piecewise cost curves** card in
Analytics shows each curve and the average cost the optimiser realised on it. The curves round-trip
through netCDF, HDF5, the CSV-folder zip (PyPSA's own layout) and project workbooks. **Settings → Solver →
Advanced → Piecewise formulation** chooses how PyPSA formulates each curve.

### Maintenance and phase shifters

Edit these as ordinary attributes in the Generators, Links, Processes and Transformers sheets
(Model view, table editor). The attribute hints explain each column.

- **Maintenance.** Set `maintainable` to true on a generator, link or process. Then set
  `maintenance_duration` (hours per event), `maintenance_events` (events per horizon) and
  `maintenance_pu` (fraction of capacity out during an event, 0 to 1). The solver places the
  events. The **Maintenance schedule** card on the Analytics dashboard shows them. Force-LP does not relax
  maintenance, so a model with it stays a MIP.
- **Phase shifters.** On a transformer, set `phase_shift_min` and `phase_shift_max` (degrees).
  The solver picks the angle inside that range. The **Phase shifters** card shows the chosen
  angles. The power-flow study does not use them.

The attribute checks are in [backend.md §5.8](backend.md#58-maintenance-and-phase-shifting-transformers).

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

### Adding a plant (the plant-type picker)

On the **Generators** step the right-hand panel starts with **Add a plant**: one picker for every kind of plant.
Pick a type, a **bus** and a **capacity** (a fixed MW, or *Let the solver size it*), fill the few key fields, and press
**Add**. Everything else is defaulted from the technology data files and sits behind **Advanced**. A live preview says what
will be created ("Creates: 1 links, 1 generators, ...") and lists warnings before anything changes.

| Type | What it makes | Key fields |
|---|---|---|
| Generator | One generator | carrier, marginal cost; advanced: capital cost, lifetime, efficiency, build year |
| BESS | One storage unit (inverter + Li-ion storage, cost from technology-data) | capacity, duration (h); advanced: one-way efficiency |
| CCGT / OCGT | A gas-to-electricity Link, the gas bus, a gas supplier and the gas carrier (an existing gas bus and supplier are reused) | capacity (MW electric), *Unit commitment*; advanced: gas price, efficiency, parameter overrides |
| Gas + H2 co-firing (simple) | One generator on a fixed gas / H2 blend | turbine, H2 share and its basis (vol % or energy %), H2 price |
| Gas + H2 co-firing (fuel network) | Gas bus and H2 bus feeding a turbine-fuel bus through two feeder Links, and the turbine Link | turbine, H2 bus (an existing one, e.g. a P2X chain's, or a new one with an H2 supplier), maximum / minimum H2 share, basis, hourly or period |
| P2X chain | The P2X chain (electrolyser, H2 storage, optional ammonia / methanol / e-fuel synthesis, offtake), built by the same code as the P2X tab | product, H2 storage, offtake MW |

**One plant is one unit.** Every component a template creates carries the plant's name in a `plant` column, and one
`RAGNAROK_PLANTS` row stores its type and settings. Below the picker the **Plants** list shows one card per plant,
expandable to its components, with **Edit** and **Delete**. The Model tab lists the same cards above the sheet tree, and
both maps draw **one marker per plant** (a violet ring at its bus) instead of one per component.

- **Edit** reopens the picker on that plant. Saving *re-derives all its components* from the stored settings plus your changes
  (a hand edit of one of its rows is replaced; edit the plant, not its rows). The plant keeps its name.
- **Delete** removes every component of the plant and nothing else. A bus or carrier that another component still uses (a
  gas bus two plants share, the electricity bus, a carrier another generator has) is **kept**; the confirmation says which.
  If a kept bus has nothing feeding it any more, the message says so.
- A plant opened from a PyPSA file has the `plant` column but no registry row: it is listed and can be deleted, but not edited.
- The `plant` column and the registry sheets are saved with the workbook, the project, the session and the PyPSA netCDF / CSV /
  Excel exports (the column; the registry is a Ragnarok sheet).

**Unit commitment (CCGT, OCGT, co-firing).** Tick *Unit commitment* and the plant's operating characteristics take effect: a
minimum load (CCGT 40 %, OCGT 20 % of rated output, DEA), minimum up / down time, a start-up cost per start (per MW x the plant's
MW) and, if the time step is coarse enough for it to bind, ramp limits. The solve becomes a MILP; the Analytics commitment view
shows the starts. Unit commitment needs a fixed size: with *Let the solver size it* the fields are not written and the preview says
so (`committable` and `extendable` cannot be combined on one unit). PyPSA has one start-up cost per unit, so hot / warm / cold
starts are not distinguished (the data has no such split for a CCGT), and the efficiency is the rated value at every load.

#### Gas + H2 co-firing

*Simple.* One generator burns a fixed blend. With H2 energy share `s`, rated efficiency `eta`, gas price `c_g`, H2 price `c_h`
(EUR/MWh of fuel, LHV), gas CO2 factor `e_g` (0.198 tCO2/MWh) and variable O&M `v`:
`marginal cost = ((1 - s) c_g + s c_h) / eta + v` and the blend carrier's `co2_emissions = (1 - s) e_g`. A share entered as
**vol %** is converted with the lower heating value per normal cubic metre (H2 10.78 MJ/Nm3, CH4 35.8 MJ/Nm3):
`s = x L_H / (x L_H + (1 - x) L_G)`, so **30 vol % is 11.4 % of the energy**.

*Fuel network.* The solver chooses the blend. Gas and H2 each enter the plant's fuel bus through a feeder Link (efficiency 1, LHV
basis); the turbine Link runs from the fuel bus to the electricity bus. Set the limits on the plant (maximum / minimum H2 share,
vol % or energy %, hourly or over the period) and they are enforced in every solve:

- *hourly*: `h_t <= s_max (h_t + g_t)` and `h_t >= s_min (h_t + g_t)` for every snapshot (`h` = H2 flow, `g` = gas flow, MW LHV);
- *period*: the same with the snapshot-weighted sums, so the H2 may pile into the hours it is cheap. A period limit is never
  tighter than the hourly one.

A run option overrides the stored limits: `options.cofiringConfig` (`describe_run_options` documents it; `{enabled: false}`
switches them off). With rolling horizon the period is each window.

An H2 derate of the turbine (efficiency or capacity) is **off by default** and has no source in the data files: it is an
assumption you can switch on with the parameter overrides (`fuels.h2_derate_efficiency_per_share`) for a sensitivity only.

*Results* (MCP `get_plant_results`, `GET /api/build/plant/results/{run}`): per plant the generation, capacity factor, full-load
hours, starts (solved for committable units), costs, and for the gas plants the gas and H2 use, the **H2 share per hour (energy %
and the vol % equivalent)**, the CO2 emitted and the **CO2 avoided against the same dispatch burnt as 100 % gas**
(`e_g x H2 energy`). Fuel is valued at the nodal price of the plant's fuel bus, so a supplier shared by two plants is not booked
on the one that created it. Results can be grouped by plant for any run with plants.

**Data and sources.** `GET /api/build/plant/technologies` lists every parameter with its value, unit, source and a `verified`
flag: `file` (read from PyPSA technology-data v0.15.0 or its DEA workbooks), `derived`, `literature` (recalled, not re-fetched) or
`assumption` (CCGT start-up cost, minimum up / down times, the H2 price and the H2 derate are assumptions: replace them with
plant data).

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

The Scenarios table shows one row per scenario and only the settings that
**differ** across them (toggle **show all settings** to reveal the rest).
This surface is for naming and running scenarios; model values are edited in
Model/Forge.

**Actions:**

| Control | Effect |
|---|---|
| Scenario name | Click to rename the scenario inline (Enter or click away to save). |
| + Add current settings as scenario | Save the live run configuration as a new named scenario (prompts for the name). Also available in the Run console as "Add as Scenario". |
| Load | Apply a scenario's settings to the live run controls. |
| Delete | Remove a scenario. Disabled when only one remains. |
| Row checkbox | Include the scenario in "Run all" (none checked = run all). |
| In order / In parallel + Run | Queue the selected scenarios sequentially or in parallel (up to N at once). |
| Compare results → | Jump to Analytics → Comparison. |

The network topology and custom-DSL constraints are shared across all scenarios.

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
| Obj. weight | Weight of this period's costs in the objective — a discounting device. Set it to the discounted number of years the period stands for (at 5 % and ten years: 8.1078, 4.9775, 3.0558 for 2030, 2040, 2050). Only the ratios between periods change the plan. |
| Years | Calendar years the period stands for. PyPSA multiplies a period's energy-sum constraints by it — a CO2 cap on a period is a cap on its annual emissions times Years — but not its costs. A cap constant and the Years value are one decision. |

Clicking **Pathway** pre-fills 2030 and 2040 with weight 1 and Years 5 and 10; **Add period** appends a row 10 years later with weight 1 and Years 10. Treat these as
placeholders. PyPSA annuitises each row's `overnight_cost` with that row's `discount_rate`
and `lifetime` (Settings → Project defaults → Fill discount_rate writes the project rate into the rows)
and charges the annual figure in every period an
asset is active (`build_year` ≤ period < `build_year` + `lifetime`); the objective
weights are separate numbers you type and are not derived from that rate. The solve
is one perfect-foresight problem; there is no myopic (period by period) mode.

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
| `carrier_max_cap` | Total capacity cap for a named carrier (MW). Binds only where the carrier has extendable capacity. |
| `carrier_min_cap` | Total capacity floor for a named carrier (MW). Binds only where the carrier has extendable capacity. |
| `carrier_max_cap_share` | Capacity share cap for a named carrier (carrier MW / total MW, %). |
| `carrier_min_cap_share` | Capacity share floor for a named carrier (carrier MW / total MW, %). |

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

CVaR risk aversion is not in the GUI. Set it through the API or MCP with `options.riskPreference`
(see [backend.md §7.3](backend.md#73-stochastic)).

#### Security-constrained (SCLOPF)

Enables N-1 security-constrained linear optimal power flow. Every dispatch
decision must remain feasible under the outage of any single passive branch
(line or transformer) in the network.

**Enabling** — click **On**. The button is disabled if rolling horizon or stochastic mode is
active; disable that mode first.

When enabled, the section shows the count of branches in N-1 coverage, broken
down by lines and transformers.

SCLOPF cannot be combined with rolling horizon or stochastic mode. It works with multi-period
pathway. The API can limit the secured branches to a subset (`securityConstrainedConfig.branchOutages`);
the GUI secures all of them.

#### Solver

Settings for the optimisation step.

| Setting | Options | Default | Notes |
|---|---|---|---|
| Threads | auto, 1, 2, 4, 8 | auto | `auto` lets HiGHS use all available cores. Concurrent queued solves share the cores. |
| Method | Auto, Simplex, IPM, PDLP, HiPO | Auto | HiGHS's LP method. `Auto` lets HiGHS choose. HiPO falls back to IPM where the HiGHS build lacks it. Method does not apply to MIP or unit-commitment runs. |
| Solution acceptance | Lenient, Strict | Lenient | What counts as a successful solve. Lenient accepts any solution the solver toolchain validated, including interior-point (IPM / HiPO) runs that finish without crossover. Strict requires an optimal vertex solution. |
| Auto-scale objective | Off, On | On | Scales the objective before the solve. It can speed up simplex. |

**Advanced (n.optimize)** is collapsed by default. It holds:

- **Solver**: the solvers installed in the backend environment. HiGHS is the default.
- **Committable big-M (MW)** and **Cycle basis method** (`bfs-refined` or `paton`).
- **Piecewise formulation**: how PyPSA formulates each piecewise curve (see above).
- **Transmission losses**: secant-based line and link losses. This adds constraints per branch.
- **Linearised unit commitment**: relaxes committable binaries to an LP.
- **Compute infeasibilities (IIS)**: on an infeasible solve, appends the solver's IIS. Gurobi and Xpress only.

#### Power flow

Runs a power-flow study instead of an optimisation. **Mode** is **Off (optimise)** or **On**; **On** is
disabled while a mode that conflicts with it is active. **Method** is **AC (Newton-Raphson)** or **Linear (DC)**. The study does not dispatch. It cannot be
combined with rolling horizon, stochastic mode, SCLOPF, pathway or sampled blocks.

---

### Cost columns (PyPSA semantics)

Ragnarok passes the cost columns to PyPSA unchanged, and they mean what PyPSA says:

| Column | Meaning |
|---|---|
| `capital_cost` | Cost per MW (MWh, MVA) for the **modelled horizon** (your snapshots), as is. A year of snapshots makes it a yearly cost; three hours makes it a three-hour cost. No annuity, no scaling. |
| `overnight_cost` | The upfront price. PyPSA turns it into the horizon cost: `overnight × annuity(discount_rate, lifetime) × years in the horizon`. Needs the row's `discount_rate`; a blank `lifetime` is infinite (the annuity is then just the rate). When both columns are filled, `overnight_cost` wins. |
| `fom_cost` | Fixed O&M per MW for the modelled horizon, added as is. |
| `discount_rate`, `lifetime` | Read from the row. **Settings → Discount rate → Fill discount_rate** writes the project rate into the rows that have an `overnight_cost`. |

The Capacity Expansion card reads these back from PyPSA's own statistics: CAPEX over the horizon, split into
new build and already built (sunk), the overnight cost and the fixed O&M; "CAPEX per year" is the horizon figure divided
by the years in the horizon.

**Older workbooks.** A workbook saved before this basis (no `ragnarok_schema_version`) kept an overnight price in
`capital_cost` and Ragnarok annuitised it when it ran. Opening one moves those numbers once to `overnight_cost`
(setting `discount_rate`, and a 20-year `lifetime` where it was blank) so the result is unchanged, and shows you the list of rows it
changed; a piecewise capital curve is flagged for you to review, and a saved scenario that overrides `capital_cost` now overrides `overnight_cost`. Older stored runs are re-read the same way.

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
| Discount rate | Fraction (0–1) | 0.05 | The project discount rate (0.05 = 5% WACC). It changes no cost at run time: the buttons beneath it (a Forge action) write it into the `discount_rate` column of every row that has an `overnight_cost`; PyPSA annuitises with the row's own rate, and a run is refused if such a row has none. |
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

After each successful run, Ragnarok saves the run on the backend and adds an entry to the run
history rail on the right side of the Analytics view. The rail reloads the list from the backend every
few seconds, so entries survive a page reload.

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

The optimising modes call `network.optimize()` (LOPF) through the selected solver, HiGHS by default.

| Mode | Description | Incompatible with |
|---|---|---|
| Single-period | One optimization over the full snapshot window. | — |
| Multi-period pathway | Joint investment + dispatch across defined periods. | Sampled blocks |
| Rolling horizon | Sequence of overlapping window solves. | Stochastic, SCLOPF |
| Two-stage stochastic | Shared capacity, scenario-specific dispatch. | Rolling horizon, SCLOPF |
| Security-constrained (SCLOPF, N-1) | Dispatch feasible under any single branch outage. | Rolling horizon, Stochastic |

Combining incompatible modes returns a 400 error from the backend.

### Capability matrix

| Feature | Supported | Notes |
|---|:---:|---|
| Single-period LOPF | Yes | |
| Multi-period pathway | Yes | |
| Rolling-horizon dispatch | Yes | Cannot combine with stochastic or SCLOPF |
| Two-stage stochastic | Yes | Cannot combine with rolling horizon or SCLOPF |
| Security-constrained LOPF (N-1) | Yes | Cannot combine with rolling horizon or stochastic; works with pathway |
| Unit commitment (MIP) | Yes | Per-generator `committable` flag; Force-LP override available |
| Custom linopy constraints (table) | Yes | 8 metric types |
| Custom DSL constraints | Yes | Free-text; `gen`, `cap`, `emissions`, `load_shed`, `cf` |
| Native global_constraints | Yes | |
| Carbon price (flat adder) | Yes | Scalar or year-indexed schedule; no ETS curve or banking |
| Load shedding (VOLL backstop) | Yes | Configurable cost; per-bus |
| Annuitised CAPEX (expansion) | Yes | |
| HiGHS solver (default) | Yes | Method Auto / Simplex / IPM / PDLP / HiPO; thread count configurable |
| Other installed solvers | Yes | Settings → Solver → Advanced lists the solvers installed in the backend |
| Piecewise cost and efficiency curves | Yes | Forge → Marginal cost curve; Piecewise cost curves (solved) card |
| Maintenance scheduling | Yes | Generator / link / process attributes; Maintenance schedule card; Force-LP does not relax it |
| Phase-shifting transformers | Yes | Transformer attributes; Phase shifters card; the power-flow study ignores the angles |
| Temporal clustering | Yes | Forge → Temporal clustering |
| Power-flow study (LPF / AC PF) | Yes | Settings → Power flow; no optimisation |
| CVaR risk aversion | No | API and MCP only (`options.riskPreference`) |
| Iterative transmission expansion | No | API and MCP only (`options.iterativeExpansion`) |
| MATPOWER / pandapower import | No | API and MCP only |
| Map-based network visualization | Yes | Leaflet |
| Dispatch / price / emissions charts | Yes | Recharts |
| Per-asset detail card | Yes | Generators, buses, lines, links, storage, processes, shunt impedances |
| LMP (nodal marginal prices) | Yes | Per-bus time series |
| Session run history | Yes | Every solved run is persisted server-side and listed in History |
| Scenario presets | Yes | Saved in the workbook (`RAGNAROK_Scenarios` sheet) |
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

**Power flow is a study mode, not a workflow.** Settings → Power flow runs PyPSA's linear or AC
power flow on the model. It does not optimise, and there is no separate power-flow view.

**HiGHS by default.** Other solvers appear in Settings → Solver → Advanced only when they are
installed in the backend environment. Ragnarok does not install them.

**Local backend only.** The FastAPI process runs at `http://127.0.0.1:8000`. There
is no authentication layer, cloud deployment, or multi-user session management.
Ragnarok is not intended for public network exposure as shipped.

**Run history lives on the backend.** Every successful run is stored in the backend's run store and
listed from `GET /api/runs`, so it survives a page reload. Export Project keeps only the current run;
earlier runs stay with the backend that solved them.

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
stochastic + rolling horizon, SCLOPF + rolling horizon, SCLOPF + stochastic, or a
power-flow study or N-1 contingency run combined with another study mode.

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

**Cause**: The history list comes from the backend (`GET /api/runs`). An empty list means the backend
that answers is not the one that solved your runs.

**Fix**: Check the address the browser uses. To keep a run on another machine, use **Export Project**
and re-import the file with **Import Project**, which restores that run as an entry in the history rail.

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

---

## 13. P2X module — power-to-X chains, RFNBO matching, LCOH

P2X is an optional module (Settings → Modules → P2X, on by default). It builds power-to-X use cases into the
working model as ordinary components and reads the results from the P2X angle; there is no separate solver. Open the
**P2X** tab (hydrogen molecule icon on the activity bar). It has three sections.

### 13.1 Chain designer

1. Pick the **products**: hydrogen (always), ammonia, methanol, e-fuel (Fischer-Tropsch liquids).
2. Choose the **electricity bus** the electrolyser draws from and the **H2 bus** (a new one, or an existing bus).
3. **Electrolyser**: alkaline or PEM, extendable (the solve sizes it) or a fixed size, the commissioning year (the
   reference for additionality), the DEA availability (forced and planned outage) and, for a fixed size only, the
   minimum load (this makes the solve a MIP: `committable` and `extendable` cannot be combined).
4. **Hydrogen storage**: none, compressed tank or salt cavern, with an optional explicit compressor that draws electricity.
5. **Synthesis**, CO2 supply (direct air capture or point source) and product tanks for the derivatives. Ammonia adds an
   air separation unit for the nitrogen.
6. **Offtake**: tonnes per year (flat) or an uploaded profile (one value per snapshot, normalised to a mean of 1). A
   chain only runs for what is asked of it.
7. **Designated renewable generators**: the RES the electrolyser is matched to (the PPA).
8. **Parameters**: every technology parameter is editable and defaults from the data file. Hover a row for its source;
   the chip says whether the value was read from the upstream file (`file`), derived, recalled from the literature
   (`literature-recalled`, not re-verified) or a Ragnarok assumption.

**Preview** shows the components that would be added, with sizes, efficiencies and overnight costs. **Apply to model**
merges them (it is enabled only for the inputs you previewed). Costs use PyPSA's own split: each priced component carries an
`overnight_cost`, a `fom_cost` (PyPSA's per-horizon column: yearly O&M × the horizon of the workbook's snapshots, shown in the preview), a `lifetime` and a `discount_rate` (from Settings), and PyPSA annualises the overnight cost and scales it by the
modelled horizon (`n.nyears`). `capital_cost` stays blank.

The synthesis steps (Haber-Bosch, methanolisation, Fischer-Tropsch), the air separation unit and the CO2 capture are PyPSA 1.4
**Process** components (`rate0 = -1` on the H2 or electricity input, `rate1..3` the product and the other inputs); the
electrolyser, compressor and H2 discharge stay **Links**. A Process and a multi-port Link with the same ratios are the same LP
(identical objective, dispatch, LCOH / LCOA / LCOM); a chain saved earlier with Links reads exactly as before, and
`componentType: "link"` in the chain spec builds the Link form. The same chain can also be added from **Build -> Generators ->
Add a plant -> P2X chain**.

### 13.2 RFNBO

RFNBO rules follow Commission Delegated Regulation (EU) 2023/1184. The settings are stored for the session and used by
the next solve that does not set its own `rfnboConfig` option.

- **Temporal correlation (Art. 6)**: *hourly* adds, for every snapshot, electrolyser electricity <= designated RES
  output. *Monthly* does the same summed over each calendar month (allowed until 31 Dec 2029; hourly from 1 Jan 2030).
  *Auto* switches at the date you give.
- **Additionality (Art. 5(a))**: the designated generator came into operation not earlier than 36 months before the
  electrolyser (by build year). This is a check, and with *Drop designated generators that fail* a candidate filter, never an
  LP constraint. An extendable generator without a build year is new. Art. 5(b), no operating or investment aid, cannot be
  read from a model and is listed for attestation.
- **Geographic correlation (Art. 7(1)(a))**: same bus or same `bidding_zone`, `zone` or `country` value.
- **Art. 4 grid alternatives** (zone renewable share above 90 %, emission intensity below 18 gCO2e/MJ) are reported after
  a solve, never enforced.

The tab shows the check results before the solve. A solve with matching on and no electrolyser or no eligible designated
generator is refused with a sentence saying why.

### 13.3 Results

Choose a stored run (for a pathway run a **period** picker lists the run's investment periods; a single-period run has none) and the electricity cost basis: **nodal** (nodal price x
consumption) or **PPA** (the designated generators' cost, with unmatched energy at the nodal price). You get LCOH per kg H2,
LCOA per t NH3, LCOM per t MeOH and the e-fuel cost per MWh and per litre; the electrolyser capacity factor and full-load
hours; a cost waterfall per product; the electrolyser dispatch against the designated RES (zoomable); the H2 store state of
charge; and the compliance table (share of compliant hours and the unmatched electricity, hourly and monthly, whether
or not matching was on in the solve), the additionality and geographic checks and the Art. 4 reports.

### 13.4 Limits

- Heat from synthesis, the electrolyser and DAC is not credited; only the energy flows listed in the preview are modelled.
- Additionality is tested on calendar years (the model's resolution). Storage behind the connection point (Art. 6) and
  the day-ahead price conditions of Art. 7(1)(b)/(c) are not modelled.
- With rolling horizon, monthly periods are cut at the window edge.
- Costs are in the model's currency; the data file is EUR2025 and no exchange rate is applied.
- Agents reach the same functions through the MCP tools `list_p2x_technologies`, `preview_p2x_chain`, `get_p2x_results`
  (read-only) and `build_p2x_chain` (gated by `confirm`). RFNBO options go through `submit_solve` as
  `options.rfnboConfig` (see `describe_run_options`).

---

## 14. Screening and siting

Two separate tabs (both modules, switched on under Settings > Modules): **Screening** (a statistical
pre-screen of solar and wind sites, and of the regions they sit in, on the history you already hold) and
**Siting** (scan candidate locations, add them to the model and let the capacity-expansion solve choose).
Screening answers *which sites and regions repeat each other*; Siting answers *where the solve builds*.
Screening hands sites to the model through **Add selected sites to model**, which can add them as
zero-capacity expansion candidates, the same candidates Siting then works with.

### 14.1 Screening

Open **Screening** in the activity bar. It answers: which sites (or regions) repeat each other (redundant), which
complement each other, whether spreading across regions buys diversification, and what portfolio is steadiest. It
uses only the series you upload; nothing touches the model until you add sites.

**1 · Data.** Choose a series file (CSV or xlsx) and a site table.

- *Wide* series: a timestamp column and one column per site. *Long* series: columns `site`, `timestamp`,
  `value`.
- Site table columns: `name`, `lat`, `lon`, `technology` (solar, wind or other), optional `region`, `unit`
  (`cf` for a capacity factor 0-1, or `mw`) and `capacity_mw` (needed for `mw`, so the series can be
  divided by it).
- **Region series** (the *Region series* button): one series per region (a national or zonal capacity factor or
  generation, wide or long) with a region table: `name`, optional `lat` / `lon` (the centroid for the map), `technology`,
  `unit`, `capacity_mw`, and optionally a GeoJSON polygon, either in a `geometry` column or as a GeoJSON file whose
  features carry `properties.name`. A region with a polygon but no centroid gets the polygon's. The same validation as
  for sites applies (timestamps, duplicates, gaps, time zone, capacity factor 0-1).
- Pick the **time zone** of timestamps that carry no offset (default UTC; type any IANA name such as
  `Asia/Seoul`). Everything is stored in UTC.
- **Validate** reports timestamps that could not be read, duplicates (averaged), gaps per site, how the time
  zone was read, and unit problems (a capacity factor outside 0-1 is rejected, with a hint if it looks like a
  percentage). **Gaps**: *Interpolate short gaps* fills holes up to 48 steps and drops the rest; *Drop*
  removes every timestamp with a hole. **Upload** stores the dataset on the server for this session; it is
  still there after a reload. Click a stored dataset to make it the active one; **Delete** removes it.
- **Reference series** stores a load or price series (MW or currency per MWh) to correlate the sites with.

**2 · Level.** *Site* | *Region* (below). **3 · Analysis** (all computed on the server).

| Control | What it does |
|---|---|
| Sites in scope | All, selected, solar only, wind only (at most 60 per analysis; at the region level: all or selected regions) |
| Basis | Hourly (raw), daily, weekly, monthly, seasonal (one value per season and year; optional mapping such as `wet:6-9; dry:12,1,2`), diurnal (24 hour-of-day means), month x hour, or any pandas offset alias (`6h`, `2W`, `QS`) |
| Method | Pearson, or Spearman (rank based, robust to the many zeros of solar) |
| Anomalies | Correlate hourly values with the diurnal and seasonal cycle removed, so two solar sites do not look alike only because the sun rises. Not offered on the diurnal bases |
| Date range, Months only | Restrict the history, for example `6-8` for summer |
| Clock = UTC + | Shifts the analysis clock so diurnal shapes follow local time |
| Clusters | Number of clusters of the hierarchical clustering on 1 - correlation |
| Reference series | Correlate each site with the model's load, the system price of the active run, or an uploaded series; *same calendar hour, any year* matches a reference from another year |

**Reading the results.**

- **Site map.** Colour by technology, by cluster or by correlation. Click a site to focus it: the other sites
  get a line and fill coloured by their correlation with it (blue positive, orange negative). Tick sites in
  the table to select them (rings on the map); *Select cluster n* picks a whole cluster.
- **Correlation heatmap.** Sites ordered by cluster, so blocks of similar sites sit together. Hover for the
  value; drag the colour scale to filter by correlation.
- **Correlation vs distance.** One point per site pair, one legend entry per technology pair (click to
  hide). Scroll to zoom, drag to pan.
- **Profiles.** For the selected sites (up to 8): diurnal, monthly, per season, or the time series. Click a
  legend entry to hide a line; the time series zooms with the wheel and the slider.
- **Lagged correlation.** The focus site against the others for lags of up to 336 hours. A positive best lag
  means the other site repeats what the focus site did that many hours earlier (a front moving between them).
- **Portfolio.** Tick sites, set weights (scaled to sum 1) or press **Optimise** (minimum variance, optionally at
  least a target mean CF; or maximum mean CF under a cap on the standard deviation; a per-site weight cap and
  region caps such as `north:0.5`). The table shows mean CF, coefficient of variation, P10 / P50 / P90 (P90 is
  the output exceeded in 90 % of the hours), the share of hours below the low-output threshold and the loss of
  output in the worst N hours, for the portfolio and each site; the pair table shows how often two sites are
  low together against what independence would give, and the correlation of their ramps. The combined output
  duration curve (legend: show a site's own curve) and the risk / return plot with the efficient frontier are
  interactive.

**Region level.** Press *Region* under *2 · Level* and every panel above reads regions instead of sites.
The region series come from one of two places:

- *Aggregated from the sites* of the active site dataset: the capacity factor of a region is
  `CF_region = sum(w x CF_site) / sum(w)` over its sites. The weights `w` are *equal*, the *installed capacity*
  of each site (then it is the region's output over its installed capacity; every site needs a `capacity_mw`) or
  *custom* (`NOR1:2, NOR2:1`; a site not listed counts 0). *One series per region and technology* splits
  `north` into `north | wind` and `north | solar`; *Technology* keeps only one technology. A site with no region
  label is left out and reported. The region centroid is the weighted mean of its sites.
- An *uploaded region dataset* (above), used as it is.

What the region panels show:

- **Region map.** Polygons when uploaded, centroids always (marker size grows with the number of sites); colour by
  region, cluster or correlation. Click a region: the others get a line and fill coloured by their correlation with it.
- **Region heatmap, correlation vs distance (between centroids), profiles and lagged correlation.** The site panels,
  on the region series, on every basis (hourly to month x hour, custom, anomalies, date range) and both methods.
  The optional reference series is correlated with each region.
- **Within- vs between-region correlation** (needs sites, so it reads the active site dataset). A box plot of the
  pairwise site correlations *inside* each region and *across* each region pair (hover for count, mean, median,
  quartiles and range; the diamond is the correlation of the two aggregated region series, always higher than the
  pair mean because averaging removes local noise). The text under it gives the pooled means and their gap: a
  large gap means region borders carry information, so spreading capacity across regions buys diversification; a
  gap near zero means they do not. The table below it gives each site's correlation with its **own region** (with
  the site left out of the region series, so it is not compared with itself) and with the closest other region,
  and flags sites that behave more like another region than their own (*Only sites that behave like another
  region* filters to them).
- **Region portfolio.** The Portfolio panel on region series: weights per region, metrics, duration curve, and
  *Optimise* with a per-region weight cap and region caps (with one series per region and technology, a cap limits
  the region's total across technologies). Region portfolios are for screening: *Add to model* is offered at the
  site level only.

**Add selected sites to model.** Opens a preview: each selected site becomes a generator (carrier = its
technology) on the nearest bus with a `p_max_pu` profile from the dataset, aligned to the model's snapshots.
Set the model clock (UTC + n hours), a capacity per site (default: the site's own capacity, else 100 MW), a
marginal cost, or make them zero-capacity *expansion candidates* with a capex. **Preview** shows, per site,
how many snapshots matched exactly, by the same calendar hour of another year, by the hour-of-day mean, or
not at all, with warnings; **Add to model** merges them (the same rules as Data > Add to workbook). Then run
the model as usual.

### 14.2 Siting

Open **Siting** in the activity bar: draw a candidate region on the map, scan it (keyless weather per grid
point), add the extendable candidates to the model and run the capacity-expansion solve; the map and table then
show the built MW per candidate, and zero-built candidates are the rejected locations.

---

## 15. Training — the power-market modelling course

The **Training** tab (activity bar, *Training*; enable it under Settings > Modules) holds one course,
*Power market modelling with Ragnarok*: seventeen modules from an empty sheet to a policy-tested investment case. It
teaches the modelling idea and the Ragnarok control together, on the real app, and never edits your model for you.

**How a module works.** Each step shows, in order: *where* (the view and control), the *concept* (the modelling idea,
independent of the tool), what to *do*, any *values to type* (shown verbatim, copyable, never auto-applied — you type
them, so you learn which sheet and column they live in), the *run* to start, and *verify* — observable facts that tell
you the step worked. **Show me** walks real controls with a ring and a note; it never blocks input. The first step of
every module offers a three-way start: from nothing, from the model the module begins with, or from the model it ends
with. Nothing loads on its own; loading replaces the session model. Progress is stored per course in the browser.

**Numbers are checked.** Every figure a lesson states was produced by solving that module's own bundled example through
the app's build path, and `backend/tests/test_training_checkpoints.py` re-solves each one (`test_module_N_*`). If a
solver or model change moves a number, the test fails before the lesson lies.

| Module | Level | Starts from |
|---|---|---|
| 1 Foundations to 15 Market design | Beginner to Expert | `training_m1` … `training_m11`, `training_m7_year` (one growing model) |
| 16 The multi-year pathway | Expert | `training_m16_start`; finished model `training_m16` |
| 17 Batteries in depth | Expert | `training_m17_start`; finished model `training_m17`; `training_m17_store` for step 10 |

Bundled examples are listed under Welcome > Start with Examples and loadable by id (`/api/examples/{id}/load`). They are
authored by `backend/scripts/make_examples.py`; regenerate one with
`.venv-pypsa/bin/python -m backend.scripts.make_examples <id>`.

### Module 16 — the multi-year pathway

A one-bus system over 2030, 2040 and 2050, each period one representative day (24 snapshots weighted 365) standing for a
year. Existing coal retires through `build_year` + `lifetime`; wind, solar and a 4-hour battery are offered as one
*vintage* per period at falling overnight cost; demand grows 20 % a decade. You set up **Settings > Multi-year
planning** (objective weights 8.1078 / 4.9775 / 3.0558, Years 10), read the period selector in **Analytics > Result**, and
then add a carbon-price schedule (**Market & Policy > Carbon price**) and a per-period CO2 cap (**Build > Constraints**,
one `global_constraints` row per period with `investment_period`).

What it establishes, each pinned by a test:

- **Two weights, two jobs.** The objective weight discounts cost; only its ratios matter (weights 1/1/1 and 10/10/10 give one
  plan, cost ×10). The Years weight multiplies energy-sum constraints. A cap typed per period with Years 1 is ten times
  too loose and never binds; annual tonnes typed with Years 10 are ten times too tight (+45 % cost). Neither warns.
- **Period views** mask assets that are not active, sum energy, weight money by the period's objective weight (so the
  period totals add to the run) and report emissions as annual × Years. Served by `GET /api/runs/{name}/period/{period}`
  and `/api/runs/{name}/kpis?period=`.
- **Annuity vs overnight.** `overnight_cost` is the upfront price; PyPSA annuitises it (with the row's `lifetime` and
  `discount_rate`) and charges the annual figure in every active period. `capital_cost` is PyPSA's other column: already
  periodised, left alone. Entering an annual cost in `overnight_cost` would annuitise it twice.
- **Retirement** is an input: extending `coal_old` to 60 years raises 2040 emissions and lowers the unconstrained cost, and
  changes nothing under a binding cap.
- **Perfect foresight.** A cap that applies only in 2050 changes what is built in 2040. There is no myopic mode.
- A cap's shadow price is a dual of the *discounted* objective per period-tonne; in the period's own money per annual
  tonne it is `mu × years / objective weight`.

### Module 17 — batteries in depth

A solar-heavy single bus over three summer days (the middle one overcast): 700 MW of solar, a 300 MW CCGT at 80, a
200 MW peaker at 140, 393 MW evening peak. Module 4 is not repeated; this module covers:

- **Duration and power** — each extra hour of energy is worth less than the last (39 900, 39 119, then 23 079 and 13 432 an
  hour) and eight hours equals sixteen; power matters only until the peak is shaved.
- **Efficiency** — the round trip is the product of the two legs; typing a round-trip figure into both legs double-counts.
- **Standing loss** — a per-hour fraction of the stock (`standing_loss` 0.01 is 21.4 % a day).
- **State-of-charge edges** — non-cyclic with initial energy is free energy; short cyclic windows forbid carrying energy;
  rolling horizon carries a soft **terminal state of charge** on its last window (default on, `rollingConfig.terminalSoc`
  and `terminalSocPenalty` in the API/MCP, no Settings switch).
- **What a battery earns** — **Market & Policy > ESS business case** is a price-taker sweep on the base run's prices
  (equivalent full cycles, throughput, average charge and discharge price, spread, NPV/IRR); inside the model the same
  battery earns less at the prices it makes and saves the system something in between. Storage energy-balance duals are in
  the run's output series `storage_units-mu_energy_balance`.
- **Capacity value** — the 100 MW battery's ELCC (**Settings > Solve > ELCC**) rises with duration: 20.0 / 20.0 / 24.2 /
  45.6 / 93.0 % at 1 / 2 / 4 / 6 / 8 hours.
- **Sizing** — an extendable StorageUnit fixes energy = `p_nom` × `max_hours`; a Store with two Links sizes charging power,
  discharging power and energy separately. Changing `max_hours` without changing the cost (`overnight_cost`) changes the price of energy.

Both modules use a short window or representative days; the lessons state where a per-year figure is a three-day (or
one-day-per-year) sample scaled up.

### Adding a module (authors)

One file per module under `frontend/Ragnarok_default/src/lib/training/course/`, one entry in `COURSE_MODULES` in
`course/index.ts` (catalog card and steps together; order is teaching order and the `N · ` prefix of the section must match),
the module's example(s) in `make_examples.py`, and `test_module_N_*` tests that solve each stated number.
`catalog.test.ts` checks the section join, the numbering, and that every example id a module names exists.
