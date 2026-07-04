# Ragnarok

Ragnarok is a local React + FastAPI application built on [PyPSA](https://pypsa.org) for:

- editing a PyPSA-style workbook
- running a PyPSA optimization with HiGHS
- reviewing results in a map, table, and analytics UI
- exporting either:
  - an input workbook (Save / Save As)
  - a full project workbook with solved PyPSA outputs (Export Project)
  - a full results workbook (Export Result)
  - PyPSA-native formats: CSV folder, netCDF, HDF5

The current schema is generated from PyPSA GitHub metadata and checked into the repo at [src/config/pypsa_schema.json](/Users/sanghyun/github/pypsa_gui/frontend/Ragnarok_default/src/config/pypsa_schema.json). The authoritative PyPSA references for this README are:

- [PyPSA Components](https://docs.pypsa.org/latest/user-guide/components/)
- [PyPSA Import and Export](https://docs.pypsa.org/latest/user-guide/import-export/)
- [PyPSA Optimization Overview](https://docs.pypsa.org/v1.0.2/user-guide/optimization/overview/)
- [PyPSA Pathway Planning / Multi-Investment Optimization](https://docs.pypsa.org/latest/examples/multi-investment-optimisation/)
- [PyPSA Stochastic Optimization](https://docs.pypsa.org/latest/user-guide/optimization/stochastic/)

## Documentation

All documentation lives in [docs/](./docs/) (start at the [docs index](./docs/README.md)).

| Document | Read it for |
|---|---|
| [docs/user-manual.md](./docs/user-manual.md) | Using the app: install, launch, every view and feature, import/export, capabilities |
| [docs/architecture.md](./docs/architecture.md) | Tech stack, repo layout, topology, data flow, process logic, design |
| [docs/backend.md](./docs/backend.md) | Backend details: HTTP API, solve pipeline, network build, results, modes, constraints |
| [docs/frontend.md](./docs/frontend.md) | Frontend details: App state, views, features, plugin host, shared utils/types |
| [docs/plugin.md](./docs/plugin.md) | Building a plugin (frontend JS or backend Python): manifest, GUI schema, hooks, own server, examples |
| [docs/SUPPORT_MATRIX.md](./docs/SUPPORT_MATRIX.md) | Generated feature support matrix |
| [docs/TODO.md](./docs/TODO.md) | Living project task log and roadmap |

## Scope

Ragnarok is not a full UI wrapper around every PyPSA capability.

The app has four different support layers, and they are not identical:

- `Workbook I/O`: can the app open, edit, and save the sheet/attribute?
- `Backend Run`: does the backend actually apply it when building/running `pypsa.Network`?
- `Project Export/Import`: can it round-trip through `Export Project` and `Import Project`?
- `Analytics UI`: does Ragnarok expose dedicated result views for it?

Support levels used below:

- `Full`: implemented end-to-end in the relevant layer.
- `Partial`: implemented with important caveats.
- `Implicit`: preserved or consumed through generic schema/workbook plumbing, but without dedicated UI or richer handling.
- `Not supported`: no active implementation path today.

## Architecture

The repository is split into a pluggable **frontend** and a pluggable **backend** so either side can be swapped independently:

- `frontend/Ragnarok_default/` — the default React/TypeScript UI (its own npm package: `package.json`, `public/`, `src/`, `scripts/`). A second frontend would live as a sibling, e.g. `frontend/<name>/`.
- `backend/app/` — the engine-agnostic FastAPI host (run lifecycle, request/response models, config, module host, and the `Backend` protocol + registry).
- `backend/pypsa/` — the reference optimisation engine (PyPSA network builder, solve, result extraction). A second backend would live as a sibling, e.g. `backend/<engine>/`.

Frontend (paths below are relative to `frontend/Ragnarok_default/`):

- [src/App.tsx](/Users/sanghyun/github/pypsa_gui/frontend/Ragnarok_default/src/App.tsx): app shell, run flow, workbook open/save/import/export, run history
- [src/constants/pypsa_schema.ts](/Users/sanghyun/github/pypsa_gui/frontend/Ragnarok_default/src/constants/pypsa_schema.ts): generated PyPSA schema adapter for the frontend
- [src/shared/utils/workbook.ts](/Users/sanghyun/github/pypsa_gui/frontend/Ragnarok_default/src/shared/utils/workbook.ts): workbook parse/save/project round-trip
- [src/shared/utils/deriveRunResults.ts](/Users/sanghyun/github/pypsa_gui/frontend/Ragnarok_default/src/shared/utils/deriveRunResults.ts): rebuilds `RunResults` from imported workbook outputs
- [src/shared/utils/helpers.ts](/Users/sanghyun/github/pypsa_gui/frontend/Ragnarok_default/src/shared/utils/helpers.ts): `normalizeDateToIso` (input date parser), `isoDate`/`isoTime` (canonical display helpers), `formatTimestamp`

### Date handling

The **Date format** setting (`auto` / `dmy` / `mdy` / `ymd`) declares only the format of the **input** data — it tells the parser how to interpret ambiguous date strings from user workbooks (e.g. `01-08-2024` → August 1st in `dmy`, January 8th in `mdy`). It does **not** control how dates are displayed anywhere in the UI.

The single canonical target format used for display, storage, and backend communication is **ISO 8601: `YYYY-MM-DD`** (with `HH:MM` or `THH:MM:SS` when time is present). Normalization happens at the import boundary via `normalizeInputDatesToIso` in `workbook.ts`, which is called at all three open/import entry points in `App.tsx`. The backend therefore always receives ISO date strings and parses them without any locale or `dayfirst` override.

Time-series chart x-axis labels adapt to the visible span: `HH:MM` (≤ 24 h), `YYYY-MM-DD HH:MM` (1–7 days), `YYYY-MM-DD` (7–90 days), `YYYY-MM` (> 90 days). Tick density scales with the span as well.

Backend:

- [backend/app/main.py](/Users/sanghyun/github/pypsa_gui/backend/app/main.py): FastAPI app and run lifecycle
- [backend/app/backends/](/Users/sanghyun/github/pypsa_gui/backend/app/backends): pluggable backend seam — `Backend` protocol, registry, and the PyPSA reference adapter (run selected by `options.backend`)
- [backend/pypsa/network/__init__.py](/Users/sanghyun/github/pypsa_gui/backend/pypsa/network/__init__.py): schema-driven network builder
- [backend/pypsa/results/__init__.py](/Users/sanghyun/github/pypsa_gui/backend/pypsa/results/__init__.py): solve + analytics result assembly
- [backend/pypsa/results/full_outputs.py](/Users/sanghyun/github/pypsa_gui/backend/pypsa/results/full_outputs.py): schema-driven solved output extraction
- [backend/pypsa/pypsa_schema.py](/Users/sanghyun/github/pypsa_gui/backend/pypsa/pypsa_schema.py): backend schema helpers

## Current User Flows

`Open`

- opens a workbook into the in-memory model
- restores Ragnarok pathway, rolling, and scenario metadata when present
- does not restore prior results

`Save` / `Save As`

- save input-only workbook content
- strip output attributes from component sheets
- keep input time-series sheets only
- keep Ragnarok pathway, rolling, and scenario metadata sheets

`Export Project`

- writes input workbook sheets
- merges solved output columns/sheets from `results.outputs` if a run exists
- keeps Ragnarok pathway metadata sheets
- keeps Ragnarok rolling and scenario metadata sheets
- also writes Ragnarok result metadata sheets for:
  - `runMeta`
  - pathway summaries / selected period
  - solver narrative
  - `co2Shadow`
  - plugin analytics
- also writes dedicated project-state metadata sheets for:
  - settings (including date format, currency, solver config)
  - active constraints
  - run window / force-LP / active scenario
  - import provenance
- does **not** include per-entry run history (the current run is reconstructed from output sheets on import; prior history entries are not preserved)
- still does not include a backend-solved network artifact

`Import Project`

- parses workbook inputs; all date strings are normalized to ISO (YYYY-MM-DD) using the date format declared in the imported settings
- parses solved PyPSA output attributes/sheets
- restores Ragnarok pathway metadata
- restores Ragnarok rolling and scenario metadata
- rebuilds a frontend `RunResults` object from workbook outputs
- restores `pluginAnalytics`, `co2Shadow`, solver narrative, `runMeta`, and pathway metadata from Ragnarok metadata sheets
- restores settings (date format, currency, solver config), constraints, run window, and import provenance
- synthesizes a single `Import N` run-history entry for the imported run (prior history entries from before the export are not preserved)
- still does not restore a backend-solved network artifact

`Export Result`

- writes a result-oriented workbook with `OUT_*` sheets for reporting

`Export Report`

- writes a self-contained HTML report of the current result

## Support Matrix: Optimization Capabilities

This section is separate from workbook/component support because PyPSA’s
optimization envelope is broader than the workflow Ragnarok currently exposes.

| PyPSA optimization capability | Ragnarok status | Notes |
|---|---|---|
| Single-period optimization | `Full` | Main optimization mode today. |
| Economic dispatch with extendable assets | `Full` | Core solved workflow. |
| Capacity expansion planning, single investment period | `Full` | Extendable generators, storage units, stores, lines, and links are supported. |
| Storage operation with perfect foresight over the chosen horizon | `Full` | Supported within the currently modeled snapshot window. |
| Carbon pricing in the optimization objective | `Full` | Implemented as a marginal-cost adder. |
| Unit commitment / mixed-integer operation | `Partial` | Supported via generator attributes, but validation and analytics are still simpler than the full PyPSA capability set. |
| Force-LP dispatch mode | `Full` | Explicit Ragnarok run option. |
| Custom/global system-wide constraints | `Partial` | Useful subset implemented, but not the full optimization space. |
| Multi-carrier optimization | `Partial` | The backend can ingest multi-carrier workbook structures, but the UX and analytics remain electricity-centric. |
| Rolling-horizon optimization | `Partial` | Backend stitching and a dedicated frontend configuration surface are implemented; analytics remain stitched-result-first rather than window-first. |
| Multi-investment / pathway planning | `Partial` | Opt-in pathway mode is implemented with backend multi-investment expansion, pathway metadata, and period-aware analytics. Authoring remains flat/workbook-first rather than native PyPSA MultiIndex editing. |
| Stochastic optimization | `Partial` | Two-stage stochastic mode is implemented (probability-weighted scenarios expressing uncertainty via per-scenario overrides, e.g. load × 0.8, fuel × 2). No scenario trees or CVaR. Cannot combine with rolling horizon. |
| Security-constrained optimization / SCLOPF | `Partial` | SCLOPF mode with branch-outage contingencies is implemented. Cannot combine with rolling, stochastic, or pathway modes. |
| Scenario-based planning UX | `Partial` | Frontend scenario presets capture window, constraints, carbon price, pathway, rolling, stochastic, and SCLOPF settings in workbook metadata. Custom constraint DSL is saved with the model workbook, not per preset. |
| Multi-period result analytics | `Partial` | Period summaries and selected-period detailed charts are supported; not every analytics surface is natively multi-period. |

## Support Matrix: PyPSA Features vs Ragnarok

| PyPSA capability | Ragnarok status | Notes |
|---|---|---|
| Excel workbook import (`Network.import_from_excel` equivalent user workflow) | `Partial` | Ragnarok opens Excel workbooks, but it parses into its own in-memory model instead of delegating import to PyPSA directly. |
| Excel workbook export (`Network.export_to_excel` equivalent) | `Partial` | `Save` exports inputs only. `Export Project` exports input + solved outputs plus Ragnarok metadata sheets, but not the backend-solved network artifact itself. |
| Generic component schema sync from PyPSA GitHub | `Full` | Build-time generator populates [src/config/pypsa_schema.json](/Users/sanghyun/github/pypsa_gui/frontend/Ragnarok_default/src/config/pypsa_schema.json). |
| Generic input table editing for documented components/attributes | `Full` | Input tables are schema-driven rather than hardcoded. |
| Generic backend ingestion of documented input attributes | `Full` | Backend uses schema-derived input static/time-series attributes in [backend/pypsa/network/__init__.py](/Users/sanghyun/github/pypsa_gui/backend/pypsa/network/__init__.py). |
| Generic solved-output extraction for documented PyPSA outputs | `Full` | Backend extracts schema-marked outputs in [backend/pypsa/results/full_outputs.py](/Users/sanghyun/github/pypsa_gui/backend/pypsa/results/full_outputs.py). |
| Input-only save/load round-trip | `Full` | Known PyPSA input sheets round-trip through [src/shared/utils/workbook.ts](/Users/sanghyun/github/pypsa_gui/frontend/Ragnarok_default/src/shared/utils/workbook.ts). |
| Full project workbook round-trip | `Partial` | Solved outputs and Ragnarok metadata now round-trip settings (including date format), constraints, run window, provenance, scenarios, pathway, rolling, and plugin analytics. Prior run-history entries are not preserved (only the current run is reconstructed on import). Remaining gap is the backend-solved network artifact. |
| Restore analytics from imported solved workbook | `Full` | Frontend reconstructs analytics locally from `(model, outputs)` and restores plugin analytics / solve metadata from workbook metadata sheets. |
| Result workbook export for reporting | `Full` | `Export Result` keeps a dedicated reporting workbook. |
| HTML report export | `Full` | Implemented in [src/shared/utils/exportReport.ts](/Users/sanghyun/github/pypsa_gui/frontend/Ragnarok_default/src/shared/utils/exportReport.ts). |
| Structural validation before solve | `Partial` | Validation is now schema-aware across documented component sheets and time-series sheets, but it still stops short of full PyPSA semantic validation. |
| HiGHS optimization | `Full` | Uses `network.optimize()` with HiGHS. |
| Carbon price adder | `Full` | Applied to generator marginal costs from carrier emission factors. |
| Capacity expansion for extendable assets | `Full` | Annualized CAPEX applied for extendable generators, storage units, stores, lines, and links. |
| Unit commitment / MIP | `Partial` | Supported through PyPSA/HiGHS generator attributes, but analytics and validation are still more dispatch-focused than UC-focused. |
| Force-LP override | `Full` | Supported in backend run options. |
| Custom constraints panel | `Partial` | Several custom constraints are implemented, but not the full PyPSA constraint space. |
| Rolling-horizon optimization | `Partial` | Backend rolling-window orchestration and frontend controls are implemented; analytics remain stitched-result-first. |
| Multi-investment / pathway planning | `Partial` | Pathway mode is implemented through backend expansion from a flat workbook plus Ragnarok-owned pathway metadata sheets. |
| Stochastic optimization | `Partial` | Two-stage stochastic solve mode with probability-weighted scenario overrides; no scenario trees. |
| Security-constrained optimization | `Partial` | SCLOPF solve mode with branch-outage contingencies. |
| Native `global_constraints` workbook usage | `Implicit` | Sheet is available and passed through the generic network builder, but Ragnarok adds only limited dedicated UI/analytics around it. |
| Plugin system (frontend + backend) | `Full` | Two kinds, one hook contract (`transform`/`contribute`/`analyze`/`options`/named actions): frontend plugins run in the browser before a run is submitted; backend plugins run in the backend process via `/api/plugins/*` and write into the server-side session. The solve pipeline itself is plugin-agnostic — no staged in-solve plugin execution. |
| Plugin analytics round-trip through project import/export | `Full` | Stored in `RAGNAROK_PluginAnalytics` and restored on import without plugin re-execution. |
| Project settings / constraints / run-state metadata round-trip | `Full` | Stored in dedicated Ragnarok metadata sheets and restored on project import. |
| CO2 shadow price restoration from imported project | `Full` | Stored in `RAGNAROK_ResultMeta` and restored on import. |
| Backend retention of solved runs | `Full` | Every successful solve is persisted server-side automatically (`run_store.py`, one SQLite file per run) and served back through History/"View result" without re-solving. The solved `pypsa.Network` object itself is not retained — results and full outputs are. |
| CSV-folder / netCDF / HDF5 workflows | `Full` | CSV folder import/export (PyPSA-native layout, zipped, frontend-side); netCDF and HDF5 import/export via backend converters (`/api/export/netcdf`, `/api/import/hdf5`, …). |
| Power flow-only studies / separate PF UX | `Not supported` | Current workflow is optimization-centric. Roadmapped — see Roadmap below. |
| Pluggable / non-PyPSA optimization backend | `Partial` | A backend abstraction layer is in place (`backend/app/backends/`): one `run(model, scenario, options)` adapter per backend, selected by `options.backend` (default `pypsa`), with `GET /api/backends` reporting capabilities. PyPSA is the only adapter today; the seam is ready for additional backends. |

## Support Matrix: PyPSA Components

| Component / sheet | Workbook I/O | Backend Run | Project Export / Import | Analytics UI | Notes |
|---|---|---|---|---|---|
| `network` | `Partial` | `Full` | `Partial` | `Not supported` | `name`, `srid`, `crs`, and `now` are applied explicitly by the backend; other fields remain limited. |
| `snapshots` | `Full` | `Full` | `Full` | `Partial` | Used to build the run horizon; no dedicated snapshots analytics surface. |
| `buses` | `Full` | `Full` | `Full` | `Full` | Dedicated map and analytics support. |
| `carriers` | `Full` | `Full` | `Full` | `Partial` | Used for colors, emissions, and aggregation; no dedicated carrier detail panel. |
| `generators` | `Full` | `Full` | `Full` | `Full` | Best-supported component class end-to-end. |
| `loads` | `Full` | `Full` | `Full` | `Partial` | Load drives system analytics, but there is no dedicated load drill-down UI. |
| `links` | `Full` | `Full` | `Full` | `Full` | Visualized as branches in analytics. |
| `lines` | `Full` | `Full` | `Full` | `Full` | Visualized as branches in analytics. |
| `transformers` | `Full` | `Full` | `Full` | `Full` | Visualized as branches in analytics. |
| `storage_units` | `Full` | `Full` | `Full` | `Full` | Dedicated detail and SoC analytics. |
| `stores` | `Full` | `Full` | `Full` | `Full` | Dedicated detail analytics. |
| `processes` | `Full` | `Full` | `Full` | `Not supported` | Generic workbook/backend support exists, but no dedicated result UX. |
| `shunt_impedances` | `Full` | `Full` | `Full` | `Not supported` | Generic workbook/backend support only. |
| `global_constraints` | `Full` | `Implicit` | `Full` | `Partial` | Workbook/backend support exists; result UX is limited. |
| `line_types` | `Full` | `Implicit` | `Full` | `Not supported` | Preserved and passed through, but no dedicated UX. |
| `transformer_types` | `Full` | `Implicit` | `Full` | `Not supported` | Preserved and passed through, but no dedicated UX. |
| `shapes` | `Partial` | `Implicit` | `Partial` | `Not supported` | Accepted by the backend through the generic schema-driven path, but no dedicated UX or result handling exists. |
| `sub_networks` | `Implicit` | `Implicit` | `Implicit` | `Not supported` | Accepted/preserved through the generic schema-driven path without dedicated UX. |

### Backend Import Contract

- `network`: explicit runtime import
- `snapshots`: explicit runtime special case for snapshot index construction
- all other schema-defined sheets: generic schema-driven import

Ragnarok does not maintain a separate backend skip policy for schema-defined sheets beyond those two special cases.

## Important Current Limitations

1. `Export Project` is workbook-driven, not backend-solved-network-driven.
   The app exports `results.outputs`, not a retained solved `pypsa.Network`. The backend persists every solved run's *results* in the run store (History), but never the solved `pypsa.Network` object itself — by design (see Roadmap / TODO "Not Needed"). The frontend round-trips losslessly, and a native `pypsa.Network` can be reconstructed from the exported workbook or CSV folder.

2. `Import Project` rebuilds project state from workbook inputs/outputs rather than reopening a retained `pypsa.Network`.
   It restores frontend project state and result metadata and reconstructs `RunResults` locally. No backend-solved network artifact is involved, by design.

3. Pathway planning is still v1-level.
   It supports flat-workbook authoring, backend multi-investment expansion, and selected-period analytics, but it does not yet provide a native frontend MultiIndex editing workflow.

4. Validation is broader, but still not full PyPSA semantic validation.
   The validator is now schema-aware across documented sheets, but it still focuses on structural/runtime-invalid data rather than reproducing every PyPSA modeling rule.

5. Ragnarok does not yet cover all of PyPSA’s broader planning modes.
   The largest optimization gaps today are:
   - stochastic optimization
   - security-constrained optimization
   - stochastic / uncertainty workflow beyond frontend scenario presets
   - richer scenario-aware analytics

## Roadmap

The project is steering toward five groups of work. Detailed entries (with IDs `B1`–`B3`, `F1`–`F2`, `R1`–`R2`, `D1`, `I1`–`I3`) and a cross-group execution order live in [docs/TODO.md](./docs/TODO.md).

1. **Backend adapters** *(next).* New adapters under the existing `Backend` protocol (`backend/app/backends/`, selected by `options.backend`, reported by `GET /api/backends`; PyPSA cost-min is the only adapter today): a **profit-focused** merchant / asset-owner optimisation adapter (`B1`), a non-optimisation **simulation** adapter that steps the system through the horizon under fixed dispatch rules / bids / prices (`B2`), and a **power-flow-only** study mode (`B3`).

2. **Financial model.** A **company / owner dimension** added to components and analytics (`F1`), and a **company-level financial model** (`F2`) — per-owner cashflow, revenue, opex, capex, debt service, IRR / NPV / DSCR / payback over the modelled horizon, driven by the dispatch and capacity-expansion results from the profit-focused adapter.

3. **Risk modules.** A **physical-climate-risk** module (`R1`) that scores assets against heat / drought / flood / storm / wildfire hazard layers and feeds the result back as availability / derate time series, and a **transition-risk** module (`R2`) that applies carbon-price trajectories, demand shocks, policy pathways, and stranded-asset assumptions to the company-level financial model.

4. **Data platform.** A backend **profile / weather data layer** (`D1`) — persistent storage, source registry (versioning + provenance), source-health checks — that owns caching, versioning, and provenance for every external dataset Ragnarok consumes (renewable, weather, fleet, grid, policy).

5. **Data importers.** Three user-facing surfaces above the data platform: a **location-based data & model bootstrap** (`I1`, pick a location → fetch weather, grid, fleet, demand, policy/price → snap to a runnable workbook); a **PyPSA-Earth / open-data toolchain importer** (`I2`, ingest country-scale networks built outside Ragnarok); and a **demand forecast generator** (`I3`, driver-based per-bus / per-region projection with hourly reshaping).

The earlier "Topology build mode" direction was retired: the unified map-driven Build already covers the intended free-form editing affordances (own-x/y placement, click-to-link, pick-on-map, drag-to-move), so a separate `Serialised vs Topology` toggle is redundant.

## Running the app

Three modes, one repo — pick by how you're using it:

| Mode | Command (macOS · Windows) | Binds | Frontend | Use it for |
|---|---|---|---|---|
| **dev** | `./run.command` · `run.bat` | `127.0.0.1` | live-reload dev server (:3000) | developing (hot reload) |
| **server** (default) | `./serve.command` · `serve.bat` | `0.0.0.0:8000` | committed `./build` | sharing on your LAN |
| **local** | `./serve.command local` · `serve.bat local` | `127.0.0.1:8000` | committed `./build` | just this machine |

`serve.*` runs **one** uvicorn process serving the API and the web UI on a
single port, using the committed `./build` — so **no Node.js is required** to run
it. With **no argument (or a double-click) it starts server mode** (`0.0.0.0`,
reachable from any machine on the network); pass `local` to bind `127.0.0.1`
(this machine only).

> **Server-mode security:** there is **no authentication** — run on trusted
> networks only (plugin install executes uploaded Python by design). Never
> expose it to the internet; use a VPN overlay (e.g. Tailscale) or an
> authenticated tunnel for remote access. Port override: `RAGNAROK_PORT`.

The web UI at `./build` is committed for zero-dependency serving. After frontend
changes, refresh it with `scripts/refresh_build.sh` (macOS/Linux) or
`scripts/refresh_build.ps1` (Windows) and commit the result.

### AI assistant (Bifrost MCP)

Ragnarok ships an MCP server (`backend/mcp/`) that exposes its tool catalog to
any MCP-capable agent — Claude Code/Desktop, Codex CLI, Gemini CLI, Goose,
LibreChat, or a local model in LM Studio.

**`serve` starts it for you.** Running `serve.command` / `serve.bat` launches the
MCP bridge over HTTP at `http://<host>:8765/mcp` alongside the app (installing
its deps on first run). A client on another machine connects by **URL with
nothing installed** — e.g. LM Studio `mcp.json`:
`{"mcpServers": {"ragnarok": {"url": "http://<server-ip>:8765/mcp"}}}`. Set
`RAGNAROK_MCP=off` to skip it, `RAGNAROK_MCP_PORT` to move it.

For a **stdio** setup (the agent launches the bridge locally) install its deps
manually — they're self-contained (`mcp` + `httpx`, no PyPSA):

```bash
.venv-pypsa/bin/python -m pip install -r backend/mcp/requirements-mcp.txt      # macOS/Linux
.venv-pypsa\Scripts\python -m pip install -r backend\mcp\requirements-mcp.txt  # Windows
```

Register it in your agent client (`command` = the venv python, `args` =
`["-m","backend.mcp"]`, `env.PYTHONPATH` = the repo path, `env.RAGNAROK_API_BASE`
= the backend URL). Full per-client config (macOS + Windows), the autonomy
guard, and the "run it on another machine" setup are in
[`docs/bifrost-agent.md`](docs/bifrost-agent.md) §10.

## Development

Run locally in dev mode (live reload):

```bash
./run.command
```

Key frontend commands (run from the frontend package root):

```bash
cd frontend/Ragnarok_default
npm run start:frontend
npm run build
npx tsc --noEmit
```

Key backend checks:

```bash
python3 -m py_compile backend/app/main.py backend/pypsa/network/__init__.py backend/pypsa/results/__init__.py
```

Regenerate the PyPSA schema:

```bash
npm run generate:pypsa-schema
```

## Repository Notes

- The frontend is intentionally Excel-first.
- The schema is generated from PyPSA GitHub metadata, but support in Ragnarok still depends on whether a feature is:
  - only preserved in workbook form
  - actively consumed by the backend
  - surfaced in analytics
- The most accurate way to read current support is the matrix above, not the presence of a sheet name in the schema alone.
