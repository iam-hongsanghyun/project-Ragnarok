# Project file format (SQLite)

Ragnarok keeps a model in one SQLite file, `project.db`, and every solved run in
another, `<run>.db`. This document is the format: what a `project.db` must hold
for Ragnarok to open it as **input**, and what a run `.db` holds as **output**.
How the stores behave at run time (connections, migration, endpoints) is in
[backend.md](./backend.md) §11–12.

| File | Where | Role |
|---|---|---|
| `project.db` | `backend/data/session/<session_id>/project.db` | The working model (input). One per session. |
| `<run>.db` | `backend/data/runs/<run>.db` | One solved run: the input model as it was solved, plus the results (output). |
| `project.db` | `backend/data/examples/<id>/project.db` | A bundled starter project: the same format as a session `project.db`. |

`backend/data` moves to `RAGNAROK_DATA_DIR` when that variable is set.

## 1. What a `project.db` holds, and what it does not

| In `project.db` | Not in `project.db` |
|---|---|
| Every component sheet (`buses`, `generators`, …) and every time series (`generators-p_max_pu`, …) | App settings, including **which modules are enabled** (`enabledModules`): browser `localStorage` |
| Module input sheets (`RAGNAROK_FuelPrices`, `RAGNAROK_CarrierOutputCap`, `RAGNAROK_PLANTS`, …) | Frontend plugin configs: browser `localStorage` |
| Run options per scenario: solve window, carbon price, pathway, rolling, stochastic, reserves, … (`RAGNAROK_Scenarios`) | Solved results: the run `.db` (§4) |
| Custom constraints, carbon schedules, composites (`RAGNAROK_CustomDSL`, `RAGNAROK_CarbonSchedules`, `RAGNAROK_Composites`, …) | The edit history: `backend/data/journal/<session>/journal.jsonl` |
| The cost-basis schema version (`RAGNAROK_Schema`) | |

To move a whole project, settings and results included, to another machine, use
**Export Project**. It writes an `.xlsx` (or a `.zip` package) that adds
`RAGNAROK_Settings`, `RAGNAROK_PluginConfigs`, `RAGNAROK_ResultMeta`,
`RAGNAROK_Constraints`, `RAGNAROK_RunState` and the output sheets to the model sheets ([user-manual.md](./user-manual.md),
Import / Export).

## 2. Layout

Every sheet is one table, and every row is one JSON object:

```sql
CREATE TABLE _kv      (k TEXT PRIMARY KEY, v TEXT);                    -- v is JSON
CREATE TABLE sheet_0  (__row INTEGER PRIMARY KEY AUTOINCREMENT, d TEXT); -- d is one row as JSON
CREATE TABLE sheet_1  (...);                                           -- one table per sheet
```

Rows are stored as JSON, not as columns, because a series sheet has one column
per asset: SQLite caps a table at 2000 columns, and asset names would need
quoting. Row order is `__row`.

`_kv` keys:

| Key | Value |
|---|---|
| `tables` | `{"<sheet name>": "sheet_<i>", …}`: the only link from a sheet name to its table. A table not listed here is ignored. |
| `meta` | Summary the GUI shows: `filename`, `scenarioName`, `savedAt`, `sheets` (`[{name, kind: "static"\|"series", rowCount, columns}]`), `snapshotCount`, `snapshotStart`, `snapshotEnd`, `scenarioYear`, `componentCounts`. |
| `cost_basis_migration` | Written only when an old model was migrated on load (the banner the user acknowledges). |
| `example` | Bundled examples only: `{label, description, order}` for the example picker. |

## 3. Sheets (input)

Sheet names and columns follow PyPSA: a sheet is a component list, and a column
is a PyPSA attribute in PyPSA's units (MW, MWh, currency/MWh, t/MWh).

**Kind is decided by the name:**

| Name | Kind | Row shape |
|---|---|---|
| `snapshots` | static (the time axis) | `{"snapshot": "2030-01-01 00:00"}`, one row per time step, in order. `scenarioYear` is read from its first 4 characters. |
| `network` | static | `{"name": …}` and network-level attributes |
| `<list>` (`buses`, `carriers`, `generators`, `loads`, `lines`, `links`, `transformers`, `stores`, `storage_units`, …) | static | One row per component: `{"name": "gas", "bus": "zone", "p_nom": 100, …}` |
| `<list>-<attr>` (`generators-p_max_pu`, `loads-p_set`, …) | series | One row per snapshot: `{"snapshot": "2030-01-01 00:00", "<component name>": value, …}` |
| `<list>-<attr>-pw` | static | Piecewise curve breakpoints, one row per breakpoint ([backend.md](./backend.md) §5.7) |
| `RAGNAROK_FuelPrices`, `RAGNAROK_CarrierOutputCap` | series | One row per snapshot, as above |
| any other `RAGNAROK_*` | static | Module or app configuration (below) |

