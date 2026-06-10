# Scenario Analytics (Ragnarok plugin, SDK v2)

System-level analytics for a **solved** Ragnarok run, built to produce the charts + numbers
the 11th-Basic-Plan alternative-scenario study (PLANiT / Greenpeace) needs. 100% frontend
(`analyze` hook) — no backend server.

> **v3** generation: compatible with Ragnarok's backend-authoritative
> architecture. The `analyze` hook reads the solved result Ragnarok provides and
> never caches the model in the browser, so it works unchanged whether the model
> lives in a local or a remote backend session.

## What it shows (Output tab, after a Run)

**KPIs:** total generation, renewable share %, total CO₂ (MtCO₂), emission factor (gCO₂/kWh),
average SMP, zero-price hours %, peak demand, reserve margin %, renewable curtailment %.

**A. Generation & capacity mix** — generation-by-carrier donut; installed capacity by carrier
(GW, from the run's embedded network); capacity-by-carrier-by-year stacked bar (when generators
carry `build_year`/`close_year`).

**B. Hourly dispatch + SMP** — stacked-area hourly dispatch by carrier over a window (set
`Dispatch window start` to a summer/winter week); system-load line; SMP line.

**C. Emissions vs targets** — cumulative CO₂ area; optional "CO₂ vs NDC" bar (set `NDC target`);
emissions-by-carrier table.

**D. Regional flows + adequacy** — inter-region flow map (region nodes = generation-mix pies,
edges = net flow); peak demand & reserve margin; load-duration curve.

Plus underlying tables and a **Download analytics (CSV)** button.

## Data source

Reads only the solved `RunResults`: per-generator `outputSeries` / `curtailmentSeries`, per-bus
`netSeries` (load/smp), `systemPriceSeries`, `systemEmissionsSeries`, `emissionsBreakdown`, and
installed capacity from `outputs.static.generators` (`p_nom_opt` / `p_nom`, `build_year`). The flow
map reuses the region-analyzer's province→region mapping + centroids.

## Install

Zip `module.json` + `index.js` (+ this README) and install via the Plugins tab. Single run at a
time (no scenario library). Requires a frontend that supports plugin charts/map (SDK v2).
