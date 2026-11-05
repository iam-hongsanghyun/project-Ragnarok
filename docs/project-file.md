# Project file format (SQLite)

A Ragnarok project is one SQLite file, `project.db`: the model, and every app
setting. Opening it restores the app exactly as it was saved. Each solved run is
a second file, `<run>.db`. This document is the format, and the guide for
building a project file from another tool or MCP server (§7). How the stores
behave at run time is in [backend.md](./backend.md) §11–12.

| File | Where | Role |
|---|---|---|
| `project.db` | `backend/data/session/<session_id>/project.db` | The working project (input). One per session. |
| `<run>.db` | `backend/data/runs/<run>.db` | One solved run: the input model and settings as solved, plus the results (output). |
| `project.db` | `backend/data/examples/<id>/project.db` | A bundled starter project, same format. |

`backend/data` moves to `RAGNAROK_DATA_DIR` when that variable is set.

## 1. What a project holds

| In the project | Not in the project |
|---|---|
| Every PyPSA component and time series | API keys (`ragnarok:secret:*`): never leave the browser |
| Ragnarok and module input sheets (`RAGNAROK_*`) | Caches and build markers (`ragnarok:config:*`, `ragnarok:build-id`) |
| **Every app setting** (`_app_state`, §5): Settings incl. enabled modules, each module's options, plugin settings, the live run controls, view state | Installed plugin packages (`ragnarok:fe-plugins:installed`): per machine |
| | Training and tour progress (`ragnarok:training:*`, `ragnarok:tour:*`): per learner, or opening a tutorial's project would roll it back |
| | Solved results: the run `.db` (§6) |
| | The edit history: `backend/data/journal/<session>/journal.jsonl` |

## 2. Layout (format version 2)

```sql
CREATE TABLE _project   (k TEXT PRIMARY KEY, v TEXT NOT NULL);       -- project facts, v is JSON
CREATE TABLE _sheets    (position INTEGER NOT NULL, name TEXT PRIMARY KEY, tbl TEXT NOT NULL UNIQUE,
                         section TEXT NOT NULL, kind TEXT NOT NULL,
                         row_count INTEGER NOT NULL, columns TEXT NOT NULL);  -- the sheet catalog
CREATE TABLE _app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- every app setting, verbatim
CREATE TABLE pypsa_0    (__row INTEGER PRIMARY KEY AUTOINCREMENT, d TEXT);  -- one table per sheet,
CREATE TABLE config_0   (...);                                              -- d is one row as JSON
```

**`_sheets`**: one row per sheet, in workbook order (`position`). `tbl` is the
table holding its rows. A table not listed here is ignored.

| `section` | Sheets | Table prefix |
|---|---|---|
| `pypsa` | `snapshots`, `network`, PyPSA component lists, `<component>-<attr>` series, `<component>-<attr>-pw` | `pypsa_<i>` |
| `ragnarok` | `RAGNAROK_*` app and module sheets | `config_<i>` |
| `other` | anything else (kept, never used by the solve) | `other_<i>` |

`kind` is `series` (one row per snapshot) or `static`. `columns` is a JSON list.

Rows are JSON, not columns, because a series sheet has one column per asset:
SQLite caps a table at 2000 columns, and asset names would need quoting.

**`_project` keys** (JSON values): `format_version` (2), `filename`,
`scenarioName`, `savedAt`, `snapshotCount`, `snapshotStart`, `snapshotEnd`,
`scenarioYear`, `componentCounts`; `cost_basis_migration` (only after an old
model was migrated on load); `example` (`{label, description, order}`, bundled
examples only).

**Older files.** A version-1 file (one `_kv` table and `sheet_<i>` tables) is
reorganised in place on first read: tables move into their sections, an empty
sheet that is neither PyPSA nor Ragnarok is dropped, and the retired `controls`
value goes (run controls are in the app state now).

## 3. Sheets

Sheet names and columns follow PyPSA: a sheet is a component list, and a column
is a PyPSA attribute in PyPSA's units (MW, MWh, currency/MWh, t/MWh).

