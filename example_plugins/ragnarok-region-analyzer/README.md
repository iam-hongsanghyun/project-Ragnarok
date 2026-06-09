# Region & Carrier Analyzer

A **100% frontend** Ragnarok plugin (SDK v2) — no backend, nothing to start.
After a solve it aggregates the network **by region** and **by carrier** and
shows the result as **tables in the Output tab**.

> **v3** generation: compatible with Ragnarok's backend-authoritative
> architecture. The analyzer reads the *solved result* Ragnarok hands its
> `analyze` hook and never caches the model in the browser — so it works
> unchanged whether the model lives in a local or a remote backend session.

## Input (same region settings as the dashboard importer)

- ☑ **Aggregate by region** — collapse nodal (per-bus) output into regions.
- **Region column** — `province` / `group1` / `group2` / `group3` / `singlenode`.
- **Province → region mapping** table (KR 17 provinces bundled; a bus is matched
  by its `short` or `official` name, then the Region column becomes its region).

That's it — nothing else to set.

**Numbered buses:** the run result carries no bus province (and `analyze` isn't
given the model), so the plugin embeds a **bus → province** lookup for the
standard KR model. A numbered bus (`1`, `2`, …) resolves bus → province →
region via the Region column. If the bus name is already a province/region (a
model aggregated by region before solving), it matches the mapping directly.
Buses not in the embedded lookup stay per-bus and are counted in the `Settings`
row as `UNMAPPED buses=N` — if you see that, your model uses different bus
numbering than the embedded one.

## Output (Output tab — runs automatically after a solve)

The current Ragnarok renders plugin output **only as scalar key→value rows** —
it stringifies arrays to `[object Object]` (the host hardcodes empty display
hints, so its table renderer never fires). So each result table is delivered as
**one CSV cell**: a couple of headline numbers plus these CSV blocks, which you
select and paste straight into a spreadsheet to chart.

| Row | What | Unit |
|---|---|---|
| `Settings` | echo of the active options | — |
| `Total generation` | system total | energy unit |
| `1. Generation by region — total [CSV]` | per region, × carrier if carrier aggregation is on | energy unit |
| `2. Generation by region — hourly [CSV]` | per region per snapshot | MW |
| `3. Regional power flow — total [CSV]` | net + gross between each region pair | energy unit |
| `4. Regional power flow — hourly [CSV]` | net per region pair per snapshot (`A→B`, + = A→B) | MW |
| `Capacity by region × carrier [CSV]` | peak-available capacity (carrier on only) | MW |
| `Carrier totals [CSV]` | system-wide carrier energy + share | energy unit |

Behaviour by checkbox:
- **Region + Carrier** → generation (and capacity) **by carrier by region**.
- **Region only** → regionally aggregated generation + **inter-region** flows
  (flow between regions, not per line).

## Notes

- **Why CSV cells (not grids/charts):** the host renders plugin output as
  scalar key→value rows and discards display hints, so an array value shows as
  `[object Object]` and there is no chart surface for plugins. Delivering each
  table as a CSV string is the only way to surface the full data readably
  without modifying Ragnarok. Real in-app grids/charts would require extending
  Ragnarok's `PluginPanel` itself.
- Total energy = Σ(MW over snapshots) × snapshot weight (from the run, unless
  overridden). Hourly tables are instantaneous **MW**.
- Hourly tables are capped at **Hourly rows cap** (default 168 = 1 week) to keep
  the output readable; `meta.hourly_truncated` says when rows were dropped.
- `capacity` is the peak available MW (exact for dispatchable, a lower bound for
  VRE) — the only capacity proxy present in the run result.

## Package

Frontend-only: the installable zip is `module.json` + `index.js`.
```bash
cd plugins_V2/ragnarok-region-analyzer
zip -r zip/ragnarok-region-analyzer.zip module.json index.js README.md
```
Install via Ragnarok → Plugins → *Install plugin…*, then run the model.
