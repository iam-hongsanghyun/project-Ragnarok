# Ragnarok TODO

Last updated: 2026-07-02 (full status re-audit against the codebase — B2, B4, I9 config-override, PP2 confirmed shipped and moved out of the open list; only genuinely-remaining work is listed below).

Single living todo for Ragnarok. **Open work lists only what is not yet done.** Completed and deliberately-dropped items are kept at the bottom in compact form so they are not re-proposed.

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
| **1. Data-in for arbitrary regions** (highest leverage) | fuel & carbon prices (**I5**), day-ahead price half (**I6**), driver-based demand (**I3**), calibration history (**I7**), one-click location→model (**I1**), self-hosted demand cache (**D2**), data-layer health/provenance (**D1**) | weather→renewable **done** (Open-Meteo/PVGIS/NASA + measured ENTSO-E/OpenElectricity/Elexon, multi-point, cached); any-country network **done** (PyPSA-Earth builder incl. per-request config); the price/demand/driver importers remain |
| **2. Feature-exposure polish** | full `n.statistics()` family + more duals, non-CO₂ global-constraint UI, chart-based **quadratic cost** authoring (**T4**), optional extra solvers | small gaps on a shipped core |
| **3. Usability for any user** | guided model wizard (**W1**), country starter framework (**W2**), in-app tour (**W3**), infeasibility / solver diagnostics (**Q2**) | demo networks + Build wizard shipped; these remain |
| **4. Scale & robustness** | thin-client for 1000s-of-bus networks — port analytics derivation server-side (**X1** / **X2**) | session-store backbone shipped; derivation port open |
| **5. Correctness & trust** | PyPSA reference-parity test suite (**Q1**) | round-trip I/O tested; end-to-end result parity not systematically pinned |

**Critical path** to "any PyPSA model, trusted, at scale": **X1 / X2** (handle large networks) → **W2** (get users to a runnable model fast) → **Q1** (prove parity with native PyPSA). The data-in layer's highest-leverage first cut (weather→renewable, any-country network) has shipped; fuel/price/demand importers are breadth on top. The per-group tables below hold the full remaining backlog; the *Suggested execution order* sequences it.

## Open work

**Only genuinely-open or partial items.** The financial/decision spine (B1, F1, F2, PP1, PP2, DW1–DW4), the market/strategic layer (**B2** simulation, **B4** strategic bidding, price-formation / unit-commitment / bid-strategy / optimal-bid analytics), the modelling-reach items (M1–M3, B3, T1–T3), and the data importers listed under *Already shipped* are all done — do not re-propose them.

### Data importers & platform

