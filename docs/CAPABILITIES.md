# Ragnarok — Capabilities (What it can and cannot do)

Ragnarok is a browser-based GUI for building and running PyPSA power-system
optimisation models. You author a network in a spreadsheet-style workbook,
configure a scenario (time window, carbon price, constraints, study mode), and
submit to a local Python/FastAPI backend that builds a `pypsa.Network`, solves
it with HiGHS, and returns analytics and exportable outputs — without touching
a command line.

---

## Can do

### Modelling — components supported

Every component listed below is editable in the Model and Build workspaces. The
schema is generated from PyPSA's own component registry.

| Component | Sheet | Map marker | Per-asset detail card |
|---|---|:---:|:---:|
| Bus | `buses` | Yes | Yes |
| Carrier | `carriers` | — | — |
| Generator | `generators` | Yes | Yes |
| Load | `loads` | — | — |
| Line | `lines` | Yes | Yes |
| Link | `links` | Yes | Yes |
| StorageUnit | `storage_units` | Yes | Yes |
| Store | `stores` | Yes | Yes |
| Transformer | `transformers` | Yes | Yes |
| ShuntImpedance | `shunt_impedances` | — | Yes |
| Process | `processes` | — | Yes |
| GlobalConstraint | `global_constraints` | — | — |
| LineType / TransformerType | `line_types` / `transformer_types` | — | — |
| Snapshots | `snapshots` | — | — |

Loads aggregate into the bus detail card. Carriers are edited via a
carrier-color picker and emission-factor table. `sub_networks` and `shapes` are
computed or optional geo metadata — not user-editable.

### Study modes

All modes invoke `network.optimize()` (LOPF) via HiGHS. There is no
standalone power-flow mode (see Limitations below).

**Single-period** — one optimisation covering the full snapshot window. The
default mode. Optimises dispatch and, when assets are marked `p_nom_extendable`,
capacity simultaneously.

**Multi-period pathway** — multi-investment-period capacity expansion planning.
Each period carries its own snapshot slice, objective weight, and years weight.
PyPSA annuitises capital cost across periods. Activated via the Pathway panel in
Run Settings.

**Rolling horizon** — solves a sequence of overlapping windows across the
snapshot timeline using `network.optimize.optimize_with_rolling_horizon()`.
Useful for long time series that exceed practical LP memory limits. Cannot be
combined with stochastic mode.

**Stochastic (two-stage)** — two-stage scenario tree. Each branch gets its own
snapshot slice; the solver returns expected-value results. Summaries per
scenario are available in a dedicated analytics card. Cannot be combined with
rolling horizon.

**Security-constrained (SCLOPF / N-1)** — every dispatch decision must remain
feasible under the outage of any single passive branch (line or transformer).
Uses `network.optimize.optimize_security_constrained()`. Cannot be combined with
rolling horizon, stochastic, or pathway mode.

### Constraints

**Global constraints** — native PyPSA `global_constraints` sheet. Editable in
the Constraints workspace alongside custom constraints.

**Custom linopy constraints (UI-authored)** — added to the linopy model inside
`extra_functionality`. Supported metrics:

- `co2_cap` — CO2 emission intensity cap (kg CO2e/MWh system average)
- `max_load_shed` — total load shedding cap (MWh over the modelled window)
- `carrier_max_gen` / `carrier_min_gen` — carrier generation cap/floor (MWh)
- `carrier_max_share` / `carrier_min_share` — carrier dispatch share cap/floor (%)
- `carrier_max_cf` / `carrier_min_cf` — carrier capacity factor cap/floor (%)

**Carbon price** — a flat $/t adder folded into per-generator marginal cost at
build time. The adder is proportional to each carrier's emission factor. The
cost is reported as a separate "Carbon cost" line in the cost breakdown.

**Load shedding** — optional VOLL (value of lost load) backstop generator
injected at each bus. Without it, any supply shortfall surfaces as solver
infeasibility. The penalty cost and enable/disable toggle are in Settings.

