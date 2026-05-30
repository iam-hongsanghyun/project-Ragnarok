# Ragnarok Backend — Function Reference

Covers: `backend/app/main.py`, `backend/app/config.py`, `backend/app/models.py`, `backend/app/backends/base.py`, `backend/app/backends/registry.py`.

---

## backend/app/models.py

Pydantic request/response models used across the FastAPI app.

### `RunPayload`

Pydantic `BaseModel`. The body of every `/api/run`, `/api/validate`, and binary-export/import request.

Fields:

- `model: dict[str, list[dict[str, Any]]]` — the in-memory workbook as `{sheet_name: [row_dict, ...]}`.
- `scenario: dict[str, Any]` — scenario-level parameters: `carbonPrice`, `discountRate`, `constraints`, `constraintSpecs`, `customDsl`, etc.
- `options: dict[str, Any] | None` — run-control metadata: `snapshotStart`, `snapshotCount`, `snapshotWeight`, `forceLp`, `enableLoadShedding`, `loadSheddingCost`, `currencySymbol`, `backend`, `pathwayConfig`, `rollingConfig`, `stochasticConfig`, `securityConstrainedConfig`, `solverThreads`, `solverType`, and more.

---

## backend/app/config.py

Loads and caches backend-owned JSON config files from `backend/config/`.

### `load_system_defaults() -> dict`

Reads and caches `backend/config/system_defaults.json`. Returns the full config dict including the `simulation` sub-object (`max_snapshots`, `default_snapshot_count`, `default_snapshot_weight`, `hours_in_year`) and `load_shedding` defaults. Uses `functools.lru_cache`; result is shared across the process lifetime.

---

## backend/app/backends/base.py

Defines the optimisation backend contract.

### `class BackendError(Exception)`

Raised when a requested backend name is unknown or cannot fulfil a run. Callers convert this to an HTTP 400.

### `class Backend(Protocol)`

Runtime-checkable protocol every backend adapter must satisfy.

Attributes:
- `name: str` — machine identifier used in `options["backend"]` (e.g. `"pypsa"`).
- `label: str` — human-readable display name (e.g. `"PyPSA"`).

Methods:

#### `capabilities(self) -> dict[str, Any]`
Returns a JSON-serialisable description of what this backend supports. Called by `GET /api/backends`; the frontend gates UI affordances on the returned `studyModes` and `features` dicts.

#### `run(self, model, scenario, options) -> dict[str, Any]`
Build, solve, and extract results for one case.
Params: `model` — workbook dict; `scenario` — constraint/price parameters; `options` — run metadata.
Returns: the Ragnarok result dict including `outputs.{static, series}`.

---

## backend/app/backends/registry.py

Maps `options["backend"]` strings to concrete adapter instances.

### `register_backend(backend: Backend) -> None`

Registers `backend` under its `name` (lower-cased). Last writer wins. Called at module import time to register `PypsaBackend`. Use this to add future backends without touching any other file.

### `get_backend(name: str | None = None) -> Backend`

Returns the backend for `name`, defaulting to `"pypsa"` when `name` is `None` or empty.
Raises: `BackendError` if `name` is given but not registered.

### `available_backends() -> list[dict[str, Any]]`

Returns the `capabilities()` descriptor of every registered backend. Used by `GET /api/backends`.

---

## backend/app/main.py

FastAPI application, job store, and all HTTP endpoints.

### Internal helpers

#### `class _SuppressPollLogs(logging.Filter)`

Logging filter attached to `uvicorn.access`. Suppresses the per-poll `GET /api/run/{id}` access-log lines at INFO level and re-emits them at DEBUG so the log stays clean during long solves.

#### `class _Job`

`dataclass` stored in the `_jobs` dict. Fields: `id` (UUID string), `proc` (`mp.Process`), `result_queue` (`mp.Queue`), `status` (`"running" | "done" | "error" | "cancelled"`), `result` (dict or None), `error` (str or None).

#### `_solve_worker(payload: RunPayload, result_queue: mp.Queue) -> None`

