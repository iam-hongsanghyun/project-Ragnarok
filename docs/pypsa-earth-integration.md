# PyPSA-Earth integration — feasibility

*Status: async-job scaffold BUILT (2026-07, first cut); the heavy workflow run
still needs an external environment. See "First cut" at the end.*

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
caching, and the network→workbook ingest. The near-term value (OSM topology +
power plants, ENTSO-E load + installed capacity, EIA demand, KPG193) is covered
by the existing importer sources.

## First cut (built, 2026-07)

`backend/app/routers/pypsa_earth.py` implements the **async job seam** and the
**network→workbook ingest** — the two architectural pieces — with the heavy
workflow gated behind an external environment:

- `POST /api/pypsa-earth/build` queues a job (`BuildRequest`: country, horizon,
  carriers, clusters) and returns a `jobId`; `GET …/build/{id}` polls
  phase/status; `GET …/build/{id}/result` returns the ingested `WorkbookFragment`
  when done; `GET …/available` reports whether the environment is set up.
- The job coroutine checks `RAGNAROK_PYPSA_EARTH_DIR` (a checked-out workflow dir
  with a `Snakefile`). **Not configured → the job fails cleanly** with a pointer
  to this doc; **configured →** it shells out to `snakemake … results/networks/
  elec_s_{clusters}.nc` and ingests the result via
  `ingest_network()` → `serialize.network_to_model` (proven on a real `.nc` in
  `tests/test_pypsa_earth.py`).

**Frontend surface — DONE.** `frontend/.../features/data/PypsaEarthPanel.tsx`
(+ `lib/api/pypsaEarth.ts`) is a left-rail "PyPSA-Earth — whole-country build"
entry whose panel (right rail) is availability-gated: when configured it submits
a build for the selected country, polls status, and applies the result via the
importer `applyFragment` path; when not, it offers a "use this directory" field
(→ `POST /configure`, persisted to `backend/data/pypsa_earth.json`) and the
one-time setup commands.

**One-command install — `scripts/setup_pypsa_earth.command`** (double-click in
Finder, or run in a terminal; gitignored target):
clones pypsa-earth into `<repo>/pypsa-earth`, optionally builds its conda env
(`--no-env` to skip), and writes the override so Ragnarok is pointed at it. The
clone + override are gitignored; only the script is committed. The CDS key is
still a manual one-time step (it's a credential).

**Still to do for a full integration:** (1) writing a per-request `config.yaml`
override into the workflow dir (currently it runs the dir's own config);
(2) provisioning/packaging the PyPSA-Earth conda env + CDS key + cutout cache on
the host; (3) cutout reuse across requests. The seam + ingest + frontend are
done and tested — those three are the operational remainder.
