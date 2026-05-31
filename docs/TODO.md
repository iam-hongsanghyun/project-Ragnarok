# Ragnarok TODO

Last updated: 2026-05-31

Single living todo for Ragnarok. Open work is grouped below by theme. Completed and deliberately-dropped items are kept at the bottom in compact form so they are not re-proposed.

## Scales

- **Status** — `Open` / `In progress` / `Done` / `Not Needed`.
- **Priority** — `Critical` / `High` / `Medium` / `Low`.
- **Surface** — `Frontend` / `Backend` / `Both`.
- **Cost** — rough implementation budget for one focused coding pass (reading, patching, verification, light docs). Not a calendar estimate.

## Open work

Fourteen items across six groups. Each group is internally coherent (shared infrastructure, schema, or interfaces); cross-group dependencies are called out in the *Why* column.

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
| `I3` | `High` | `Both` | **Driver-based demand forecast generator** — per-bus / per-region future demand profiles from drivers (population, GDP, electrification rate, weather sensitivity) with hourly reshaping for pathway runs. | Pathway runs need decade-spanning demand with an evolving shape (electrification of heat / transport shifts the hourly profile, not just the level). Distinct from **T1** (which just scales an existing series with simple methods); this one drives a *new* shape from exogenous drivers. Depends on **D1** for driver datasets. | 24,000 |
| `I4` | `High` | `Both` | **Renewable resource profile importer** — pick a region on the map (polygon / buffer around a point / pre-built admin shape), pull wind / solar / hydro inflow time series for that region, then auto-match the imported profile to generators in the workbook by location. | Wind / solar capacity factors vary inside a country; a single national profile is too coarse for siting work. Polygon / buffer selection on the Leaflet map plus a nearest-or-within join to generator coordinates lets the user attach the right shape to the right asset. Depends on **D1** for cached weather / atlite outputs and on the Data view shell shipped this PR. | 20,000 |

### Transformation tools

Tools that transform an already-imported workbook between Data and Run — sit alongside the Build view's edit affordances but operate at sheet-scale rather than row-scale.

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---:|
| `T1` | `High` | `Both` | **Forecast tool** — extend any temporal sheet (loads, generator availability, prices, inflow, …) over a future horizon. Methods: (a) time-series extrapolation (ARIMA / Prophet / linear), (b) annual CAGR with a chosen base year, (c) flat multiplication of a base series. Updates the workbook's snapshots so the run window includes the forecast horizon. | Pathway / multi-year runs need future temporal data; today users have to hand-build it outside Ragnarok. **T1** is the lightweight scaling path. Differs from **I3** (which derives a new shape from exogenous drivers); **T1** just stretches an existing series. | 18,000 |
| `T2` | `High` | `Both` | **Reduced-order / clustering tool** — collapse the workbook to a smaller topology before running. User picks the method (k-means on bus coordinates, voltage-class merge, carrier-bundle aggregation for generators, removal-of-low-flow lines, …) and the target size. Output is a new workbook fragment that runs the same physics on fewer components. | OSM-imported grids and PyPSA-Eur-style bundles often arrive with thousands of buses / lines; many studies need a 50-bus / 20-cluster reduction before they can iterate fast. Today users export to CSV and reduce externally. | 26,000 |
| `T3` | `High` | `Both` | **Component-to-bus reconciliation** — primarily a per-row affordance in the **Build** view's right rail, next to each component's bus dropdown (Add / Edit Generator, Load, Storage, Process, …): a small **Find nearest bus** action that snaps the current component to the closest bus by haversine, plus a popover with alternative strategies (within an admin polygon, by name match, by free-form rule). Same action also lives in a **Reconcile all** button on the sheet header for bulk fix-up after multi-source imports, with a preview of which rows will move where before applying. | After importing plants (e.g. **WRI GPPD**) and grid (e.g. **OSM**) independently, generators land on synthetic per-plant buses. The inline button makes a one-row fix obvious when the user is already editing that component; the bulk action handles the post-import sweep. Same operation also fixes plant-by-name imports that arrive without coordinates. | 14,000 |

## Suggested execution order

Across groups, respecting cross-group dependencies marked above.

1. **T3** — Component-to-bus reconciliation (unblocks merged WRI + OSM imports shipped 2026-05-31).
2. **T1** — Forecast tool (lightweight; immediately useful for pathway runs).
3. **B1** — Profit-focused optimisation (foundation for the financial model layer).
4. **F1** — Company / owner dimension (frontend-heavy; can run in parallel with **B1**).
5. **F2** — Company-level financial model (consumes **B1** + **F1**).
6. **R1** — Physical-climate-risk module.
7. **R2** — Transition-risk module (depends on **F2**).
8. **T2** — Reduced-order / clustering tool.
9. **D1** — Profile / weather data layer.
10. **I1** — Location-based data & model bootstrap (user surface above **D1**).
11. **I4** — Renewable resource profile importer (polygon / buffer region selection).
12. **I3** — Driver-based demand forecast.
13. **B2** — Simulation backend adapter.
14. **B3** — Power-flow-only study mode.

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
- **PyPSA-Earth as a registered data source** (former `I2`) — PyPSA-Earth is a Snakemake workflow that *produces* country networks from upstream OSM / ERA5 / GADM / atlite outputs, it does not publish data itself. Importing a PyPSA-Earth-built network is equivalent to importing any PyPSA-native `.nc`, which is already covered by the existing `POST /api/import/netcdf` endpoint and the corresponding **Import netCDF** button. A standalone registry entry would duplicate that path without adding value; remove from the Data view registry.
