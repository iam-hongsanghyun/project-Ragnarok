# Ragnarok TODO

Last updated: 2026-07-01 (status audited against the codebase — many items previously listed open were already shipped; see *Already shipped*).

Single living todo for Ragnarok. Open work is grouped below by theme. Completed and deliberately-dropped items are kept at the bottom in compact form so they are not re-proposed.

## Scales

- **Status** — `Open` / `In progress` / `Done` / `Deferred` / `Not Needed`.
- **Priority** — `Critical` / `High` / `Medium` / `Low`.
- **Surface** — `Frontend` / `Backend` / `Both`.
- **Cost** — rough implementation budget for one focused coding pass (reading, patching, verification, light docs). Not a calendar estimate.

## North star — a fully-available PyPSA frontend

Where Ragnarok stands against "the GUI for *any* PyPSA model": the **modeling core is ~80–90 % complete**. The grid schema is generated at runtime from PyPSA's own component registry (`backend/app/pypsa_schema_builder.build_pypsa_schema`), so **every component and attribute is already editable** — committable / ramp / min-up-down, storage inflow / spillage / cyclic, multi-port Links, global constraints, line & transformer types. All major `optimize()` modes are wired (LOPF / capacity-expansion, unit commitment, multi-investment pathways, stochastic, rolling-horizon, SCLOPF, MGA) plus AC/DC power flow, and I/O (netCDF / CSV-folder / HDF5 / Excel / JSON) round-trips.

So the gap is **not** "expose more of PyPSA" — it is the five layers *around* the core:

| Layer | Gap → items | Status |
|---|---|---|
| **1. Data-in for arbitrary regions** (highest leverage) | general weather → renewable profiles (**D1** + **I4**), fuel & carbon prices (**I5**), driver-based demand (**I3**), any-country network (**I9**) | mostly open — KOR / EU / US already covered |
| **2. Feature-exposure polish** | carrier-aware charts + multi-port Links (**M1** remainder), full `n.statistics()` family + more duals, non-CO₂ global-constraint UI, optional extra solvers | small gaps on a shipped core |
| **3. Usability for any user** | guided model wizard (**W1**), country starter framework (**W2**), in-app tour (**W3**), infeasibility / solver diagnostics (**Q2**) | open — demo networks + Build wizard shipped |
| **4. Scale & robustness** | thin-client for 1000s-of-bus networks — port analytics derivation server-side (**X1** / **X2**) | session-store backbone shipped; derivation port open |
| **5. Correctness & trust** | PyPSA reference-parity test suite (**Q1**) | round-trip I/O tested; end-to-end result parity not systematically pinned |

**Critical path** to "any PyPSA model, trusted, at scale": **D1 → I4** (model any region) → **X1 / X2** (handle large networks) → **W2** (get users to a runnable model fast) → **Q1** (prove parity with native PyPSA). Everything else is breadth on top of that spine. The per-group tables below hold the full backlog; the *Suggested execution order* sequences it.

## Open work

Genuinely-open or partially-complete items only. The whole financial / decision-workflow spine and the modelling-reach items (B1, F1, F2, PP1, DW1–DW4, M1–M3, B3, T2) have shipped — they live under *Already shipped*. The remaining frontier is **risk, resource adequacy, the weather/data-import layer, guided & conversational surfaces, and architecture**.

### Backend adapters

