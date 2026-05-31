# Ragnarok TODO

Last updated: 2026-05-31

Single living todo for Ragnarok. Open work is grouped below by theme. Completed and deliberately-dropped items are kept at the bottom in compact form so they are not re-proposed.

## Scales

- **Status** — `Open` / `In progress` / `Done` / `Not Needed`.
- **Priority** — `Critical` / `High` / `Medium` / `Low`.
- **Surface** — `Frontend` / `Backend` / `Both`.
- **Cost** — rough implementation budget for one focused coding pass (reading, patching, verification, light docs). Not a calendar estimate.

## Open work

Seventeen items across eight groups. Each group is internally coherent (shared infrastructure, schema, or interfaces); cross-group dependencies are called out in the *Why* column.

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
| `D2` | `High` | `Backend` | **Self-hosted historical hourly demand database** — Ragnarok-owned snapshot of EU + global hourly load, with a refresh process. Replaces the direct-OPSD path long-term. | OPSD's `time_series_60min_singleindex.csv` is ~150 MB and stops circa 2020; bad fit for a browser-direct deployment model and increasingly stale anyway. Hosting our own per-country slice (10 MB) lets the frontend fetch only what it needs and lets us refresh on our own cadence (via ENTSO-E's API + our key, run server-side once per refresh, not per user). | 20,000 |

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
| `T1` | `High` | `Both` | **Forecast tool / snapshot editor** — a single Model-side surface for editing the workbook's `snapshots` index and the temporal sheets attached to it. Three concerns in one tool: (a) **Define / re-aim the snapshot window** — calendar picker for new start / end (and resolution: hourly / daily / monthly); imported series are clipped if the window shrinks or pad-extrapolated if it widens. (b) **Forecast / extrapolate** — extend any temporal sheet (`loads-p_set`, `generators-p_max_pu`, prices, inflow, …) over a future horizon. Methods: time-series extrapolation (ARIMA / Prophet / linear), annual CAGR with a chosen base year, flat multiplication of a base series. (c) **Resample / shift** — change time-step or shift a series by N hours / days. The shared point: every operation here is "fix the snapshots so the model can run with the data the user already imported, plus a sensible projection". | After importing OPSD hourly load (year 2019) and a Renewables.ninja profile (year 2018), users end up with a snapshots index that's the union of both ranges and pad-filled gaps. **T1** is the editor that lets them retarget the window (e.g. "I actually want 2025-Jan-01 to 2025-Dec-31"), interpolate / extrapolate the imported series onto the new index, and clip ranges down for fast iteration. Distinct from **I3** (which derives a *new* shape from exogenous drivers); **T1** transforms whatever is already in the workbook. Conceptually the tool lives in the **Model** view next to the snapshots sheet — every operation works directly on the in-memory model, no backend round-trip. | 22,000 |
| `T2` | `High` | `Both` | **Reduced-order / clustering tool** — collapse the workbook to a smaller topology before running. User picks the method (k-means on bus coordinates, voltage-class merge, carrier-bundle aggregation for generators, removal-of-low-flow lines, …) and the target size. Output is a new workbook fragment that runs the same physics on fewer components. | OSM-imported grids and PyPSA-Eur-style bundles often arrive with thousands of buses / lines; many studies need a 50-bus / 20-cluster reduction before they can iterate fast. Today users export to CSV and reduce externally. | 26,000 |
| `T3` | `High` | `Both` | **Component-to-bus reconciliation** — primarily a per-row affordance in the **Build** view's right rail, next to each component's bus dropdown (Add / Edit Generator, Load, Storage, Process, …): a small **Find nearest bus** action that snaps the current component to the closest bus by haversine, plus a popover with alternative strategies (within an admin polygon, by name match, by free-form rule). Same action also lives in a **Reconcile all** button on the sheet header for bulk fix-up after multi-source imports, with a preview of which rows will move where before applying. | After importing plants (e.g. **WRI GPPD**) and grid (e.g. **OSM**) independently, generators land on synthetic per-plant buses. The inline button makes a one-row fix obvious when the user is already editing that component; the bulk action handles the post-import sweep. Same operation also fixes plant-by-name imports that arrive without coordinates. | 14,000 |

### Guided workflows

Top-down user surfaces that build a runnable Ragnarok workbook from high-level intent rather than per-sheet editing. The point is to lower the bar so non-modellers (policy / strategy / finance users) can drive Ragnarok without needing to know PyPSA component schemas.

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---:|
| `W1` | `High` | `Both` | **Guided model-builder wizard** — a stepped flow that asks the user a small ladder of questions and assembles a workbook for them: (1) **Region** — pick a country / region on the map (re-uses the Data view shell); (2) **Question** — "What do you want to study?" (least-cost dispatch / capacity expansion / carbon-cap pathway / merchant IPP / N-1 security / climate-risk); (3) **Time horizon** — historic year, single future year, or multi-period pathway; (4) **Scope** — sectors (electricity only / multi-vector), carriers in-play, candidate technologies; (5) **Constraints** — carbon price / cap, renewable share targets, build-rate limits; (6) **Confidence** — let the wizard fall back to defaults the user did not answer. Output is a fully-populated workbook that is immediately runnable, with provenance flagging every cell the wizard filled vs the user edited. Power users can drop out into the regular Build / Model views at any step. | The Data view we shipped is bottom-up (pick a database, pull rows, repeat). A non-modeller cannot navigate that — they don't know which databases they need, which sheets to populate, or what defaults are reasonable. **W1** is the answer: state your goal in plain language, get a model. Internally it composes the existing importers (`I1`, `I4`, …) plus the transformation tools (`T1`, `T2`, `T3`) into one orchestrated flow, so it has zero new data-source code — it just sequences what is already there with sensible defaults per question. | 32,000 |

