# Ragnarok TODO

Last updated: 2026-06-24

Single living todo for Ragnarok. Open work is grouped below by theme. Completed and deliberately-dropped items are kept at the bottom in compact form so they are not re-proposed.

## Scales

- **Status** — `Open` / `In progress` / `Done` / `Not Needed`.
- **Priority** — `Critical` / `High` / `Medium` / `Low`.
- **Surface** — `Frontend` / `Backend` / `Both`.
- **Cost** — rough implementation budget for one focused coding pass (reading, patching, verification, light docs). Not a calendar estimate.

## Open work

Forty-two items across fourteen groups. Each group is internally coherent (shared infrastructure, schema, or interfaces); cross-group dependencies are called out in the *Why* column.

### Backend adapters

Adapters that plug into the existing `Backend` protocol (`backend/app/backends/`). PyPSA cost-min is the default; each item below is an additional adapter selectable by `options.backend`.

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---:|
| `B1` | `High` | `Both` | **Merchant / price-taker optimisation** — asset-owner adapter that maximises one owner's profit (NPV of dispatch + investment) against an **exogenous price signal**: either user-supplied or taken from a stage-1 system cost-min run (`buses_t.marginal_price`). Stays a single-level LP/MILP on the existing **PyPSA + linopy + HiGHS** stack via `extra_functionality` (a market node priced at `−p(t)`, or a custom linear objective term — the same hook custom constraints already use; note carbon pricing is no longer in this hook — it became a build-time `marginal_cost` adder in v3.4.0). Genuinely non-trivial for storage / hydro / unit-commitment and for build-vs-retire timing; degenerate (a threshold rule) only for an unconstrained single asset. | Current solve answers *least-cost for the whole system*; investor / IPP / merchant use-cases need *most-profitable for this owner*. The two-stage form (system price → owner optimises against it) is the standard merchant-investor model and feeds **F2** directly. Foundation for **F1**, **F2**. Does **not** model market power — that is **B4**. | 24,000 |
| `B2` | `High` | `Both` | **Simulation adapter** — non-optimisation. Given dispatch rules / bids / prices, step the system through the horizon and report flows, prices, and revenues. | Take a fixed strategy or operating rule and simulate the outcome under a chosen market structure. Different from **B3** (steady-state network analysis, not time-stepped market simulation). | 30,000 |
| `B3` | `Medium` | `Both` | **Power-flow-only study mode** — non-optimisation `network.pf()` / `network.lpf()` workflow with its own UI surface. | Steady-state network-analysis use case that pairs with the optimiser / simulator pair (**B1**, **B2**). Currently `Not supported` in the README support matrix. | 16,000 |
| `B4` | `Low` | `Both` | **Strategic / price-maker optimisation (deferred)** — endogenous prices where the owner's bids move the clearing price (market power, capacity withholding). A **bilevel / MPEC** problem (lower-level market clearing reformulated via KKT + complementarity) that PyPSA's single-level LP **cannot express**; needs a hand-built linopy / pyomo / gurobipy model (MILP via SOS1) or an iterative equilibrium solver — a different stack, not an adapter over PyPSA. Research-grade and data-hungry (requires rivals' cost curves). | The only flavour of profit-max that captures market power, i.e. *strategic* decision-making per company. Separated from **B1** because it is a different problem class and a different solver stack. **Deferred** — documented, not built. | 40,000 |

### Financial model

Items that turn dispatch / capacity-expansion results into investor- and company-level financial metrics. **Revenue signal:** the *competitive-benchmark* revenue/profit comes from **F0** (shipped — see *Already shipped → Analytics & UX*); the *strategic / exogenous-price* revenue comes from **B1**.

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---:|
| `F1` | `High` | `Both` | **Company / owner dimension** — `owner` attribute on generators / storage / lines / stores, schema-driven through workbook I/O, with per-company KPIs (capacity, dispatch, revenue, emissions) and a company drill-down view in Analytics. | Components have no owner field today, so every analytics surface treats the system as one consolidated entity. Bridges dispatch results to **F2**. | 22,000 |
| `F2` | `High` | `Both` | **Company-level financial model** — per-owner cashflow, revenue, opex, capex, debt service, IRR / NPV / DSCR / payback over the modelled horizon, driven by dispatch + capacity-expansion results. | Investors need project- and company-finance metrics, not raw revenue. Makes the tool usable for infrastructure investors and corporate planners. Required input to **R2**. Revenue inputs: **F0** (competitive benchmark, shipped) and/or **B1** (merchant / strategic). | 26,000 |

### Power procurement

Tools for buyers — corporates, utilities, large industrials — who need to procure electricity rather than dispatch assets. The distinction from the **Financial model** group: those items (F1/F2) look at the system or asset *owner's* economics; these items look at the *buyer's* exposure, contract strategy, and cost. Depends on the dispatch / price signal from Ragnarok runs (or an exogenous price series) as the spot reference.

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---:|
| `PP1` | `High` | `Both` | **PPA contract modeler** — model a bilateral power purchase agreement between a generator (seller) and a corporate or utility buyer. Contract parameters: volume (flat-block MW, load-following, or shaped profile), price formula (fixed €/MWh, hub-indexed ± basis, Contract-for-Difference strike vs spot), delivery point, term, settlement frequency, and collar / cap / floor optionality. For a given Ragnarok dispatch run the tool computes: contract revenue / cost stream per period, mark-to-market value vs spot, financial settlement (net vs physical), and P50/P90 cost under price uncertainty (using the stochastic engine or a price-scenario fan). Seller and buyer views switchable — the same contract is modelled from both sides. | Corporate buyers face growing pressure to procure directly from renewables (RE100, Scope-2 accounting, grid tariff hedging). Today there is no way to attach a contract to a generator in Ragnarok and evaluate whether the agreed price covers the dispatch cost or whether the buyer is over/under-hedged. PPA analytics closes that gap. Pairs with **F2** (seller's project finance) and **B1** (dispatch optimisation that informs the seller's offer curve). | 24,000 |
| `PP2` | `High` | `Both` | **Procurement strategy optimizer** — given a buyer's load profile and a menu of available instruments (spot exposure, one or more fixed-price PPAs, futures / forward contracts, retail tariff, self-supply), find the portfolio mix that minimises expected annual energy cost subject to a price-risk budget (e.g. CVaR constraint on total spend at a chosen confidence level). Uses `buses_t.marginal_price` from a Ragnarok solve (or a user-supplied price series) as the spot reference. Outputs: optimal contract volumes per instrument, efficient frontier (cost vs risk), sensitivity to price assumptions and load growth. | Large buyers typically manage a mix of spot, PPA, and hedging instruments but size them by rules-of-thumb rather than optimisation. A CVaR-constrained LP over the instrument menu finds the cheapest risk-adjusted portfolio and shows the trade-off curve. Natural follow-on to **PP1** (which models a single PPA) and to **B1** / **F2** on the seller's side. | 22,000 |

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
| `I4` | `High` | `Both` | **Renewable resource profile importer** — fetch wind / solar / hydro-inflow capacity-factor series for a location and land them as `generators-p_max_pu`. **The generator is the anchor** (availability is per-generator in PyPSA): query at each renewable generator's coordinate, fall back to its bus coordinate, attach only to generators that exist. Three entry points: (a) attach to the existing fleet by location, (b) polygon / buffer region select → attach to all generators inside / nearest, (c) pin-on-map to *create* a generator for siting. Sources: keyless **PVGIS / NASA POWER / Open-Meteo** plus **Renewables.ninja** (per-user key — now unblocked by the API-keys panel). See the *I4 design* note below. | Wind / solar capacity factors vary inside a country; a single national profile is too coarse for siting. Coordinate-driven attachment + snapshot alignment (via **T1**) puts the right shape on the right asset with no manual pinning for imported fleets. Depends on **D1** for cached weather / atlite outputs; reuses the shipped haversine snap. | 22,000 |
| `I5` | `High` | `Frontend` | **Fuel & commodity-price importer** — historical and forward fuel prices (coal, gas, oil, uranium, biomass) plus carbon prices (EU ETS, K-ETS, RGGI, etc.) attached to the workbook's `carriers` sheet as `marginal_cost` (and `co2_price` on `global_constraints`). Multiple upstreams: EIA / IEA for retrospective monthly averages, the user's own front-month futures snapshot for forward curves. | Optimisation is dispatch-cost-driven and fuel prices move the answer more than any other input. Today users hand-type these into the carriers sheet from PDFs. **I5** lets them import historical → present in one click and attach a forward curve where one exists. EIA's series API needs an API key; commodity / futures sources are mostly behind paywalls and read from the user's own session. | 16,000 |
| `I6` | `High` | `Frontend` | **Hourly load & price (ENTSO-E / EIA-930)** — hourly demand + day-ahead price per bidding zone (EU) or balancing authority (US). Land as `loads-p_set` + a new `electricity_price` sheet keyed by snapshot. | The Tier-2 follow-on to OPSD: same role (hourly demand) but for actual freshness, plus the price half that retrospective settlements need. ENTSO-E's Transparency Platform requires a free per-user API key (see ENTSO-E's stance on redistribution — fetch on-demand, don't bulk-cache); EIA-930 is public domain via the EIA series endpoint. | 20,000 |
| `I7` | `Med` | `Frontend` | **Capacity-factor / generation history (Ember / IEA)** — country-by-month or country-by-year generation by carrier. Lands as long-form aggregates for analytics calibration ("does my model's 2023 gas dispatch match reality?") and as a fallback when hourly data is unavailable. | A cheap sanity check that costs no money to fetch but catches order-of-magnitude errors in a model. Ember's monthly electricity data is CC-BY; IEA needs free registration and is per-user. | 10,000 |
| `I8` | `Med` | `Frontend` | **Policy & target snapshot** — NDC pledges, national net-zero targets, RPS / CES levels, emissions caps; per-country JSON pulled from Climate Action Tracker / Climate Watch / IPCC's NDC tracker, dropped into `global_constraints` with provenance. | Studies that need to bound capacity expansion against an emissions trajectory currently get the number from a PDF. **I8** automates the trajectory-to-constraint step. Mostly open data, no key needed. | 12,000 |
| `I9` | `Med` | `Backend` | **PyPSA-Earth network builder (async job)** — for an arbitrary country/region, run PyPSA-Earth's `populate` workflow server-side and ingest the resulting PyPSA network as a workbook. NOT a synchronous importer: a queued job with progress polling (reuse the `startup_status` pattern), its own conda env, and cutout caching. Feasibility + design captured in [`docs/pypsa-earth-integration.md`](pypsa-earth-integration.md). | The top-down complement to the per-source importers: one config → a complete buses/lines/generators(+capacity)/renewable-profile/demand network, PyPSA-ready by construction (it *is* a PyPSA network). Supersedes hand-built OSM topology/plants + capacity for arbitrary countries; does not replace curated reference grids (KPG193). Heavy: ERA5 cutouts (GB-scale, CDS key), Atlite compute (minutes–hours), powerplantmatching/GADM/WDPA/GEBCO. **Deferred** — documented, not built. | 40,000 |

#### API-key infrastructure (cross-cutting, all I5–I8)

The browser-direct fetch model needs somewhere for per-user API keys to live without committing them or relaying them through a server. The pattern landed alongside this TODO entry:

  • Dev hosts: `.env.local` (gitignored) seeds defaults via `process.env.REACT_APP_RAGNAROK_*_KEY`. These ship to every browser when bundled — only use them for keys with no rate / revenue cost.
  • Production users: in-app Settings panel writes the key to `localStorage['ragnarok:secret:<name>']` (per-user, persistent) or `sessionStorage` (per-tab). Never leaves the user's machine.
  • Resolver `src/lib/api/secrets.ts` walks the chain `sessionStorage → localStorage → process.env` for every fetch.

#### I4 design — renewable profile attachment model

A profile is `generators-p_max_pu`, so availability lives on the **generator**, not the bus. The generator is the unit; it needs a coordinate to query weather. Resolve the query point by a **fallback chain** so users rarely pin anything:

1. Generator has its own `x` / `y` (imported fleet — WRI GPPD, OSM plants) → query there (plant-precise).
2. No generator coords but its bus has `x` / `y` → inherit the bus coordinate (coarser; one CF per bus per carrier, the `gen_<carrier>_<bus>` pattern).
3. Neither → fall back to pin-on-map.

Only attach a series to a generator that already exists (the KPG193 renewable-profile rule — no orphan profiles).

- **Granularity follows the fleet.** Plant-resolved fleets (per-plant `x`/`y`) get plant-specific CF; bus-resolved fleets (one renewable generator per bus) get one CF per bus — the fallback chain covers both. After a WRI + OSM merge (plants on synthetic per-plant buses) query at the *plant* coordinate; keep bus-snapping (the shipped Forge snap) as a separate electrical step.
- **Snapshot alignment.** The fetched series is keyed by timestamp; reconcile it onto the workbook `snapshots` index via **T1** (clip / retarget / resample) when the weather year differs from the run window.
- **Sources.** Prefer keyless, queryable upstreams — **PVGIS** (EU JRC; free, no key; hourly PV/wind CF per point), **NASA POWER** and **Open-Meteo** (free, no key, global). **Renewables.ninja** works as a per-user-key (BYOK) source via the API-keys panel — caveats: tight free-tier rate limits (cache via **D1**) and a redistribution license (fetch per-user, never bulk-cache server-side).

`I5`–`I8` reuse that resolver; what's still pending is the Settings-panel UI for typing the keys in (cheap; ~3,000).

### Transformation tools

Tools that transform an already-imported workbook between Data and Run — sit alongside the Build view's edit affordances but operate at sheet-scale rather than row-scale.

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---:|
| `T1` | `High` | `Both` | **Forecast tool / snapshot editor** — a single Model-side surface for editing the workbook's `snapshots` index and the temporal sheets attached to it. Three concerns in one tool: (a) **Define / re-aim the snapshot window** — calendar picker for new start / end (and resolution: hourly / daily / monthly); imported series are clipped if the window shrinks or pad-extrapolated if it widens. (b) **Forecast / extrapolate** — extend any temporal sheet (`loads-p_set`, `generators-p_max_pu`, prices, inflow, …) over a future horizon. Methods: time-series extrapolation (ARIMA / Prophet / linear), annual CAGR with a chosen base year, flat multiplication of a base series. (c) **Resample / shift** — change time-step or shift a series by N hours / days. The shared point: every operation here is "fix the snapshots so the model can run with the data the user already imported, plus a sensible projection". | After importing OPSD hourly load (year 2019) and a Renewables.ninja profile (year 2018), users end up with a snapshots index that's the union of both ranges and pad-filled gaps. **T1** is the editor that lets them retarget the window (e.g. "I actually want 2025-Jan-01 to 2025-Dec-31"), interpolate / extrapolate the imported series onto the new index, and clip ranges down for fast iteration. Distinct from **I3** (which derives a *new* shape from exogenous drivers); **T1** transforms whatever is already in the workbook. Conceptually the tool lives in the **Model** view next to the snapshots sheet — every operation works directly on the in-memory model, no backend round-trip. | 22,000 |
| `T2` | `High` | `Both` | **Reduced-order / clustering tool** — collapse the workbook to a smaller topology before running. User picks the method (k-means on bus coordinates, voltage-class merge, carrier-bundle aggregation for generators, removal-of-low-flow lines, …) and the target size. Output is a new workbook fragment that runs the same physics on fewer components. | OSM-imported grids and PyPSA-Eur-style bundles often arrive with thousands of buses / lines; many studies need a 50-bus / 20-cluster reduction before they can iterate fast. Today users export to CSV and reduce externally. | 26,000 |

### AI conversational interface — Bifrost

A new project wrapper (sibling to Mjolnir) that places an LLM chat interface in front of Ragnarok. The name follows Norse mythology: Bifrost is the rainbow bridge connecting Midgard (the user's world of questions) to the model's verified answers. Without the bridge you are guessing; with it you cross into provable territory.

The anti-hallucination principle: the LLM never answers the question directly. Instead it builds a Ragnarok workbook — buses, generators, loads, scenarios, constraints — from the conversation. The answer is the model's solver output, not the LLM's prediction. Every number in the response traces back to a workbook cell and a HiGHS solve. Confabulation is blocked at the architecture level, not by prompt engineering.

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---:|
| `L1` | `High` | `Both` | **Bifrost — AI conversational model builder** — stand-alone project (React/TS chat shell + thin Python relay) that sits in front of Ragnarok. The user asks a question ("how much solar does Korea need to reach 60 % renewables by 2040?"); Bifrost conducts a structured multi-turn conversation, asks clarifying questions where intent is ambiguous, and incrementally assembles a Ragnarok workbook from the answers via LLM tool-calls — an **agentic tool-use loop**: the model decides which Ragnarok importer / schema tools to call (data fetch, sheet edits, constraints) rather than following a fixed question ladder — that map to the existing JSON workbook schema (same format accepted by `POST /api/run`). When the model is complete the user **chooses**: (a) **inspect** — Bifrost hands the built workbook to the normal Model / Build editor for review and manual edits before any solve; or (b) **run** — Bifrost submits to `POST /api/run`, streams solve progress, and returns the live Ragnarok analytics result view (not a prose prediction). Either way the workbook is fully inspectable, exportable, and re-runnable without Bifrost. Data gaps ("I need demand data — WRI/OSM baseline or paste your own?") are resolved by asking the user, not by hallucinating numbers. Architecture: Bifrost chat shell → LLM **tool-calling + structured-outputs** layer → Ragnarok JSON workbook schema → backend `POST /api/run`. Recommended brain: **Claude Opus 4.8** (or **Sonnet 4.6** for ~5× lower cost) via a thin Python relay on the existing backend that keeps the key server-side; the LLM key reuses the shipped **BYOK key store** (`lib/api/secrets.ts` + API-keys Settings panel) — no new infra beyond the relay. A **local model** (Ollama + Llama/Qwen, JSON-schema/grammar-constrained decoding) is a possible offline / privacy mode but is materially weaker at strict-schema tool-calls — a later add-on, not the primary path. Bifrost itself does not own a solver, a database, or a workbook editor; it delegates everything to Ragnarok. | LLM answers to energy questions are fast but unverifiable — the model may confabulate capacity factors, costs, or dispatch physics. Routing through a real PyPSA solve makes every conclusion traceable and falsifiable. Distinct from **W1** (a stepped UI wizard that composes importers): Bifrost has the same output (a runnable Ragnarok workbook) via a free-text conversational affordance. Transparency is architectural, not a disclaimer. | 36,000 |
| `L2` | `Medium` | `Both` | **Bifrost data-ask loop** — when the LLM identifies a gap that cannot be filled from open data (e.g. a private corporate fleet, a confidential grid topology), Bifrost switches mode and asks the user to supply the missing sheet rows directly — paste a CSV snippet, answer a quick form, or point to a file. The user's response is validated against the Ragnarok schema and merged into the workbook-under-construction before the conversation continues. | Prevents silent gap-filling with hallucinated defaults. The conversation only advances once every required field has either a sourced value (from a Ragnarok data importer) or an explicit user-supplied value. Depends on **L1**. | 12,000 |

### Guided workflows

Top-down user surfaces that build a runnable Ragnarok workbook from high-level intent rather than per-sheet editing. The point is to lower the bar so non-modellers (policy / strategy / finance users) can drive Ragnarok without needing to know PyPSA component schemas.

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---:|
| `W3` | `Medium` | `Frontend` | **Interactive in-app tutorial / guided tour** — a skippable, resumable step-through walkthrough for first-time users that teaches the core loop (open / build a model → edit sheets in Model · Build → set scenario, constraints & run window → Run → read Analytics) via coach-marks / tooltips anchored to real UI elements, driven by a small **declarative step script** (selector + copy + "next on action"). Launchable any time from a Help / "?" entry; tracks completion in persisted state so it auto-offers once on first run. Runs against the solve-validated **demo network** (the onboarding model already pending in the Model-builder UX work) so every step acts on a real, runnable workbook. | New users land in a dense five-view app (Data · Model · Build · Run · Analytics) with no guided path and currently learn it only from external docs. An in-context tour teaches the workflow where the user actually works. **Distinct from W1/W2**, which *build a model from intent*; **W3 teaches how to drive the tool itself.** Pairs with the demo-network onboarding and gives the F0 / analytics surfaces a place to be introduced. | 16,000 |
| `W1` | `High` | `Both` | **Guided model-builder wizard** — a stepped flow that asks the user a small ladder of questions and assembles a workbook for them: (1) **Region** — pick a country / region on the map (re-uses the Data view shell); (2) **Question** — "What do you want to study?" (least-cost dispatch / capacity expansion / carbon-cap pathway / merchant IPP / N-1 security / climate-risk); (3) **Time horizon** — historic year, single future year, or multi-period pathway; (4) **Scope** — sectors (electricity only / multi-vector), carriers in-play, candidate technologies; (5) **Constraints** — carbon price / cap, renewable share targets, build-rate limits; (6) **Confidence** — let the wizard fall back to defaults the user did not answer. Output is a fully-populated workbook that is immediately runnable, with provenance flagging every cell the wizard filled vs the user edited. Power users can drop out into the regular Build / Model views at any step. | The Data view we shipped is bottom-up (pick a database, pull rows, repeat). A non-modeller cannot navigate that — they don't know which databases they need, which sheets to populate, or what defaults are reasonable. **W1** is the answer: state your goal in plain language, get a model. Internally it composes the existing importers (`I1`, `I4`, …) plus the transformation tools (`T1`, `T2`, `T3`) into one orchestrated flow, so it has zero new data-source code — it just sequences what is already there with sensible defaults per question. | 32,000 |
| `W2` | `High` | `Both` | **Country starter models (per-country baseline packs)** — three-question landing flow: (1) **Country** — pick on the map (any country in the Data view's coverage map); (2) **Year** — snapshot or planning horizon year (e.g. 2023 historic, 2030 single-year, 2030–2050 pathway); (3) **What to do** — short list (least-cost dispatch / capacity expansion / merchant IPP / carbon-cap pathway / N-1 security / climate-risk). The output is a curated, immediately-runnable workbook composed from the best baseline available for that (country, year) pair: grid topology (KPG193 for Korea, PyPSA-Eur cluster for EU members, country-specific public networks elsewhere, OSM-derived elsewhere), generation fleet (WRI GPPD + per-country overrides), demand profile (annual aggregate from World Bank or hourly slice if the year is in coverage), carrier costs scaled to the chosen year, policy constraints for that country/year (NDC, RPS, emission caps). Each pack carries a `kind` (`research-grade`, `policy-grade`, `quick-start`) so the user knows the fidelity bar. **KPG193 (this PR) is the prototype starter pack for KOR.** | The Data view is bottom-up (pick a database, pull rows, …). **W2** is the top-down complement: state country + year + question, get a working model. Distinct from **W1**, which is a multi-step wizard that composes data sources on the fly; **W2** ships pre-curated baselines so the answer to "give me Korea 2030 for capacity expansion" is one click instead of six. Internally it sequences the importers we already have (KPG193 / OSM / WRI GPPD / World Bank, plus **I5**–**I8** when those land) with a per-country recipe file describing which database to prefer at each slot for each (country, year) bin. Packs live under `src/lib/importers/starter_packs/<ISO3>/<year>/recipe.json` so adding a new country is just one recipe and one PR. | 24,000 |

### Decision workflows (financial use-cases)

The product positioning shift: from a **grid-modelling tool** (the user authors a network and reads system-level dispatch/cost) to a **financial-decision tool** (the user asks a money question and gets an investment answer). Each item below is a goal-driven workflow that *composes the engine* — `F0` (asset economics, shipped) + `F1`/`F2` (owner dimension, project finance) + `B1` (merchant optimisation) + `PP1`/`PP2` (PPA) — into a packaged answer with financial KPIs (NPV / IRR / payback / Δrevenue / Δemissions), not new solver math. The grid model becomes the *means*; the financial decision is the *deliverable*. Requires a **financial-first UX** (`DW1`) and the engine items as prerequisites. Distinct from *Guided workflows* (`W1`/`W2`), which build a runnable **model** from intent; these build an **answer to a financial question**.

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---:|
| `DW1` | `High` | `Frontend` | **Financial-first UX + use-case launcher** — a goal-oriented home surface that frames the tool around financial questions ("What's the profit of switching gas → solar?", "Find me the best PPA", "Is an ESS business viable here?") instead of around PyPSA component editing. Picking a use-case launches the matching `DW*` workflow; results lead with **money** (NPV / IRR / payback / annual margin) and only then show the MW/MWh detail. Power users still drop into the Model/Build/Analytics views. Reframes the F0 economics card and the financial layer as the headline, not a sub-tab. | Today the app is bottom-up grid modelling — a finance/strategy user lands in a component grid with no path to a money answer. This is the UX half of the repositioning: make the financial question the entry point and the investment metric the headline output. The umbrella surface for every `DW*` workflow below. | 24,000 |
| `DW2` | `High` | `Both` | **Asset-swap / repowering what-if** — pick an existing asset or carrier (e.g. a gas plant), define a replacement (solar + storage, wind, …), and the tool runs **before vs after** as two scenarios and reports the financial **delta**: ΔNPV, Δrevenue (at competitive LMPs via `F0`, or merchant via `B1`), Δfuel/Δcarbon cost, Δemissions, capex, and simple/discounted payback. "Profit of changing gas to solar?" answered as a number with the assumptions exposed. | The canonical repowering / transition-investment question. Composes `F0`/`F2` economics + the shipped cross-scenario comparison (`ScenarioPivotCard`) + `B1` for the merchant view — mostly orchestration + a delta-report card, little new solver code. Depends on `F2` (finance metrics) and the comparison engine. | 18,000 |
| `DW3` | `High` | `Both` | **ESS business-case builder** — size a storage asset (or sweep sizes) and stack its revenue streams — energy arbitrage (already in `F0`), avoided peak / capacity value, and ancillary/reserve where modelled — then report IRR / NPV / payback and the revenue-stack breakdown over the horizon. "Is an ESS business viable here, and at what size?" | Storage business cases are a top finance use-case and don't fall out of system cost-min — they need per-asset revenue stacking and project finance. Builds on `F0` storage arbitrage + `B1` (price-taker storage dispatch) + `F2` (IRR/NPV). A size sweep reuses the stochastic/Monte-Carlo sweep plumbing. | 20,000 |
| `DW4` | `Medium` | `Both` | **PPA opportunity explorer (buyer & seller)** — rank candidate PPA structures for a given asset (seller view) or load (buyer view): generate a menu of contract shapes (fixed / CfD / hub-indexed, volume profiles), value each against the dispatch/price signal, and surface the **best opportunities** by net value and risk. "What's the best available PPA, as a procurer or a seller?" | The discovery/ranking layer over `PP1` (single-contract valuation) and `PP2` (portfolio optimisation): no new pricing engine, just enumerate + value + rank + present. Seller-side offer curves come from `B1`. Depends on `PP1`/`PP2`. | 14,000 |

### Modelling extensions

Modelling-capability extensions that broaden Ragnarok beyond the single-vector electricity case it ships with today. Each item is a vertical slice — schema-aware Build/Model affordances, importers for sector-specific datasets, optimiser handling, and analytics. PyPSA already supports the underlying mechanics (multi-carrier buses, Links, Stores); the work here is exposing them cleanly through the GUI.

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---:|
| `M1` | `High` | `Both` | **Sector coupling** — multi-carrier buses (electricity, gas, hydrogen, heat, district cooling, transport, biomass, CO₂) plus the conversion components that link them (electrolyser, gas turbine / CCGT, heat pump, electric boiler, fuel cell, methaniser, CCS / DAC). Includes per-carrier transport (gas pipelines, hydrogen pipelines, district heating loops) modelled as `Link` networks, carrier-aware filters in the Build view (show only components on the active carrier), and per-vector energy-balance + emissions analytics. Carrier defaults (efficiency, capex, opex, lifetime) seeded from PyPSA-Eur's `costs.csv`. | The decarbonisation studies users want — green-hydrogen merchant, electrify-everything pathways, gas-network repurposing, district-heat decarbonisation — all need more than one energy vector. Today Ragnarok models electricity only; **M1** unlocks the multi-vector cases without changing the optimisation engine (PyPSA already handles it). Lands on the **optimisation** backend — sector coupling is a modelling/GUI job (multi-carrier buses + Links + Stores), **not** blocked on the simulation / merchant adapters (**B1**/**B2**), which address a different axis (fixed-rule / market-behaviour evaluation, not least-cost). Fuel price is modelled either as a fuel **Bus + Link** (price first-class in the LP) or folded into `marginal_cost` via **M3** — both stay in the optimiser. | 40,000 |
| `M3` | `Medium` | `Both` | **Fuel system** — explicit fuel carriers + a per-generator fuel input (heat rate / efficiency), so emissions and fuel cost derive from *fuel consumed* (`electrical output ÷ efficiency × emission_factor`) rather than electrical output. Then make carbon pricing **efficiency-aware** (divide the adder by efficiency) and align the custom `co2_cap` / DSL `emissions` with the thermal basis. | Carbon price and the custom CO₂ accounting currently use `co2_emissions × electrical dispatch` (output basis, generator efficiency ignored — correct only while efficiencies are 1, as they are today; see `backend/pypsa/carbon_price.py`). A fuel system makes the thermal basis explicit, divides emissions/cost by efficiency, and matches PyPSA's native `global_constraints` accounting. Pairs with **M1** (multi-carrier / gas vectors). | 20,000 |
| `M2` | `High` | `Both` | **Demand response** — flexible load modelling beyond static `p_set`. Three flexibility modes: (a) **Shed** — load can be curtailed at a per-MWh outage cost (extends today's coarse `load_shedding` option to per-load granularity + per-snapshot caps); (b) **Shift** — load can move within a user-defined window (e.g. ±4 h) preserving total daily energy, implemented as a Storage-like component; (c) **Price-elastic** — demand drops as the bus price exceeds a tier threshold (piecewise demand curve). UI: new "Flexibility" section on the Load editor in Build, time-of-use programs as a DSL/template library, analytics showing DR utilisation (energy shifted, energy shed, peak reduction). | Modern systems lean heavily on DR for peak shaving and renewable integration; capacity-expansion models that ignore it over-build firm capacity. **M2** is the missing demand-side complement to **T1** (forecast growth) and **R2** (transition risk). | 28,000 |

#### M1 readiness — what's needed *beyond* authoring a multi-carrier model

Verified against the code: the **optimiser needs nothing** (PyPSA does multi-carrier LP natively) and the **schema is already complete** — multi-port Links (`bus2`/`bus3`, `efficiency2`/`efficiency3`) and the `processes` component (`rate2`/`rate3`) exist, so the schema-driven **Model** editor can already author electrolysers / CCGT / heat-pump links. The gap is the electricity-centric app layer around it:

1. **Carrier-aware analytics (largest piece).** Results currently aggregate across *all* buses regardless of carrier — e.g. `load_dispatch = loads_t.p_set.sum(axis=1)` (`backend/pypsa/results/__init__.py:348`) would add electricity + heat + H₂ demand into one MWh figure, and `buses_t.marginal_price.mean(axis=1)` (`:350`) averages €/MWh across electricity / gas / heat buses (mixed units). Split energy balance, "total load", and "average price" **per carrier**; add per-vector views + Link conversion flows.
2. **Emissions from conversion, not just generators — depends on `M3`.** Carbon price + `co2_cap` + emissions reporting only see `generators × co2_emissions`; fuel burned in **Links** (gas→power CCGT, boilers) or tracked via a CO₂ bus/Store would be untaxed/uncounted. `M1` and `M3` should land together.
3. **Carrier-aware Build/Model UX.** Carrier filter on the map (show only the active vector); handle **non-geographic** carriers (abstract CO₂/H₂ buses with no x/y).
4. **Technology defaults** (efficiency/capex/opex/lifetime per conversion tech) — curated in-app or from a queryable source (not a static CSV, per the data-source rule).
5. **(Deferred) Importers** for sector data (gas networks, heat/H₂ demand) — a later layer.

### Resource adequacy & robustness

Tools that test how a solved model holds up under renewable/weather and outage uncertainty, and quantify reliability. Build on the existing **stochastic optimisation** engine (`backend/pypsa/stochastic.py`) and the `load_shedding` unserved-energy signal already in the model.

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---:|
| `A1` | `High` | `Both` | **Stochastic renewable profile generator** — generate an ensemble of synthetic wind / solar capacity-factor profiles (`generators-p_max_pu`) from a base series, with a user-set similarity/variability knob: a target **R²** (or RMSE / std-dev / lag-1 autocorrelation) between each synthetic draw and the base, so a run can be stress-tested against renewable variability. Methods preserve diurnal + seasonal shape and hourly autocorrelation (correlated-noise injection, block-bootstrap resampling, or an AR/Markov model fit to the base); the knob sets how far each draw departs. Output: N perturbed profiles wired into the existing **stochastic optimisation** (per-scenario series) or a Monte-Carlo sweep, plus a robustness readout (spread of objective / cost / curtailment / unserved energy across draws). | A model is solved against one weather year / one profile; users need to know how sensitive cost, capacity and reliability are to renewable variability. Reuses the stochastic engine already shipped and produces the input ensemble for **A2**. | 18,000 |
| `A2` | `High` | `Both` | **LOLE calculator** — resource-adequacy metrics from an ensemble of dispatch runs (or an analytic convolution of forced-outage + renewable + load distributions): **LOLE** (h/yr or d/yr), **LOLP** per snapshot, **EUE / EENS** (expected unserved energy), and the worst contributing periods. Driven by the **A1** ensemble plus per-unit forced-outage rates, counting snapshots where available capacity < load — unserved energy is already observable via the `load_shedding` generators. Surfaced as an Analytics card against the standard "1 day in 10 years" yardstick. | Capacity-expansion / adequacy studies need LOLE / EUE — the reliability metrics regulators use. Today the tool shows load shedding per run but no reliability statistic across draws. Depends on **A1** for the input ensemble; storage and **M2** demand-response contribute to the adequacy result. | 16,000 |

### Run history

Items that tighten what History means and extend what can be brought into it. History's semantic contract is: *every entry is a result you can analyse, compare, and replay* — whether it was produced by solving, imported from a Ragnarok project, or ingested from an external results file.

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---|---:|
| `H2′` | `Medium` | `Both` | **Pluggable result-mapper registry + raw-sheet surfacing** — the **core** of H2 shipped (see *Already shipped → Project exchange*): `POST /api/import/result` ingests a Ragnarok package verbatim or reconstructs analytics from a bare results `.xlsx` via `from_outputs`, persists with `origin="xlsx_import"`. What remains: per-source-format **column-mapping rules in a small registry** (extendable by plugins via a `result_mapper` hook) so arbitrary third-party result layouts map onto `outputs.{static,series}`, and **unrecognised sheets stored verbatim + surfaced as raw tables**. | Today's reconstruction handles Ragnarok's own schema and bare workbooks that already use canonical attribute names; a true third-party layout (different column names) needs a mapping layer. The residual after H2's core landed. | 10,000 |

### Architecture

Cross-cutting platform direction (not a single feature). Assumes a dedicated backend server service rather than a browser-resident app.

| ID | Pri | Surface | Task | Why | Cost |
|---|---|---|---|---:|---:|
| `X1` | `Medium` | `Both` | **Backend-centric data processing (thin browser)** — move all data processing and the end-to-end model lifecycle to the backend so the browser is a light, fast view layer. In scope: a stateful server-side workspace (model + edits) with an API for every mutation; server-computed analytics/derivation (port `deriveRunResults` + chart series); **plugin execution server-side** (the backend-plugin framework now covers this for Python plugins — `/api/plugins/*` runs hooks in-process against the session; what remains is sandboxing and migrating the in-browser JS plugin runtime); push/poll sync. Assumes a dedicated backend service deployment. | The browser currently owns the model, all editing, normalization, analytics derivation, and the plugin runtime, so large models (full-year, many components) make it heavy/slow and a heavy plugin can freeze the tab. Moving the work to the server keeps the browser light and fast and matches a hosted, multi-user deployment. **Big re-architecture** (touches state management, every editor, charts, plugins) — sequence after the targeted perf wins (grid is already virtualized; snapshot-canonicalization fast-path landed) prove insufficient. Related: the "Backend retention of solved network" item under *Deliberately not pursued* was scoped to trust, not performance — this supersedes that reasoning if pursued. | 60,000 |
| `X5` | `Low` | `Frontend` | **Frontend-plugin Worker sandbox.** Evaluate frontend-plugin JS in a Web Worker instead of `new Function` in the page: hooks become postMessage round-trips (model structured-cloned per call), `worker.terminate()` enforces a timeout. Gains: no DOM/localStorage/app-state access for plugin code, and a runaway plugin can no longer freeze the tab. Conforming (data-in/data-out) plugins keep working unchanged. | The JS runtime is the weakest isolation point (in-page eval). Deferred while backend plugins absorb plugin workloads (see "Deliberately not pursued" on runtime unification) — build only if 3rd-party *frontend* plugins stay first-class. | 12,000 |
| `X3` | `Low` | `Both` | **Scenario library vs. run history — review.** Now that the backend stores *every* run (History is the single source of truth), the in-model scenario library (`RAGNAROK_Scenarios` presets) overlaps with it and is arguably no longer central: decide whether to slim/deprecate it or reposition it explicitly as "named run-config *presets*" (intent) distinct from History ("runs I actually executed"). NOTE: scenario **rename already exists** (Settings → Scenarios → *Active scenario label*, via `handleRenameScenario`); renaming *runs* is the separate **X4**. | History already captures "what I ran" comprehensively, so the preset library is less load-bearing. A scoping/decision item, not a build. | 4,000 |
| `X2` | `Medium` | `Both` | **Data-import KPI computation → backend API** — move the data-import KPI / analysis computation off the browser to a backend endpoint. NOTE: the import *preview* (`PreviewSummary` from `POST /api/import/run`) is already backend-computed; this item targets the *remaining* client-side analysis of imported data — `src/features/input/InputAnalyser.tsx` and any KPI/statistics derived in-browser from imported rows (counts, ranges, hourly/temporal stats, distributions). Add an endpoint that takes the imported rows (or a stored import handle) and returns the KPI summary; the frontend just renders it. A concrete, low-risk slice of **X1** that can ship independently. | Keeps heavy per-row statistics off the main thread (consistent with the thin-browser direction), and centralises the KPI definitions so they don't drift between the import preview and the post-import analyser. | 10,000 |
| `X6` | `Medium` | `Both` | **Richer / clearer plugin output scheme** — extend the plugin contract beyond *single-run, data-in/data-out* so plugins can (a) declare **composite host-rendered layouts** (e.g. a grid / matrix of charts with rows, columns, and shared legend/settings grouping) as declarative specs — not just a flat list of `PluginChartSpec` rendered sequentially; (b) receive **multiple runs / scenarios** as input (an analytics-over-N-runs hook), not only the latest `RunResults`; (c) be documented as one crisp, versioned contract. Keep the "host owns rendering, no raw HTML/SVG" rule — this is about giving the host *more* declarative layout vocabulary, not opening an escape hatch. | The **scenario-comparison matrix** (built directly into the Comparison tab — see *Analytics & UX shipped*) is the motivating case: it *could not* be a plugin because the contract is single-run + no custom layout + no `/api` access. Generalising the scheme lets comparison / multi-run analytics features ship as plugins instead of core code, and makes the plugin API legible enough for third parties. Pairs with **X1** (server-side plugin execution) and **X5** (sandbox). | 20,000 |

## Suggested execution order

Forward plan from 2026-06-24, respecting the cross-group dependencies marked above. The list is renumbered as one clean sequence (the previous pass had duplicate / skipped numbers).

**Done:** ~~F0 — Asset profit & revenue reporting~~ (shipped 2026-06-26), ~~H1 — Decouple import-project from History~~ and ~~H2 (core) — Import external results → History~~ (verified already implemented 2026-06-26). See *Already shipped*.

**Near-term — small, modular, useful for every run from here:**

1. **T1** — Forecast / snapshot editor (lightweight; immediately useful for pathway runs).
2. **M2** — Demand response (slots into the existing Load editor).
3. **H2′** — Pluggable result-mapper registry + raw-sheet surfacing (the residual after H2's core; do when a real third-party result layout needs it).

**Financial engine:**

4. **B1** — Merchant / price-taker optimisation (foundation for the *strategic* financial layer; F0 already covers the competitive case).
5. **F1** — Company / owner dimension (frontend-heavy; can run in parallel with **B1**).
6. **F2** — Company-level financial model (consumes **F0**/**B1** + **F1**).

**Financial decision workflows (the product direction — grid tool → financial-decision tool):**

7. **DW1** — Financial-first UX + use-case launcher (make the money question the entry point; depends on **F2** for the headline metrics).
8. **DW2** — Asset-swap / repowering what-if (gas→solar profit delta; composes **F0**/**F2**/**B1** + the shipped comparison).
9. **DW3** — ESS business-case builder (size + revenue-stack storage; composes **F0**/**B1**/**F2**).

**Risk:**

10. **R1** — Physical-climate-risk module.
11. **R2** — Transition-risk module (depends on **F2**).

**Data & model-assembly layer:**

12. **T2** — Reduced-order / clustering tool.
13. **D1** — Profile / weather data layer.
14. **I1** — Location-based data & model bootstrap (user surface above **D1**).
15. **I4** — Renewable resource profile importer (polygon / buffer region selection).
16. **I3** — Driver-based demand forecast.
17. **I5** — Fuel & commodity-price importer (moves the dispatch answer more than any other input).
18. **I6** — Hourly load & price (ENTSO-E / EIA-930).

**Modelling reach & guided surfaces:**

19. **M3** — Fuel system (efficiency-aware emissions / carbon; lands *with* **M1**).
20. **M1** — Sector coupling (largest single item; lifts Ragnarok out of electricity-only — land together with **M3**).
21. **W2** — Country starter models (per-country baseline packs, composed from the importers above).
22. **W1** — Guided model-builder wizard (composes every importer + tool + **M1**/**M2**).
23. **W3** — Interactive in-app tutorial / guided tour (after the demo network + guided surfaces exist; teaches the core loop in-context).

**Backend adapters & adequacy:**

24. **B2** — Simulation backend adapter.
25. **B3** — Power-flow-only study mode.
26. **A1** — Stochastic renewable profile generator (reuses the shipped stochastic engine; feeds **A2**).
27. **A2** — LOLE calculator (depends on **A1**).

**Procurement & conversational front-end:**

28. **PP1** — PPA contract modeler (depends on **B1** for a meaningful price signal; front-loadable with an exogenous series).
29. **PP2** — Procurement strategy optimizer (depends on **PP1**).
30. **DW4** — PPA opportunity explorer (buyer & seller ranking; composes **PP1**/**PP2** + **B1**).
31. **L1** — Bifrost AI conversational model builder (sequence after core importers + guided workflows so the LLM has real data sources and schema to call into).
32. **L2** — Bifrost data-ask loop (depends on **L1**).

**Off the linear path** (sequenced opportunistically, not blocking the above):

- **I7**, **I8** — lower-priority calibration / policy importers.
- **B4** — strategic / price-maker (MPEC) optimisation — research-grade, different solver stack; deferred.
- **I9** — PyPSA-Earth network builder — heavy async job; deferred.
- **X1**–**X6** — architecture / thin-browser direction; pursue after targeted perf wins prove insufficient.

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

- **`H1` Import-project decoupled from History** — "Import Project" is now *opening a file*, not a run. The frontend (`handleImportProject` in `App.tsx`) calls `POST /api/import/project/load`, which parses the package (`.zip`/`.xlsx`) and **returns the bundle without persisting**; the model + solved results load into the editor and `activeRunName` is cleared. History entries come only from a solve or the explicit `POST /api/import/result` path. `POST /api/import/project` (persisting) is retained for API clients that explicitly want it. Residual: a one-off backfill to tag pre-decouple import-sourced entries `origin:"import"` (cosmetic; no new such entries are created).
- **`H2` (core) Import external results → persistent History** — `POST /api/import/result` (alias `/result/xlsx`) ingests a Ragnarok package verbatim or reconstructs analytics from a bare results `.xlsx` (rebuild network → inject outputs → `derive_imported_result`), persists via `store_run(origin="xlsx_import")`, returns the run name. The pluggable per-format mapper registry + raw-sheet surfacing remain as **H2′** (open).
- Pure-JSON project export/import (PR #9) — backend returns schema-driven `outputs.{static,series}`; frontend assembles the project workbook locally. Sidebar split into Import Project / Export Project / Export Result.
- `deriveRunResults` (PR #11) rebuilds summary / dispatch / costs / carrier mix / nodal balance / line loading / merit order / emissions / expansion / asset details from `(model, outputs)` on import. `co2Shadow` is the one field still needing a fresh solve.
- Ragnarok metadata sheets round-trip end-to-end: settings (incl. date format, currency, solver config), active constraints, run window, scenarios, pathway, rolling-horizon, plugin analytics, CO2 shadow, solver narrative, import provenance.
- HTML report export (PR #12) — standalone `.html` with inline CSS and inline SVG charts.
- CSV-folder, netCDF, HDF5 import/export. CSV folder uses `fflate` in-browser; netCDF/HDF5 go through backend endpoints (`netCDF4`, `tables`).
- Round-trip test suites: frontend `workbook.test.ts`, `csvFolder.test.ts`; backend `test_import_contract.py`, `test_binary_io.py`, `test_full_outputs.py`, `test_type_references.py`.

### Analytics & UX

- **`F0` Asset economics (revenue / margin / capex recovery)** — competitive-benchmark profit read out of the cost-min solve with **no extra solve** (least-cost dispatch = perfectly-competitive profit-max equilibrium). `build_generator_economics(network)` in `backend/pypsa/results/market.py` computes per-generator / per-storage / per-carrier revenue (Σ LMP·dispatch), gross margin, capture price, and capex recovery (margin ÷ annualised `capital_cost`·`p_nom_opt`, pro-rated to the modeled horizon); wired into both analytics paths (`results/__init__.py` solve + `from_outputs.py` import). `GeneratorEconomicsCard` renders it (default Result layout + addable card); XLSX export sheets `OUT_EconBy{Generator,Carrier,Storage}`. Preserved through the client `deriveRunResults` merge (`App.tsx`), so it shows for solves, stored/light views, pathway runs, and re-imported bundles that carry it. Math pinned by `backend/tests/test_generator_economics.py` (hand-computed + a real-solve check that the marginal unit earns zero margin). **Not** recomputed by `deriveRunResults`, so a bundle fully re-derived from bare outputs with no backend economics (e.g. a pre-F0 export re-opened) lacks it — acceptable, not a functional hole.
- Capacity-by-period chart for pathway runs (PR #16).
- Cross-scenario `ScenarioPivotCard` in the Comparison tab — Δ columns vs the leftmost scenario; appears when ≥ 2 scenarios are present.
- Carrier-level analytics card — capacity factor, curtailment ratio, effective cost / MWh, emissions intensity.
- Load drill-down card — load factor, coincidence factor, per-bus contribution table.
- Run-history schema-driven counts (PR #10) — `RunHistoryEntry.componentCounts` is `Record<string, number>`.
- Auto-generated support matrix (`scripts/generate-support-matrix.mjs` → `docs/SUPPORT_MATRIX.md`).
- Constraints workspace overlay (`ConstraintsWorkspaceView`) — Custom + native `global_constraints` editor.
- **Component-to-bus reconciliation** (former `T3`) — bulk **Snap to nearest bus** in the Forge view (`src/lib/forge/snap.ts`, `ForgeView.tsx`): haversine matching, configurable buffer (km), per-sheet multi-select across generators / loads / storage / lines, and a post-run report of snapped vs out-of-buffer components; paired with a validation scanner (`src/lib/forge/validate.ts`) that flags coordinate-bearing components with missing / unknown bus refs. OSM import additionally auto-snaps line endpoints (`snap_endpoints` toggle, `backend/app/importers/databases/osm/`). Covers T3's reconciliation engine + post-import bulk sweep; the originally-envisioned per-row inline "Find nearest bus" button in Build was not added separately because Forge's bulk action already handles the multi-source-import use case (Build retains "Pick on map" for manual per-row assignment).
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

### Plugin platform

In-browser plugin runtime (`src/lib/plugins/`, `src/features/plugins/`). All additive **SDK 2** features (no `sdkVersion` bump); documented in `docs/plugin.md` (incl. its §15 SDK changelog). Plugins return data; the host owns rendering — every capability is a declared schema/format type plus a host-side renderer, never raw HTML/SVG injection.

- **`P1` Plugin chart output** — `chart` value on `PluginFieldFormat` + a `PluginChartSpec` (line / area / bar / donut) rendered by the host via the app's own chart components (`PluginChart.tsx`, `lib/plugins/chartSpec.ts`). Tests in `chartSpec.test.ts`.
- **`P2` General multi-select control** — `multi-select` field type (arbitrary `options`, returns `string[]`) generalising `carrier-select` beyond workbook carriers.
- **`P3` Dynamic select options (`optionsFrom`)** — `select` / `multi-select` fields and `"select"` table columns can source options at render time from the workbook model (`source: "model"`) or a sibling `table` field (`source: "config"`), with static `options` as fallback; switch sets via field-level `visibleWhen`. Resolver in `lib/plugins/options.ts`, tests in `options.test.ts`.

## Deliberately not pursued

- **Unifying the two plugin runtimes (`PluginDetail` vs `BackendPluginDetail`)** — the duplication is managed (one contract, one form renderer, documented divergences) and the thin-client direction (X1) resolves it by attrition: backend plugins become *the* plugin system and the in-browser JS runtime shrinks toward display-only. A unification refactor now would fight that direction for no user-visible gain.

- **Backend retention of solved `pypsa.Network`** — the run store persists every solved run's *results* (History), but the solved `pypsa.Network` object itself is intentionally never retained. The JSON output cache round-trips losslessly on the frontend (PR #9) and `deriveRunResults` rebuilds the full `RunResults` on import (PR #11), so retaining the network object buys nothing for Ragnarok-internal trust. Users who need a native `pypsa.Network` can reconstruct one from the exported workbook or CSV folder.
- **Separate "Topology" build mode (`Serialised vs Topology` toggle)** — the unified map-driven Build already folds in the intended free-form affordances (own-x/y placement, click-to-link buses, "pick on map" linking, drag-to-move), so a distinct toggle is redundant rather than a separate mode.
- **PyPSA-Earth as a registered data source** (former `I2`) — PyPSA-Earth is a Snakemake workflow that *produces* country networks from upstream OSM / ERA5 / GADM / atlite outputs, it does not publish data itself. Importing a PyPSA-Earth-built network is equivalent to importing any PyPSA-native `.nc`, which is already covered by the existing `POST /api/import/netcdf` endpoint and the corresponding **Import netCDF** button. A standalone registry entry would duplicate that path without adding value; remove from the Data view registry.
- **Renewables.ninja as a registered data source** — *originally deferred* because its endpoint needs an API key and there was no per-user key store. **Now resolved:** the BYOK API-keys Settings panel (`ApiKeys.tsx`) + secrets resolver (`src/lib/api/secrets.ts`) exist, so Renewables.ninja is folded into **I4** as a per-user-keyed source (alongside keyless PVGIS / NASA POWER / Open-Meteo). Kept here only as a pointer — no longer "not pursued."
- **PyPSA `technology-data` as a registered data source** (former Tier-1 candidate) — it is a *static CSV in a git repo*, not a queryable database. Pulling cost snapshots from a checked-in file violates the user-stated rule "we don't gather data from static format never ever. you only gather data from proper database." Cost defaults will be sourced from a proper queryable upstream (or curated in-app) when the Costs & parameters category is revisited.
- **OWID Energy as a registered data source** — same reason: a static CSV in a git repo, not a queryable database.
- **OPSD `time_series_60min_singleindex.csv` (former `opsd_load`)** — a ~150 MB CSV that the target browser-direct deployment cannot fetch in full per user, the upstream snapshot stops circa 2020, and slicing it server-side per request reintroduces the centralised data-gathering backend we explicitly moved away from. Tracked for replacement under **D2** (self-hosted hourly demand database with our own refresh cadence).
