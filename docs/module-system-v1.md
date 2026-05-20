# Ragnarok Plugin System v1

## Status

**v1 is fully implemented.**

All four capability types are supported, plugin code is executed by the backend at runtime,
and the frontend renders configuration and results without any hardcoded knowledge of
individual plugins.

What is working:

- local module discovery, `module.json` manifest validation, install/uninstall via the UI
- frontend sidebar manager: enable/disable, per-plugin config editing, display-mode toggle
- full backend execution pipeline across four stages (pre-build, post-build, in-solve, post-solve)
- post-solve analytics returned in `RunResults.pluginAnalytics` and rendered in the Plugins tab
- four sample plugins covering all four capability types (`sample-plugins/`)

What is **not** in v1:

- `activate()` / `deactivate()` lifecycle hooks — plugins are stateless Python callables
- dynamic frontend UI injection from module entrypoints (output is rendered through the
  generic `PluginPanel` result table, not custom React components bundled with the plugin)
- remote registry, signed modules, or sandboxed worker-process isolation

---

## Trust model

v1 uses `user-installed trusted local modules`.

- Modules are installed by the user from their own machine.
- The host copies the extracted module into a managed local directory.
- The host validates the manifest before the module can be enabled.
- The user explicitly enables each module before it participates in a run.
- No remote code is fetched by Ragnarok itself.

---

## Goals

- Let users extend Ragnarok without modifying core frontend or backend source code.
- Keep the host in control of UI, workbook state, solver execution, and compatibility checks.
- Use a narrow, versioned Python function contract so plugins are easy to write and easy to audit.
- Support four plugin capability types:
  - `data-importer` — transform or inject workbook data before the network is built
  - `data-manipulator` — patch the built network before it is solved
  - `analytics-pack` — compute and return extra metrics after the solve
  - `constraint-pack` — register additional solver constraints during solve

## Non-goals for v1

- No online marketplace or registry.
- No sandboxed third-party execution environment.
- No direct plugin access to React internals or FastAPI route registration.
- No remote module download by Ragnarok.
- No promise of process isolation beyond explicit trust by the local user.

---

## Installation

Plugins are distributed as `.zip` archives containing a `module.json` and a Python entry file.

To install, click **Install** in the **Modules** sidebar section and select the `.zip`.
The backend extracts it into the managed module root:

```
.ragnarok/modules/          ← managed root (${PROJECT_ROOT}/.ragnarok/modules)
  <module-id>/
    module.json             ← required
    main.py                 ← or whatever "entry" names
    README.md               ← optional but recommended
```

To pack a local plugin directory into an installable zip:

```bash
cd sample-plugins/ragnarok-cost-reporter
zip -r ragnarok-cost-reporter.zip .
```

To uninstall, expand the module card in the sidebar and click **Uninstall**.

---

## Manifest (`module.json`)