| Name | Kind | Row shape |
|---|---|---|
| `snapshots` | static (the time axis) | `{"snapshot": "2030-01-01 00:00"}`, one row per time step, in order |
| `network` | static | `{"name": …}` and network-level attributes |
| `<list>` (`buses`, `carriers`, `generators`, `loads`, `lines`, `links`, `transformers`, `stores`, `storage_units`, …) | static | One row per component: `{"name": "gas", "bus": "zone", "p_nom": 100, …}` |
| `<list>-<attr>` (`generators-p_max_pu`, `loads-p_set`, …) | series | One row per snapshot: `{"snapshot": …, "<component name>": value, …}` |
| `<list>-<attr>-pw` | static | Piecewise curve breakpoints ([backend.md](./backend.md) §5.7) |
| `RAGNAROK_FuelPrices`, `RAGNAROK_CarrierOutputCap` | series | One row per snapshot |
| any other `RAGNAROK_*` | static | Module or app configuration (below) |

A column that only some rows carry is still a column. A missing attribute takes
PyPSA's default.

| Sheet | Holds |
|---|---|
| `RAGNAROK_Schema` | `{"ragnarok_schema_version": 4}`. **Without it, Ragnarok treats the model as an old file and rewrites its cost columns on first open.** The builders in §7 add it. |
| `RAGNAROK_Scenarios` | One row per saved scenario: `id`, `label`, `active`, `notes`, `json` (its run options) |
| `RAGNAROK_Pathway`, `RAGNAROK_PathwayPeriods`, `RAGNAROK_Rolling` | Multi-period and rolling-horizon set-up |
| `RAGNAROK_CustomDSL` | Custom constraints |
| `RAGNAROK_CarbonSchedules` | Carbon price schedules |
| `RAGNAROK_PLANTS`, `RAGNAROK_StartCosts`, `RAGNAROK_P2X` | Plant registry, start costs, power-to-X chains |
| `RAGNAROK_Composites`, `RAGNAROK_CompositeTemplates` | Composite assets |
| `RAGNAROK_FuelPrices`, `RAGNAROK_FuelPriceScenarios`, `RAGNAROK_VariableOM` | Fuel prices and VOM → marginal cost at run time |
| `RAGNAROK_CarrierOutputCap` | Per-snapshot output cap by carrier |
| `RAGNAROK_AnnualBudgets` | Annual budgets |
| `RAGNAROK_TimeUnits` | Time units of time-based columns |
| `RAGNAROK_PeriodBudgets` | Energy or CO2 limits over a month, a year or any range (§8) |
| `RAGNAROK_RunSettings` | How the run is solved, as `setting` / `value` rows (§8). Read on open and folded into `_app_state`; never stored as a sheet |

The column contract of each module sheet lives with its module: see
[module.md](./module.md), or the MCP tools (`describe_run_options`,
`get_fuel_inputs`, …).

## 4. Where the settings come from