A column that only some rows carry is still a column. A missing attribute takes
PyPSA's default.

**Ragnarok sheets a model may carry:**

| Sheet | Holds | Written by |
|---|---|---|
| `RAGNAROK_Schema` | `{"ragnarok_schema_version": 4}` | Always present. **Without it, Ragnarok treats the model as an old file and rewrites its cost columns on first open.** |
| `RAGNAROK_Scenarios` | One row per scenario: `id`, `label`, `active`, `notes`, `json` (the run options as a JSON string: `snapshotStart`, `snapshotEnd`, `snapshotWeight`, `carbonPrice`, `discountRate`, `pathwayConfig`, `rollingConfig`, `stochasticConfig`, `reserveConfig`, `constraints`, …) | Run options panel |
| `RAGNAROK_Pathway`, `RAGNAROK_PathwayPeriods`, `RAGNAROK_Rolling` | Multi-period and rolling-horizon set-up | Run options panel |
| `RAGNAROK_CustomDSL` | Custom constraints | Constraints panel |
| `RAGNAROK_CarbonSchedules` | Carbon price schedules | Carbon panel |
| `RAGNAROK_PLANTS`, `RAGNAROK_StartCosts`, `RAGNAROK_P2X` | Plant registry, start costs, power-to-X chains | Build, P2X |
| `RAGNAROK_Composites`, `RAGNAROK_CompositeTemplates` | Composite assets | Build |
| `RAGNAROK_FuelPrices`, `RAGNAROK_FuelPriceScenarios`, `RAGNAROK_VariableOM` | Fuel prices and VOM → marginal cost at run time | Fuel costs module |
| `RAGNAROK_CarrierOutputCap` | Per-snapshot output cap by carrier | Constraints module |
| `RAGNAROK_AnnualBudgets` | Annual budgets | Annual budgets module |
| `RAGNAROK_TimeUnits` | Time units of time-based columns | Cost-basis migration |

The column contract of each module sheet lives with its module: see
[module.md](./module.md), or ask the MCP server (`describe_run_options`,
`get_fuel_inputs`, …).

## 4. Run `.db` (output)

Each solve writes `backend/data/runs/<label>_<UTC timestamp>.db`:

| Part | Holds |
|---|---|
| `_kv.meta` | The History entry: `savedAt`, `label`, `filename`, `origin`, `snapshotStart`, `snapshotEnd`, `snapshotWeight`, … |
| `_kv.head` | The run's `scenario` and `options` |
| `_kv.result_light` | The result without its series: `summary`, `carrierMix`, `costBreakdown`, `expansionResults`, `meritOrder`, `statistics`, study payloads, …, and `outputs.static` (`{list: {component: {attr: value}}}`: `p_nom_opt`, `mu_*`, …). `outputs.seriesSheets` names the output series. |
| `_kv.analytics` | The small bundle the Analytics view opens first |
| `_kv.model_tables` → `m_<i>` | The input model exactly as solved, sheet by sheet (same row shape as §3) |
| `_kv.series_tables` → `o_<i>` | Each output series `<list>-<attr>` (`generators-p`, `buses-marginal_price`, `storage_units-state_of_charge`, …), one row per snapshot: `{"snapshot": …, "<component>": value}` |

Read it with `json_extract`, for example the dispatch of one generator:

```sql
SELECT json_extract(d, '$.snapshot'), json_extract(d, '$.gas')
FROM o_0 ORDER BY __row;   -- o_0 from _kv.series_tables["generators-p"]
```

## 5. Building a `project.db` to use as input

Build it with Ragnarok's own writer, so `tables` and `meta` come out right, and
stamp the schema version first:

```python
# run from the repo root with .venv-pypsa/bin/python
from pathlib import Path
from backend.app import sqlite_store
from backend.pypsa.network import cost_basis

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
out = Path("backend/data/examples/my_model/project.db")
out.parent.mkdir(parents=True, exist_ok=True)
sqlite_store._build_db("my_model", cost_basis.stamp(model), filename="my_model", db_path=out)
sqlite_store.write_kv(out, "example", {"label": "My model", "description": "Built by script", "order": 99})
```

**How to open it.** The app does not accept a `.db` upload today: Import Project
takes `.xlsx` or `.zip`. Two routes work:

1. **As an example** (above): a folder under `backend/data/examples/<id>/` with a
   `project.db` appears in the examples list, and loading it copies the file
   into the session.
2. **As a project file**: build the same `model` dict and import it as an
   `.xlsx`/`.zip` through Import Project (MCP: `import_project_file`), or send
   the dict straight to the session with the MCP `save_model` tool.

A model written by hand without the writer must still satisfy §2: every sheet
listed in `_kv.tables`, and a `meta` whose `sheets` match the tables.
