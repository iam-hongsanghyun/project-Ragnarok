# Region & Carrier Analyzer

A **backend (server-side)** Ragnarok plugin. It reads a **stored run** straight
from the backend run store, aggregates the solved network **by region** and
**by carrier**, and renders charts, a **flow map**, and tables in the Output
tab. No separate server, nothing in `plugins.env` — the plugin runs inside the
Ragnarok backend process.

> **v7** — ported from the v6 frontend (browser-JS) plugin. The browser version
> read `result.assetDetails` from the page, which is **empty when a stored run
> is viewed** (the light "View result" payload strips per-component series), so
> its charts and map rendered blank. Server-side, the plugin reads exactly the
> series it needs (generator dispatch + branch flows) with granular SQL reads —
> nothing heavy ever reaches the browser.

## Input

- **Stored run** — which backend-stored run to analyze. Blank = the most
  recent. (Runs are stored when *Store run in backend* is enabled.)
- ☑ **Aggregate by region** — collapse nodal (per-bus) output into regions.
- **Region column** — `province` / `group1` / `group2` / `group3` / `singlenode`.
- ☑ **Split by carrier** — split generation by carrier for the mix charts.
- **Energy unit** — MWh / GWh / TWh.
- **Chart region** — region for the per-region donut + hourly area charts
  (blank = highest-generation region).
- **Hourly chart length** — snapshots plotted in the hourly chart (default 168).
- **Province → region mapping** table (KR 17 provinces bundled; a bus is
  matched by its `short` or `official` name, then the Region column becomes its
  region).

**Numbered buses:** the plugin embeds a **bus → province** lookup for the
standard KR model. A numbered bus (`1`, `2`, …) resolves bus → province →
region via the Region column. A bus whose name is already a province/region
matches the mapping directly. Buses not in the embedded lookup stay per-bus and
are counted in the `Settings` row as `UNMAPPED buses=N`.

## Output (Output tab — refreshes automatically when the config changes)

| Entry | What |
|---|---|
| `Settings` | echo of run + active options (+ unmapped-bus count) |
| `Total generation` | system total (energy unit) |
| `Total curtailment` | system total (energy unit) |
| `Carrier mix (system)` | donut |
| `Generation by region` | stacked bar, × carrier |
| `Curtailment by region` | bar (energy unit) — renewable available-minus-dispatched |
| `Carrier mix — <region>` | donut for the chart region |
| `Hourly generation — <region>` | stacked area (MW) for the chart region |
| `Inter-region net flow` | bar (energy unit) |
| `Inter-region flow map` | map: node = region (pie = carrier mix, size = generation), line = net flow |
| `… — table` rows | the underlying tables (generation, capacity MW, curtailment + share of generation, carrier totals, flows) |

- Total energy = Σ(max(MW, 0) over snapshots) × snapshot weight (from the run).
- Curtailment = Σ max(p_max_pu × p_nom_opt − dispatch, 0) × weight per renewable
  generator (computed by the run), folded onto each generator's region.
- Capacity = solved `p_nom_opt` when present, else the input `p_nom`.
- Flows aggregate lines + links + transformers whose endpoints map to
  different regions; `net` is the magnitude of the signed sum, `gross` the sum
  of absolute flows.

## Package

Backend plugin: the installable zip is `manifest.json` + `plugin.py`.

```bash
cd example_plugins/ragnarok-region-analyzer
zip ../zips/ragnarok-region-analyzer.zip manifest.json plugin.py README.md
```

Install via Ragnarok → Plugins → *Install plugin…* (it is routed to the backend
automatically), store a run, and open the plugin's Output tab.