The browser keeps every setting as a `localStorage` key → string. Every write
to a project key is stored into `_app_state` (debounced), so the project always
holds the screen's current settings. When a project is opened, its set becomes
the browser's exactly and the page reloads once so every view reads it. A
project that carries no settings (a plain PyPSA workbook, an importer's model)
takes the current ones. Code: `frontend/…/src/lib/appState/appState.ts`.

## 5. `_app_state`

`key` and `value` are the browser's strings, verbatim; most values are JSON.

| Key | Holds |
|---|---|
| `project_ragnarok_settings` | Settings: solver, currency, discount rate, load shedding, `enabledModules`, … |
| `ragnarok:session:controls` | Live run controls: window, carbon price and schedule, constraints, pathway, rolling, sampling, and the full live scenario |
| `ragnarok:fe-plugins:configs`, `ui:be-plugin-cfg:<plugin>`, `ui:be-plugin-runs:<plugin>` | Plugin settings |
| `ragnarok:p2x:rfnbo` | RFNBO matching settings (P2X) |
| `ragnarok:data-import:*`, `ragnarok:pypsa-earth:*`, `ragnarok.screening.*`, `ui:screening:*`, `ui:siting:*`, `ui:forge:*`, `ui:forge-*`, `ui:procurement:*`, `ui:carbon:*`, `ui:composites:*`, `ui:physical-risk:*`, `ui:snapshot-builder:*`, `ui:pypsa-earth:*`, `ui:network-analysis:*`, `ui:input-analyser:*`, `ui:tables:*` | Each module's and tool's inputs |
| `ragnarok:dashboard:*`, `ui:card:*`, `ui:comparison:*`, `ui:reporting:*`, `ui:history:*`, `ui:scenario-diff:*` | Analytics layouts, chart choices, compared runs, reports |
| `ui:app:*` (`tab`, `active-run-name`, `chart-sections`, `dry-run`), other `ui:*`, `pypsa.*` | Where the screen was: open tab, shown run, panel sizes, column widths, hidden columns, map layers |

Not carried (by design): API keys (`ragnarok:secret:*`) - a security boundary; caches and build markers; installed plugin
packages and their uploaded files (per machine: a config keeps the file name, the user re-picks the file); training and
tour progress (per learner). Data the server keeps per installation - uploaded Screening datasets, physical-risk
portfolios, the PyPSA-Earth folder, the run History - stays on that machine; the project keeps the reference (its id).

Outside `project.db` the same pairs travel as a `RAGNAROK_AppState` sheet
(`key`, `part`, `value`; a value longer than one Excel cell is split across
`part` 0, 1, …): in an exported workbook or package, in a run's model snapshot,
and in any model sent to the server. The server takes that sheet out and stores
it in `_app_state`, so it is never a model sheet.

## 6. Run `.db` (output)

Each solve writes `backend/data/runs/<label>_<UTC timestamp>.db`:

| Part | Holds |
|---|---|
| `_kv.meta` | The History entry: `savedAt`, `label`, `filename`, `origin`, `snapshotStart`, `snapshotEnd`, … |
| `_kv.head` | The run's `scenario` and `options` |
| `_kv.result_light` | The result without its series: `summary`, `carrierMix`, `costBreakdown`, `expansionResults`, `meritOrder`, `statistics`, study payloads, …, and `outputs.static` (`{list: {component: {attr: value}}}`) |
| `_kv.analytics` | The small bundle the Analytics view opens first |
| `_kv.model_tables` → `m_<i>` | The input model exactly as solved, including `RAGNAROK_AppState`: the settings it was solved with |
| `_kv.series_tables` → `o_<i>` | Each output series `<list>-<attr>` (`generators-p`, `buses-marginal_price`, …), one row per snapshot |

```sql
SELECT json_extract(d, '$.snapshot'), json_extract(d, '$.gas')
FROM o_0 ORDER BY __row;   -- o_0 from _kv.series_tables["generators-p"]
```

## 7. Building a project file (VOID, scripts, other MCP servers)

Assemble the model as `{sheet: rows}` (§3), optionally with settings
`{key: value}` (§5; copy the keys from a project set up in the GUI with
`get_app_state`), then let Ragnarok's own writer produce the file: it stamps
`RAGNAROK_Schema`, fills the catalog and sections, and stores the settings.

**From an MCP client** (Ragnarok's MCP server):

| Step | Tool |
|---|---|
| Read this format | `describe_project_file` |
| Write a `.db` from a model, without touching the working project | `build_project_file(model, dest, app_state)` |
| Open a `.db` as the working project | `import_project(path)` |
| Save the working project as a `.db` | `export_project_file(dest)` |
| Start from a runnable example | `get_project_template(dest, format)` (§9) |
| Read or change how it runs | `get_run_settings`, `set_run_settings` (§8) |
| Read or change any other setting | `get_app_state`, `set_app_state` (every key of §5) |
| Run it with its own settings | `submit_solve` with no options |

**Over HTTP:**

| Endpoint | Does |
|---|---|
| `POST /api/project-file/build` `{model, appState?, filename?, scenarioName?, example?}` | Returns the built `.db` |
| `POST /api/project-file?session_id=…` (multipart `file`) | Opens a `.db` as the session's project |
| `GET /api/project-file?session_id=…` | Downloads the session's project |
| `GET` / `PUT /api/session/app-state` | Reads / writes the settings |
| `GET /api/project-file/guide` | This document |
| `GET /api/project-file/template?format=xlsx\|db` | The template (§9) |
| `GET` / `PUT /api/session/run-settings` | Reads / writes the run settings (§8) |

**In Python** (from the repo root, `.venv-pypsa/bin/python`):

```python
from pathlib import Path
from backend.app import sqlite_store

snaps = [f"2030-01-01 {h:02d}:00" for h in range(24)]
model = {
    "snapshots": [{"snapshot": s} for s in snaps],
    "buses": [{"name": "zone", "v_nom": 380, "carrier": "AC"}],
    "carriers": [{"name": "AC"}, {"name": "gas", "co2_emissions": 0.2}, {"name": "solar"}],
    "generators": [
        {"name": "gas", "bus": "zone", "carrier": "gas", "p_nom": 100, "marginal_cost": 60},
        {"name": "solar", "bus": "zone", "carrier": "solar", "p_nom": 80},
    ],
    "generators-p_max_pu": [{"snapshot": s, "solar": max(0.0, 1 - abs(h - 12) / 6)} for h, s in enumerate(snaps)],
    "loads": [{"name": "demand", "bus": "zone"}],
    "loads-p_set": [{"snapshot": s, "demand": 70} for s in snaps],
}
sqlite_store.build_file(
    model, Path("my_model.db"),
    app_state={"project_ragnarok_settings": '{"currencyCode": "KRW", "currencySymbol": "₩"}'},
    filename="my_model",
)
```

**Opening it in the app:** Model → **Import Project** takes the `.db`; **Save
Project File** writes one. A folder `backend/data/examples/<id>/` holding a
`project.db` with an `example` key in `_project` appears in the examples list.

## 8. Run settings and period limits

**`RAGNAROK_RunSettings`**: one row per setting (`setting`, `value`; `unit` and `description` are for people and
ignored on read). A blank value keeps the app default. Opening a file applies the sheet on top of the project's
settings; an exported workbook writes it back, so an edited workbook round-trips. The same table is
`GET`/`PUT /api/session/run-settings` and the MCP tools `get_run_settings` / `set_run_settings`.

| Setting | Unit | Meaning |
|---|---|---|
| `windowStart`, `windowEnd` | snapshot label | The snapshots the run solves (inclusive); blank = all |
| `carbonPrice` | currency/tCO2 | Carbon price |
| `discountRate` | fraction | Annualises overnight cost |
| `loadShedding`, `loadSheddingCost` | true/false, currency/MWh | Unserved load and its value |
| `forceLp`, `dryRun` | true/false | LP relaxation of unit commitment; build and check without solving |
| `rolling`, `rollingWindowHours`, `rollingOverlapHours`, `rollingTerminalSoc` | true/false, h, h, true/false | Rolling horizon |
| `solverType`, `solverThreads`, `solveAcceptance`, `objectiveAutoScale` | auto/simplex/ipm/pdlp/hipo, threads, lenient/strict, true/false | Solver |
| `currencyCode`, `currencySymbol`, `enabledModules`, `dateFormat` | text | Currency, module tabs shown, how dates are read |

The time resolution is the model's: the `snapshots` sheet's `objective` / `generators` / `stores` columns give the
hours each snapshot stands for (6 for 6-hourly); rolling hours are converted with it.

A run submitted without options (an agent's `submit_solve`, a script) takes the project's own settings key by key;
what the submitter states wins.

**`RAGNAROK_PeriodBudgets`**: one row per limit.

| Column | Meaning |
|---|---|
| `name` | Label (optional) |
| `measure` | `energy` (MWh of generator output, default) or `emissions` (tCO2: carrier `co2_emissions` / efficiency) |
| `carrier` / `generator` | Carrier(s) or generator name(s), comma separated; blank `carrier` = every generator (emissions only) |
| `period` | `YYYY-MM` (a month) or `YYYY` (a year); or leave blank and use `start` (inclusive) / `end` (exclusive) |
| `sense` | `<=` (default), `>=`, `==` |
| `value` | The period total |

A single solve keeps each limit exactly. A rolling run gives each window what is left of the limit for the period
hours it sees, so the run never overspends and monthly windows reproduce the single solve. Under rolling the
model's own whole-run limits (a CO2 `GlobalConstraint`, a carrier `operational_limit`, a generator's
`e_sum_max` / `e_sum_min`) are tracked the same way instead of being applied in full to every window
([backend.md](./backend.md), *Period budgets*).

## 9. The template

`GET /api/project-file/template?format=xlsx` (Model → More formats… → **Project template**, or MCP
`get_project_template`) is a small model that runs as it is: two regions, 6-hourly over January-February 2030,
gas, solar and a hydro plant with monthly limits, solved in monthly rolling windows. It has every sheet a person
fills in - the model sheets, `RAGNAROK_RunSettings`, `RAGNAROK_PeriodBudgets` - and a `README` sheet. Replace the
data and settings, then **Import Project** and **Run**: the run uses exactly what the file states. `format=db` gives
the same project as a project file.
