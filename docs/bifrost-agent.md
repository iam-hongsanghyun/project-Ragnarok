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

The MCP server has 154 tools: 116 in `backend/mcp/server.py` (§2.1–§2.6 group most of them, not all) and 38 in
`backend/mcp/tools_*.py`. The table below covers the 38. The GUI reaches the same backend routes through its own
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

**Analysis and Forge edits (`tools_analysis.py`)**

| Tool | Endpoint(s) | Gate | What it does |
|---|---|---|---|
| `compare_runs` | `GET /api/results/compare` | — | Side-by-side comparison of 2-5 stored runs - the Analytics -> Comparison matrix as data. 'topics' picks columns of detail: kpi (summary KPIs with the generator/storage capacity split), … |
| `get_kpis` | `GET /api/runs/{name}/kpis` | — | The KPI strip of a stored run: total cost, dispatch MWh, average/min/max price, peak load MW, load factor, renewable share % (zero-emission carriers excluding nuclear and storage), … |
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
| **0 · MCP prototype** ✅ *shipped* | An MCP server (`backend/mcp/`) — 154 tools spanning the full surface (§2.7 lists the newest 38): introspect + **schema** (`list_components`/`describe_component`/`describe_run_options` over the live PyPSA registry) · data-in · edit · **generic component CRUD** (`add_component`/`set_component`/`remove_component` cover every PyPSA component + attribute) + typed `add_*` conveniences · series transforms · solve (all modes via free-form scenario/options) · analyse · plugins. Drivable from any MCP client with any model. See §10 to connect a client. | existing API |
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