Adapters that plug into the existing `Backend` protocol (`backend/app/backends/`). PyPSA cost-min is the default; each item below is an additional adapter selectable by `options.backend`.

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `B2` | `Open` | `High` | `Both` | **Simulation adapter** — non-optimisation. Given dispatch rules / bids / prices, step the system through the horizon and report flows, prices, and revenues. | Take a fixed strategy or operating rule and simulate the outcome under a chosen market structure. Different from **B3** (steady-state network analysis, not time-stepped market simulation). | 30,000 |
| `B4` | `Deferred` | `Low` | `Both` | **Strategic / price-maker optimisation** — endogenous prices where the owner's bids move the clearing price (market power, capacity withholding). A **bilevel / MPEC** problem (lower-level market clearing reformulated via KKT + complementarity) that PyPSA's single-level LP **cannot express**; needs a hand-built linopy / pyomo / gurobipy model (MILP via SOS1) or an iterative equilibrium solver — a different stack, not an adapter over PyPSA. Research-grade and data-hungry (requires rivals' cost curves). | The only flavour of profit-max that captures market power, i.e. *strategic* decision-making per company. Separated from **B1** because it is a different problem class and a different solver stack. **Deferred** — documented, not built. Note: the *analytics* precursors (price formation, unit commitment, bid strategy, optimal single-owner bid) already shipped — see *Already shipped → Market power & strategic pricing*. | 40,000 |

### Power procurement

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `PP2` | `Deferred` | `High` | `Both` | **Procurement strategy optimizer** — given a buyer's load profile and a menu of available instruments (spot exposure, one or more fixed-price PPAs, futures / forward contracts, retail tariff, self-supply), find the portfolio mix that minimises expected annual energy cost subject to a price-risk budget (e.g. CVaR constraint on total spend). Outputs: optimal contract volumes per instrument, cost-vs-risk efficient frontier, sensitivity to price / load-growth. | A meaningful PP2 needs a **risk model** (CVaR / variance) — deterministic min-cost is trivial (100 % on the cheapest instrument). **Deferred by design decision (2026-07-01):** build it inside a dedicated **use-case surface** (goal → objective → instruments → risk budget) that also reframes PP1 (valuation) + DW4 (shape explorer), rather than as another Settings panel. Not a piecemeal build. | 22,000 |

### Risk modules

Climate-related exposure modules. Physical risk perturbs *inputs* (asset availability); transition risk perturbs *outputs* (financial-model assumptions). Neither exists in code yet.

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `R1` | `Open` | `High` | `Both` | **Physical-climate-risk module** — score assets against heat / drought / flood / storm / wildfire hazard layers tied to location and operating envelope; feed the result back into the model as availability / derate time series. | Thermal, hydro, transmission, and renewables all have location-dependent physical exposure that changes under climate change. Pathway runs currently assume historical availability for every future period. | 26,000 |
| `R2` | `Open` | `High` | `Both` | **Transition-risk module** — apply carbon-price trajectories, demand shocks, policy pathways, and stranded-asset assumptions to the company-level financial model. | Today's carbon-price input is a single number (or a year→price schedule); transition-risk needs trajectories + policy pathways evaluated against each company's portfolio so stranded-asset and revenue-at-risk exposure is visible over the horizon. Depends on **F2** (shipped). | 22,000 |

### Data platform

Backend infrastructure that stores, versions, and serves external datasets. Read by the importers in the next group. Partially addressed: an importer **source registry** exists (`backend/app/importers/registry.py` + per-database modules); the **weather/reanalysis caching layer** does not.

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `D1` | `In progress` | `High` | `Backend` | **Profile / weather data layer** — persistent storage, source registry (versioning + provenance), and source-health checks for renewable, weather, fleet, grid, and policy datasets. **Done:** the source registry + per-database module pattern (`importers/registry.py`, `importers/databases/*`). **Remaining:** the weather/reanalysis (ERA5 / atlite / PVGIS) caching + provenance layer that **I4** needs. | One coherent backend layer that owns caching, versioning, provenance, and health for every external dataset Ragnarok consumes. Prerequisite for the weather-driven half of **I4**. | 14,000 |
| `D2` | `Open` | `High` | `Backend` | **Self-hosted historical hourly demand database** — Ragnarok-owned snapshot of EU + global hourly load, with a refresh process. Note: on-demand hourly demand is already covered by the **ENTSO-E load** and **EIA-930** importers (shipped); D2 is the *self-hosted cached* alternative for scale / offline. | Fetch-per-user against ENTSO-E/EIA works but is rate-limited and network-bound; a per-country self-hosted slice (≈10 MB) lets the frontend fetch only what it needs and refresh on our cadence. | 20,000 |

### Data importers

User-facing surfaces that bring data into a Ragnarok workbook. **Substantial infrastructure already shipped** — the importer framework + these sources: **OSM** grid topology, **OSM power plants**, **WRI GPPD** fleet, **World Bank** annual demand, **ENTSO-E** installed capacity, **ENTSO-E** hourly load, **EIA-930** hourly demand, and the **KPG193** Korea pack (network / demand profile / renewable capacity / renewable profile). The items below are what's left.

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `I1` | `In progress` | `High` | `Both` | **Location-based data & model bootstrap** — pick a point / region / country and assemble a runnable workbook. **Done:** the Data view country-first importer surface (pick a region → pull network / plants / demand / renewable profiles from OSM / WRI / World Bank / KPG193). **Remaining:** the *one-click, one-location → complete runnable model* orchestration (currently the user pulls each source in turn) — this overlaps **W1**/**W2**. | The integrated surface above the importers: one location selected → one runnable model. | 14,000 |
| `I3` | `Open` | `High` | `Both` | **Driver-based demand forecast generator** — per-bus / per-region future demand profiles from drivers (population, GDP, electrification rate, weather sensitivity) with hourly reshaping for pathway runs. | Pathway runs need decade-spanning demand with an evolving *shape* (electrification of heat/transport shifts the hourly profile, not just the level). Distinct from **T1** (scales an existing series) — this derives a *new* shape from exogenous drivers. Depends on **D1** for driver datasets. | 24,000 |
| `I4` | `In progress` | `High` | `Both` | **Renewable resource profile importer** — fetch wind / solar / hydro-inflow capacity-factor series for a location and land them as `generators-p_max_pu`. **Done:** per-bus renewable profiles for the KPG193 pack (`kpg193_renewable_profile`). **Remaining:** the general coordinate-driven importer (query at each renewable generator's coord, fall back to bus coord; polygon / pin-on-map entry points) from keyless **PVGIS / NASA POWER / Open-Meteo** + BYOK **Renewables.ninja**. See *I4 design* below. | A single national profile is too coarse for siting. Coordinate-driven attachment + snapshot alignment (via **T1**) puts the right shape on the right asset. Depends on **D1** for cached weather. | 16,000 |
| `I5` | `Open` | `High` | `Frontend` | **Fuel & commodity-price importer** — historical + forward fuel prices (coal, gas, oil, uranium, biomass) plus carbon prices (EU ETS, K-ETS, RGGI) attached to the `carriers` sheet as `marginal_cost` (and `co2_price` on `global_constraints`). Sources: EIA/IEA retrospective averages, user's own futures snapshot for forward curves. | Fuel prices move the dispatch answer more than any other input; today users hand-type them from PDFs. Reuses the shipped BYOK key store. | 16,000 |
| `I6` | `In progress` | `High` | `Frontend` | **Hourly load & price (ENTSO-E / EIA-930)**. **Done:** hourly demand via `entsoe_load` (EU) and `eia_demand` (US). **Remaining:** the **day-ahead price** half — land it as a new `electricity_price` sheet keyed by snapshot for retrospective settlement analytics. | The demand half shipped; the price half is what retrospective settlement / PPA valuation needs against real spot. | 8,000 |
| `I7` | `Open` | `Med` | `Frontend` | **Capacity-factor / generation history (Ember / IEA)** — country-by-month / -year generation by carrier, for analytics calibration and as a fallback when hourly data is unavailable. | A cheap sanity check that catches order-of-magnitude model errors. Ember monthly data is CC-BY; IEA needs free registration. | 10,000 |
| `I8` | `Open` | `Med` | `Frontend` | **Policy & target snapshot** — NDC pledges, net-zero targets, RPS / CES levels, emission caps; per-country JSON from Climate Action Tracker / Climate Watch, dropped into `global_constraints` with provenance. | Automates the trajectory-to-constraint step for studies that bound expansion against an emissions path. Mostly open data. | 12,000 |
| `I9` | `Deferred` | `Med` | `Backend` | **PyPSA-Earth network builder (async job)** — for an arbitrary country, run PyPSA-Earth's `populate` workflow server-side and ingest the resulting network. A queued job with progress polling, its own conda env, cutout caching. Design in [`docs/pypsa-earth-integration.md`](pypsa-earth-integration.md). | Top-down complement to the per-source importers. Heavy: ERA5 cutouts (CDS key), Atlite compute, powerplantmatching/GADM/WDPA/GEBCO. **Deferred** — documented, not built. | 40,000 |

#### API-key infrastructure — SHIPPED (cross-cutting, powers I4–I8)

The BYOK per-user key store landed: dev-host `.env.local` seeds via `process.env.REACT_APP_RAGNAROK_*_KEY`; production users type keys into the **API-keys Settings panel** (`ApiKeys.tsx`) which writes `localStorage['ragnarok:secret:<name>']` / `sessionStorage`; resolver `src/lib/api/secrets.ts` walks `sessionStorage → localStorage → process.env` per fetch. Keys never leave the user's machine.

#### I4 design — renewable profile attachment model (for the remaining general importer)

A profile is `generators-p_max_pu`, so availability lives on the **generator**. Resolve the query point by a **fallback chain**: (1) generator's own `x`/`y` (imported fleet — WRI GPPD, OSM plants) → query there; (2) else its bus `x`/`y`; (3) else pin-on-map. Only attach to generators that already exist (the KPG193 rule — no orphan profiles). Snapshot alignment via **T1**. Sources: keyless **PVGIS / NASA POWER / Open-Meteo**, BYOK **Renewables.ninja** (rate-limited — cache via **D1**; redistribution license — fetch per-user, never bulk-cache).

### Transformation tools

Tools that transform an already-imported workbook between Data and Run.

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `T1` | `In progress` | `High` | `Both` | **Forecast tool / snapshot editor.** **Done:** bulk series transforms on temporal sheets — scale / offset / shift (wrap or edge-fill) / interpolate / clip / **grow** (demand-growth ramp), server-side via `POST /api/session/series/{name}/transform`, applied to all or a selected column subset from the Model/Build Transform control. **Remaining:** (a) **snapshot-window retarget** (calendar picker for new start/end + resolution; clip/pad imported series onto the new index) and (b) **multi-year forecast/extrapolation** (ARIMA / Prophet / CAGR to future years — the "remember 3" follow-on). | After importing series from different weather years, users need to retarget the window and project onto it. The per-series maths shipped; the snapshot-index editing + multi-year projection remain. | 12,000 |

### AI conversational interface — Bifrost

A new project wrapper (sibling to Mjolnir) that places an LLM chat interface in front of Ragnarok. The anti-hallucination principle: the LLM never answers directly — it builds a Ragnarok workbook, and the answer is the solver output, traceable to workbook cells + a HiGHS solve. Neither item exists in code yet.

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `L1` | `Open` | `High` | `Both` | **Bifrost — AI conversational model builder** — stand-alone project (React/TS chat shell + thin Python relay). The user asks a question; Bifrost runs an **agentic tool-use loop**, deciding which Ragnarok importer / schema tools to call to assemble a workbook (same JSON schema `POST /api/run` accepts), then lets the user **inspect** (hand to the Model/Build editor) or **run** (submit + stream the live analytics view). Data gaps are resolved by asking, not hallucinating. Recommended brain: **Claude Opus 4.8** (or **Sonnet 4.6**) via a thin relay reusing the shipped BYOK key store. Bifrost owns no solver / DB / editor — it delegates to Ragnarok. | LLM answers to energy questions are unverifiable; routing through a real PyPSA solve makes every conclusion falsifiable. Distinct from **W1** (a stepped UI wizard): same output via a free-text affordance. | 36,000 |
| `L2` | `Open` | `Medium` | `Both` | **Bifrost data-ask loop** — when a gap can't be filled from open data (private fleet, confidential topology), Bifrost asks the user to supply the rows directly (CSV paste / quick form / file), validated against the schema and merged before continuing. | Prevents silent gap-filling with hallucinated defaults. Depends on **L1**. | 12,000 |

### Guided workflows

Top-down surfaces that build a runnable workbook from high-level intent. (The existing **Build view** is a step-by-step *sheet* editor; W1/W2 build from *intent*.)

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `W1` | `Open` | `High` | `Both` | **Guided model-builder wizard** — a stepped flow (Region → Question → Time horizon → Scope → Constraints → Confidence-defaults) that composes the existing importers (`I1`, `I4`, …) + transforms (`T1`, `T2`) into a fully-populated, immediately-runnable workbook, with provenance flagging wizard-filled vs user-edited cells. | State your goal in plain language, get a model. The Data view is bottom-up (pick a database, pull rows); non-modellers can't navigate that. Zero new data-source code — it sequences what exists. | 32,000 |
| `W2` | `In progress` | `High` | `Both` | **Country starter models (per-country baseline packs)** — three-question landing (Country → Year → What to do) that emits a curated, immediately-runnable workbook from the best baseline for that (country, year). **Done:** the **KPG193 pack** is the working prototype for KOR (network + demand + renewable capacity/profile, loadable from the Welcome screen). **Remaining:** the per-country **recipe framework** (`starter_packs/<ISO3>/<year>/recipe.json`) that picks the best source per slot for arbitrary countries. | Top-down complement to the Data view: state country + year + question, get a model. KPG193 proves the shape; the generalisation to any country is the work. | 18,000 |
| `W3` | `Open` | `Medium` | `Frontend` | **Interactive in-app tutorial / guided tour** — a skippable, resumable coach-mark walkthrough of the core loop (build → edit → run → analyse), driven by a declarative step script, auto-offered once on first run. Runs against the bundled demo/example networks (already shipped — three solve-validated examples with a Welcome picker). | New users land in a dense five-view app with no guided path. Teaches the workflow in-context. Distinct from W1/W2 (build a model) — W3 teaches how to drive the tool. | 16,000 |

### Modelling extensions

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `M1` | `In progress` | `High` | `Both` | **Sector coupling** — multi-carrier buses + conversion Links (electrolyser, CCGT, heat pump, boiler, fuel cell, …). **Done:** ingestion of multi-carrier buses / Links / Stores (generic component path), the schema-driven Model/Build editors for them (incl. multi-port Links), **per-carrier energy-balance analytics** (`results/energy_balance.py` + card), correct **conversion emissions** (counted at the fuel generator at primary energy, efficiency-aware via **M3** — verified, no double-count), bus `carrier` settable in the Build form, and carrier filtering via the Pivot chart. **Remaining (polish):** carrier-aware filters baked into the map / dispatch-mix charts and non-geographic (CO₂/H₂) bus handling; technology defaults per conversion tech; sector-data importers (later). | The decarbonisation studies users want need >1 vector. The engine + core analytics shipped; what's left is chart-level carrier awareness and curated tech defaults. | 12,000 |

#### M1 remainder — what's left after the core shipped

The optimiser needs nothing (PyPSA does multi-carrier LP natively), the schema is complete, and the **per-carrier energy balance + emissions** now exist. Remaining app-layer polish: (1) carrier-aware **map / dispatch-mix** views (the energy-balance card is per-carrier, but the carrier-mix donut and map still lump vectors); (2) non-geographic carrier handling (abstract CO₂/H₂ buses with no x/y); (3) curated conversion-tech defaults (efficiency/capex/opex/lifetime) from a queryable source; (4) *(deferred)* sector-data importers (gas networks, heat/H₂ demand).

### Resource adequacy & robustness

Build on the shipped stochastic engine (`backend/pypsa/stochastic.py`) + the `load_shedding` unserved-energy signal. Neither item exists yet.

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `A1` | `Open` | `High` | `Both` | **Stochastic renewable profile generator** — an ensemble of synthetic wind/solar CF profiles from a base series, with a similarity/variability knob (target R² / RMSE / autocorrelation) preserving diurnal + seasonal shape. Feeds the shipped stochastic optimisation or a Monte-Carlo sweep, plus a robustness readout (objective / cost / curtailment / unserved-energy spread). | A model is solved against one weather year; users need sensitivity to renewable variability. Reuses the stochastic engine; produces the input ensemble for **A2**. | 18,000 |
| `A2` | `Open` | `High` | `Both` | **LOLE calculator** — resource-adequacy metrics from an ensemble (or analytic convolution): **LOLE** (h/yr), **LOLP** per snapshot, **EUE / EENS**, worst contributing periods, against the "1 day in 10 years" yardstick. Unserved energy is already observable via `load_shedding`. | Adequacy studies need the reliability metrics regulators use. Depends on **A1**; storage + **M2** demand response contribute to the result. | 16,000 |

### Run history

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `H2′` | `Open` | `Medium` | `Both` | **Pluggable result-mapper registry + raw-sheet surfacing** — the **core** of H2 shipped (`POST /api/import/result`). What remains: per-source-format **column-mapping rules in a small registry** (extendable via a `result_mapper` plugin hook) so arbitrary third-party result layouts map onto `outputs.{static,series}`, and **unrecognised sheets stored verbatim + surfaced as raw tables**. | Today's reconstruction handles Ragnarok's own schema + canonical bare workbooks; a true third-party layout needs a mapping layer. Do it when a real third-party format needs it. | 10,000 |

### Architecture

Cross-cutting platform direction (not single features). Assumes a dedicated backend server rather than a browser-resident app.

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `X1` | `In progress` | `Medium` | `Both` | **Backend-centric data processing (thin browser)** — move data processing + model lifecycle to the backend so the browser is a light view layer. **Done:** the stateful server-side session store (`backend/app/{model_store,sqlite_store,session_store}.py` + `/api/session/*`), server-held time-series with windowed/downsampled fetch, server-side Python plugin execution (`/api/plugins/*`), and light stored-run views. **Remaining:** porting `deriveRunResults` / chart-series derivation server-side, JS-plugin sandboxing/migration (**X5**), and full push/poll sync. | Large models make a browser-resident app heavy; the session-store direction shipped, the analytics-derivation port + plugin sandbox remain. | 30,000 |
| `X2` | `Open` | `Medium` | `Both` | **Data-import KPI computation → backend API** — move the remaining client-side analysis of imported data (`InputAnalyser.tsx` + in-browser KPI/statistics) to an endpoint; the frontend just renders. The import *preview* is already backend-computed. A concrete, low-risk slice of **X1**. | Keeps heavy per-row statistics off the main thread and centralises KPI definitions so they don't drift from the import preview. | 10,000 |
| `X6` | `Open` | `Medium` | `Both` | **Richer / clearer plugin output scheme** — extend the plugin contract beyond single-run, data-in/data-out: (a) declarative **composite host-rendered layouts** (chart grids with shared legend/settings); (b) **multiple runs / scenarios** as input (analytics-over-N-runs); (c) one crisp versioned contract. Keep "host owns rendering, no raw HTML/SVG". | The scenario-comparison matrix couldn't be a plugin (single-run + no custom layout). Generalising lets multi-run analytics ship as plugins. Pairs with **X1** / **X5**. | 20,000 |
| `X3` | `Open` | `Low` | `Both` | **Scenario library vs. run history — review.** Decide whether to slim/deprecate the in-model scenario library (`RAGNAROK_Scenarios` presets) or reposition it explicitly as "named run-config *presets*" distinct from History ("runs I actually executed"). A scoping decision, not a build. | History captures "what I ran" comprehensively, so the preset library is less load-bearing. | 4,000 |
| `X5` | `Low` | `Low` | `Frontend` | **Frontend-plugin Worker sandbox** — evaluate frontend-plugin JS in a Web Worker instead of in-page `new Function`; hooks become postMessage round-trips, `worker.terminate()` enforces a timeout. | The JS runtime is the weakest isolation point. Deferred while backend plugins absorb plugin workloads — build only if 3rd-party *frontend* plugins stay first-class. | 12,000 |

### Correctness & trust

What makes Ragnarok a *faithful* PyPSA frontend rather than just a feature-alike — see *North star* layer 5 (and layer 3 for diagnostics).

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `Q1` | `Open` | `High` | `Backend` | **PyPSA reference-parity test suite** — run PyPSA's own example networks plus a curated set covering unit commitment / multi-investment / storage / sector coupling / SCLOPF end-to-end through Ragnarok's build → solve → results path, and assert objective, dispatch, prices, and optimal capacities match native `n.optimize()` within tolerance. | The strongest "faithful frontend" guarantee: proves Ragnarok *reproduces* PyPSA, not just round-trips its files. Round-trip I/O is already tested; end-to-end result parity across features is not systematically pinned. | 18,000 |
| `Q2` | `Open` | `Medium` | `Both` | **Infeasibility & solver diagnostics** — when a solve is infeasible / unbounded / numerically ill, surface *why* (offending constraint group, per-bus energy-balance shortfall, suspect coefficient ranges) instead of a raw solver string, and suggest fixes (enable load shedding, relax a cap). | A proper frontend must *explain* failure, not just report it. Today an infeasible model returns a solver error with no self-diagnosis path. Pairs with the shipped `load_shedding` backstop. | 14,000 |

## Suggested execution order

Forward plan from 2026-07-01 (re-sequenced after the status audit — the financial/decision spine + modelling reach are done). Respecting cross-group dependencies.

> **If the goal is "a fully-available PyPSA frontend"**, follow the *North star* critical path first: **D1 → I4 → X1/X2 → W2 → Q1**. The theme-ordered list below is the fuller backlog; the near-term block leads with the pieces on that path.

**Recently shipped** (see *Already shipped* for detail): B1, F1, F2, PP1, DW1–DW4, M1 (core), M2, M3, B3, T2, statistics passthrough, MGA near-optimal, the strategic-pricing analytics tiers, and the bulk-transform half of T1.

**Near-term — finish the partials:**

1. **T1** — snapshot-window retarget + multi-year forecast (the remaining half; the transforms shipped).
2. **I6** — day-ahead price half (hourly load already shipped).
3. **M1** — carrier-aware map / dispatch-mix polish + conversion-tech defaults.

**Data & model-assembly layer:**

4. **D1** — weather/reanalysis caching layer (the registry half shipped).
5. **I4** — general coordinate-driven renewable importer (KPG193 profiles shipped).
6. **I3** — driver-based demand forecast · **I5** — fuel & commodity prices.
7. **I1** — one-location → one-model bootstrap orchestration (importer surface shipped).

**Risk & adequacy:**

8. **R1** — physical-climate-risk · **R2** — transition-risk (depends on F2 ✓).
9. **A1** — stochastic renewable ensemble → **A2** — LOLE calculator.

**Scale & trust (the "frontend-of-PyPSA" backbone):**

10. **X1 / X2** — thin-client: port analytics derivation server-side so 1000s-of-bus networks don't choke the browser (session store shipped).
11. **Q1** — PyPSA reference-parity test suite · **Q2** — infeasibility & solver diagnostics.

**Guided & conversational surfaces:**

12. **W2** — country starter-pack framework (KPG193 prototype shipped).
13. **W1** — guided model-builder wizard · **W3** — in-app tutorial (demo networks shipped).
14. **L1** — Bifrost AI model builder → **L2** — data-ask loop.

**Financial-decision surface:**

15. **PP2** — procurement optimizer, inside a dedicated use-case surface that also reframes PP1 + DW4 (deferred design decision).

**Off the linear path** (opportunistic, non-blocking): **B2** simulation adapter · **I7**/**I8** calibration/policy importers · **D2** self-hosted demand DB · **H2′** result-mapper registry · **X3**/**X5**/**X6** architecture / plugin-sandbox items · **B4** strategic MPEC (deferred) · **I9** PyPSA-Earth builder (deferred).

## Already shipped

Compact history of completed work, grouped by area. Kept so completed items are not re-proposed. Items marked with their original ID.

### Financial & decision layer

- **`B1` Merchant / price-taker optimisation** — `backend/pypsa/results/merchant.py`. Two-stage: stage-1 system LMP (`buses_t.marginal_price`) or a user-fixed price → reduced network of the owner's assets + a per-bus **price-taker market node** (Generator priced at π(t), `p_min_pu=-1` so it can sell *and* buy). Minimising `Σ mc·p + Σ π·p_market` = maximising owner profit. Runs on a `network.copy()` of the solved optimum. Card + preset row + tests.
- **`F1` Company / owner dimension** — `results/company.py`; per-owner KPIs (capacity, dispatch, revenue, emissions) grouped by a configurable **owner column** (default `owner`, free-text; drives F1/F2/B1). Synthetic `owner` schema column injected so the grid offers it. Company drill-down card.
- **`F2` Company-level financial model** — `results/finance.py`; NPV / IRR / payback / DSCR per owner. Reconstructs overnight capex from the annualised `capital_cost` via inverse CRF; IRR by bisection; optional debt config → DSCR.
- **`PP1` PPA contract modeler** — `results/ppa.py`; fixed-price PPA valued against the run LMP as a Contract-for-Difference (owner generation at bus LMP, or a flat block at mean price). Seller/buyer net, energy, capture vs strike. Card + tests. *(Full contract-shape / P50-P90 uncertainty depth is folded into the future use-case surface with PP2/DW4.)*
- **`DW1` Financial-first UX + use-case launcher** — `Decisions.tsx`; money-question cards that enable a workflow's config + route to setup; the Market tab's default landing.
- **`DW2` Asset-swap / repowering what-if** — `results/asset_swap.py`; retire a multi-filter selection, replace at a ratio (+ optional paired storage), re-solve, report Δemissions / Δcost / payback. Card + tests.
- **`DW3` ESS business-case builder** — `results/ess.py`; battery size sweep, arbitrage vs LMP → NPV/IRR/payback per size. Card + tests.
- **`DW4` PPA opportunity explorer** — `results/ppa_explorer.py`; ranks candidate PPA shapes (as-produced generation / flat block / peak block) by capture price at a given strike; companion to PP1 (reuses its config). Card + tests.
- **Market power & strategic pricing (analytics precursors to B4)** — price formation (`price_formation.py` — price vs residual demand, marginal carrier), unit commitment (`commitment.py` — starts / on-off), bid strategy (`bid_strategy.py` — raise owner offers, re-clear, profit vs price-taker), optimal single-owner bid (`optimal_bid.py` — markup sweep for best response). Each a card + test. Full oligopoly (endogenous prices) remains **B4**, deferred.
- **Market & Policy tab** — `SettingsView` `variant` split; technical settings vs a new top-level Market & Policy tab housing the ownership/market-behaviour sections.

### Optimisation & analytics modes

- Statistics passthrough (PyPSA `network.statistics()` card) and **MGA near-optimal** corridor (`optimize_mga`) — Phase 2.
- Single-period dispatch, multi-investment / pathway planning, rolling-horizon, stochastic (`stochastic.py`), security-constrained (SCLOPF).
- **`B3` Power-flow study mode** — `results/power_flow.py`; standalone `n.pf()`/`n.lpf()` (gated by `pf_enabled`) returning a focused payload (convergence, branch loading, voltage profile, losses, nodal balance). Section + card + tests.
- Backend abstraction layer (`backend/app/backends/`) — `Backend` protocol, registry, `PypsaBackend`, `GET /api/backends`.
- **`F0` Asset economics** — competitive-benchmark profit from the cost-min solve with no extra solve; per-generator/storage/carrier revenue, margin, capture price, capex recovery. `GeneratorEconomicsCard` + XLSX sheets + tests.

### Modelling extensions

- **`M3` Fuel system — efficiency-aware emissions & carbon** — `co2_emissions` treated on the primary-energy (fuel) basis: emissions and the carbon adder divide by generator `efficiency` (`utils/emissions.py::per_generator_emission_factor`), applied across all 12 emission-computation sites (carbon adder, DSL `emissions`, custom `co2_cap`, breakdown, company, asset-swap, stochastic, pathway, system-emissions series, carrier totals, cost-breakdown, imported-results). η=1 reproduces the old numbers. Tests in `test_fuel_efficiency.py`.
- **`M1` Sector coupling (core)** — per-carrier energy balance (`results/energy_balance.py`) + card; conversion emissions verified correct at the fuel generator (no double-count); multi-carrier ingestion + Model/Build editing. *Remaining polish tracked above.*
- **`M2` Demand response** — `network/demand_response.py`: **shiftable load** (DR bus + lossless Link + cyclic Store, energy-conserving) and **price-elastic demand** (stepped willingness-to-pay curve); per-load selection; analytics (`build_demand_response`, `build_price_elastic`) + cards. Tests in `test_demand_response.py`. *(The coarse per-bus `load_shedding` shed mode predates this.)*

### Transformation tools

- **`T2` Reduced-order / clustering tool** — `backend/app/routers/transforms.py`; spatial network reduction (greedy network-**modularity** clustering + **k-means** on bus x/y via scikit-learn), returns the reduced model + busmap for map preview. Surfaced in the **Forge** view ("Reduce network").
- **`T3` Component-to-bus reconciliation** — bulk **Snap to nearest bus** in Forge (`lib/forge/snap.ts`) + validation scanner; OSM import auto-snaps line endpoints.
- **`T1` (partial)** — server-side bulk series transforms (scale/offset/shift/interpolate/clip/grow) via `/api/session/series/{name}/transform` + Transform control. *Snapshot retarget + multi-year forecast remain (see Open work).*

### Data importers (framework + sources)

- Importer framework: source registry (`importers/registry.py`), per-database modules (`importers/databases/*`), region selection, combine/preview endpoints, Data view country-first surface, BYOK API-key store (`ApiKeys.tsx` + `secrets.ts`).
- Sources shipped: **OSM** grid topology + **OSM power plants**, **WRI GPPD** fleet, **World Bank** annual demand, **ENTSO-E** installed capacity, **ENTSO-E** hourly load, **EIA-930** hourly demand, **KPG193** Korea pack (network / demand profile / renewable capacity / renewable profile).

### Project exchange

- **`H1` Import-project decoupled from History** — "Import Project" opens a file (no persist); History comes only from a solve or the explicit `POST /api/import/result`.
- **`H2` (core) Import external results → History** — `POST /api/import/result` ingests a Ragnarok package verbatim or reconstructs analytics from a bare `.xlsx` (`from_outputs`), persists `origin="xlsx_import"`. Per-format mapper registry remains **H2′**.
- Pure-JSON project export/import; `deriveRunResults` rebuild on import; metadata sheets round-trip; HTML report export; CSV-folder / netCDF / HDF5 I/O. Round-trip test suites (frontend + backend).

### Analytics & UX

- Capacity-by-period chart; cross-scenario `ScenarioPivotCard`; carrier-level analytics card; load drill-down; ECharts pivot (SVG renderer load-bearing for Excel export); dashboard card system (kind + interface + case + label + conditional preset row); chart/card-type switching; constraints workspace overlay; adaptive time-axis; standard `line_types`/`transformer_types` typeahead.
- Bundled solve-validated **example networks** (three_bus / renewables_storage / capacity_expansion) with a Welcome-screen picker + `/api/examples` loader — the onboarding demo (W3 will teach against these).

### Data integrity

- ISO date normalisation at the import boundary (Date-format setting governs *parsing* only; canonical `YYYY-MM-DD`). Schema-driven validation across component + time-series sheets; backend dry-run mirrors the catalogue. Explicit `network` sheet import.

### Component result UX

- Full analytics: `buses`, `generators`, `lines`, `links`, `transformers`, `storage_units`, `stores`. Detail panels: `processes`, `shunt_impedances`. Round-tripped without dedicated UX: `carriers`, `global_constraints`, `line_types`, `transformer_types`, `shapes`, `sub_networks`.

### Plugin platform

- In-browser plugin runtime + server-side Python plugin execution (`/api/plugins/*`). SDK 2 (documented in `docs/plugin.md`): **`P1`** chart output, **`P2`** multi-select control, **`P3`** dynamic select options (`optionsFrom`). Plugins return data; the host owns rendering.

## Deliberately not pursued

- **Unifying the two plugin runtimes (`PluginDetail` vs `BackendPluginDetail`)** — duplication is managed; the thin-client direction (X1) resolves it by attrition.
- **Backend retention of solved `pypsa.Network`** — the run store persists results (History), not the network object; the JSON cache + `deriveRunResults` round-trip losslessly, so retaining the object buys nothing.
- **Separate "Topology" build mode** — the unified map-driven Build already folds in the free-form affordances.
- **PyPSA-Earth as a registered data source** (former `I2`) — it *produces* networks from upstream data; importing its output is just importing a PyPSA `.nc` (already covered by `POST /api/import/netcdf`).
- **PyPSA `technology-data` / OWID Energy as registered data sources** — static CSVs in git repos, not queryable databases (violates the "data only from a proper database" rule). Cost defaults will come from a queryable upstream or curated in-app.
- **OPSD `time_series_60min_singleindex.csv`** — a ~150 MB CSV, stops ~2020; replaced by the shipped ENTSO-E/EIA on-demand importers and tracked for a self-hosted cache under **D2**.
