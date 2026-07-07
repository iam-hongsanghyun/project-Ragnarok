# Physical-risk CLIMADA worker

The Physical Risk tab's run kinds (physical, uncertainty, cost-benefit,
supply-chain, calibration, forecast) are computed by [CLIMADA](https://climada.ethz.ch/)
when its worker environment is present, and by a deterministic stub otherwise.
The worker package lives at `backend/physical_risk_worker/`, vendored from the
standalone `climaterisk` project (both projects are GPL-3.0, so vendoring is
license-clean); only the package name changed (`climaterisk_worker` →
`physical_risk_worker`).

## Why a separate conda env (dependency isolation, not licensing)

CLIMADA needs the conda-forge geospatial stack (GDAL / PROJ / rasterio /
geopandas) on **Python 3.11 with older numpy/pandas pins**. Ragnarok's backend
runs in `.venv-pypsa` (**Python 3.13, numpy 2.4, pandas 3.0**). The two
dependency sets cannot share an interpreter, and the geo stack is not
pip-installable — so the worker is a **project-local conda prefix env**
(`./.climada-env`, never a global/named env) invoked as a subprocess. The only
coupling is a JSON file contract per run:

```
backend (venv, camelCase API)                worker (conda, snake_case contract)
  build request  ── request.json ──▶  python -m physical_risk_worker.run_job <dir>
  parse result   ◀── result.json ──          runs CLIMADA, writes result
```

The backend **never imports climada** (and the worker never imports the backend).
The translation between our camelCase entities and the worker's snake_case
contract (climaterisk `engines/base.py` shapes) lives in
`backend/app/physical_risk/worker.py`.

## Build the env

Needs conda or mamba (miniforge recommended). Downloads ~2 GB on first build.

```bash
scripts/setup_climada_worker.sh
# equivalent to:
#   conda env create -f backend/physical_risk_worker/env_climada.yml --prefix ./.climada-env
#   ./.climada-env/bin/python -c "import climada; print('ok')"
```

Restart the backend afterwards — worker selection is `auto` by default, so runs
switch from the stub to real CLIMADA as soon as the env exists. No solver flag,
no config edit.

## Engine selection and fallback

Every run kind funnels through one seam (`backend/app/physical_risk/engine.py::run_kind`):

| situation | engine used | result `detail` |
|---|---|---|
| gate `auto` (default) + env exists | CLIMADA worker | worker's own note |
| gate `auto` + no env | stub | none (silent) |
| gate `1` + env exists | CLIMADA worker | worker's own note |
| gate `1` + no env | stub | fallback reason recorded |
| gate `0` | stub | none |
| worker attempted but **fails** (spawn error, timeout, error status, bad result) | stub | fallback reason recorded |

A worker failure never fails the run — the stub result is served with the reason
appended to the result's `detail`, so the frontend can flag it.

## Environment variables

| var | default | meaning |
|---|---|---|
| `RAGNAROK_CLIMADA_WORKER` | `auto` | `auto` = use worker if env exists; `1`/`true`/`on` = force (missing env noted on results); `0`/`false`/`off` = never |
| `RAGNAROK_CLIMADA_WORKER_ENV` | `<repo>/.climada-env` | conda prefix env dir holding `bin/python` |
| `RAGNAROK_CLIMADA_TIMEOUT` | `900` | wall-clock cap (seconds) per worker run; exceeded runs are killed and fall back to the stub |
| `CLIMATERISK_HAZARD_DB` | `<repo>/data/hazard_db` | local hazard-catalog dir (passed through to the worker) |
| `CLIMATERISK_DEM_PATH` | unset | optional Copernicus DEM GeoTIFF for TC storm-surge (inherited by the worker) |
| `CLIMATERISK_EMDAT_PATH` | unset | optional EM-DAT loss CSV for impact-function calibration (inherited by the worker) |

The `CLIMATERISK_*` names are kept as-is because the vendored worker reads them;
renaming them would fork the vendored code.

## Seed hazard data (optional but recommended)

Without a local catalog the worker fetches hazards from the CLIMADA Data API on
every run (slow, network-bound). `scripts/physical_risk_build_hazard.py` (run in
the **worker** env) caches hazards into the local catalog at
`$CLIMATERISK_HAZARD_DB` (default `<repo>/data/hazard_db`, git-ignored):

```bash
# cache a Data-API hazard for offline / reproducible runs
./.climada-env/bin/python scripts/physical_risk_build_hazard.py cache \
    --data-type tropical_cyclone --peril tropical_cyclone \
    --scenario rcp45 --region KOR --year 2040 \
    --props '{"country_iso3alpha":"KOR","climate_scenario":"rcp45","ref_year":"2040","event_type":"synthetic","model_name":"random_walk","spatial_coverage":"country"}'

# ingest WRI Aqueduct flood layers around your assets (river_flood / coastal_flood)
./.climada-env/bin/python scripts/physical_risk_build_hazard.py ingest \
    --source aqueduct --peril river_flood --scenario rcp45 --year 2050 --point 37.5,127.0

# list what the catalog holds
./.climada-env/bin/python scripts/physical_risk_build_hazard.py list
```

The worker resolves hazards catalog-first and falls back to the live Data API.

## Testing without conda

`backend/tests/test_physical_risk_worker.py` exercises the full subprocess seam
with a fake worker (a shim `bin/python` that reads `request.json` and writes a
canned `result.json`) — request field translation, result parsing, the timeout
fallback, and the silent stub when no env exists. It runs in `.venv-pypsa`, no
conda needed. The real CLIMADA regression lives upstream in the climaterisk
project and is not vendored.
