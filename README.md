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
| [docs/getting-started.md](./docs/getting-started.md) | Install, launch, and a quick tour |
| [docs/guides/USER_MANUAL.md](./docs/guides/USER_MANUAL.md) | End-user manual for analysts |
| [docs/guides/PLUGIN_AUTHORING.md](./docs/guides/PLUGIN_AUTHORING.md) | How to build a plugin |
| [docs/architecture/ARCHITECTURE.md](./docs/architecture/ARCHITECTURE.md) | System overview, tech stack, repo layout, data flow |
| [docs/architecture/PROCESSES.md](./docs/architecture/PROCESSES.md) | Step-by-step logic of each process |
| [docs/architecture/DESIGN.md](./docs/architecture/DESIGN.md) | UI design philosophy |
| [docs/CAPABILITIES.md](./docs/CAPABILITIES.md) | What Ragnarok can and cannot do (code-checked) |
| [docs/SUPPORT_MATRIX.md](./docs/SUPPORT_MATRIX.md) | Generated feature support matrix |
| [docs/reference/](./docs/reference/) | Per-module function reference (backend + frontend) |
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

## Sample Networks

Maintained sample workbooks live in [sample-networks](/Users/sanghyun/github/pypsa_gui/sample-networks).

- [sample-networks/pathway_capacity_expansion.xlsx](/Users/sanghyun/github/pypsa_gui/sample-networks/pathway_capacity_expansion.xlsx): canonical pathway-planning test case
- [sample-networks/capacity_expansion.xlsx](/Users/sanghyun/github/pypsa_gui/sample-networks/capacity_expansion.xlsx): single-period expansion baseline
- [sample-networks/two_bus_dispatch.xlsx](/Users/sanghyun/github/pypsa_gui/sample-networks/two_bus_dispatch.xlsx): small dispatch baseline

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
| Stochastic optimization | `Not supported` | No scenario-tree, two-stage, or CVaR workflow. |
| Security-constrained optimization / SCLOPF | `Not supported` | No branch-outage or contingency solve path. |
| Scenario-based planning UX | `Partial` | Frontend scenario presets now capture window, constraints, carbon price, pathway, and rolling settings in workbook metadata, but there is still no stochastic backend workflow. |
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
| Stochastic optimization | `Not supported` | No scenario-tree workflow or stochastic solve mode. |
| Security-constrained optimization | `Not supported` | No SCLOPF / branch outage workflow. |
| Native `global_constraints` workbook usage | `Implicit` | Sheet is available and passed through the generic network builder, but Ragnarok adds only limited dedicated UI/analytics around it. |
| Plugin execution pipeline | `Full` | `pre-build`, `post-build`, `in-solve`, `post-solve` stages are implemented. |
| Plugin analytics round-trip through project import/export | `Full` | Stored in `RAGNAROK_PluginAnalytics` and restored on import without plugin re-execution. |
| Project settings / constraints / run-state metadata round-trip | `Full` | Stored in dedicated Ragnarok metadata sheets and restored on project import. |
| CO2 shadow price restoration from imported project | `Full` | Stored in `RAGNAROK_ResultMeta` and restored on import. |
| Backend retention of solved network/workbook | `Not Needed` | Deliberate: the server is stateless. The backend returns result JSON and derived output caches; the frontend round-trips losslessly, so no solved `pypsa.Network` artifact is retained server-side. |
| CSV-folder / netCDF / HDF5 workflows | `Not supported` | Ragnarok is currently Excel-first in the UI. |
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
   The app exports `results.outputs`, not a retained solved `pypsa.Network`. This is by design — the server is stateless and does not retain solved artifacts (see Roadmap / TODO "Not Needed"). The frontend round-trips losslessly, and a native `pypsa.Network` can be reconstructed from the exported workbook or CSV folder.

2. `Import Project` rebuilds project state from workbook inputs/outputs rather than reopening a retained `pypsa.Network`.
   It restores frontend project state and result metadata and reconstructs `RunResults` locally. No backend-solved network artifact is involved, by design (stateless server).

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

The project is steering toward three large bodies of work, tackled one at a time. Detailed entries live in [docs/TODO.md](./docs/TODO.md).

1. **Topology build mode** *(next).* The Build tab currently authors a model with a step-by-step (Serialised) wizard. A `Serialised vs Topology` toggle will add a free-form mode where the whole model is placed, connected, and edited directly on the map / network topology. It reuses the Build map (own-x/y component placement, click-to-link buses, "pick on map", drag-to-move) already shipped, plus multi-bus click-linking for branches.

2. **Pluggable backend** *(seam landed; additional backends future).* The backend abstraction layer is in place: a single `run(model, scenario, options)` adapter per backend, selected by `options.backend` (default `pypsa`), registered in `backend/app/backends/` and reported by `GET /api/backends`. PyPSA is the only adapter today. The server stays stateless — each adapter returns the schema-driven output cache and the frontend remains the single source of round-trip truth (no per-run backend artifact retention). Remaining work is adding a second adapter when a concrete alternative backend is chosen.

3. **Data platform.** Location-based renewable (wind/solar) profile generation and import, a persistent profile database/cache layer, national-level starter model imports, a source registry with versioning and provenance, data-source health checks, and country/region import presets.

A **power-flow-only (PF / linear PF) study mode** is also planned as a non-optimization companion to the topology builder.

## Development

Run locally:

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