**Unit commitment** — generators with `committable = True` in the workbook
activate MIP unit-commitment constraints (PyPSA's native binary commitment
variables). A `forceLp` toggle in Run Settings overrides all `committable` flags
to keep the problem as an LP.

**Annuitised CAPEX** — extendable assets (`p_nom_extendable = True`) have their
capital cost annuitised by PyPSA and included in the objective. The expansion
results card reports annualised CAPEX per asset.

### Analytics and visualisation

- Interactive Leaflet map of the network topology with bus/line/generator
  markers coloured by carrier.
- Dispatch time-series chart (stacked area by carrier), generator-level
  breakdown, storage state-of-charge.
- System price series, nodal price series (LMPs per bus).
- System emissions series, emissions breakdown by carrier.
- Cost breakdown: fuel cost, carbon cost, load shedding cost, annualised CAPEX.
- Carrier mix (pie / bar).
- Merit order chart and CO2 shadow price card.
- Line/link loading (peak % utilisation per corridor).
- Nodal balance (generation vs load per bus).
- KPI summary cards: installed capacity, peak demand, reserve margin, peak
  price, system emissions, transmission stress.
- Per-asset detail panel: click any generator, line, bus, storage unit, etc.
  on the map or in a results table to view its input parameters and solved
  output time series.
- Pathway period selector — re-derive all analytics for a chosen investment
  period without re-running.
- Stochastic scenarios card — per-scenario totals alongside the
  representative-scenario detail view.
- Run history (session-scoped) — compare and restore any run from the current
  session. Survives model swaps within the session; cleared only by "Clear
  all" or page reload.
- Plugin analytics tab — post-solve output from installed plugins rendered
  generically.

### Data I/O

| Operation | Format | Direction | Notes |
|---|---|---|---|
| Open workbook | `.xlsx` | Import | SheetJS parse; inputs only |
| Save / Save As | `.xlsx` | Export | Inputs only |
| Import Project | `.xlsx` | Import | Inputs + solved outputs + metadata |
| Export Project | `.xlsx` | Export | Inputs + solved outputs + run metadata |
| Export Result workbook | `.xlsx` | Export | Full solved output dataset |
| CSV folder | `.zip` (PyPSA CSV folder layout) | Import + Export | Frontend-side; no backend call |
| netCDF | `.nc` | Import + Export | Backend conversion via PyPSA |
| HDF5 | `.h5` | Import + Export | Backend conversion via PyPSA |

### Extensibility

**Plugin system v1** — install local `.zip` plugin packages via the Plugins
sidebar. Four execution stages: `pre-build` (transform or inject workbook
data), `post-build` (patch the built network), `in-solve` (add extra linopy
constraints), `post-solve` (compute and return analytics). Plugin output is
rendered in the Plugins tab without any hardcoded frontend knowledge of
individual plugins.

**Pluggable backend / frontend** — the `PypsaBackend` class exposes a
`capabilities()` declaration and a `run()` entry point. Alternative backends
(wrapping different solvers or engines) can be registered via the backend
registry at `backend/app/backends/`. The frontend is a standalone npm package
(`frontend/Ragnarok_default/`) that communicates with the backend only via the
REST API.

---

## Cannot do / current limitations

**No standalone power-flow study.** `studyModes` in the backend capabilities
response contains only `"optimize"`. Power-flow-only modes (`pf`, `lpf`) are
roadmapped but not implemented. Every run is an optimisation (LOPF).

**HiGHS only.** No UI mechanism to switch solvers. Gurobi, GLPK, CPLEX, and
other solvers are not exposed. HiGHS algorithm (simplex vs IPM) and thread
count are configurable in Run Settings; the solver binary is not.

**Local backend only.** The FastAPI process runs at `http://127.0.0.1:8000`.
There is no authentication layer, cloud deployment, or multi-user session
management. CORS is wide open (`allow_origins=["*"]`); Ragnarok is not intended
for public network exposure as shipped.

