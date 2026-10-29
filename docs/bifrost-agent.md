# Bifrost — the agentic AI model-builder for Ragnarok

**Status:** design / roadmap (TODO items **L1** conversational builder, **L2** data-ask loop).
**Goal:** a user states an intent in plain language ("build a 2030 Korea power system with 40% renewables and tell me the cost and emissions"), and an AI agent **builds the model in Ragnarok, runs it under the user's settings, and analyses the result** — with the human in the loop for anything expensive or irreversible.

The central insight: **Ragnarok's HTTP API + the session store already are a complete tool layer.** Everything a human does in the GUI is one REST call against a stateful working model. So Bifrost is not new modelling capability — it is (1) a **driver** (an LLM agent loop), (2) a **tool catalog** over the existing API, and (3) a **chat surface**. Nothing about the solver, importers, or analytics needs to change for the first working version.

---

## 1. Architecture at a glance

```
┌────────────────────────── Bifrost UI (new "Assistant" tab) ──────────────────────────┐
│  chat stream · tool-call cards · confirmation gates · inline model diff & analytics    │
└───────────────────────────────────────┬───────────────────────────────────────────────┘
                                         │ SSE / WebSocket
┌────────────────────────────── Agent orchestrator (backend) ───────────────────────────┐
│  plan → act → observe → reflect loop · budgets · guardrails · audit log                 │
│                                                                                         │
│   ┌──────────────── LLMProvider (pluggable) ────────────────┐   ┌──── Tool executor ──┐ │
│   │  ClaudeAPI  │  ClaudeCode/CLI  │  Local (Hermes/Ollama)  │   │  calls Ragnarok API │ │
│   └──────────────────────────────────────────────────────────┘   └─────────┬──────────┘ │
└────────────────────────────────────────────────────────────────────────────┼───────────┘
                                                                               │
                        ┌──────────────────────────────────────────────────────┘
                        ▼
       Existing Ragnarok API  (session store = shared working memory)
   import/* · session/* · transform/* · /api/queue · runs/*/analytics · plugins/*
```

Two deployment shapes, same tool catalog:
- **Embedded** — the orchestrator runs in Ragnarok's backend; the chat tab talks to it. This is the product.
- **External (MCP)** — the same tools exposed as an **MCP server**, so Claude Code / Claude Desktop / any MCP client can drive Ragnarok directly. This is the *fastest path to a working prototype* (Phase 0) and doubles as the power-user interface.

---

## 2. The tool catalog (maps 1:1 to today's API)

Grouped by the phase of a modelling session. Each tool is a thin, typed wrapper over an existing endpoint; the **session store is the shared state** between tools, so the agent composes them without passing the model around.

### 2.1 Introspect / ground (read-only, cheap — call freely)
| Tool | Endpoint | Purpose |
|---|---|---|
| `list_importers` | `GET /api/import/sources` | what data sources exist, per country, their filters |
| `describe_component` | (from `pypsa_schema_builder`) | attributes + units + status of a PyPSA component |
| `source_health` | `GET /api/import/health` | which upstreams are reachable now (skip dead ones) |
| `get_world_state` | `GET /api/session/meta` + `/sheet/{n}/stats` | what's loaded: buses, carriers, snapshot window, sizes |
| `get_sheet_page` | `GET /api/session/sheet/{name}` | inspect rows (paged — never dump 8760) |
| `derive_series` | `GET /api/session/sheet/{n}/derive` | duration curve / daily profile / grouped aggregate |

### 2.2 Data-in
| Tool | Endpoint |
|---|---|
| `one_click_model(iso3)` | `POST /api/import/location-model/{iso3}` |
| `build_starter_pack(iso3, year)` | `POST /api/import/starter-packs/{iso3}/{year}/build` |
| `import_dataset(sources, filters, country)` | `POST /api/import/run` |
| `attach_renewable_profiles(...)` | `POST /api/transform/renewable-profiles` |
| `attach_hydro_inflow(...)` | `POST /api/transform/hydro-inflow` |

### 2.3 Model-edit / transform
| Tool | Endpoint |
|---|---|
| `edit_sheet(name, ops)` | `PATCH /api/session/sheet/{name}` (set / addRow / deleteRows) |
| `retarget_snapshots(...)` | `POST /api/session/snapshots/retarget` |
| `forecast_demand(...)` / `driver_forecast(...)` | `POST /api/session/snapshots/forecast` \| `/driver-forecast` |
| `ev_reshape_demand(...)` | `POST /api/session/snapshots/ev-demand` |
| `cluster_network(n, method)` | `POST /api/transform/cluster` |
| `adjust_carrier_capacity(carrier, target_mw, method, mode)` | `POST /api/transform/scale-carrier-capacity` |

### 2.3b Build from primitives (pypsa-mcp-style, native to the session)
Ergonomic component constructors so an agent can build a network from scratch —
the same low-level surface as the community [`pypsa-mcp`](https://github.com/open-energy-transition/pypsa-mcp),
but mapped onto Ragnarok's **shared session** (via `edit_sheet` `addRow`), so what
the agent builds is persisted, visible live in the GUI, importer-augmentable, and
solvable via the real queue with full analytics — one unified world, not a
separate in-memory scratch network.

| Tool | Adds to sheet |
|---|---|
| `add_bus(name, v_nom, x, y, carrier, extra)` | `buses` |
| `add_generator(name, bus, carrier, p_nom, marginal_cost, p_nom_extendable, …)` | `generators` |
| `add_load(name, bus, p_set, carrier, extra)` | `loads` |
| `add_line(name, bus0, bus1, s_nom, x, r, s_nom_extendable, …)` | `lines` |
| `add_storage(name, bus, carrier, p_nom, max_hours, …)` | `storage_units` |
| `set_snapshots(snapshots)` | replaces `snapshots` |

Each drops unset fields and passes any other PyPSA attribute via `extra`. They're
"cheap" in-session edits — they run under `guided`, gate only under `manual`.

### 2.4 Configure + solve
| Tool | Endpoint | Notes |
|---|---|---|
| `submit_solve(scenario, options)` | `POST /api/queue` | **async**: queues the run and returns its queue item. `scenario` and `options` are the user settings (carbon price, discount rate, solve mode, solver, …); `describe_run_options` documents every key |
| `get_queue()` | `GET /api/queue` | the agent polls this for each item's status (`queued`, `running`, `done`, `error`) |
| `cancel_solve(item_id)` | `POST /api/queue/{id}/cancel` | cancels a queued item or kills a running one. Never gated |

### 2.5 Analyse
| Tool | Endpoint |
|---|---|
| `get_analytics(run)` | `GET /api/runs/{name}/analytics` (summary, carrier mix, cost, emissions, adequacy…) |
| `get_derived(run, metric)` | `GET /api/runs/{name}/derived/{metric}` |
| `run_plugin_analysis(id, config, runs)` | `POST /api/plugins/{id}/analyze` (X6 multi-run comparison) |
| (no separate tool) | `GET /api/queue` | the infeasibility diagnosis (`backend/pypsa/results/diagnostics.py`) is written into a failed run's error text; the agent reads it from `get_queue` and repairs the model for **self-repair** |

### 2.6 The rest of the GUI's reach
Everything else a person can do from the web UI. Read tools run freely; writes
gate like their peers (`confirm=true`).

| Tool | Endpoint |
|---|---|
| `get_server_info` | `GET /api/health` + `/status` + `/identity` + `/backends` + `/config/build-id` |
| `get_server_log(tail, level)` / `reload_config` | `GET /api/log` / `POST /api/config/reload` |
| `list_examples` / `load_example(id)` | `GET /api/examples` / `POST /api/examples/{id}/load` |
| `list_import_databases` / `list_starter_packs` / `list_import_countries` / `get_import_provenance` | `GET /api/import/databases` \| `/starter-packs` \| `/countries` \| `/provenance` |
| `list_import_secrets` / `set_import_secret` / `delete_import_secret` | `GET` / `PUT` / `DELETE /api/import/secrets[/{name}]` (names only — values never returned) |
| `get_distinct_values(sheet, column, master)` | `GET /api/session/sheet/{n}/distinct` \| `/api/session/master/distinct` |
| `import_master(path)` / `clear_master` | `POST /api/session/master/import` \| `/clear` |
| `get_run_model_sheet(run, sheet)` / `load_queue_item(id)` | `GET /api/runs/{n}/model/sheet/{s}` / `POST /api/queue/{id}/import` |
| `export_workbook(dest)` / `import_result(path)` | `POST /api/export/workbook` / `POST /api/import/result` |
| `get_plugin` / `refresh_plugins` / `install_plugin(path)` / `uninstall_plugin` | `GET /api/plugins/{id}` \| `?refresh=true`, `POST /api/plugins/install` (a .zip, or a directory zipped on the fly), `DELETE /api/plugins/{id}` |
| `list_plugin_files` / `upload_plugin_file` / `delete_plugin_file` | `/api/plugins/{id}/files[/{name}]` |
| `get_plugin_options` / `run_plugin_action` | `POST /api/plugins/{id}/options` \| `/action` |
| `install_tab_module_zip(path)` | `POST /api/modules/install` |
| `siting_scan(bbox, …, apply)` | `POST /api/siting/scan` — buses and target snapshots default to the working model's |
| `pypsa_earth_status` / `_configure` / `_build` / `_build_status` / `_stop` / `_apply(job, replace)` | `/api/pypsa-earth/*` |

Fragments from `import_dataset`, `siting_scan` and `pypsa_earth_apply(replace=false)`
merge through `POST /api/session/merge-fragment` (`backend/app/fragment_merge.py`,
the same implementation the GUI uses): rows are appended with name dedupe (never a whole-sheet
replace), carriers and snapshots are unioned, temporal sheets are widened.
`submit_solve` reports the run **its own** queue job stored (the queue item's
`runName`), not the newest run in History.

Not wrapped, on purpose: the SSE stream (`/api/events`), the removed direct
`/api/run` (the queue replaced it: `submit_solve` and `get_queue`), async export jobs (`/api/exports`, covered
by `export_run`), the country GeoJSON and `DELETE /api/log`.

**Confirmation-gated tools** (never auto-run): `submit_solve` (minutes of compute), `import_dataset`/`one_click_model` (live network, rate limits), any `edit_sheet`/`delete` that overwrites user data, and anything spending money (paid APIs). The UI shows a diff/preview and an Approve button; an "autonomy level" setting can pre-authorise the cheap tiers.

### 2.7 MCP-only modelling and scenario tools

The MCP server has 199 tools: 117 in `backend/mcp/server.py` (§2.1–§2.6 group most of them, not all) and 82 in
`backend/mcp/tools_*.py`. The table below covers the 38 added before 2026-10-28; `compare_run_statistics` (tools_results_extra.py, read-only, `GET /api/results/compare?topics=statistics`) compares runs through `pypsa.NetworkCollection` statistics, and `get_metric_options` (same module, read-only, `GET /api/runs/{name}/metrics`), `get_period_results` (same module, read-only, `GET /api/runs/{name}/period/{period}`) and `get_run_analysis` (same module, read-only, `GET /api/runs/{name}/analysis/{topic}`) are listed in the last table below. The GUI reaches the same backend routes through its own
controls (Forge, the Solver section, the Scenarios panel). This table is a snapshot from 2026-10-28, read from the
code: the tool name and module from the `@mcp.tool` decorator, the endpoints from the `RagnarokClient` method each
tool calls, the gate from the `confirm` argument, and the purpose from the first sentence of the description. The
MCP `list_tools` call returns the full descriptions, and `describe_run_options` documents every run-option key.

**Scenario authoring and run specs (`tools_runspec.py`)**

| Tool | Endpoint(s) | Gate | What it does |
|---|---|---|---|
| `list_scenarios` | `GET /api/scenarios`; `GET /api/scenarios/carbon-schedules`; `GET /api/scenarios/dsl` | — | List the model's saved scenario presets (id, label, window, carbon price, enabled study modes, constraint count, model overrides), its carbon-schedule library, and the status of its … |
| `describe_scenario` | `POST /api/scenarios/resolve` | — | One saved scenario in full (every preset field) and the exact {scenario, options} run body submit_scenario would send |
| `submit_scenario` | `POST /api/scenarios/resolve`; `POST /api/queue` | confirm | Solve ONE saved scenario exactly as the web UI's scenario run would (preset + the model's DSL sheet + solver defaults) - no hand-built options |
| `submit_scenarios` | `GET /api/scenarios`; `POST /api/scenarios/resolve`; `POST /api/validate`; `GET /api/queue`; `POST /api/queue` | confirm | Queue SEVERAL saved scenarios as a batch (scenario_ids=None or [] runs ALL saved scenarios), one queue job each with a distinct run label, like the UI's 'run scenarios' |
| `save_scenario` | — | confirm | Create or update a saved scenario preset — the same record the Scenarios panel in the web UI edits. 'fields' merge over the stored preset (a config block such as pathwayConfig replaces the … |
| `set_active_scenario` | — | confirm | Make a saved scenario the model's active one (the preset the web UI loads its run controls from) |
| `delete_scenario` | — | confirm | Remove a saved scenario preset from the model (stored runs are untouched) |
| `set_custom_dsl` | `PUT /api/scenarios/dsl` | confirm | Replace the model's custom-constraint DSL sheet (RAGNAROK_CustomDSL) — one constraint per line, e.g. 'gen("gas") <= 120' or 'emissions() <= 5000' |

**Result metrics (`tools_results_extra.py`)**

| Tool | Endpoint(s) | Gate | What it does |
|---|---|---|---|
| `get_metric_options` | `GET /api/runs/{name}/metrics` | — | Chart-ready metrics (rows, series, colours) of one per-asset focus (generator, bus, storageUnit, store, branch, process, shuntImpedance) of a stored run - the options the Analytics chart card offers; narrow by `keys`, `group_by`, `bus_filter`, `carrier_filter`, `period`, `end`. Returns `{run, focus, items, total}` |
| `get_period_results` | `GET /api/runs/{name}/period/{period}` | — | The result payload of ONE investment period of a pathway run, from that period's slice of `n.statistics` (inactive assets masked, money x the period's objective weight, energy summed); compact sections by default, `fields` for others. Returns `{run, period, result}`. `get_kpis`, `compare_companies`, `get_asset_details` and `get_metric_options` take the same `period` |
| `get_run_analysis` | `GET /api/runs/{name}/analysis/{topic}` | — | The Analytics-card metrics the browser no longer computes (P28), by `topic`: `load-analysis` (system peak / energy, load factor, coincidence, per-bus shares), `carrier-performance` (nameplate / generated MW, energy, shares, `n.statistics` capacity factor and curtailment, totals), `transition-risk` (company net margin while the carbon price rises; `base_year`, `years`, `base_price`, `escalation_pct`, `stranded_threshold`, `demand_growth_pct`, `fuel_growth_pct`), `duration-curve` (`source` price or load, ranked descending) and `totals` (sums over result rows). `period` picks a pathway investment period. Mean nodal price per bus is `get_asset_details(kind='buses')` field `averageSmp` |

