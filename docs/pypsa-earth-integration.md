# PyPSA-Earth integration — feasibility

*Status: investigated, build deferred (2026-06). Captured so the option isn't
re-litigated from scratch.*

The question: can [PyPSA-Earth](https://pypsa-earth.readthedocs.io/) be wired
into Ragnarok as a data source, the way OSM / WRI / ENTSO-E / KPG193 are?

**Short answer: yes, but not as an importer — as an async "network builder"
job.** PyPSA-Earth is a Snakemake workflow that *constructs a whole network*
from global datasets; it does not expose a REST API and does not run in the
seconds-scale, per-request budget the `/api/import/*` importers assume.

## What PyPSA-Earth's `populate` stage actually is

A [Snakemake](https://snakemake.readthedocs.io/) workflow whose `populate`
rules build the modelling inputs ([rules reference](https://pypsa-earth.readthedocs.io/en/latest/user-guide/rules-reference/populate/)):

| Rule | Produces | Main inputs |
|------|----------|-------------|
| `build_cutout` | ERA5 weather cutout | ERA5 (Atlite / CDS API) |
| `build_bus_regions` | Voronoi cell per substation | OSM substations, GADM shapes |
| `build_powerplants` | thermal plant capacities → nearest substation | powerplantmatching (GEM, GPPD, …) |
| `build_natura_raster` | protected-area raster | WDPA / Natura |
| `build_renewable_profiles` | hourly PV / on- & offshore-wind capacity factors + land-use potentials | Atlite + cutout, Natura raster, GEBCO |
| `build_demand_profiles` | hourly demand per substation | GEGIS / load distribution |

End to end it assembles buses, lines, generators *with capacities*, renewable
availability profiles, and demand — i.e. essentially the entire PyPSA network
Ragnarok otherwise builds from a workbook.

## Why it's not a drop-in importer

- **It's a workflow, not an API.** Driving it means invoking Snakemake (or its
  Python rule functions) with a `config.yaml`, not an HTTP GET.
- **Heavy inputs + compute.** ERA5 cutouts are GB-scale downloads (CDS API key,
  rate-limited); `build_renewable_profiles` is minutes-to-hours of Atlite
  compute; `powerplantmatching`, GADM, WDPA, GEBCO are large auxiliary datasets.
  This cannot sit behind the synchronous `/api/import/run` call.
- **Different env.** PyPSA-Earth pins its own conda environment (atlite,
  powerplantmatching, geopandas/rasterio stack, a solver). It would live beside
  Ragnarok's backend, not inside the importer package.

## Recommended integration (when pursued): an async job

1. Frontend submits a **build request** (country/region + a small config subset:
   horizon, renewable carriers, clustering) — a new long-running endpoint, *not*
   `/api/import/run`. Reuse the existing background-progress pattern
   (`backend/app/startup_status.py` — phase/detail/ready snapshots polled by the
   frontend) for status.
2. Backend runs the PyPSA-Earth Snakemake workflow for that config in its own
   environment (cutouts cached on disk and reused across requests).
3. On completion, **ingest the output PyPSA network** (`.nc` / the CSV folder)
   into a Ragnarok workbook. PyPSA's own `Network.export_to_csv_folder` output
   maps directly onto our sheet model, and the importer's `WorkbookFragment` +
   `mergeFragment` path already merges full networks — so the result is
   **PyPSA-ready by construction** (it *is* a PyPSA network).

So it slots in as a **source whose "fetch" is a queued job**, returning the same
`WorkbookFragment` shape once done.

## Overlap with the hand-built sources

PyPSA-Earth's `populate` largely *supersedes* the per-country hand-built data we
add via importers:

- `build_powerplants` ↔ **OSM power plants** / **WRI GPPD** (generators+capacity)
- OSM substations/lines ↔ **OSM grid topology**
- `build_renewable_profiles` ↔ a profiles source (none yet for arbitrary countries)
- `build_demand_profiles` ↔ **ENTSO-E / EIA demand** (but global, not just EU/US)

It does **not** replace curated reference grids like **KPG193**, or the
lightweight single-source importers when a user only wants one slice of data.

## Cost & decision

A first integration is a substantial, multi-pass effort: the async job runner +
status plumbing, packaging the PyPSA-Earth environment, wiring CDS/cutout
caching, and the network→workbook ingest. **Deferred for now** — documented here
so the path is clear when prioritised. The near-term value (OSM topology + power
plants, ENTSO-E load + installed capacity, EIA demand, KPG193) is covered by the
existing importer sources.