Every plugin must include a `module.json` at its root.

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "0.1.0",
  "sdkVersion": "1",
  "entry": "main.py",
  "stage": "post-solve",
  "hook": "analyse",
  "description": "One-line description shown in the sidebar.",
  "capabilities": ["analytics-pack"],
  "permissions": ["results.read", "analytics.register"],
  "config": {
    "my_flag": {
      "type": "boolean",
      "label": "Enable feature",
      "default": true
    }
  },
  "ui": {
    "my_metric": { "label": "My Metric", "unit": "MWh", "format": "number" }
  }
}
```

### Required fields

| Field | Type | Description |
|---|---|---|
| `id` | string | Stable unique identifier (kebab-case). Never changes across versions. |
| `name` | string | Display name shown in the sidebar and Plugins tab. |
| `version` | string | Semver string (e.g. `"0.1.0"`). |
| `sdkVersion` | string | Must be `"1"` for v1 plugins. |
| `entry` | string | Relative path to the Python entry file (e.g. `"main.py"`). |
| `stage` | string | Which pipeline stage the plugin runs at (see [Execution stages](#execution-stages)). |
| `hook` | string | Name of the Python function to call in the entry file. |
| `capabilities` | array | At least one of the four capability type strings (see below). |

### Optional fields

| Field | Type | Description |
|---|---|---|
| `description` | string | Shown in the module card and the Plugins tab. |
| `permissions` | array | Declared but not currently enforced at runtime; used for auditing. |
| `config` | object | Per-plugin config schema (see [Config schema](#config-schema)). |
| `ui` | object | Display hints for post-solve analytics results (see [UI hints](#ui-hints)). |

### Validation rules

- `sdkVersion` must match the host's supported SDK version (currently `"1"`).
- `capabilities` must be a subset of the host's known list.
- Unknown permissions are rejected during manifest validation.
- The entry file must exist in the module directory for status to be `"ready"`.

### Module status values

| Status | Meaning |
|---|---|
| `ready` | Manifest valid, SDK compatible, entry file present. Can be enabled. |
| `incompatible` | `sdkVersion` does not match the host. Disabled. |
| `invalid` | Manifest has missing/unknown fields, or entry file missing. Disabled. |

---

## Execution stages

When the user clicks **Run**, `run_pypsa()` calls `execute_plugins_at_stage()` at each
stage in order. Only plugins whose `stage` field matches are invoked.

```
POST /api/run
  │
  ├── stage: pre-build    → plugins with stage="pre-build"
  │     └─ build_network()
  │
  ├── stage: post-build   → plugins with stage="post-build"
  │
  │   network.optimize(extra_functionality=...)
  │     └── stage: in-solve   → plugins with stage="in-solve"
  │
  └── stage: post-solve   → plugins with stage="post-solve"
        └─ results returned to frontend
```

### Stage contracts

Each stage defines the arguments the hook function receives and what it may return.

#### `pre-build`

```python
def <hook>(
    model: dict[str, list[dict]],   # workbook JSON — sheet → list of row dicts
    scenario: dict,                  # carbonPrice, constraints, …
    options: dict,                   # snapshotWeight, snapshotStart, …
                                     # options["moduleConfig"] = this plugin's config
) -> dict | None:
    ...
    # Return a modified model dict to replace the workbook for downstream stages.
    # Return None to leave the model unchanged.
```

Typical capability: `data-importer`.
The host replaces the model with the plugin's return value (last writer wins if multiple
pre-build plugins are enabled).

#### `post-build`

```python
def <hook>(
    network: pypsa.Network,   # fully assembled network, not yet solved
    scenario: dict,
    options: dict,            # options["moduleConfig"] = this plugin's config
) -> None:
    ...
    # Modify network in-place. Return value is ignored.
```

Typical capability: `data-manipulator`.

#### `in-solve`

```python
def <hook>(
    network: pypsa.Network,          # network with linopy model at network.model
    model: dict[str, list[dict]],    # workbook JSON (read-only)
    scenario: dict,
    options: dict,                   # options["moduleConfig"] = this plugin's config
) -> None:
    ...
    # Register constraints via network.model.add_constraints(...).
    # Return value is ignored.
    # Exceptions are re-raised — failure aborts the solve rather than silently
    # running without the constraint.
```

Typical capability: `constraint-pack`.

#### `post-solve`

```python
def <hook>(
    network: pypsa.Network,        # solved network
    results: dict,                 # core Ragnarok results assembled so far (read-only)
    scenario: dict,
    options: dict,                 # options["moduleConfig"] = this plugin's config
) -> dict | None:
    ...
    # Return a dict of metric values to expose in the frontend.
    # Keys must match keys in the "ui" map in module.json for labelling to work.
    # Return None to emit no analytics.