**Session-scoped run history, not a persisted scenario manager.** The run
history list lives in React in-memory state. It survives model swaps within the
same browser session but is wiped on page reload or "Clear all". There is no
database-backed scenario store, no named scenario comparison across sessions,
and no export of the full run history.

**Copper-plate unless impedances and limits are provided.** A network with buses
but no lines (or lines with `s_nom = 0` and no resistance/reactance) behaves as
a copper-plate system. Transmission constraints and nodal price separation are
only active when the user provides line impedances and `s_nom` limits.

**Carbon price is a flat per-tonne adder.** The carbon price is folded into
each generator's marginal cost at build time as `marginal_cost += carbon_price *
emission_factor`. There is no ETS permit curve, no permit banking/borrowing
between periods, and no endogenous carbon market clearing. It is a scalar input
per run, not a time-varying series.

**Mode exclusions.** The following mode combinations raise a 400 error from the
backend and cannot be run:

- Stochastic + rolling horizon
- SCLOPF + rolling horizon
- SCLOPF + stochastic
- SCLOPF + multi-period pathway

**No dynamic frontend UI from plugins.** Plugin post-solve output is rendered
through a generic result table in the Plugins tab. Plugins cannot inject custom
React components, register new sidebar panels, or add workbook sheets
dynamically. There is no remote plugin registry or sandboxed plugin process.

**No built-in time-series generation.** The `snapshots` sheet defines the
timestamp index, but load profiles, renewable capacity factors, and price series
must be supplied by the user in the corresponding time-series sheets. Ragnarok
does not fetch weather data, ENTSO-E profiles, or any external time-series
source.

---

## Capability matrix

| Feature | Supported | Notes |
|---|:---:|---|
| Single-period LOPF | Yes | |
| Multi-period pathway | Yes | |
| Rolling-horizon dispatch | Yes | Cannot combine with stochastic or SCLOPF |
| Two-stage stochastic | Yes | Cannot combine with rolling horizon or SCLOPF |
| Security-constrained LOPF (N-1) | Yes | Cannot combine with rolling, stochastic, or pathway |
| Unit commitment (MIP) | Yes | Per-generator `committable` flag; Force-LP override available |
| Power-flow only (PF/LPF) | No | Roadmapped |
| Custom linopy constraints | Yes | 7 metric types |
| Native global_constraints | Yes | |
| Carbon price (flat adder) | Yes | Scalar; no ETS curve or banking |
| Carbon price schedule / ETS | No | |
| Load shedding (VOLL backstop) | Yes | Configurable cost; per-bus |
| Annuitised CAPEX (expansion) | Yes | |
| HiGHS solver | Yes | Simplex or IPM, thread count configurable |
| Gurobi / GLPK / other solvers | No | |
| Map-based network visualisation | Yes | react-leaflet / Leaflet |
| Dispatch / price / emissions charts | Yes | Recharts |
| Per-asset detail card | Yes | Generators, buses, lines, links, storage, etc. |
| LMP (nodal marginal prices) | Yes | Per-bus time series |
| Merit order chart | Yes | |
| CO2 shadow price | Yes | |
| Session run history | Yes | Session-scoped; not persisted |
| Persisted scenario manager | No | |
| Open / Save workbook (.xlsx) | Yes | Inputs only |
| Export Project (.xlsx) | Yes | Inputs + solved outputs + metadata |
| Export Result workbook (.xlsx) | Yes | Full output dataset |
| CSV folder (import + export) | Yes | PyPSA-native; zipped; frontend-side |
| netCDF (import + export) | Yes | Backend-side PyPSA conversion |
| HDF5 (import + export) | Yes | Backend-side PyPSA conversion |
| Plugin system (4 stages) | Yes | Local trusted packages; no remote registry |
| Pluggable backend | Yes | Backend registry; REST API seam |
| Cloud / multi-user deployment | No | Local only; no auth |
| Time-series data fetching | No | User must supply all time-series sheets |