Runs inside a spawned child process. Selects the backend from `payload.options["backend"]`, calls `backend.run(payload.model, payload.scenario, options)`, and puts `("ok", result)` or `("err", message)` onto `result_queue`. Must be a module-level function so the `spawn` start method can pickle it.

#### `_collect_job(job_id: str) -> None` (async)

Background asyncio task. Polls `job.result_queue` with a 0.5 s sleep loop. On receipt of the worker's result, transitions `job.status` to `"done"` or `"error"`. If the process dies without posting a result, transitions to `"cancelled"`.

#### `_model_payload_to_network(payload: RunPayload) -> pypsa.Network`

Builds a `pypsa.Network` from a `RunPayload` without solving. Calls `build_network(payload.model, payload.scenario, payload.options)`. Used by the netCDF and HDF5 export endpoints; solve-mode flags in `options` are ignored.

#### `_network_to_model_json(network: pypsa.Network) -> dict[str, Any]`

Converts a built `pypsa.Network` back to the in-memory model shape `{sheet: [row_dict, ...]}`. Emits a `snapshots` sheet, a `network` row if named, static rows for each populated component (filtering to `input_static_attributes`), and temporal sheets `<list_name>-<attr>` for each non-empty `*_t` dynamic frame. Used by the netCDF and HDF5 import endpoints.

### HTTP endpoints

#### `GET /api/health` — `health() -> dict[str, str]`

Liveness probe. Returns `{"status": "ok"}`.

#### `GET /api/config` — `get_config() -> dict[str, Any]`

Returns snapshot limits from `system_defaults.json`: `maxSnapshots`, `defaultSnapshotCount`, `defaultSnapshotWeight`.

#### `GET /api/backends` — `get_backends() -> dict[str, Any]`

Lists registered backends and their capabilities. Returns `{"backends": [...], "default": "pypsa"}`.

#### `POST /api/validate` — `validate_case(payload: RunPayload) -> dict[str, Any]`

Runs the model validator (see `backend-network.md`) and returns `{valid, errors, warnings, notes, snapshotCount, networkSummary}`. No network is built; no solve occurs.

#### `POST /api/run` — `start_run(payload: RunPayload) -> dict[str, Any]` (async)

Starts a PyPSA optimisation job in a child process and returns immediately. Validates the backend name first (HTTP 400 on unknown backend), prunes stale completed jobs, spawns a `spawn`-context child process running `_solve_worker`, creates an asyncio background task via `_collect_job`, and returns `{"jobId": uuid, "status": "running"}`.

#### `GET /api/run/{job_id}` — `poll_run(job_id: str) -> dict[str, Any]` (async)

Returns the current job status. When status is `"done"`, returns the full result dict and removes the job from the store. On `"error"` raises HTTP 500. On `"cancelled"` raises HTTP 499. On unknown `job_id` raises HTTP 404.

#### `DELETE /api/run/{job_id}` — `cancel_run(job_id: str) -> dict[str, Any]` (async)

Terminates the child process (`proc.terminate()`, joins with 3 s timeout), marks the job cancelled, removes it from the store. Safe to call on an already-completed job.

#### `POST /api/export/netcdf` — `export_netcdf(payload: RunPayload) -> Response` (async)

Builds a `pypsa.Network` from the payload (no solve), exports to a temporary `.nc` file via `network.export_to_netcdf()`, and returns the bytes as `application/x-netcdf` with filename `ragnarok_network.nc`.

#### `POST /api/export/hdf5` — `export_hdf5(payload: RunPayload) -> Response` (async)

Same as `export_netcdf` but uses `network.export_to_hdf5()` and returns `application/x-hdf5` with filename `ragnarok_network.h5`.

#### `POST /api/import/netcdf` — `import_netcdf(file: UploadFile) -> dict[str, Any]` (async)

Accepts a PyPSA-native `.nc` upload, writes to a temp file, loads with `pypsa.Network.import_from_netcdf()`, converts via `_network_to_model_json()`, and returns `{"model": {...}}`.

#### `POST /api/import/hdf5` — `import_hdf5(file: UploadFile) -> dict[str, Any]` (async)

Same as `import_netcdf` but reads HDF5 via `pypsa.Network.import_from_hdf5()`.
