# Ragnarok TODO

Last updated: 2026-05-30

Single living todo for Ragnarok. Open work is grouped below by theme. Completed and deliberately-dropped items are kept at the bottom in compact form so they are not re-proposed.

## Scales

- **Status** — `Open` / `In progress` / `Done` / `Not Needed`.
- **Priority** — `Critical` / `High` / `Medium` / `Low`.
- **Surface** — `Frontend` / `Backend` / `Both`.
- **Cost** — rough implementation budget for one focused coding pass (reading, patching, verification, light docs). Not a calendar estimate.

## Open work

Eleven items across five groups. Each group is internally coherent (shared infrastructure, schema, or interfaces); cross-group dependencies are called out in the *Why* column.

### Backend adapters

Adapters that plug into the existing `Backend` protocol (`backend/app/backends/`). PyPSA cost-min is the default; each item below is an additional adapter selectable by `options.backend`.

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---:|
| `B1` | `High` | `Both` | **Profit-focused optimisation** — merchant / asset-owner objective as a second adapter. Maximises owner revenue under exogenous market prices, bidding strategies, or contract terms. | Current solve answers *least-cost for the whole system*; investor / IPP / merchant use-cases need *most-profitable for this owner*. Foundation for **F1**, **F2**. | 24,000 |
| `B2` | `High` | `Both` | **Simulation adapter** — non-optimisation. Given dispatch rules / bids / prices, step the system through the horizon and report flows, prices, and revenues. | Take a fixed strategy or operating rule and simulate the outcome under a chosen market structure. Different from **B3** (steady-state network analysis, not time-stepped market simulation). | 30,000 |
| `B3` | `Medium` | `Both` | **Power-flow-only study mode** — non-optimisation `network.pf()` / `network.lpf()` workflow with its own UI surface. | Steady-state network-analysis use case that pairs with the optimiser / simulator pair (**B1**, **B2**). Currently `Not supported` in the README support matrix. | 16,000 |

### Financial model

Items that turn dispatch / capacity-expansion results into investor- and company-level financial metrics. Depends on **B1** for the revenue signal.

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---:|
| `F1` | `High` | `Both` | **Company / owner dimension** — `owner` attribute on generators / storage / lines / stores, schema-driven through workbook I/O, with per-company KPIs (capacity, dispatch, revenue, emissions) and a company drill-down view in Analytics. | Components have no owner field today, so every analytics surface treats the system as one consolidated entity. Bridges dispatch results to **F2**. | 22,000 |
| `F2` | `High` | `Both` | **Company-level financial model** — per-owner cashflow, revenue, opex, capex, debt service, IRR / NPV / DSCR / payback over the modelled horizon, driven by dispatch + capacity-expansion results. | Investors need project- and company-finance metrics, not raw revenue. Makes the tool usable for infrastructure investors and corporate planners. Required input to **R2**. | 26,000 |

### Risk modules

Climate-related exposure modules. Physical risk perturbs *inputs* (asset availability); transition risk perturbs *outputs* (financial model assumptions).

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---:|
| `R1` | `High` | `Both` | **Physical-climate-risk module** — score assets against heat / drought / flood / storm / wildfire hazard layers tied to location and operating envelope; feed the result back into the model as availability / derate time series. | Thermal, hydro, transmission, and renewables all have location-dependent physical exposure that changes under climate change. Pathway runs currently assume historical availability for every future period. | 26,000 |
| `R2` | `High` | `Both` | **Transition-risk module** — apply carbon-price trajectories, demand shocks, policy pathways, and stranded-asset assumptions to the company-level financial model. | Today's carbon-price input is a single number applied uniformly. Transition-risk needs trajectories and policy pathways evaluated against each company's portfolio so stranded-asset and revenue-at-risk exposure is visible over the planning horizon. Depends on **F2**. | 22,000 |

### Data platform