### Modelling extensions

Modelling-capability extensions that broaden Ragnarok beyond the single-vector electricity case it ships with today. Each item is a vertical slice — schema-aware Build/Model affordances, importers for sector-specific datasets, optimiser handling, and analytics. PyPSA already supports the underlying mechanics (multi-carrier buses, Links, Stores); the work here is exposing them cleanly through the GUI.

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---:|
| `M1` | `High` | `Both` | **Sector coupling** — multi-carrier buses (electricity, gas, hydrogen, heat, district cooling, transport, biomass, CO₂) plus the conversion components that link them (electrolyser, gas turbine / CCGT, heat pump, electric boiler, fuel cell, methaniser, CCS / DAC). Includes per-carrier transport (gas pipelines, hydrogen pipelines, district heating loops) modelled as `Link` networks, carrier-aware filters in the Build view (show only components on the active carrier), and per-vector energy-balance + emissions analytics. Carrier defaults (efficiency, capex, opex, lifetime) seeded from PyPSA-Eur's `costs.csv`. | The decarbonisation studies users want — green-hydrogen merchant, electrify-everything pathways, gas-network repurposing, district-heat decarbonisation — all need more than one energy vector. Today Ragnarok models electricity only; **M1** unlocks the multi-vector cases without changing the optimisation engine (PyPSA already handles it). | 40,000 |
| `M2` | `High` | `Both` | **Demand response** — flexible load modelling beyond static `p_set`. Three flexibility modes: (a) **Shed** — load can be curtailed at a per-MWh outage cost (extends today's coarse `load_shedding` option to per-load granularity + per-snapshot caps); (b) **Shift** — load can move within a user-defined window (e.g. ±4 h) preserving total daily energy, implemented as a Storage-like component; (c) **Price-elastic** — demand drops as the bus price exceeds a tier threshold (piecewise demand curve). UI: new "Flexibility" section on the Load editor in Build, time-of-use programs as a DSL/template library, analytics showing DR utilisation (energy shifted, energy shed, peak reduction). | Modern systems lean heavily on DR for peak shaving and renewable integration; capacity-expansion models that ignore it over-build firm capacity. **M2** is the missing demand-side complement to **T1** (forecast growth) and **R2** (transition risk). | 28,000 |

## Suggested execution order

Across groups, respecting cross-group dependencies marked above.

1. **T3** — Component-to-bus reconciliation (unblocks merged WRI + OSM imports shipped 2026-05-31).
2. **T1** — Forecast tool (lightweight; immediately useful for pathway runs).
3. **M2** — Demand response (small, modular — slots into the existing Load editor; useful for every other run from here on).
4. **B1** — Profit-focused optimisation (foundation for the financial model layer).
5. **F1** — Company / owner dimension (frontend-heavy; can run in parallel with **B1**).
6. **F2** — Company-level financial model (consumes **B1** + **F1**).
7. **R1** — Physical-climate-risk module.
8. **R2** — Transition-risk module (depends on **F2**).
9. **T2** — Reduced-order / clustering tool.
10. **D1** — Profile / weather data layer.
11. **I1** — Location-based data & model bootstrap (user surface above **D1**).
12. **I4** — Renewable resource profile importer (polygon / buffer region selection).
13. **I3** — Driver-based demand forecast.
14. **M1** — Sector coupling (largest single item; lifts Ragnarok out of electricity-only).
15. **W1** — Guided model-builder wizard (composes every importer + tool + **M1**/**M2** above).
16. **B2** — Simulation backend adapter.
17. **B3** — Power-flow-only study mode.

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
- **Renewables.ninja as a registered data source** (former Tier-1 candidate) — the public endpoint returns HTTP 406 without an API key, and routing every user fetch through a Ragnarok-held key conflicts with the "no server-side API config" security stance. Revisit once a per-user API-key Settings panel exists (paired with Tier-2 ENTSO-E / EIA work).
- **PyPSA `technology-data` as a registered data source** (former Tier-1 candidate) — it is a *static CSV in a git repo*, not a queryable database. Pulling cost snapshots from a checked-in file violates the user-stated rule "we don't gather data from static format never ever. you only gather data from proper database." Cost defaults will be sourced from a proper queryable upstream (or curated in-app) when the Costs & parameters category is revisited.
- **OWID Energy as a registered data source** — same reason: a static CSV in a git repo, not a queryable database.
- **OPSD `time_series_60min_singleindex.csv` (former `opsd_load`)** — a ~150 MB CSV that the target browser-direct deployment cannot fetch in full per user, the upstream snapshot stops circa 2020, and slicing it server-side per request reintroduces the centralised data-gathering backend we explicitly moved away from. Tracked for replacement under **D2** (self-hosted hourly demand database with our own refresh cadence).