User-facing surfaces that bring data in, plus the infrastructure under them. **Substantial framework + sources already shipped** (see *Already shipped → Data importers*). What remains:

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `I5` | `Open` | `High` | `Frontend` | **Fuel & commodity-price importer** — historical + forward fuel prices (coal, gas, oil, uranium, biomass) plus carbon prices (EU ETS, K-ETS, RGGI) attached to the `carriers` sheet as `marginal_cost` (and `co2_price` on `global_constraints`). Sources: EIA/IEA retrospective averages, user's own futures snapshot for forward curves. | Fuel prices move the dispatch answer more than any other input; today users hand-type them from PDFs. Reuses the shipped BYOK key store. No fuel/price importer exists in code yet. | 16,000 |
| `I6` | `In progress` | `High` | `Frontend` | **Day-ahead price importer** — the *price* half of hourly load & price. Hourly **demand** is shipped (`entsoe_load`, `eia_demand`, `elexon_demand`, `openelectricity_demand`). **Remaining:** land day-ahead price as a new `electricity_price` sheet keyed by snapshot (ENTSO-E A44 reuses the existing client; Elexon makes GB price nearly free). | Retrospective settlement / PPA valuation needs real spot price; the demand half already shipped. No price importer / `electricity_price` sheet exists yet. | 8,000 |
| `I3` | `Open` | `High` | `Both` | **Driver-based demand forecast generator** — per-bus / per-region future demand profiles from drivers (population, GDP, electrification rate, weather sensitivity) with hourly reshaping for pathway runs. | Pathway runs need decade-spanning demand with an evolving *shape*. Distinct from **T1** (scales an existing series) — this derives a *new* shape from drivers. The World Bank importer fetches annual population/per-capita drivers but no hourly-shape generator exists. Depends on **D1** for driver datasets. | 24,000 |
| `I7` | `Open` | `Med` | `Frontend` | **Capacity-factor / generation history (Ember / IEA)** — country-by-month / -year generation by carrier, for analytics calibration and as a fallback when hourly data is unavailable. | A cheap sanity check that catches order-of-magnitude model errors. Ember monthly data is CC-BY; IEA needs free registration. No Ember/IEA importer exists. | 10,000 |
| `I1` | `In progress` | `High` | `Both` | **Location → runnable-model bootstrap** — the *one-click, one-location → complete runnable model* orchestration. **Done:** the Data-view country-first importer surface (pick a region → pull network / plants / demand / renewable profiles per source). **Remaining:** a single orchestration that composes those pulls into one runnable workbook (today the user pulls each source in turn). Overlaps **W1**/**W2**. | The integrated surface above the importers: one location selected → one runnable model. | 14,000 |
| `D1` | `In progress` | `High` | `Backend` | **Profile / weather data layer** — persistent storage, source registry, source-health checks, versioned provenance. **Done:** source registry + per-database module pattern; keyless Open-Meteo weather; **on-disk weather caching** (`openmeteo_renewable/cache.py`, `RAGNAROK_WEATHER_CACHE`). **Remaining:** source-health checks, versioned provenance, and a **general (multi-source) cache abstraction** beyond the Open-Meteo-specific one. | Owns caching, versioning, provenance, health for every external dataset. Weather caching exists; the general layer + health/provenance remain. | 8,000 |
| `D2` | `Open` | `High` | `Backend` | **Self-hosted historical hourly demand database** — Ragnarok-owned snapshot of EU + global hourly load, with a refresh process. On-demand hourly demand is already covered by the ENTSO-E/EIA-930 importers; D2 is the *self-hosted cached* alternative for scale / offline. | Fetch-per-user against ENTSO-E/EIA is rate-limited and network-bound; a per-country self-hosted slice (≈10 MB) lets the frontend fetch only what it needs. Not started. | 20,000 |

### Transformation & authoring tools

Tools that transform / author an already-imported workbook between Data and Run. (`T1` series transforms + retarget + forecast, `T2` clustering, `T3` snap-to-bus have shipped — see *Already shipped*.)

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `T4` | `Open` | `Med` | `Both` | **Chart-based quadratic marginal-cost editor** — an interactive editor to set PyPSA's `marginal_cost` (linear) + `marginal_cost_quadratic` (quadratic) across a *filtered selection*. Select by **carrier**, **component name**, and **multiple filters on any column** (reuse `FilterPanel`); target generators / storage_units / stores / links. The user **draws the cost curve on a chart** — click to place points, drag the curve / handles — over the output range (0 → `p_nom`); a **least-squares fit finds the closest quadratic** `C(p) = c₁·p + c₂·p²` (the PyPSA cost form; marginal cost `dC/dp = c₁ + 2c₂·p`) to the drawn points and writes `c₁ → marginal_cost`, `c₂ → marginal_cost_quadratic` onto every matched row via the session bulk-write path. Enforce convexity (`c₂ ≥ 0`) for a valid QP. The editor is a **single chart panel** over the filtered selection (confirmed 2026-07-02: a chart, **not** per-node editing on the map). | PyPSA supports convex quadratic generation cost (verified: `marginal_cost` + `marginal_cost_quadratic` on generators/storage_units/stores/links, PyPSA 1.2.4), but today users can only hand-type the two coefficients per row — no way to *see* the resulting curve, *set* it visually, or *apply* one curve to a whole filtered fleet at once. **Solver note:** quadratic terms make the solve a **QP** — needs a QP-capable solver (HiGHS/Gurobi); flag this in the UI. **Remaining scoping:** which axis the user draws — marginal-cost line (`c₁ + 2c₂·p`) vs. total-cost parabola (`c₁·p + c₂·p²`); either maps to (c₁, c₂), marginal-cost view is usually more intuitive for dispatch. Reuse points: `features/data/FilterPanel.tsx` (multi-column filter), ECharts `graphic` + `convertFromPixel` (draggable curve), `POST /api/session/...` bulk write. | 16,000 |

### Modelling extensions

(`M1` sector coupling, `M2` demand response, `M3` efficiency-aware emissions have shipped — see *Already shipped*.)

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `M4` | `Open` | `Med` | `Both` | **Spatially-mobile storage / EV mobility coupling** — model demand that is *energy physically relocating between regions*, not just power flowing along a fixed edge. An EV fleet charges in region A, drives to region B, and discharges (or is unavailable) there: the stored energy moves with the vehicles. Standard PyPSA Links move power along a static edge and Stores are pinned to one bus, so neither captures a *state of charge that migrates between buses on a mobility schedule*. Approaches to evaluate: (a) PyPSA-Eur's BEV/V2G pattern (per-region transport bus + electricity↔transport Link + battery Store with time-varying `e_max_pu` + a `p_set` mobility-demand series) — captures charging flexibility but **not** inter-region transfer; (b) an OD (origin–destination) mobility matrix realised as time-varying Links between regional EV-battery Stores; (c) a dedicated mobile-storage component with a bus-assignment time series. **Scope first** (pick a/b/c) — it touches ingestion, the schema, and analytics. | Ragnarok can model EV *charging load* per region today but cannot represent the *transport of stored energy between regions* — the battery that fills at home overnight and discharges at the workplace bus. Raised as a design question 2026-07-02; not started. | 20,000 |

### Risk modules

Climate-related exposure modules. Physical risk perturbs *inputs* (asset availability); transition risk perturbs *outputs* (financial-model assumptions). Neither exists in code yet (confirmed by audit).

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `R1` | `Open` | `High` | `Both` | **Physical-climate-risk module** — score assets against heat / drought / flood / storm / wildfire hazard layers tied to location and operating envelope; feed the result back into the model as availability / derate time series. | Thermal, hydro, transmission, and renewables all have location-dependent physical exposure that changes under climate change. Pathway runs currently assume historical availability for every future period. | 26,000 |
| `R2` | `Open` | `High` | `Both` | **Transition-risk module** — apply carbon-price trajectories, demand shocks, policy pathways, and stranded-asset assumptions to the company-level financial model. | Today's carbon-price input is a single number (or a year→price schedule); transition-risk needs trajectories + policy pathways evaluated against each company's portfolio so stranded-asset and revenue-at-risk exposure is visible over the horizon. Depends on **F2** (shipped). | 22,000 |

### Resource adequacy & robustness

Build on the shipped stochastic engine (`backend/pypsa/stochastic.py`, a stochastic *optimiser*) + the `load_shedding` unserved-energy signal. Neither item below exists yet (confirmed by audit).

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `A1` | `Open` | `High` | `Both` | **Stochastic renewable profile generator** — an ensemble of synthetic wind/solar CF profiles from a base series, with a similarity/variability knob (target R² / RMSE / autocorrelation) preserving diurnal + seasonal shape. Feeds the shipped stochastic optimisation or a Monte-Carlo sweep, plus a robustness readout. | A model is solved against one weather year; users need sensitivity to renewable variability. `stochastic.py` is the *optimiser* — it needs an input *ensemble*, which A1 produces (input to **A2**). | 18,000 |
| `A2` | `Open` | `High` | `Both` | **LOLE calculator** — resource-adequacy metrics from an ensemble (or analytic convolution): **LOLE** (h/yr), **LOLP** per snapshot, **EUE / EENS**, worst contributing periods, against the "1 day in 10 years" yardstick. Unserved energy is already observable via `load_shedding`. | Adequacy studies need the reliability metrics regulators use. Depends on **A1**; storage + **M2** demand response contribute. | 16,000 |

### Guided & conversational surfaces

Top-down surfaces that build a runnable workbook from high-level intent, and the AI wrapper. (The **Build view** is a step-by-step *sheet* editor; these build from *intent*.)

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `W2` | `In progress` | `High` | `Both` | **Country starter models** — three-question landing (Country → Year → What to do) emitting a curated, immediately-runnable workbook. **Done:** the **KPG193 pack** (KOR) loadable from Welcome. **Remaining:** the per-country **recipe framework** (`starter_packs/<ISO3>/<year>/recipe.json`) that picks the best source per slot for arbitrary countries. | Top-down complement to the Data view. KPG193 proves the shape; generalising to any country is the work. | 18,000 |
| `W1` | `Open` | `High` | `Both` | **Guided model-builder wizard** — a stepped flow (Region → Question → Time horizon → Scope → Constraints → Confidence-defaults) that composes the existing importers + transforms into a fully-populated, immediately-runnable workbook, with provenance flagging wizard-filled vs user-edited cells. | State your goal in plain language, get a model. The Data view is bottom-up; non-modellers can't navigate that. Zero new data-source code — it sequences what exists. | 32,000 |
| `W3` | `Open` | `Med` | `Frontend` | **Interactive in-app tutorial / guided tour** — a skippable, resumable coach-mark walkthrough of the core loop (build → edit → run → analyse), driven by a declarative step script, auto-offered on first run. Runs against the bundled demo/example networks (shipped). | New users land in a dense multi-view app with no guided path. Teaches the workflow in-context. Distinct from W1/W2 (build a model). | 16,000 |
| `L1` | `Open` | `High` | `Both` | **Bifrost — AI conversational model builder** — stand-alone project (React/TS chat shell + thin Python relay). The user asks a question; Bifrost runs an **agentic tool-use loop** deciding which Ragnarok importer / schema tools to call to assemble a workbook (same JSON schema `POST /api/run` accepts), then lets the user inspect or run. Data gaps are resolved by asking, not hallucinating. Brain: **Claude Opus 4.8** (or **Sonnet 4.6**) via a thin relay reusing the BYOK key store. Bifrost owns no solver / DB / editor — it delegates to Ragnarok. | LLM answers to energy questions are unverifiable; routing through a real PyPSA solve makes every conclusion falsifiable. Not started. | 36,000 |
| `L2` | `Open` | `Med` | `Both` | **Bifrost data-ask loop** — when a gap can't be filled from open data (private fleet, confidential topology), Bifrost asks the user to supply rows directly (CSV paste / quick form / file), validated against the schema and merged before continuing. Depends on **L1**. | Prevents silent gap-filling with hallucinated defaults. | 12,000 |

### Architecture

Cross-cutting platform direction (not single features). Assumes a dedicated backend server rather than a browser-resident app.

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `X1` | `In progress` | `Medium` | `Both` | **Backend-centric data processing (thin browser)**. **Done:** the stateful server-side session store (`model_store` / `sqlite_store` / `session_store` + `/api/session/*`), server-held time-series with windowed/downsampled fetch, server-side Python plugins, light stored-run views. **Remaining:** porting `deriveRunResults` / chart-series derivation server-side (still in `lib/results/runResults.ts`), JS-plugin sandboxing (**X5**), full push/poll sync. | Large models make a browser-resident app heavy; the session-store direction shipped, the analytics-derivation port remains. | 30,000 |
| `X2` | `Open` | `Medium` | `Both` | **Data-import KPI computation → backend API** — move the remaining client-side analysis of imported data (`InputAnalyser.tsx` in-browser KPI/statistics) to an endpoint; the frontend just renders. The import *preview* is already backend-computed. A concrete, low-risk slice of **X1**. | Keeps heavy per-row statistics off the main thread and centralises KPI definitions. | 10,000 |
| `X6` | `Open` | `Medium` | `Both` | **Richer / clearer plugin output scheme** — extend the plugin contract: (a) declarative **composite host-rendered layouts** (chart grids with shared legend/settings); (b) **multiple runs / scenarios** as input (analytics-over-N-runs); (c) one crisp versioned contract. Grid `inputLayout`/`outputLayout` exists; multi-run + composite layouts remain. Keep "host owns rendering, no raw HTML/SVG". | The scenario-comparison matrix couldn't be a plugin (single-run + no custom layout). Pairs with **X1** / **X5**. | 20,000 |
| `X3` | `Open` | `Low` | `Both` | **Scenario library vs. run history — review.** Decide whether to slim/deprecate the in-model scenario library (`RAGNAROK_Scenarios` presets) or reposition it explicitly as "named run-config presets" distinct from History. A scoping decision, not a build. | History captures "what I ran" comprehensively, so the preset library is less load-bearing. | 4,000 |
| `X5` | `Low` | `Low` | `Frontend` | **Frontend-plugin Worker sandbox** — evaluate frontend-plugin JS in a Web Worker instead of in-page `new Function` (still the case in `lib/plugins/runtime.ts`); hooks become postMessage round-trips, `worker.terminate()` enforces a timeout. | The JS runtime is the weakest isolation point. Deferred while backend plugins absorb plugin workloads. | 12,000 |

### Correctness & trust

What makes Ragnarok a *faithful* PyPSA frontend rather than just a feature-alike — see *North star* layer 5 (and layer 3 for diagnostics). Neither exists yet (confirmed by audit).

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `Q1` | `Open` | `High` | `Backend` | **PyPSA reference-parity test suite** — run PyPSA's own example networks plus a curated set (unit commitment / multi-investment / storage / sector coupling / SCLOPF) end-to-end through Ragnarok's build → solve → results path, and assert objective, dispatch, prices, and optimal capacities match native `n.optimize()` within tolerance. | The strongest "faithful frontend" guarantee: proves Ragnarok *reproduces* PyPSA, not just round-trips its files. Round-trip I/O is tested; end-to-end result parity is not systematically pinned. | 18,000 |
| `Q2` | `Open` | `Medium` | `Both` | **Infeasibility & solver diagnostics** — when a solve is infeasible / unbounded / numerically ill, surface *why* (offending constraint group, per-bus energy-balance shortfall, suspect coefficient ranges) and suggest fixes (enable load shedding, relax a cap), instead of a raw solver string. | A proper frontend must *explain* failure, not just report it. Pairs with the shipped `load_shedding` backstop. | 14,000 |

### Run history

| ID | Status | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---|---:|
| `H2′` | `Open` | `Medium` | `Both` | **Pluggable result-mapper registry + raw-sheet surfacing** — the **core** of H2 shipped (`POST /api/import/result`). What remains: per-source-format **column-mapping rules in a small registry** (extendable via a `result_mapper` plugin hook) so arbitrary third-party result layouts map onto `outputs.{static,series}`, and **unrecognised sheets stored verbatim + surfaced as raw tables**. | Today's reconstruction handles Ragnarok's own schema + canonical bare workbooks; a true third-party layout needs a mapping layer. Do it when a real third-party format needs it. | 10,000 |

## Suggested execution order

Forward plan from 2026-07-02 (re-sequenced after the full status re-audit). Respecting cross-group dependencies.

> **If the goal is "a fully-available PyPSA frontend"**, follow the *North star* critical path first: **X1/X2 → W2 → Q1**. The data-in first cut (weather→renewable, any-country network) has shipped; the theme-ordered list below is the fuller backlog.

**Scale & trust (the "frontend-of-PyPSA" backbone — next on the critical path):**

1. **Q1** — PyPSA reference-parity test suite · **Q2** — infeasibility & solver diagnostics.
2. **X1 / X2** — thin-client: port analytics derivation server-side so 1000s-of-bus networks don't choke the browser (session store shipped).

**Data & model-assembly layer:**

3. **I6** — day-ahead price half (Elexon makes GB price nearly free; ENTSO-E A44 reuses the existing client).
4. **I5** — fuel & commodity prices · **I1** — one-location → one-model bootstrap orchestration.
5. **I3** — driver-based demand forecast · **I7** — calibration history · **D1** remaining (health/provenance/general cache) · **D2** self-hosted demand DB.

**Authoring & modelling:**

6. **T4** — chart-based quadratic marginal-cost editor (the near-term ask, 2026-07-02).
7. **M4** — EV / spatially-mobile storage (scope a/b/c first).

**Risk & adequacy:**

8. **R1** — physical-climate-risk · **R2** — transition-risk (depends on F2 ✓).
9. **A1** — stochastic renewable ensemble → **A2** — LOLE calculator.

**Guided & conversational surfaces:**

10. **W2** — country starter-pack framework (KPG193 prototype shipped).
11. **W1** — guided model-builder wizard · **W3** — in-app tutorial.
12. **L1** — Bifrost AI model builder → **L2** — data-ask loop.

**Off the linear path** (opportunistic, non-blocking): **I7** calibration importer · **H2′** result-mapper registry · **X3** / **X5** / **X6** architecture & plugin-sandbox items.

## Already shipped

Compact history of completed work, grouped by area. Kept so completed items are not re-proposed. Items marked with their original ID.

### Financial & decision layer

- **`B1` Merchant / price-taker optimisation** — `results/merchant.py`. Two-stage: stage-1 system LMP (or user-fixed price) → reduced network of the owner's assets + a per-bus **price-taker market node** (Generator at π(t), `p_min_pu=-1` so it can sell *and* buy). Minimising `Σ mc·p + Σ π·p_market` = maximising owner profit. Runs on a `network.copy()` of the solved optimum. Card + preset + tests.
- **`F1` Company / owner dimension** — `results/company.py`; per-owner KPIs grouped by a configurable **owner column** (default `owner`, free-text; drives F1/F2/B1). Synthetic `owner` schema column injected. Drill-down card.
- **`F2` Company-level financial model** — `results/finance.py`; NPV / IRR / payback / DSCR per owner. Overnight capex reconstructed from annualised `capital_cost` via inverse CRF; IRR by bisection; optional debt → DSCR.
- **`PP1` PPA contract modeler** — `results/ppa.py`; fixed-price PPA valued against the run LMP as a Contract-for-Difference. Card + tests.
- **`PP2` Procurement strategy optimizer** — `app/procurement.py` + `routers/procurement.py`; CVaR-constrained (Rockafellar–Uryasev LP via scipy/HiGHS) least-cost instrument mix (spot + PPA + forward + retail) over bootstrapped price scenarios; optimal mix + spot baseline + cost-vs-risk efficient frontier. Stateless `POST /api/procurement/optimize`. Frontend = the dedicated **Post-analysis** use-case surface (`Procurement.tsx`) with a risk-budget slider + inline frontier plot. 7 tests.
- **`DW1` Financial-first UX + use-case launcher** — `Decisions.tsx`; money-question cards that enable a workflow's config + route to setup (cross-tab aware).
- **`DW2` Asset-swap / repowering what-if** — `results/asset_swap.py`; retire a multi-filter selection, replace at a ratio (+ optional paired storage), re-solve, report Δemissions / Δcost / payback. Card + tests.
- **`DW3` ESS business-case builder** — `results/ess.py`; battery size sweep, arbitrage vs LMP → NPV/IRR/payback per size. Card + tests.
- **`DW4` PPA opportunity explorer** — `results/ppa_explorer.py`; ranks candidate PPA shapes by capture price at a given strike. Card + tests.
- **`B2` Market simulation adapter** — `results/simulation.py` (`run_market_simulation` + `run_market_sim_study`), gated in `run_pypsa` as a study mode (`market_sim_enabled`, short-circuits before `optimize()`). Rule-based merit-order clearing: uniform vs pay-as-bid settlement, VOLL scarcity, storage price-quantile arbitrage. Frontend Market-simulation section + `MarketSimulationCard`. 10 tests.
- **`B4` Strategic price-maker bidding** — `results/strategic.py` (`build_strategic_bidding`); best-response sweep over the B2 simulator (bid adder or capacity withholding), profits at true marginal cost, optional two-owner alternating best-response (≈ Nash). Rides the B2 study payload (`marketSimConfig.strategic`). `StrategicBiddingCard`. 6 tests. *(The old "MPEC/bilevel" framing was overkill — on single-zone merit order it reduces to a best-response search.)*
- **Market-power analytics precursors** — price formation (`price_formation.py`), unit commitment (`commitment.py`), bid strategy (`bid_strategy.py`), optimal single-owner bid (`optimal_bid.py`). Each a card + test.
- **Tabs = SettingsView variants** — `variant` ∈ {settings, market, analysis}: technical **Settings**; **Market & Policy** (solve-inputs: asset swap, ESS, carbon, constraints); **Post-analysis** (reads results, no re-solve: Decisions launcher, procurement, company, merchant, bidding, PPA). ActivityBar line-icons + hover tooltips; cross-tab launcher navigation.

### Optimisation & analytics modes

- Statistics passthrough (`network.statistics()` card) and **MGA near-optimal** corridor (`optimize_mga`).
- Single-period dispatch, multi-investment / pathway planning, rolling-horizon, stochastic (`stochastic.py`), security-constrained (SCLOPF).
- **`B3` Power-flow study mode** — `results/power_flow.py`; standalone `n.pf()`/`n.lpf()` (gated by `pf_enabled`). Section + card + tests.
- Backend abstraction layer (`backend/app/backends/`) — `Backend` protocol, registry, `PypsaBackend`, `GET /api/backends`. *(B2/B4 deliberately use the study-mode gate, not this adapter seam.)*
- **`F0` Asset economics** — competitive-benchmark profit from the cost-min solve with no extra solve. `GeneratorEconomicsCard` + XLSX sheets + tests.

### Modelling extensions

- **`M3` Efficiency-aware emissions & carbon** — `co2_emissions` on the primary-energy (fuel) basis: emissions and the carbon adder divide by generator `efficiency` (`utils/emissions.py`), applied across all 12 emission-computation sites. η=1 reproduces the old numbers. `test_fuel_efficiency.py`.
- **`M1` Sector coupling** — per-carrier energy balance (`results/energy_balance.py`) + card; conversion emissions correct at the fuel generator (no double-count); multi-carrier ingestion + Model/Build editing; **conversion-template library** (`lib/build/conversions.ts` + ConversionPicker); **carrier-aware dispatch mix** (`results/dispatch.py::electricity_dispatch_by_carrier`). *Minor remaining: non-geographic (CO₂/H₂) bus map rendering for hand-made carrier buses; sector-data importers — both deferred, low value.*
- **`M2` Demand response** — `network/demand_response.py`: shiftable load (DR bus + lossless Link + cyclic Store) and price-elastic demand (stepped WTP curve); per-load selection; analytics + cards. `test_demand_response.py`.

### Transformation tools

- **`T1` Forecast tool / snapshot editor** — bulk series transforms (scale/offset/shift/interpolate/clip/grow) via `POST /api/session/series/{name}/transform`; **snapshot retarget** (`/snapshots/retarget`); **multi-year forecast** (`/snapshots/forecast`) with five methods (CAGR / linear / regression / ARIMA / Prophet — `timeseries.py::STAT_METHODS`). Surfaced in Forge → Temporal.
- **`T2` Reduced-order / clustering** — `routers/transforms.py`; spatial reduction (modularity clustering + k-means on bus x/y), returns reduced model + busmap. Forge "Reduce network".
- **`T3` Component-to-bus reconciliation** — bulk **Snap to nearest bus** in Forge (`lib/forge/snap.ts`) + validation scanner; OSM import auto-snaps line endpoints.

### Data importers (framework + sources)

- Importer framework: source registry (`importers/registry.py`), per-database modules (`importers/databases/*`), region selection, combine/preview endpoints, Data view country-first surface, BYOK API-key store (`ApiKeys.tsx` + `secrets.ts` — resolver walks sessionStorage → localStorage → process.env; keys never leave the machine).
- Sources shipped: **OSM** grid topology + power plants, **WRI GPPD** fleet, **World Bank** annual demand, **ENTSO-E** hourly load + installed capacity + **measured renewable profiles** (`entsoe_generation_profile`, A75÷A68), **EIA-930** hourly demand, **OpenElectricity** (AU, BYOK — demand + measured renewable), **Elexon** (GB, keyless — demand + measured renewable), **KPG193** Korea pack (network / demand / renewable capacity / renewable profile), **Open-Meteo / PVGIS / NASA POWER** keyless weather → renewable CF (any coordinate, multi-point, UTC-offset, on-disk cache), **Renewables.ninja** validated CF (BYOK, live-only per licence).
- **`I4` Renewable resource profile importer** — the weather + measured-profile sources above + the **attach-to-existing-fleet transform** (`POST /api/transform/renewable-profiles`, own x/y → bus x/y, fetch once per 0.1° cell) + on-disk caching. *Minor remaining: hydro-inflow (`storage_units-inflow`).*
- **`I8` Policy & target snapshot** — `climatewatch_policy` importer; baseline emissions from Climate Watch's keyless API, trajectory (target year + % reduction) → one `primary_energy`/`co2_emissions` global constraint with provenance.
- **`I9` PyPSA-Earth network builder (async job)** — `routers/pypsa_earth.py`: build queue + poll + result + availability, gated behind `RAGNAROK_PYPSA_EARTH_DIR`; **per-request config override** (`_build_overlay` writes `countries=[iso2]`, clusters, cost year → `ragnarok_config_{iso2}.yaml`, passed via `--configfile`); `ingest_network()` → `serialize.network_to_model`; Data-tab frontend panel; setup script. *Only external ops remain (host conda env + CDS key + cutout cache — cannot live in this repo).*

### Project exchange

- **`H1` Import-project decoupled from History** — "Import Project" opens a file (no persist); History comes only from a solve or explicit `POST /api/import/result`.
- **`H2` (core) Import external results → History** — `POST /api/import/result` ingests a Ragnarok package verbatim or reconstructs analytics from a bare `.xlsx`, persists `origin="xlsx_import"`. Per-format mapper registry remains **H2′**.
- Pure-JSON project export/import; `deriveRunResults` rebuild on import; metadata sheets round-trip; HTML report export; CSV-folder / netCDF / HDF5 I/O. Round-trip test suites.

### Analytics & UX

- Capacity-by-period chart; cross-scenario `ScenarioPivotCard`; carrier-level card; load drill-down; ECharts pivot (SVG renderer load-bearing for Excel export); dashboard card system (kind + interface + case + label + conditional preset row); chart/card-type switching; constraints workspace overlay; adaptive time-axis; standard `line_types`/`transformer_types` typeahead.
- Bundled solve-validated **example networks** (three_bus / renewables_storage / capacity_expansion) with a Welcome picker + `/api/examples` loader.

### Data integrity

- ISO date normalisation at the import boundary (Date-format setting governs *parsing* only; canonical `YYYY-MM-DD`). Schema-driven validation across component + time-series sheets; backend dry-run mirrors the catalogue. Explicit `network` sheet import.

### Component result UX

- Full analytics: `buses`, `generators`, `lines`, `links`, `transformers`, `storage_units`, `stores`. Detail panels: `processes`, `shunt_impedances`. Round-tripped without dedicated UX: `carriers`, `global_constraints`, `line_types`, `transformer_types`, `shapes`, `sub_networks`.

### Plugin platform

- In-browser plugin runtime + server-side Python plugin execution (`/api/plugins/*`). SDK 2 (`docs/plugin.md`): chart output, multi-select control, dynamic select options, grid `inputLayout`/`outputLayout`. Plugins return data; the host owns rendering.

## Deliberately not pursued

- **Unifying the two plugin runtimes (`PluginDetail` vs `BackendPluginDetail`)** — duplication is managed; the thin-client direction (X1) resolves it by attrition.
- **Backend retention of solved `pypsa.Network`** — the run store persists results (History), not the network object; the JSON cache + `deriveRunResults` round-trip losslessly.
- **Separate "Topology" build mode** — the unified map-driven Build already folds in the free-form affordances.
- **PyPSA-Earth as a registered data source** (former `I2`) — it *produces* networks; importing its output is just importing a PyPSA `.nc` (already covered by `POST /api/import/netcdf`).
- **PyPSA `technology-data` / OWID Energy as registered data sources** — static CSVs in git repos, not queryable databases. Cost defaults will come from a queryable upstream or curated in-app.
- **OPSD `time_series_60min_singleindex.csv`** — a ~150 MB CSV, stops ~2020; replaced by the shipped ENTSO-E/EIA on-demand importers, tracked for a self-hosted cache under **D2**.