Backend infrastructure that stores, versions, and serves external datasets. Read by the importers in the next group.

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---:|
| `D1` | `High` | `Backend` | **Profile / weather data layer** — persistent storage, source registry (versioning + provenance), and source-health checks for renewable, weather, fleet, grid, and policy datasets. | One coherent backend layer that owns caching, versioning, provenance, and health for every external dataset Ragnarok consumes. Prerequisite for **I1**, **I2**, **I3**. | 22,000 |

### Data importers

User-facing surfaces that bring data into a Ragnarok workbook — either from the **D1** platform or from external open-data toolchains.

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---:|
| `I1` | `High` | `Both` | **Location-based data & model bootstrap** — pick a point / region / country in the UI and assemble a runnable Ragnarok workbook from **D1**: weather profiles, grid topology, generation fleet, demand, policy / price data. | The integrated user surface above **D1**: one location selected → one runnable model. Replaces per-piece "location profile import / national starter / country preset" workflows. | 28,000 |
| `I2` | `High` | `Both` | **PyPSA-Earth (and similar open-data toolchain) importer** — read networks built by PyPSA-Earth / atlite / similar workflows directly into Ragnarok, mapping their outputs to the Ragnarok workbook schema. | Open-data toolchains already build country-scale PyPSA networks. Ingesting their output avoids re-implementing data harvesting and snaps the user straight into a country-scale model. Complements **I1** (which builds models inside Ragnarok) by importing models built outside. | 20,000 |
| `I3` | `High` | `Both` | **Demand forecast generator** — per-bus / per-region future demand profiles from drivers (population, GDP, electrification rate, weather sensitivity) with hourly reshaping for pathway runs. | Pathway runs need decade-spanning demand with an evolving shape (electrification of heat / transport shifts the hourly profile, not just the level). Subsumes the simpler "annual demand-growth multiplier" idea. Depends on **D1** for driver datasets. | 24,000 |

## Suggested execution order

Across groups, respecting cross-group dependencies marked above.

1. **B1** — Profit-focused optimisation (foundation for the financial model layer).
2. **F1** — Company / owner dimension (frontend-heavy; can run in parallel with **B1**).
3. **F2** — Company-level financial model (consumes **B1** + **F1**).
4. **R1** — Physical-climate-risk module.
5. **R2** — Transition-risk module (depends on **F2**).
6. **D1** — Profile / weather data layer.
7. **I1** — Location-based data & model bootstrap (user surface above **D1**).
8. **I2** — PyPSA-Earth importer.
9. **I3** — Demand forecast.
10. **B2** — Simulation backend adapter.
11. **B3** — Power-flow-only study mode.

## Already shipped

Compact history of work completed in earlier passes, grouped by area. Kept so completed items are not re-proposed and to anchor the trust chain for the current implementation. Detailed fulfillment notes were collapsed during the 2026-05-30 cleanup; the original entries are recoverable from git history.

### Optimisation modes

- Single-period optimisation, economic dispatch with extendable assets, carbon pricing as a marginal-cost adder, force-LP override.
- Multi-investment / pathway planning (opt-in mode, period-aware analytics, pathway sample workbook). PR #15 polish: dedicated **Multi-year planning** sidebar group, pill-button period selector, single-period robustness on pathway-style workbooks.
- Rolling-horizon optimisation (`optimize_with_rolling_horizon`) with sidebar horizon / overlap controls.
- Stochastic optimisation (`backend/pypsa/stochastic.py`) — per-scenario summary card, weight normalisation, stochastic-vs-rolling rejection at the API. Tests in `backend/tests/test_stochastic.py`.
- Security-constrained optimisation (`optimize_security_constrained`) — N-1 coverage readout, worst-case line-loading banner. Tests in `backend/tests/test_sclopf.py`.
- Backend abstraction layer (`backend/app/backends/`) — `Backend` protocol, registry, `PypsaBackend` adapter, `GET /api/backends` capability reporting. PyPSA is today's only adapter; **B1**, **B2**, **B3** are the planned second / third / fourth adapters. Tests in `backend/tests/test_backends.py`.