```

Typical capability: `analytics-pack`.
The returned dict is stored in `RunResults.pluginAnalytics[<module-id>]` and displayed
in the Plugins workspace tab (or the sidebar card, depending on the plugin's display mode).

---

## Config schema

The `config` object in `module.json` declares per-plugin settings that are editable in
the UI before a run. The host injects the current values as `options["moduleConfig"]`
so the plugin reads its own config without knowing its ID.

Each config key maps to a field descriptor:

| Field | Required | Description |
|---|---|---|
| `type` | yes | `"boolean"`, `"number"`, `"string"`, `"select"`, `"carrier-select"` |
| `label` | no | Display label shown in the UI. Defaults to the key name. |
| `description` | no | Hint text shown below the field. |
| `default` | no | Default value used before the user edits the field. |
| `unit` | no | Unit label appended after the value. |
| `min` / `max` | no | For `"number"` — renders a slider when both are present. |
| `step` | no | Slider/input step increment for `"number"`. |
| `options` | no | For `"select"` — array of `{ "value": ..., "label": ... }` objects. |

**`carrier-select`** is a multi-checkbox field populated from the carriers defined in the
current workbook. The config value is a `list[str]` of selected carrier names.

Example:

```json
"config": {
  "renewable_floor": {
    "type": "number",
    "label": "Minimum renewable share",
    "default": 20,
    "min": 0,
    "max": 100,
    "step": 5,
    "unit": "%"
  },
  "renewable_carriers": {
    "type": "carrier-select",
    "label": "Renewable carriers",
    "default": ["wind", "solar", "hydro"]
  }
}
```

---

## UI hints

The `ui` object in `module.json` maps post-solve result keys to display metadata.
This is how the frontend labels and formats results without hardcoding anything about
a specific plugin.

```json
"ui": {
  "total_cost":   { "label": "Total System Cost", "unit": "$",     "format": "currency" },
  "lcoe_per_mwh": { "label": "LCOE",              "unit": "$/MWh", "format": "number"   },
  "by_carrier":   { "label": "Cost by Carrier",   "unit": "$",     "format": "table"    }
}
```

| `format` value | Rendered as |
|---|---|
| `"number"` | Locale-formatted number with up to 4 decimal places |
| `"currency"` | Same as `number` |
| `"table"` | Nested sub-table (value must be a `dict[str, scalar]`) |
| `"text"` or absent | Plain string |

---

## Permissions

Permissions are declared in `module.json` as a signal of intent. They are validated
against the host's supported set during manifest validation; unknown permissions cause
rejection. They are not currently enforced at Python runtime — v1 relies on the user's
trust in locally installed code.

Supported permissions:

- `filesystem.read` / `filesystem.write`
- `network.access`
- `workbook.read` / `workbook.write`
- `results.read`
- `ui.panel` / `ui.action`
- `constraints.register`
- `analytics.register`

---

## Error isolation

The runtime isolates failures per plugin:

- Import errors or missing entry files are logged and the plugin is skipped for that run.
- Runtime exceptions at `pre-build`, `post-build`, and `post-solve` are caught, logged,
  and stored as `{"error": "<message>"}` in the results — the rest of the pipeline continues.
- **`in-solve` exceptions are re-raised.** A constraint plugin that fails must abort the
  solve; swallowing the error would let the solver run silently without the declared
  constraint and produce wrong results.
- The frontend shows a plugin error row in the results table when `{"error": ...}` is present.

---

## Compatibility and versioning

- The host supports exactly one `sdkVersion` major at a time (currently `"1"`).
- Each plugin declares exactly one `sdkVersion`. Mismatched plugins are shown as
  `incompatible` and cannot be enabled.
- Capability or hook contract changes that would break existing plugins require a new
  SDK major version bump.

---

## Out of scope (post-v1)

- Remote module registry or marketplace
- Signed module packages
- Sandboxed or worker-process isolated execution for untrusted code
- Dynamic frontend UI injection from plugin bundles (custom charts, panels)
- `activate()` / `deactivate()` stateful lifecycle
- Module billing or cloud deployment
