# backend-host — Function Reference

Covers: `backend/app/main.py`, `backend/app/module_host.py`, `backend/app/config.py`, `backend/app/models.py`, `backend/app/backends/base.py`, `backend/app/backends/registry.py`.

---

## backend/app/models.py

Pydantic request/response models used across the FastAPI app.

### `RunPayload`

Pydantic `BaseModel`. The body of every `/api/run`, `/api/validate`, and binary-export/import request.

Fields:

- `model: dict[str, list[dict[str, Any]]]` — the in-memory workbook as `{sheet_name: [row_dict, ...]}`.
- `scenario: dict[str, Any]` — scenario-level parameters: `carbonPrice`, `discountRate`, `constraints`, etc.
- `options: dict[str, Any] | None` — run-control metadata: `snapshotStart`, `snapshotCount`, `snapshotWeight`, `forceLp`, `enableLoadShedding`, `loadSheddingCost`, `currencySymbol`, `backend`, `enabledModules`, `pathwayConfig`, `rollingConfig`, `stochasticConfig`, `securityConstrainedConfig`, `solverThreads`, `solverType`, `moduleConfigs`, and more.

---

## backend/app/config.py

Loads and caches backend-owned JSON config files from `backend/config/`.

### `load_system_defaults() -> dict`

Reads and caches `backend/config/system_defaults.json`. Returns the full config dict including the `simulation` sub-object (`max_snapshots`, `default_snapshot_count`, `default_snapshot_weight`, `hours_in_year`) and `load_shedding` defaults. Uses `functools.lru_cache`; result is shared across the process lifetime.

### `load_module_host_config() -> dict`

Reads and caches `backend/config/module_host.json`. Returns the host's `sdk_version`, `capabilities`, `permissions`, and `managed_root` settings consumed by the module system. Uses `functools.lru_cache`.

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

#### `GET /api/modules` — `get_modules() -> dict[str, Any]`

Scans the managed module root and returns the full module discovery response from `discover_modules()`.

#### `POST /api/modules/install` — `install_module(file: UploadFile) -> dict[str, Any]`

Accepts a `.zip` upload. Delegates to `install_module_from_upload(zip_bytes)`. Returns the validated module descriptor or raises HTTP 400 on bad input.

#### `DELETE /api/modules/{module_id}` — `delete_module(module_id: str) -> dict[str, Any]`

Removes an installed module via `uninstall_module(module_id)`. Returns `{"uninstalled": True, ...}` or raises HTTP 400.

#### `POST /api/modules/{module_id}/preview` — `preview_module(module_id: str, payload: RunPayload) -> dict[str, Any]`

Invokes a single plugin's `transform` hook in isolation without running the solver. Powers action-button previews in the module panel. The plugin's `stage` field in its manifest is ignored — any installed plugin can expose a `transform` function this way. Returns `{"model": transformed_model_dict}`. Raises HTTP 400 if the hook is absent, returns None, returns a non-dict, or raises an exception.

#### `POST /api/validate` — `validate_case(payload: RunPayload) -> dict[str, Any]`

Runs the model validator (see `backend-network.md`) and returns `{valid, errors, warnings, notes, snapshotCount, networkSummary}`. No network is built; no solve occurs.

#### `POST /api/run` — `start_run(payload: RunPayload) -> dict[str, Any]` (async)

Starts a PyPSA optimisation job in a child process and returns immediately. Validates the backend name first (HTTP 400 on unknown backend), prunes stale completed jobs, spawns a `spawn`-context child process running `_solve_worker`, creates an asyncio background task via `_collect_job`, and returns `{"jobId": uuid, "status": "running"}`.

#### `GET /api/run/{job_id}` — `poll_run(job_id: str) -> dict[str, Any]` (async)

Returns the current job status. When status is `"done"`, returns the full result dict and removes the job from the store. On `"error"` raises HTTP 500. On `"cancelled"` raises HTTP 499. On unknown `job_id` raises HTTP 404.

#### `DELETE /api/run/{job_id}` — `cancel_run(job_id: str) -> dict[str, Any]` (async)

Terminates the child process (`proc.terminate()`, joins with 3 s timeout), marks the job cancelled, removes it from the store. Safe to call on an already-completed job.

#### `POST /api/export/netcdf` — `export_netcdf(payload: RunPayload) -> Response` (async)

Builds a `pypsa.Network` from the payload, exports it to a temporary `.nc` file via `network.export_to_netcdf()`, and returns the bytes as `application/x-netcdf`. No solve occurs.

#### `POST /api/export/hdf5` — `export_hdf5(payload: RunPayload) -> Response` (async)

Same as `export_netcdf` but uses `network.export_to_hdf5()` and returns `application/x-hdf5`.

#### `POST /api/import/netcdf` — `import_netcdf(file: UploadFile) -> dict[str, Any]` (async)

Accepts a PyPSA-native `.nc` upload, writes to a temp file, loads with `pypsa.Network.import_from_netcdf()`, converts via `_network_to_model_json()`, and returns `{"model": {...}}`.

#### `POST /api/import/hdf5` — `import_hdf5(file: UploadFile) -> dict[str, Any]` (async)

Same as `import_netcdf` but reads HDF5 via `pypsa.Network.import_from_hdf5()`.

---

## backend/app/module_host.py

Module discovery, installation, uninstallation, validation, and plugin execution.

### Internal helpers (private)

#### `_cfg() -> dict[str, Any]`
Returns the loaded `module_host.json` config.

#### `_sdk_version() -> str`
Returns the host's declared `sdk_version` string (used for compatibility checks).