### Project exchange

- Pure-JSON project export/import (PR #9) — backend returns schema-driven `outputs.{static,series}`; frontend assembles the project workbook locally. Sidebar split into Import Project / Export Project / Export Result.
- `deriveRunResults` (PR #11) rebuilds summary / dispatch / costs / carrier mix / nodal balance / line loading / merit order / emissions / expansion / asset details from `(model, outputs)` on import. `co2Shadow` is the one field still needing a fresh solve.
- Ragnarok metadata sheets round-trip end-to-end: settings (incl. date format, currency, solver config), active constraints, run window, scenarios, pathway, rolling-horizon, plugin analytics, CO2 shadow, solver narrative, import provenance.
- HTML report export (PR #12) — standalone `.html` with inline CSS and inline SVG charts.
- CSV-folder, netCDF, HDF5 import/export. CSV folder uses `fflate` in-browser; netCDF/HDF5 go through backend endpoints (`netCDF4`, `tables`).
- Round-trip test suites: frontend `workbook.test.ts`, `csvFolder.test.ts`; backend `test_import_contract.py`, `test_binary_io.py`, `test_full_outputs.py`, `test_type_references.py`.

### Analytics & UX

- Capacity-by-period chart for pathway runs (PR #16).
- Cross-scenario `ScenarioPivotCard` in the Comparison tab — Δ columns vs the leftmost scenario; appears when ≥ 2 scenarios are present.
- Carrier-level analytics card — capacity factor, curtailment ratio, effective cost / MWh, emissions intensity.
- Load drill-down card — load factor, coincidence factor, per-bus contribution table.
- Run-history schema-driven counts (PR #10) — `RunHistoryEntry.componentCounts` is `Record<string, number>`.
- Auto-generated support matrix (`scripts/generate-support-matrix.mjs` → `docs/SUPPORT_MATRIX.md`).
- Constraints workspace overlay (`ConstraintsWorkspaceView`) — Custom + native `global_constraints` editor.
- Standard PyPSA `line_types` / `transformer_types` catalogues (`scripts/generate-pypsa-standard-types.mjs`) surfaced as datalist typeahead in input cells.
- Adaptive time-series x-axis labels and tick density (span-driven format selection).
- Run dialog simplified — scenario presets live in the sidebar; the dialog is an execution summary.
- Resizable Settings / Plugins rails; in-browser plugin runtime; plugin-server launcher driven by `plugins.env`.

### Data integrity

- ISO date normalisation at the import boundary (`normalizeInputDatesToIso`). The Date-format setting now governs *parsing* only; the canonical target everywhere is `YYYY-MM-DD`.
- Schema-driven validation across documented component sheets and time-series sheets; backend dry-run mirrors the schema catalogue.
- Explicit `network` sheet runtime import for `name` / `srid` / `crs` / `now`.

### Component result UX

- **Full** analytics: `buses`, `generators`, `lines`, `links`, `transformers`, `storage_units`, `stores`.
- Dedicated detail panels: `processes`, `shunt_impedances`.
- Round-tripped through workbook + backend without dedicated UX: `carriers`, `global_constraints`, `line_types`, `transformer_types`, `shapes`, `sub_networks`.

## Deliberately not pursued

- **Backend retention of solved `pypsa.Network`** — the server is intentionally stateless. The JSON output cache round-trips losslessly on the frontend (PR #9) and `deriveRunResults` rebuilds the full `RunResults` on import (PR #11), so backend retention buys nothing for Ragnarok-internal trust. Users who need a native `pypsa.Network` can reconstruct one from the exported workbook or CSV folder.
- **Separate "Topology" build mode (`Serialised vs Topology` toggle)** — the unified map-driven Build already folds in the intended free-form affordances (own-x/y placement, click-to-link buses, "pick on map" linking, drag-to-move), so a distinct toggle is redundant rather than a separate mode.
