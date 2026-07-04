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
   import/* · session/* · transform/* · /api/run + queue · runs/*/analytics · plugins/*
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
| `cluster_network(n, method)` | `POST /api/session/cluster` |

### 2.4 Configure + solve
| Tool | Endpoint | Notes |
|---|---|---|
| `set_run_options(scenario, options)` | (payload for the solve) | carbon price, discount, pathway/rolling/stochastic, market-sim, owner column — the "user settings" |
| `submit_solve()` | `POST /api/run` → queue | **async**: returns a job; the agent polls, does not block |
| `poll_run(job_id)` | `GET /api/queue` / `/api/run/{job_id}` | wait for `ready` / `error` |

### 2.5 Analyse
| Tool | Endpoint |
|---|---|
| `get_analytics(run)` | `GET /api/runs/{name}/analytics` (summary, carrier mix, cost, emissions, adequacy…) |
| `get_derived(run, metric)` | `GET /api/runs/{name}/derived/{metric}` |
| `run_plugin_analysis(id, config, runs)` | `POST /api/plugins/{id}/analyze` (X6 multi-run comparison) |
| `diagnose_infeasibility()` | Q2 `diagnostics.py` | fed back to the agent on a failed solve for **self-repair** |

**Confirmation-gated tools** (never auto-run): `submit_solve` (minutes of compute), `import_dataset`/`one_click_model` (live network, rate limits), any `edit_sheet`/`delete` that overwrites user data, and anything spending money (paid APIs). The UI shows a diff/preview and an Approve button; an "autonomy level" setting can pre-authorise the cheap tiers.

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
| **0 · MCP prototype** ✅ *in progress (Tier 1)* | An MCP server (`backend/mcp/`) wrapping the tool catalog — ~21 tools, drivable from any MCP client with any model. Proves the tool surface end-to-end with zero UI work. See §10 to connect a client. | existing API |
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

### Mjolnir note

`backend/mcp/` is subtree-vendored into Mjolnir (the serve wrapper) on the next
pull but isn't needed there — exclude it from Mjolnir's build (or leave it
unused; it imports nothing from `backend.app`, so it's inert without an explicit
launch).