#### `_supported_capabilities() -> list[str]`
Returns the list of capability strings the host accepts from manifests.

#### `_supported_permissions() -> list[str]`
Returns the list of permission strings the host accepts from manifests.

#### `_expand_path(raw: str) -> Path`
Resolves `${HOME}` and `${PROJECT_ROOT}` tokens in a path string to absolute `Path` objects.

#### `_managed_root_cfg() -> dict[str, Any]`
Returns the `managed_root` sub-dict from `module_host.json`.

#### `_managed_root() -> Path`
Returns the resolved `Path` of the directory where managed modules are installed. Defaults to `<repo_root>/.ragnarok/modules`.

#### `_managed_root_descriptor() -> dict[str, Any]`
Returns a JSON descriptor of the managed root: `label`, `path`, `configuredPath`, `exists`, `isDirectory`, `managed: True`.

#### `_is_relative_to(path: Path, root: Path) -> bool`
Returns `True` if `path` is inside `root`. Used as a path-traversal guard before any file operation.

#### `_load_module_entry(module_id: str) -> tuple[module_object | None, manifest_dict | None]`
Loads a module's entry Python file via `importlib.util`. Reads `module.json` to find the entry path, creates a module spec, and `exec_module`s it. Returns `(None, None)` on any failure (missing manifest, missing entry, import error). The loaded module object is used to `getattr` hook functions.

### Public functions

#### `validate_manifest(manifest: dict[str, Any], module_dir: Path | None = None) -> dict[str, Any]`

Validates a parsed `module.json` dict against the host's schema.
Params: `manifest` — parsed dict; `module_dir` — if provided, the entry file existence is checked on disk.
Returns: enriched dict with `id`, `name`, `version`, `sdkVersion`, `entry`, `entryPath`, `entryExists`, `description`, `capabilities`, `permissions`, `compatible`, `valid`, `status` (`"ready" | "invalid" | "incompatible"`), `diagnostics` (list of error strings).
Notes: checks required fields, unknown capabilities/permissions, SDK version compatibility, and entry file existence.

#### `discover_modules() -> dict[str, Any]`

Scans the managed module root. Finds every subdirectory (and the root itself) that contains a `module.json`, validates each manifest, and assembles the full discovery response.
Returns: `{"host": {sdkVersion, supportedCapabilities, supportedPermissions, managedRoot}, "modules": [...], "summary": {discovered, ready, invalid, incompatible}}`.

#### `install_module_from_upload(zip_bytes: bytes) -> dict[str, Any]`

Installs a module from a zip archive.
Params: `zip_bytes` — raw bytes of the uploaded `.zip`.
Steps: open the archive, detect the prefix (supports flat or single top-level-directory layouts), parse and validate `module.json`, extract files to `<managed_root>/<module_id>/` (skipping path traversal entries), re-validate with the final path.
Raises: `ValueError` with a human-readable message on bad zip, missing `module.json`, unresolvable id, or id already installed.
Returns: validated module descriptor plus `"installed": True`.

#### `uninstall_module(module_id: str) -> dict[str, Any]`

Removes the installed module directory `<managed_root>/<module_id>` via `shutil.rmtree`.
Params: `module_id` — must be non-empty and resolve inside the managed root.
Raises: `ValueError` if the id is blank, the path escapes the managed root, the directory does not exist, or it lacks `module.json`.
Returns: `{"uninstalled": True, "moduleId": ..., "removedPath": ...}`.

#### `get_module_metadata(module_id: str) -> dict[str, Any]`

Reads `name` and the optional `ui` dict from a module's `module.json`.
Returns: `{"name": str, "ui": dict}`. Returns `{"name": module_id, "ui": {}}` on any read failure.
Notes: used by `run_pypsa` to enrich `pluginAnalytics` with display hints so the frontend can render results generically.

#### `execute_plugins_at_stage(stage: str, enabled_ids: list[str], **kwargs) -> dict[str, Any]`

Runs all enabled plugins registered for `stage`.
Params: `stage` — one of `"pre-build"`, `"post-build"`, `"in-solve"`, `"post-solve"`; `enabled_ids` — module IDs currently enabled by the user; `**kwargs` — stage-specific context variables.

Stage contracts (what kwargs each stage receives):

| Stage | Kwargs | Return |
|---|---|---|
| `pre-build` | `model, scenario, options` | returned dict replaces `model` |
| `post-build` | `network, scenario, options` | ignored (in-place) |
| `in-solve` | `network, model, scenario, options` | ignored (in-place) |
| `post-solve` | `network, results, scenario, options` | stored in `pluginAnalytics` |

Notes: per-module errors are caught and stored as `{"error": "..."}` for all stages except `in-solve`, where they are re-raised (constraint failures must not be silently swallowed). Each plugin's own config is injected as `options["moduleConfig"]` from `options["moduleConfigs"][module_id]`.
Returns: `{module_id: return_value}` for modules that returned a non-None value.

#### `execute_module_action(module_id: str, hook_name: str, stage_kwargs_for: str = "pre-build", **kwargs) -> Any`

Invokes a named hook on a single module, bypassing the manifest `stage` filter.
Params: `module_id` — module to invoke; `hook_name` — Python function name in the entry file; `stage_kwargs_for` — which stage's kwarg contract to apply (default `"pre-build"`); `**kwargs` — stage context.
Returns: whatever the hook returns, or `None` if the module or hook cannot be loaded. Exceptions propagate to the caller.
Notes: used by `POST /api/modules/{module_id}/preview` so any plugin can expose a `transform` action regardless of its declared pipeline stage.