**Analysis and Forge edits (`tools_analysis.py`)**

| Tool | Endpoint(s) | Gate | What it does |
|---|---|---|---|
| `compare_runs` | `GET /api/results/compare` | — | Side-by-side comparison of 2-5 stored runs - the Analytics -> Comparison matrix as data. 'topics' picks columns of detail: kpi (summary KPIs with the generator/storage capacity split), … |
| `get_kpis` | `GET /api/runs/{name}/kpis` | — | The KPI strip of a stored run: total cost, dispatch MWh, load-weighted average price (`runMeta.averageSystemPrice` = `n.statistics.prices(weighting="load")`; the unweighted series mean only for runs stored before that field), min/max price, peak load MW, load factor, renewable share % (zero-emission carriers excluding nuclear and storage), … |
| `compare_companies` | `GET /api/runs/{name}/companies` | — | Company comparison for a stored run: the per-owner breakdown (capacity, energy, revenue, emissions), project finance (NPV, IRR, payback) and P&L (net margin) joined by company and ranked by … |
| `get_asset_details` | `GET /api/runs/{name}/assets` | — | Per-asset details of a stored run. kind is one of generators, buses, storageUnits, stores, branches, processes, shuntImpedances (default all) |
| `list_conversions` | `GET /api/build/conversions` | — | The sector-coupling conversion templates (CCGT, OCGT, CHP, electrolyser, fuel cell, heat pump, resistive heater, gas boiler, methanation) with efficiency, capital cost and fuel assumptions, … |
| `snap_to_buses` | `POST /api/forge/snap` | confirm | Forge spatial snap: set bus / bus0 / bus1 of every row on 'sheet' that carries x/y (x0/y0, x1/y1 for branches) to its nearest bus within 'buffer_km' (great-circle) |
| `adjust_values` | `POST /api/forge/adjust` | confirm | Forge bulk adjust: 'adjustments' is a list of {sheet, attribute, action: multiply\|add\|set, amount, filters: [{column, value}]} (filters are ANDed equality matches; multiply amount is a … |
| `revert_adjustments` | `POST /api/forge/adjust/revert` | confirm | Undo adjust_values: restore the cells targeted by 'adjustments' to their ORIGINAL value from 'baseline' (a cell that was absent originally is removed). 'adjustments' is a list of {sheet, … |
| `add_conversion` | `POST /api/build/conversion` | confirm | Build: add one conversion technology to the working model - the Link plus any missing carrier bus, carriers and (for gas-fed templates) a fuel-supply generator, reusing existing ones. … |
| `merge_fragment` | `POST /api/session/merge-fragment` | confirm | Merge a WorkbookFragment (from import_dataset, siting_scan or PyPSA-Earth) into the working model with the GUI's 'Add to workbook' rules: rows are appended with name dedupe (never a … |

**Optimisation options, network analysis and transforms (`tools_optimise.py`)**

| Tool | Endpoint(s) | Gate | What it does |
|---|---|---|---|
| `describe_optimise_options` | `GET /api/optimise/options` | — | Installed solvers (capability flags) and every n.optimize / study option key accepted in submit_solve's options: transmissionLosses, linearizedUnitCommitment, committableBigM, … |
| `export_lp` | `POST /api/optimise/export-lp` | — | Write the working model's LP (or .mps) file WITHOUT solving, for inspection or an external solver. options may carry the same model-building keys as submit_solve (transmissionLosses, … |
| `consistency_check` | `POST /api/analysis/consistency` | — | Run PyPSA's n.consistency_check on the working model (no solve): returns errors (strict failures such as maintenance/phase-shift/scenario-invariant violations) and every warning. … |
| `network_analysis` | `POST /api/analysis/network` | — | Grid-analysis outputs of the topology (no solve): include any of subnetworks (slack bus/generator), ptdf, bodf, cycles, adjacency, incidence. cycle_basis_method bfs-refined\|paton |
| `get_statistics` | `POST /api/statistics/query` | — | One PyPSA n.statistics metric on a stored run with PyPSA's own parameters. metric: … |
| `temporal_cluster` | `POST /api/session/model`; `POST /api/transform/temporal` | confirm | Reduce the time axis with PyPSA's native temporal clustering and replace the working model. method: resample (offset like '3h' or '1D', optional drop_leap_day, aggregation_rules), … |
| `slice_model` | `POST /api/session/model`; `POST /api/transform/slice` | confirm | Keep only a snapshot window (start/end: integer positions, end exclusive, or ISO labels, inclusive) and/or a bus subset (buses) of the working model via n.slice_network |
| `merge_models` | `POST /api/session/model`; `POST /api/transform/merge` | confirm | Merge another model into the working model with n.merge: give other_run (a stored run name) OR other_session_id |
| `cluster_network_hac` | `POST /api/transform/cluster`; `POST /api/session/model` | confirm | Hierarchical agglomerative (HAC) spatial clustering to n_clusters buses on numeric bus columns (features, default ['x','y']), linkage ward\|complete\|average\|single, affinity … |
| `set_carrier_growth_limit` | `POST /api/forge/query/apply` | confirm | Set a carrier's PyPSA growth limits on the carriers sheet: max_growth (MW of NEW capacity per investment period) and/or max_relative_growth (ratio) |

**Component coverage and PyPSA-native I/O (`tools_components.py`)**

| Tool | Endpoint(s) | Gate | What it does |
|---|---|---|---|
| `apply_seasonal_rating` | `POST /api/transform/seasonal-rating`; `POST /api/session/model` | confirm | Write per-snapshot line limits (lines-s_max_pu) from summer/winter MVA ratings, via PyPSA's Lines.apply_seasonal_rating. ratings = {line: {summer: MVA, winter: MVA}}; s_nom is unchanged … |
| `set_maintenance` | `GET /api/session/sheet/{name}`; `PATCH /api/session/sheet/{name}` | confirm | Configure scheduled maintenance (PyPSA 1.3+) on a Generator, Link or Process |
| `import_pypsa_native` | `POST /api/import/pypsa-excel`; `POST /api/import/pypsa-csv`; `POST /api/import/matpower`; `POST /api/import/pandapower` | confirm | Import a PyPSA-native or grid-model file INTO the working model through PyPSA's own importers. kind (inferred from the extension when omitted): 'pypsa-excel' (.xlsx, … |
| `export_pypsa_native` | `POST /api/export/pypsa-excel`; `POST /api/export/pypsa-csv` | — | Export the CURRENT working model as a PyPSA-native Excel workbook (kind='excel', Network.export_to_excel) or a zip of a PyPSA CSV folder (kind='csv', export_to_csv_folder). … |
| `pypsa_io_capabilities` | `GET /api/import/pypsa-io/capabilities` | — | Which PyPSA-native import/export paths the backend offers, the netCDF export option keys, and whether the optional pandapower library is installed |

**Piecewise curves (`tools_piecewise.py`)**

| Tool | Endpoint(s) | Gate | What it does |
|---|---|---|---|
| `describe_piecewise` | `GET /api/piecewise/catalog` | — | Reference for piecewise-linear cost / efficiency curves (PyPSA 1.3+): which component attributes accept a curve (marginal_cost on Generator/Link/Process/StorageUnit/Store; capital_cost also … |
| `get_piecewise_curve` | `GET /api/piecewise/catalog`; `GET /api/session/model/full`; `POST /api/piecewise/check` | — | Read piecewise curves from the working model. component: 'Generator' or 'generators' etc.; name and attribute (marginal_cost \| capital_cost \| efficiency \| rate0..) narrow the result |
| `set_piecewise_curve` | `GET /api/piecewise/catalog`; `POST /api/piecewise/check`; `PATCH /api/session/sheet/{name}` | confirm | Set (replace) the piecewise curve of ONE component: component 'Generator'\|'Link'\|'Process'\|'StorageUnit'\|'Store' (capital_cost also 'Line'\|'Transformer'), name, attribute ('marginal_cost' \| … |
| `clear_piecewise_curve` | `GET /api/piecewise/catalog`; `PATCH /api/session/sheet/{name}` | confirm | Remove the piecewise curve of one component (the scalar cost / efficiency applies again). attribute omitted = every curve of that component |
| `check_piecewise_options` | `POST /api/piecewise/options/check` | — | Validate and normalise the piecewise run option |

**Self-hosted demand database (`tools_demand_db.py`, D2)**

| Tool | Endpoint(s) | Gate | What it does |
|---|---|---|---|
| `list_demand_db` | `GET /api/demand-db/coverage` | — | What the offline hourly-demand snapshot holds: per series (`opsd/DE`, `eia930/ERCO`, ...) the years, coverage, rows, retrieved date, licence, and what each source measures. MW, UTC, hour-beginning |
| `get_demand_db_slice` | `GET /api/demand-db/slice` | — | One series for `year_from..year_to` (by `series` or `country`): full-window stats (hours, TWh, peak/mean MW) plus up to `max_values` hourly values |
| `import_demand_db` | `POST /api/import/run` (`demand_db`); `POST /api/session/merge-fragment` | confirm | Put a series into the working model as a national bus, a Load and an hourly `loads-p_set` with snapshots; reads the local snapshot only, no network or key |

**Screening module (`tools_screening.py`, tool names keep the `siting_` prefix)** — read-only unless marked confirm; routes under `/api/screening/*`, see [backend.md](backend.md) §14.2. The statistic tools take `level='region'` (regions aggregated from a site dataset, or a region dataset) with `weighting`, `site_weights`, `by_technology`, `technology`.

| Tool | Gate | What it does |
|---|---|---|
| `list_siting_datasets`, `get_siting_dataset`, `validate_siting_dataset` | — | List, read and validate per-site historical series (CF 0–1, UTC) |
| `upload_siting_dataset`, `delete_siting_dataset` | confirm | Store or delete a dataset (without confirm, upload returns the validation preview) |
| `siting_correlation`, `siting_lagged_correlation`, `siting_profiles` | — | Pearson/Spearman matrices on a chosen basis, lagged cross-correlation, diurnal/seasonal profiles |
| `siting_portfolio_metrics`, `siting_optimise_portfolio`, `siting_cluster_sites` | — | Portfolio complementarity metrics, min-variance / max-CF weights, hierarchical clusters |
| `siting_region_series`, `siting_region_structure` | — | Region series in use (members, weights, centroid); within- vs between-region correlation and site-vs-region table |
| `promote_siting_sites` | confirm | Add selected sites as generators with `p_max_pu` aligned to the model's snapshots |

**P2X and plants (`tools_p2x.py`, `tools_plants.py`)**

| Tool | Gate | What it does |
|---|---|---|
| `list_p2x_technologies`, `preview_p2x_chain`, `get_p2x_results` | — | Technology data with sources; a chain preview; LCOH/LCOA/LCOM and RFNBO compliance for a run |
| `build_p2x_chain` | confirm | Add an H2 chain (electrolyser, storage, NH3/MeOH/e-fuel Processes) to the model |
| `list_plant_types`, `get_plant_results` | — | Plant types and defaults; per-plant generation, CF, starts, H2 share and CO2 avoided |
| `add_plant`, `edit_plant`, `remove_plant` | confirm | Add, re-derive or remove a whole plant (Generator, BESS, CCGT/OCGT, co-firing, P2X chain) |

**Operations and temporal modules (`tools_operations_modules.py`)** — PyPSA counts ramps, UC times and rolling windows per snapshot; these tools keep the user's hours and per-hour rates visible and write the per-snapshot values at solve time with the run's weights. See [backend.md](backend.md) §5.13.

| Tool | Gate | What it does |
|---|---|---|
| `get_time_units`, `preview_time_units` | — | The stated ramp and UC-time rows (`RAGNAROK_TimeUnits`), and what a run would write for PyPSA from them |
| `set_time_units` | confirm | Upsert time-unit rows (hours / minutes, per_hour / per_minute) |
| `set_weightings_from_spacing` | confirm | Fill the snapshot weightings from the timestamp spacing |
| `sample_workbook` | confirm | Write test-run sampling (snapshots, weights, averaged series) into the workbook |
| `make_noncyclic_for_rolling`, `relax_maintenance` | confirm | The visible steps rolling horizon and Force-LP ask for: cyclic flags off; `maintainable` off |

### 2.8 Tool catalogue by area (generated)

Every tool carries one area tag, declared next to the tool with `declare_areas({...})` and collected in `backend/mcp/catalogue.py` (the single source of truth). That registry feeds three things: the routing map in the server instructions, the read-only `tool_catalogue(area)` tool (tools of one area, one line each, plus recipes), and the block below. A test fails when a tool has no area or when this block is stale; regenerate it with `.venv-pypsa/bin/python scripts/gen_mcp_catalogue_doc.py`. The offline routing eval (`backend/tests/test_mcp_catalogue.py`, cases in `backend/tests/fixtures/mcp_routing_cases.json`) checks that a keyword search over names, descriptions and areas finds the right tool for common requests in English and Korean.

<!-- tool-catalogue:start (generated by scripts/gen_mcp_catalogue_doc.py; do not edit by hand) -->

The server has 199 tools in 13 areas (mode: R read-only, W+confirm preview then confirm=true, W writes without confirm).

| Area | Tools | Start with |
|---|---|---|
| `inspect` | 12 | `get_world_state`, `check_model`, `get_sheet_page` |
| `build` | 19 | `add_generator`, `edit_sheet`, `forge_query`, `add_component` |
| `composites` | 11 | `list_plant_types`, `add_plant`, `build_p2x_chain`, `get_plant_results` |
| `time_ops` | 9 | `get_time_units`, `set_time_units`, `retarget_snapshots` |
| `transforms` | 11 | `cluster_network`, `temporal_cluster`, `slice_model`, `sample_workbook` |
| `run` | 21 | `submit_solve`, `get_queue`, `describe_run_options`, `submit_scenario` |
| `results` | 16 | `list_runs`, `get_kpis`, `get_analytics`, `get_report` |
| `studies` | 2 | `describe_analytics`, `optimize_procurement` |
| `policy` | 9 | `set_carbon_price`, `set_annual_budget`, `set_custom_dsl`, `apply_demand_response` |
| `physical_risk` | 9 | `physical_risk_seed`, `physical_risk_run`, `physical_risk_report` |
| `siting` | 15 | `siting_scan`, `upload_siting_dataset`, `siting_portfolio_metrics` |
| `data` | 38 | `list_starter_packs`, `build_starter_pack`, `import_dataset`, `export_model` |
| `session` | 27 | `get_journal`, `undo_journal_entry`, `list_plugins`, `get_server_info` |

**`inspect`** - Inspect the model. Read what is loaded: sheets, component schema, series windows, validity checks. Never changes anything.

| Tool | Mode | What it does |
|---|---|---|
| `check_model` | R | Answer 'is this the model I asked for?' by READING the model back |
| `consistency_check` | R | Run PyPSA's n.consistency_check on the working model (no solve): returns errors (strict failures such as maintenance/phase-shift/scenario-i… |
| `derive_series` | R | Derive a chart-ready series from a sheet, computed server-side |
| `describe_component` | R | Describe a PyPSA component's full attribute schema (name, type, unit, default, required, description) |
| `get_distinct_values` | R | Sorted distinct non-empty values of one column in a working-model sheet (master=true: in the master model)  |
| `get_series_window` | R | A windowed, downsampled slice of an INPUT time-series sheet in the working session (e.g. one asset's year of a demand or p_max_pu sheet) |
| `get_sheet_page` | R | Return one page of a sheet's rows (static or time-series) |
| `get_sheet_stats` | R | Per-column statistics for an input sheet (count, nulls, min/max/mean/median/std/quartiles/histogram |
| `get_world_state` | R | What is loaded right now in the working session: buses, carriers, snapshot window, sheet list and sizes |
| `list_components` | R | List every PyPSA component type Ragnarok supports (Bus, Generator, Line, Link, Transformer, StorageUnit, Store, Carrier, GlobalConstraint,… |
| `network_analysis` | R | Grid-analysis outputs of the topology (no solve): include any of subnetworks (slack bus/generator), ptdf, bodf, cycles, adjacency, incidence |
| `validate_model` | R | Validate the working model WITHOUT solving  |

Recipes:

- what is loaded and is it right: get_world_state -> check_model -> validate_model
- look inside a sheet: get_sheet_stats -> get_sheet_page -> derive_series

**`build`** - Build and edit components. Add or change buses, generators, loads, lines, storage and any PyPSA component; bulk edits; piecewise cost curves.

| Tool | Mode | What it does |
|---|---|---|
| `add_bus` | W+confirm | Add a bus (node) to the working model |
| `add_component` | W+confirm | Add ANY PyPSA component (generic constructor over the full registry) |
| `add_generator` | W+confirm | Add a generator on a bus. Set p_nom_extendable=true for capacity expansion. capital_cost is PyPSA's periodised cost per MW for the MODELLED… |
| `add_line` | W+confirm | Add an AC transmission line between two buses (bus0, bus1) |
| `add_load` | W+confirm | Add a load (electricity demand) on a bus |
| `add_storage` | W+confirm | Add a battery (BESS, 배터리), pumped hydro or other storage unit on a bus (basic StorageUnit row |
| `adjust_carrier_capacity` | W+confirm | Increase or decrease the total installed capacity of a carrier (e.g. all gas, wind or solar generators) to a target (MW), distributed acros… |
| `adjust_values` | W+confirm | Increase, decrease or set values in bulk, e.g. scale all gas generator capacity or costs by a percentage (Forge bulk adjust): 'adjustments'… |
| `apply_seasonal_rating` | W+confirm | Write per-snapshot line limits (lines-s_max_pu) from summer/winter MVA ratings, via PyPSA's Lines.apply_seasonal_rating |
| `clear_piecewise_curve` | W+confirm | Remove the piecewise curve of one component (the scalar cost / efficiency applies again) |
| `describe_piecewise` | R | Reference for piecewise-linear cost / efficiency curves (PyPSA 1.3+): which component attributes accept a curve (marginal_cost on Generator… |
| `edit_sheet` | W+confirm | Edit a sheet in the working session |
| `forge_query` | W+confirm | Bulk conditional edit — Ragnarok's Forge Query & Edit. Select a component 'target' sheet (e.g. 'generators') and an 'attribute' column; nar… |
| `get_piecewise_curve` | R | Read piecewise curves from the working model |
| `remove_component` | W+confirm | Remove components by name (any component type) |
| `revert_adjustments` | W+confirm | Undo adjust_values: restore the cells targeted by 'adjustments' to their ORIGINAL value from 'baseline' (a cell that was absent originally… |
| `set_component` | W+confirm | Set attributes on an existing component (by name)  |
| `set_piecewise_curve` | W+confirm | Set (replace) the piecewise curve of ONE component: component 'Generator'\|'Link'\|'Process'\|'StorageUnit'\|'Store' (capital_cost also 'Line'\|… |
| `snap_to_buses` | W+confirm | Forge spatial snap: set bus / bus0 / bus1 of every row on 'sheet' that carries x/y (x0/y0, x1/y1 for branches) to its nearest bus within 'b… |

Recipes:

- build a small network from scratch: add_bus -> add_generator -> add_load -> add_line -> set_snapshots -> validate_model
- bulk-change a column with a preview: adjust_values -> adjust_values(confirm=true) -> get_journal_diff

**`composites`** - Plants and composite builders (CCGT, OCGT, BESS, co-firing, P2X, hydrogen). Add one plant as a unit (CCGT/OCGT with part-load and start costs, gas+H2 co-firing, BESS battery) or a power-to-X hydrogen/ammonia/methanol chain, then read plant-level results (LCOH, H2 share, CO2 avoided).

| Tool | Mode | What it does |
|---|---|---|
| `add_conversion` | W+confirm | Add a heat pump, electric boiler, CHP, fuel cell, methanation or simple gas turbine conversion link to the working model - the Link plus an… |
| `add_plant` | W+confirm | Add a CCGT, OCGT gas turbine (가스터빈), BESS battery (배터리), plain generator, gas + hydrogen co-firing or P2X plant to the model as one unit, w… |
| `build_p2x_chain` | W+confirm | Build a hydrogen (electrolyser) / ammonia / methanol / e-fuel power-to-X chain into the working model through the fragment merge (buses, ca… |
| `edit_plant` | W+confirm | Edit a CCGT / OCGT / BESS battery / co-firing plant (change capacity, bus, efficiency, hydrogen share) |
| `get_p2x_results` | R | P2X results of a stored run (hydrogen production cost 수소 생산 단가): LCOH per kg H2, LCOA per t NH3, LCOM per t MeOH, e-fuel cost per MWh and p… |
| `get_plant_results` | R | Results of a stored run grouped by plant id (server-side groupby): per plant the generation, capacity factor, full-load hours, starts (solv… |
| `list_conversions` | R | The sector-coupling conversion templates (CCGT, OCGT, CHP, electrolyser, fuel cell, heat pump, resistive heater, gas boiler, methanation) w… |
| `list_p2x_technologies` | R | P2X technology data used by the chain builder: electrolysers (alkaline, PEM), H2 compression and storage (tank, salt cavern), air separatio… |
| `list_plant_types` | R | List the plant types add_plant accepts (CCGT, OCGT gas turbine, BESS battery, generator, gas + hydrogen co-firing, P2X) with fields, defaul… |
| `preview_p2x_chain` | R | Preview a P2X chain (electrolyser, H2 compression and storage, ammonia / methanol / e-fuel synthesis, N2 and CO2 supply, product tanks, off… |
| `remove_plant` | W+confirm | Remove a CCGT / OCGT / BESS battery / co-firing plant |

Recipes:

- add a CCGT on bus X and solve: list_plant_types -> add_plant -> add_plant(confirm=true) -> submit_solve -> get_plant_results
- hydrogen production cost (LCOH): list_p2x_technologies -> preview_p2x_chain -> build_p2x_chain(confirm=true) -> submit_solve -> get_p2x_results
- add a simple conversion link (heat pump, boiler, CHP): list_conversions -> add_conversion -> add_conversion(confirm=true)

**`time_ops`** - Time units and operations. Ramp rates, minimum up/down time and start-up times stated in hours or minutes; snapshot step and weightings; maintenance.

| Tool | Mode | What it does |
|---|---|---|
| `get_time_units` | R | The ramp and unit-commitment times of the working model, as stated by the user (sheet RAGNAROK_TimeUnits): component generators \| links \| p… |
| `make_noncyclic_for_rolling` | W+confirm | Rolling horizon refuses cyclic storage (each window starts from the previous window's end state) |
| `preview_time_units` | R | What a run with these options would write for PyPSA from the time-units rows: per row the stated value, the step in hours (smallest stores… |
| `relax_maintenance` | W+confirm | Force-LP is PyPSA's linearized unit commitment and cannot relax scheduled maintenance (no native switch), so a Force-LP run with maintainab… |
| `retarget_snapshots` | W+confirm | Change the time step / resolution (시간 단위, e.g. hourly to 3-hourly) and the date window: regenerate the snapshot index over [start,end] at s… |
| `set_maintenance` | W+confirm | Configure scheduled maintenance (PyPSA 1.3+) on a Generator, Link or Process |
| `set_snapshots` | W+confirm | Set the model's snapshots (time steps) from an explicit list of timestamps, e.g. ['2030-01-01 00:00','2030-01-01 01:00'] |
| `set_time_units` | W+confirm | Set ramp rates and minimum up / down times (hours, minutes, per minute) of generators, links and CCGT units |
| `set_weightings_from_spacing` | W+confirm | Fill objective / stores / generators of the snapshots sheet from the timestamp spacing (each snapshot weighs the gap to the next |

Recipes:

- state a ramp limit in per-minute or hours: get_time_units -> set_time_units -> preview_time_units
- change the time step to 3 hours: retarget_snapshots -> set_weightings_from_spacing -> validate_model

**`transforms`** - Transforms (cluster, slice, merge, sample, reshape). Reduce or reshape the working model: spatial clustering, temporal clustering, window/bus slice, merge another model, test-run sampling, demand forecast, series scaling.

| Tool | Mode | What it does |
|---|---|---|
| `cluster_network` | W+confirm | Cluster/reduce the network to fewer buses (method: modularity\|kmeans) or merge buses sharing a column value (group_by_column, e.g. 'country… |
| `cluster_network_hac` | W+confirm | Hierarchical agglomerative (HAC) spatial clustering to n_clusters buses on numeric bus columns (features, default ['x','y']), linkage ward\|… |
| `derive_from_master` | W+confirm | Derive this session's working model from its stored multi-year MASTER by keeping only selected 'years' and applying attribute 'filters' ([{… |
| `driver_forecast` | W+confirm | Driver-based demand forecast  |
| `ev_reshape_demand` | W+confirm | Reshape per-region demand from an EV fleet's daily movement (home overnight, work daytime) |
| `forecast_demand` | W+confirm | Forecast demand growth to a future year (load projection) |
| `merge_models` | W+confirm | Merge another model into the working model with n.merge: give other_run (a stored run name) OR other_session_id |
| `sample_workbook` | W+confirm | Representative-day sampling for a fast test run, written into the workbook: the sampled snapshots, their weightings (objective/generators =… |
| `slice_model` | W+confirm | Keep only part of the model, e.g. the first week of snapshots or a subset of buses |
| `temporal_cluster` | W+confirm | Reduce the number of snapshots (representative days, resampling, downsampling) to speed up a run, with PyPSA's native temporal clustering a… |
| `transform_series` | W+confirm | Bulk-transform a time-series sheet (e.g. loads-p_set, generators-p_max_pu) |

Recipes:

- make the model small for a quick test: cluster_network -> cluster_network(confirm=true) -> slice_model -> validate_model
- project demand to 2040: forecast_demand -> forecast_demand(confirm=true) -> check_model

**`run`** - Run and solve. Queue solves, watch and cancel them, saved scenarios, run options and solver reference, stored-run housekeeping.

| Tool | Mode | What it does |
|---|---|---|
| `cancel_solve` | W | Cancel or stop a queued or running solve (kill it)  |
| `check_piecewise_options` | R | Validate and normalise the piecewise run option |
| `delete_queue_item` | W+confirm | Delete a queue item and its retained model payload (prune the queue) |
| `delete_run` | W+confirm | Delete a stored run from History (bundle + meta) |
| `delete_scenario` | W+confirm | Remove a saved scenario preset from the model (stored runs are untouched) |
| `describe_optimise_options` | R | Installed solvers (capability flags) and every n.optimize / study option key accepted in submit_solve's options: transmissionLosses, linear… |
| `describe_run_options` | R | Reference for EVERY key submit_solve's scenario/options accept: type, default, unit, allowed values, meaning and the backend reader, for ~5… |
| `describe_scenario` | R | One saved scenario in full (every preset field) and the exact {scenario, options} run body submit_scenario would send |
| `export_lp` | W | Write the working model's LP (or .mps) file WITHOUT solving, for inspection or an external solver |
| `get_queue` | R | The solve queue: jobs with their status (queued/running/done/error) and concurrency settings |
| `list_scenarios` | R | List the model's saved scenario presets (id, label, window, carbon price, enabled study modes, constraint count, model overrides), its carb… |
| `load_queue_item` | W+confirm | Load a queue item's model snapshot back into the working model (to tweak and re-run as a new entry) |
| `promote_run` | W+confirm | Load a stored run's input model back into the working session as the editable model  |
| `rename_run` | W+confirm | Rename a stored run (its file, identity and display labels together)  |
| `rerun_queue_item` | W+confirm | Re-run a staged, finished or cancelled queue item in place  |
| `save_scenario` | W+confirm | Create or update a saved scenario preset  |
| `set_active_scenario` | W+confirm | Make a saved scenario the model's active one (the preset the web UI loads its run controls from) |
| `set_queue_concurrency` | W+confirm | Set the maximum number of concurrent solves (1 = serial) |
| `submit_scenario` | W+confirm | Solve ONE saved scenario exactly as the web UI's scenario run would (preset + the model's DSL sheet + solver defaults) - no hand-built opti… |
| `submit_scenarios` | W+confirm | Queue SEVERAL saved scenarios as a batch (scenario_ids=None or [] runs ALL saved scenarios), one queue job each with a distinct run label,… |
| `submit_solve` | W+confirm | Run / solve (optimise) the working model (submits to the queue  |

Recipes:

- solve the working model and read the cost: validate_model -> submit_solve -> submit_solve(confirm=true) -> get_queue -> get_kpis
- run saved scenarios as a batch: list_scenarios -> submit_scenarios -> submit_scenarios(confirm=true) -> compare_runs

**`results`** - Results and analytics. Read stored runs: KPIs, carrier mix, prices, cost, emissions, dispatch series, PyPSA statistics, comparison, reports.

| Tool | Mode | What it does |
|---|---|---|
| `compare_companies` | R | Company comparison for a stored run: the per-owner breakdown (capacity, energy, revenue, emissions), project finance (NPV, IRR, payback) an… |
| `compare_run_statistics` | R | PyPSA-native statistics side by side for 2-5 stored runs, evaluated in ONE pypsa.NetworkCollection (n.statistics with PyPSA's own definitio… |
| `compare_runs` | R | Compare scenarios: side-by-side comparison (base vs alternative) of 2-5 stored runs - the Analytics -> Comparison matrix as data |
| `get_analytics` | R | Full analytics for a stored run: summary, carrier mix, cost, emissions, adequacy |
| `get_asset_details` | R | Per-asset details of a stored run |
| `get_derived` | R | A specific derived metric for a stored run: hourly dispatch by carrier (dispatch_by_carrier), duration curve, generation series |
| `get_kpis` | R | Headline results of a stored run: total system cost, emissions, dispatch MWh, load-weighted average price (n.statistics.prices), min/max pr… |
| `get_metric_options` | R | Chart-ready metrics of one per-asset focus of a stored run - what the Analytics chart card offers: rows, series and colours per metric opti… |
| `get_period_results` | R | The result payload of ONE investment period of a stored pathway (multi-period) run, extracted from that period's slice of n.statistics: ass… |
| `get_report` | R | Assemble the deterministic report document for a stored run under a perspective (run_name may be 'latest') |
| `get_run_analysis` | R | Analytics-card metrics of a stored run, computed on the server (the UI cards show the same numbers) |
| `get_run_model_sheet` | R | One page of a STORED run's input model sheet (what that run solved), e.g. to compare it with the working model |
| `get_run_series` | R | A windowed, downsampled slice of a stored run's OUTPUT time-series sheet  |
| `get_statistics` | R | One PyPSA n.statistics metric on a stored run with PyPSA's own parameters |
| `list_report_perspectives` | R | List the report perspectives (policy maker, investor, PPA buyer, lender, procurement) with their audience and section outline |
| `list_runs` | R | List stored solve runs (newest first) with their names and metadata |

Recipes:

- explain a run: list_runs -> get_kpis -> get_analytics -> get_report
- compare two runs: list_runs -> compare_runs -> compare_run_statistics

**`studies`** - Reliability and market studies. Adequacy (LOLE/EENS), reserves, forced-outage Monte Carlo, ramping, ELCC, LMP decomposition, procurement hedging; enabled as options on a normal solve.

| Tool | Mode | What it does |
|---|---|---|
| `describe_analytics` | R | Reliability and adequacy (loss of load, LOLE, EENS) and market analytics: the seven solve-mode reliability/market analytics (reserves, forc… |
| `optimize_procurement` | R | Optimise a power-procurement hedging mix: CVaR-constrained least-cost blend of PPA / forward / retail instruments over a price series, plus… |

Recipes:

- run an adequacy and reserve study: describe_analytics -> describe_run_options -> submit_solve -> submit_solve(confirm=true) -> get_analytics

**`policy`** - Policy (carbon, budgets, constraints, demand response). Carbon price (flat or schedule), annual energy/emission budgets, custom constraint DSL, carrier growth limits, demand response; RFNBO is a run option.

| Tool | Mode | What it does |
|---|---|---|
| `apply_annual_budgets` | W+confirm | Write the module's horizon values (annual x sum(w)/8760) into the e_sum / constant cells of the working model, so the workbook shows what P… |
| `apply_demand_response` | W+confirm | Write the demand-response module's rows into the working model (buses / links / stores / loads / generators / carriers), replacing its prev… |
| `get_annual_budgets` | R | The annual-budgets sheet (RAGNAROK_AnnualBudgets) and the horizon values the module writes for the model's own horizon: annual x sum(w)/876… |
| `get_carbon_price` | R | What the carbon-pricing module sends PyPSA for a price: per emitting generator the carbon cost per MWh (price x co2_emissions / efficiency)… |
| `get_demand_response` | R | Demand response as workbook rows: what the module would write for a config (shiftable load: bus dr_<load>, link drlink_<load> from the pare… |
| `set_annual_budget` | W+confirm | Cap or floor the annual energy (TWh) or CO2 emissions of a generator or carrier (annual budget) |
| `set_carbon_price` | W+confirm | Set the carbon price (탄소 가격, CO2 price / tax, currency per tCO2) of a saved scenario preset (the module's input): price (currency/tCO2) and… |
| `set_carrier_growth_limit` | W+confirm | Set a carrier's PyPSA growth limits on the carriers sheet: max_growth (MW of NEW capacity per investment period) and/or max_relative_growth… |
| `set_custom_dsl` | W+confirm | Add custom constraints, e.g. a CO2 emissions cap or a generation limit per carrier: replace the model's custom-constraint DSL sheet (RAGNAR… |

Recipes:

- price carbon and compare: set_carbon_price -> set_carbon_price(confirm=true) -> submit_scenario -> compare_runs
- cap a carrier's annual energy: get_annual_budgets -> set_annual_budget -> apply_annual_budgets

**`physical_risk`** - Physical climate risk. A separate subsystem (own session id): seed a portfolio from the model, set perils/climate/horizon, run, read damage, transition and finance results.

| Tool | Mode | What it does |
|---|---|---|
| `physical_risk_finance` | W | Compute the Climate Risk Premium (finance) for a DONE physical run  |
| `physical_risk_get_portfolio` | R | The physical-risk portfolio (assets + scenario config) for a session |
| `physical_risk_get_run` | R | Poll one physical-risk run by id (a pure status read) |
| `physical_risk_libraries` | R | The physical-risk methodology libraries: perils, climate/NGFS scenarios, vulnerability classes, impact functions and finance reference  |
| `physical_risk_report` | R | The physical-risk report bundle for a session: portfolio, latest result per run kind, transition and (when available) finance |
| `physical_risk_run` | W | Submit a physical-risk analysis (kind defaults to 'physical') for the seeded portfolio and POLL to completion up to poll_seconds |
| `physical_risk_seed` | W | Start a physical climate-risk analysis (flood, heatwave, wildfire damage to assets): seed a physical-risk portfolio from the CURRENT workin… |
| `physical_risk_set_scenario` | W | Update the portfolio's scenario in place: set any of perils (peril ids), climate (RCP/SSP id), horizon_year, sector |
| `physical_risk_transition` | W | Compute the portfolio's transition (NGFS carbon-cost) risk  |

Recipes:

- climate damage for the current model: physical_risk_seed -> physical_risk_set_scenario -> physical_risk_run -> physical_risk_report

**`siting`** - Siting and screening. Screen candidate solar/wind sites: scan a bounding box, upload site series, correlation, portfolio diversification, promote chosen sites into the model.

| Tool | Mode | What it does |
|---|---|---|
| `delete_siting_dataset` | W+confirm | Delete a stored siting-screening dataset (series + site table) |
| `get_siting_dataset` | R | One siting-screening dataset: its sites (name, lat, lon, technology, region, unit, mean CF), step, window and the full validation report (t… |
| `list_siting_datasets` | R | List the siting-screening datasets stored for this session (uploaded per-site capacity-factor series + site table, or reference load / pric… |
| `promote_siting_sites` | W+confirm | Add screened sites to the working model as generators with p_max_pu profiles from the dataset, aligned to the model's snapshots (exact time… |
| `siting_cluster_sites` | R | Hierarchical clustering of sites on 1 - correlation (linkage average\|complete\|single\|ward) |
| `siting_correlation` | R | Which wind or solar sites are correlated or complementary: site-by-site correlation matrix (Pearson or Spearman) of a screening dataset on… |
| `siting_lagged_correlation` | R | Lagged cross-correlation of one site against others, lags -N..+N hours (weather fronts moving between sites) |
| `siting_optimise_portfolio` | R | Choose the best mix of complementary wind / solar sites: long-only portfolio optimiser over the chosen sites (weights >= 0, sum 1) |
| `siting_portfolio_metrics` | R | How complementary are wind and solar sites: complementarity metrics of a weighted portfolio of sites (weights {site: w}, normalised to sum… |
| `siting_profiles` | R | Mean-CF profiles per site: diurnal (24 hour-of-day values), monthly (12) and seasonal (DJF/MAM/JJA/SON or season_map), optionally a down-sa… |
| `siting_region_series` | R | The region series in use at region level: each region's members and normalised weights (when aggregated from a site dataset: CF_region = su… |
| `siting_region_structure` | R | Does spreading capacity across regions buy diversification? On a site dataset: the distribution (n, mean, median, std, min, q1, q3, max) of… |
| `siting_scan` | W+confirm | Siting scan: sample candidate solar/wind sites in a bbox [minLon, minLat, maxLon, maxLat], fetch their weather (open-meteo \| pvgis \| nasa-p… |
| `upload_siting_dataset` | W+confirm | Store a siting-screening dataset server-side for this session (survives reload |
| `validate_siting_dataset` | R | Validate an upload WITHOUT storing it |

Recipes:

- pick complementary wind and solar sites: validate_siting_dataset -> upload_siting_dataset -> siting_correlation -> siting_optimise_portfolio -> promote_siting_sites

**`data`** - Data import and export. Bring data in (country models, starter packs, datasets, demand database, weather profiles, PyPSA-Earth, files) and write models and runs out.

| Tool | Mode | What it does |
|---|---|---|
| `attach_hydro_inflow` | W+confirm | Fetch GloFAS river-discharge-shaped inflow (keyless Open-Meteo Flood API) for the model's hydro storage units and attach it as storage_unit… |
| `attach_renewable_profiles` | W+confirm | Fetch weather-derived capacity-factor profiles for the model's existing solar/wind fleet and attach them, aligning the snapshot axis to the… |
| `build_starter_pack` | W+confirm | Assemble a runnable workbook for a country + year from its starter-pack recipe and load it |
| `clear_master` | W+confirm | Remove the stored master model (the working model is untouched) |
| `delete_import_secret` | W+confirm | Remove a stored importer API key |
| `export_model` | W | Export the CURRENT working model to a file: format ∈ netcdf \| hdf5 \| project |
| `export_pypsa_native` | W | Export the CURRENT working model as a PyPSA-native Excel workbook (kind='excel', Network.export_to_excel) or a zip of a PyPSA CSV folder (k… |
| `export_run` | W | Export a STORED run to a file on disk |
| `export_workbook` | W | Save / export the CURRENT working model to an Excel workbook (.xlsx), input-only  |
| `get_demand_db_slice` | R | Hourly load of one series from the self-hosted demand database for year_from..year_to (UTC years, max 12) |
| `get_import_provenance` | R | Recent data imports from the persistent provenance log (source, dataset, country, filters, time), newest first |
| `get_master_meta` | R | Metadata for the multi-year MASTER model stored in this session (its sheets and the calendar 'years' it spans), or {} if none is stored |
| `import_dataset` | W+confirm | Import one source's datasets for a country and merge them into the working model |
| `import_demand_db` | W+confirm | Import one series from the self-hosted demand database into the working model: a national bus, a Load and an hourly loads-p_set series over… |
| `import_master` | W+confirm | Store a multi-year project (.zip/.xlsx on disk) as the MASTER model  |
| `import_network` | W+confirm | Import a PyPSA-native netCDF (.nc) or HDF5 (.h5) file from disk INTO the working model (format inferred from the extension) |
| `import_project` | W+confirm | Import a Ragnarok Project .zip (or workbook .xlsx) from disk |
| `import_pypsa_native` | W+confirm | Import a PyPSA-native or grid-model file INTO the working model through PyPSA's own importers |
| `import_result` | W+confirm | Import a RESULT-bearing file from disk as a new History run (model + results): a Ragnarok project .zip, or a bare results .xlsx from anothe… |
| `list_demand_db` | R | What the self-hosted hourly demand database holds: per series (key 'source/area', e.g. 'opsd/DE', 'eia930/ERCO') the country, years, covera… |
| `list_examples` | R | List the bundled example models (id, label, description) |
| `list_import_countries` | R | The country index importers accept (ISO codes and names) |
| `list_import_databases` | R | The flat dataset registry: one entry per importable dataset across every source (id, source, kind, filters) |
| `list_import_secrets` | R | Names of the API keys the backend holds for importers (stored on the server or set in its environment) |
| `list_importers` | R | List the data-import sources Ragnarok knows, with their per-country datasets and filters |
| `list_starter_packs` | R | Country starter-pack recipes (country → years) that build_starter_pack can assemble |
| `load_example` | W+confirm | Load an example model (sample network) as the working model (replaces the current model) |
| `merge_fragment` | W+confirm | Merge a WorkbookFragment (from import_dataset, siting_scan or PyPSA-Earth) into the working model with the GUI's 'Add to workbook' rules: r… |
| `one_click_model` | W+confirm | One-click: import a country's power plants, network and demand: assemble a runnable model for a country from keyless global sources (OSM ne… |
| `pypsa_earth_apply` | W+confirm | Load a finished PyPSA-Earth build into Ragnarok |
| `pypsa_earth_build` | W+confirm | Start a PyPSA-Earth build for a country (country_iso like 'KR'): runs the snakemake workflow in the background (can take hours, downloads d… |
| `pypsa_earth_build_status` | R | Status of one PyPSA-Earth build job (queued / running / done / error / stopped, phase, detail) |
| `pypsa_earth_configure` | W+confirm | Point Ragnarok at a pypsa-earth checkout on the server (must contain a Snakefile) |
| `pypsa_earth_status` | R | PyPSA-Earth: whether the workflow is set up on the server (and where), suggested checkout dirs, and every build job this backend knows about |
| `pypsa_earth_stop` | W+confirm | Stop a running PyPSA-Earth build |
| `pypsa_io_capabilities` | R | Which PyPSA-native import/export paths the backend offers, the netCDF export option keys, and the state of the isolated pandapower environm… |
| `set_import_secret` | W+confirm | Store an importer API key on the backend (e.g. name='entsoe_token') |
| `source_health` | R | Which upstream data sources are reachable right now |

Recipes:

- a runnable model for a country: list_starter_packs -> build_starter_pack -> build_starter_pack(confirm=true) -> check_model
- save the model to a file: export_workbook -> export_model

**`session`** - Session, journal, plugins. Undo and journal of edits, clear session, server health and log, backend plugins and tab modules.

| Tool | Mode | What it does |
|---|---|---|
| `clear_session` | W+confirm | Clear the working model in this session (start from an empty network) |
| `delete_plugin_file` | W+confirm | Delete one uploaded data file from a backend plugin |
| `get_journal` | R | The mutation journal — newest-first entries of every edit made to the session (by you or the user), with actor, kind and a summary. Read it… |
| `get_journal_diff` | R | The detailed before/after diff for one journal entry (cell-level or sheet-level) |
| `get_plugin` | R | One backend plugin's manifest: hooks, GUI config schema, actions and options sources |
| `get_plugin_options` | R | Ask a backend plugin for the choices of one of its dropdowns ('name' = the options source in its manifest), given the current config |
| `get_server_info` | R | Which Ragnarok this is and whether it is ready: health checks (store, queue, solver, disk), warm-up status, checkout root + data dir, optim… |
| `get_server_log` | R | Recent backend log lines (HTTP access, errors, backend loggers), newest last |
| `install_plugin` | W+confirm | Install (or update) a BACKEND plugin from a .zip or a directory on disk holding manifest.json + plugin.py |
| `install_tab_module` | W+confirm | Install a third-party tab-module from a DIRECTORY on this machine  |
| `install_tab_module_zip` | W+confirm | Install a third-party tab-module from a .zip on disk (the zip form of install_tab_module, which takes a directory) |
| `list_plugin_files` | R | List the data files uploaded to a backend plugin (referenced by name in its config) |
| `list_plugins` | R | List installed plugins and their ids/config |
| `list_tab_modules` | R | List third-party tab-modules installed on the server: id, label, activity-bar order, whether the tab is shown, and the package's files |
| `refresh_plugins` | R | Re-scan the plugins directory (picks up a plugin copied in by hand) and list the loaded backend plugins |
| `reload_config` | W+confirm | Rebuild the cached PyPSA schema/config bundle (after the PyPSA package changed) without restarting the backend |
| `remove_tab_module` | W+confirm | Uninstall a third-party tab-module: deletes its package directory on the server and removes its tab |
| `revert_session` | W+confirm | Revert the session to a past version by undoing EVERY entry newer than to_version (newest first) |
| `run_plugin_action` | W+confirm | Run a backend plugin's named action hook (a manifest 'action' button, e.g. 'Fill table') with a config |
| `run_plugin_analysis` | R | Run an installed plugin's read-only analyze(result, config) hook and return its output  |
| `run_plugin_contribute` | W+confirm | Run an installed plugin's contribute(model, config) hook and MERGE its produced sheets + DSL constraints into the working model (additive,… |
| `run_plugin_transform` | W+confirm | Run an installed plugin's transform(model, config) hook, which rewrites the working model and persists it |
| `set_tab_module_enabled` | W+confirm | Show or hide an installed tab-module's tab |
| `tool_catalogue` | R | Find the right Ragnarok tool for a task |
| `undo_journal_entry` | W+confirm | Undo my last edit: undo a single journal entry by id (self-correct a bad edit) |
| `uninstall_plugin` | W+confirm | Uninstall a backend plugin: deletes its directory and its uploaded data files |
| `upload_plugin_file` | W+confirm | Upload a data file from disk into a backend plugin's server-side store (e.g. the workbook a dashboard importer reads) |

Recipes:

- undo a bad edit: get_journal -> get_journal_diff -> undo_journal_entry -> undo_journal_entry(confirm=true)
- run a plugin analysis on a run: list_plugins -> get_plugin -> run_plugin_analysis

<!-- tool-catalogue:end -->

---

## 3. LLM provider abstraction

One interface, several backends. Tool-calling is the hard part — strong models do it natively; local models need help.

```python
class LLMProvider(Protocol):
    async def chat(self, messages, tools, *, system, max_tokens) -> LLMTurn: ...
    # LLMTurn = { text: str, tool_calls: list[ToolCall], stop_reason, usage }
    capability: Literal["strong", "medium", "weak"]
```

| Adapter | How | Tool-calling | Tier |
|---|---|---|---|
| **Claude API** (Anthropic SDK) | `claude-opus-4-8` / `claude-sonnet-5` | native tool use (best) | strong |
| **Claude Code / CLI** | subprocess or the Agent SDK, pointed at the **MCP server** | native; Claude Code already *is* an agent loop | strong |
| **Local — Hermes** (Ollama / llama.cpp OpenAI-compat) | OpenAI-style function calling; Hermes-3 / Hermes-2-Pro have strong FC | normalise OpenAI `tool_calls` ↔ our schema | medium |
| **Local — generic** | JSON/ReAct protocol with a strict grammar + repair loop | constrained decoding, retry-on-malformed | weak |

**Capability tiers change the strategy, not the tools:**
- *strong* — hand it the full tool catalog and the goal; let it plan freely.
- *medium* — a **narrower** catalog per phase (only data tools during data-in), structured JSON, and a validate-and-repair wrapper on every tool call.
- *weak* — a **scripted skeleton** where the LLM only fills slots (pick country, pick carriers, choose carbon price) and the orchestrator owns control flow. Bifrost degrades gracefully instead of failing.

Model choice is a **user setting** (BYOK keys already live in the secrets store; local endpoint URL is config). The orchestrator is model-agnostic.

---

## 4. The agent loop

A bounded **plan → act → observe → reflect** cycle. The session store is working memory, so the agent stays small in context — it *reads state back* each step instead of carrying the whole model.

```
1. UNDERSTAND  parse goal → a checklist (region, year, tech mix, run mode, questions to answer)
2. PLAN        order the steps; identify confirmation gates & missing inputs (→ ask user, L2)
3. ACT         call one tool
4. OBSERVE     read the result + refreshed world-state summary
5. REFLECT     on error/infeasible → diagnose (Q2) → repair; else advance
6. REPORT      when the checklist is done: narrate results, cite the numbers, offer next steps
```

**Guardrails (hard limits):** max iterations, token/cost budget per session, wall-clock cap, and a "no repeated identical tool call" circuit-breaker. Exceeding a budget pauses and asks the user.

**Grounding each turn:** a compact *world-state* block (loaded sheets, carriers, snapshot window, run status) + retrieval tools for the schema (never dump the full PyPSA registry — it's huge; fetch `describe_component` on demand). Few-shot exemplars of good sessions.

**Self-correction is a first-class path, not an exception:** Ragnarok already computes infeasibility diagnoses (Q2) and calibration references (Ember I7, adequacy A2). On a failed or implausible solve, feed those back verbatim so the agent fixes the model (raise a starved `e_sum_max`, add capacity, relax a constraint) and re-solves.

---

## 5. Verification & trust (the part that makes it usable, not a toy)

An agent that silently builds a *wrong* model is worse than none. Layers:

1. **Validate before solve** — schema-check every edit against the PyPSA registry (reject hallucinated attributes at the tool boundary, not at solve time); check the model has buses/loads/generators and a snapshot window.
2. **Infeasibility repair loop** — Q2 diagnosis → agent fix → re-solve, capped at N attempts, then hand back to the human with the diagnosis.
3. **Sanity vs reality** — after a solve, compare carrier mix / total generation against **Ember** (I7) for that country and flag order-of-magnitude divergences; check adequacy (A2).
4. **Numeric narration is cited, not vibes** — every claim in the final report links to the analytics field it came from (the report is generated *from* `get_analytics`, not free-composed).
5. **Full audit trail** — reuse the provenance-log pattern: every tool call, its args, and its result are logged, so a session is replayable and reviewable.

---

## 6. UI — the Bifrost surface

A new **Assistant** tab (activity bar), consistent with the existing view shell:
- **streaming chat** with tool-call **cards** ("Importing OSM network for KOR…", "Solving — 40s…") so the user sees *what* and *why*, not a black box;
- **confirmation prompts** inline (Approve / Edit / Skip) for gated tools, with a preview/diff;
- **inline results** — render the model diff and the actual analytics **cards** (reuse the dashboard cards) in the chat, plus "jump to Model / Analytics";
- **per-step undo/redo** (the session store already versions edits) and "explain this step";
- **autonomy slider** — Manual (confirm everything) → Guided (auto cheap tools) → Auto (only gate money/destructive).

---

## 7. Build sequence (phased, each phase shippable)

| Phase | Deliverable | Leans on |
|---|---|---|
| **0 · MCP prototype** ✅ *shipped* | An MCP server (`backend/mcp/`) — 199 tools spanning the full surface (§2.7 lists the newest 82): introspect + **schema** (`list_components`/`describe_component`/`describe_run_options` over the live PyPSA registry) · data-in · edit · **generic component CRUD** (`add_component`/`set_component`/`remove_component` cover every PyPSA component + attribute) + typed `add_*` conveniences · series transforms · solve (all modes via free-form scenario/options) · analyse · plugins. Drivable from any MCP client with any model. See §10 to connect a client. | existing API |
| **1 · Embedded agent (L1 shell)** | `LLMProvider` abstraction + Claude API adapter + the plan/act/observe loop + a minimal Assistant chat tab (stream + tool cards). Happy path: "build KOR, solve, report." | Phase 0 tools |
| **2 · Guardrails & grounding** | confirmation gates, budgets, world-state summarisation, schema retrieval tools, exemplars. | pypsa_schema_builder |
| **3 · Verification loop** | validate-before-solve, Q2 repair loop, Ember/adequacy sanity, cited report generator. | Q2, I7, A2 |
| **4 · Local models** | Hermes/Ollama adapter + capability tiers + the eval harness (a benchmark of scored tasks). | Phase 1 |
| **5 · L2 data-ask + scenarios** | agent asks for missing inputs conversationally; multi-scenario sweeps; scenario comparison via X6 multi-run plugins. | L2, X6 |

**Evaluation harness** (built alongside Phase 1, run every phase): a fixed set of goals with checkable outcomes — *"KOR 2030 model solves feasibly"*, *"renewable share within X of Ember"*, *"report cites cost & emissions"* — scored per provider/tier so we can measure whether a change (or a weaker local model) still passes. This is the equivalent of the parity/analytical tests that already gate the numeric code.

---

## 8. Key risks → mitigations

| Risk | Mitigation |
|---|---|
| Hallucinated schema fields / bad edits | validate at the tool boundary against the live PyPSA registry; reject before it reaches the model |
| Silently wrong analytics | reports are generated from `get_analytics` fields with citations; Ember/adequacy sanity flags |
| Runaway cost / infinite loops | per-session token+wall-clock budgets, no-repeat circuit breaker, confirmation gates |
| Long solves block the loop | solves are already **async/queued** — the agent submits and polls; the UI stays live |
| Weak local-model tool-calling | capability tiers: narrow catalog + JSON grammar + repair for medium, scripted slot-filling for weak |
| Destructive/expensive actions | never auto-run; preview + Approve; autonomy level opt-in |
| Secret leakage | BYOK keys stay server-side (existing secrets store); never sent to the model or logged |

---

## 9. Why this is low-risk to start

- **No solver/importer changes** for Phases 0–3 — the tool layer is the existing, tested API.
- **Phase 0 is days, not weeks** — an MCP wrapper + Claude Code gives a real, drivable agent immediately, and de-risks the tool design before any UI is built.
- **Each phase is independently useful** and testable, matching the repo's "feature branch → tests → merge" rhythm and the analytical-verification bar in `CLAUDE.md`.

---

## 10. Connecting a client (Phase 0)

The MCP server (`backend/mcp/`) is a thin HTTP client of the **running** Ragnarok
backend. It's model-agnostic: any MCP-capable agent drives it, with any model.

### Install as a connector (one click)

For Claude Desktop (including Cowork), the Ragnarok tools install as a **desktop
extension** (`ragnarok.mcpb`) rather than through the JSON config below:

1. Build it once on a machine that has the checkout: `scripts/build_connector.sh`
   → `dist/ragnarok.mcpb`. (Or take the file from whoever built it.)
2. Double-click `dist/ragnarok.mcpb`. Claude Desktop opens its install dialog.
3. Set **Ragnarok folder** to your checkout (default `~/github/ragnarok`). Keep
   **Session** at `default` to watch Claude's work live in the web app. Leave
   **Remote backend address** empty to run the backend on this computer.
4. The connector starts the backend itself on port 8000 (or the port you set)
   and stops it when Claude closes. The first launch installs the Python packages
   into `.venv-pypsa` (about 5–15 minutes); until then tools answer "still starting"
   with the log path.

Requirements: Python 3.11+ on the machine (python.org or Homebrew); macOS or
Windows. Logs: `<checkout>/.connector/logs/connector.log` (launcher) and `backend.log`
(backend). Details and the design: [`connector/README.md`](../connector/README.md).
The `RAGNAROK_MCP_AUTOSTART` flag that the connector sets is documented in
`backend/mcp/autostart.py`; it is off for every other launch path.

### Prerequisites

```bash
# 1. The Ragnarok backend must be running (the server talks to it over HTTP):
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

# 2. Install the MCP server's deps (kept separate from the backend's):
.venv-pypsa/bin/python -m pip install -r backend/mcp/requirements-mcp.txt
```

### Configuration (environment variables)

| Var | Default | Purpose |
|---|---|---|
| `RAGNAROK_API_BASE` | `http://127.0.0.1:8000` | URL of the running backend |
| `RAGNAROK_SESSION_ID` | `bifrost` | Working-model session. Defaults to a **dedicated agent session** so it won't touch the web UI's `default` session. Set to `default` to share (and watch live in) the UI — see "Watching it live". |
| `RAGNAROK_MCP_AUTONOMY` | `guided` | `guided` (gate imports/transforms/solves) · `manual` (gate every edit) · `auto` (no gating) |
| `RAGNAROK_MCP_TRANSPORT` | `stdio` | `stdio` (local agents) or `streamable-http` (networked, e.g. LibreChat) |
| `RAGNAROK_MCP_PORT` | `8765` | Port for `streamable-http` (not 8000 — the backend uses that) |

The launch command for stdio clients is the **venv Python** running
`-m backend.mcp` with `PYTHONPATH=<repo>`:

- macOS/Linux: `<repo>/.venv-pypsa/bin/python`
- Windows: `<repo>\.venv-pypsa\Scripts\python.exe`

The examples below use the macOS path; on Windows swap in `Scripts\python.exe`
and backslash the `PYTHONPATH`. Example Windows `claude_desktop_config.json` /
LM Studio `mcp.json` entry:

```json
{
  "mcpServers": {
    "ragnarok": {
      "command": "C:\\path\\to\\project-Ragnarok\\.venv-pypsa\\Scripts\\python.exe",
      "args": ["-m", "backend.mcp"],
      "env": {
        "PYTHONPATH": "C:\\path\\to\\project-Ragnarok",
        "RAGNAROK_API_BASE": "http://127.0.0.1:8000",
        "RAGNAROK_MCP_AUTONOMY": "guided"
      }
    }
  }
}
```

Paths are **per-machine** — use each box's real repo/venv path. Install the MCP
deps once (`.venv-pypsa\Scripts\python -m pip install -r backend\mcp\requirements-mcp.txt`);
they're separate from the backend's, so `serve`/`run` don't install them. To
drive a backend on another host, point `RAGNAROK_API_BASE` at `http://<host-ip>:8000`.

### stdio clients

**Claude Code:**
```bash
claude mcp add ragnarok \
  --env PYTHONPATH=<repo> \
  --env RAGNAROK_API_BASE=http://127.0.0.1:8000 \
  --env RAGNAROK_MCP_AUTONOMY=guided \
  -- <repo>/.venv-pypsa/bin/python -m backend.mcp
```

**Claude Desktop / Gemini CLI** (`claude_desktop_config.json` · `~/.gemini/settings.json`) — same JSON shape:
```json
{
  "mcpServers": {
    "ragnarok": {
      "command": "<repo>/.venv-pypsa/bin/python",
      "args": ["-m", "backend.mcp"],
      "env": {
        "PYTHONPATH": "<repo>",
        "RAGNAROK_API_BASE": "http://127.0.0.1:8000",
        "RAGNAROK_MCP_AUTONOMY": "guided"
      }
    }
  }
}
```

**Codex CLI** (`~/.codex/config.toml`):
```toml
[mcp_servers.ragnarok]
command = "<repo>/.venv-pypsa/bin/python"
args = ["-m", "backend.mcp"]
env = { PYTHONPATH = "<repo>", RAGNAROK_API_BASE = "http://127.0.0.1:8000", RAGNAROK_MCP_AUTONOMY = "guided" }
```

**Goose** (`~/.config/goose/config.yaml`, or `goose configure` → Add stdio extension):
```yaml
extensions:
  ragnarok:
    type: stdio
    cmd: <repo>/.venv-pypsa/bin/python
    args: ["-m", "backend.mcp"]
    envs:
      PYTHONPATH: <repo>
      RAGNAROK_API_BASE: http://127.0.0.1:8000
      RAGNAROK_MCP_AUTONOMY: guided
```

### Networked client — LibreChat (the near-term GUI)

Run the server in HTTP mode (still pointing at the backend):
```bash
RAGNAROK_MCP_TRANSPORT=streamable-http RAGNAROK_MCP_PORT=8765 \
RAGNAROK_API_BASE=http://127.0.0.1:8000 \
PYTHONPATH=<repo> <repo>/.venv-pypsa/bin/python -m backend.mcp
```
Then in `librechat.yaml` (use `host.docker.internal` when LibreChat runs in Docker):
```yaml
mcpServers:
  ragnarok:
    type: streamable-http
    url: http://host.docker.internal:8765/mcp
```
LibreChat gives a self-hosted web chat with model selection (OpenAI / Anthropic /
Gemini / local Ollama) driving the Ragnarok tools.

### Local models

A raw local model (Ollama / llama.cpp) is not an MCP client — it needs an
MCP-aware harness. Point **Goose** or **LibreChat** at your local model
(Ollama provider) and connect them to this server exactly as above; the server
is identical regardless of the model.

### Watching it live

By default the server uses a dedicated `bifrost` session, isolated from the web
UI. To watch the agent work **live in the browser tab**, set
`RAGNAROK_SESSION_ID=default` so it shares the UI's working model — imports,
edits, transforms, and queued solves then appear in real time. Caveat: in that
mode the agent shares (and can overwrite) whatever you have open in the UI, so
use it for demos/throwaway sessions, not alongside unsaved work.

### Split setup — backend on a server, agent on a client (e.g. LM Studio)

Run Ragnarok on one machine and drive it from another with **nothing installed
client-side** — `serve` starts the MCP bridge over HTTP automatically, and the
client (LM Studio, Claude Desktop, …) just points at a URL.

**On the server** (hosts the model + solves) — one command:
1. `./serve.command` (macOS) / `serve.bat` (Windows). Server mode binds the app
   on `0.0.0.0:8000` **and** the MCP bridge on `0.0.0.0:8765/mcp` (it installs
   `requirements-mcp.txt` on first run). It prints both URLs.
2. Note the machine's LAN IP; allow inbound **TCP 8000 and 8765** on the firewall.
   (Set `RAGNAROK_MCP=off` to skip the bridge, or `RAGNAROK_MCP_PORT` to move it.)

**On the client** (runs LM Studio / the agent) — nothing to install:
1. In LM Studio's `mcp.json` (or any client that supports **remote** MCP
   servers), add a URL entry pointing at the server's MCP port:
   ```json
   {
     "mcpServers": {
       "ragnarok": { "url": "http://<SERVER-IP>:8765/mcp" }
     }
   }
   ```
2. Restart LM Studio, load a tool-capable model → the tools drive the model on
   the server. Sanity check from the client:
   `curl http://<SERVER-IP>:8000/api/session/meta?session_id=bifrost` → JSON.

> If your client only supports **local/stdio** MCP servers (not URLs), fall back
> to running the bridge on the client instead: clone Ragnarok there, install
> `requirements-mcp.txt` (self-contained — `mcp` + `httpx`, no PyPSA), and use a
> `command`/`args` entry (`-m backend.mcp`) with
> `RAGNAROK_API_BASE=http://<SERVER-IP>:8000`.

To watch changes live in the server's web UI, run the client with
`RAGNAROK_SESSION_ID=default` (share the UI session — but on the URL setup that
env lives on the *server's* MCP process, so set it before `serve`) and open
`http://<SERVER-IP>:8000`; otherwise the agent uses the isolated `bifrost` session.

### Mjolnir note

`backend/mcp/` is subtree-vendored into Mjolnir (the serve wrapper) on the next
pull but isn't needed there — exclude it from Mjolnir's build (or leave it
unused; it imports nothing from `backend.app`, so it's inert without an explicit
launch).
