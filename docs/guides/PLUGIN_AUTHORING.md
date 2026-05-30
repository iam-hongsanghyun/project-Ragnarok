# Ragnarok plugin authoring guide (SDK v2)

This guide covers everything you need to write, package, and register a
Ragnarok plugin. Read it top to bottom once; the reference sections are
designed for later lookup.

---

## 1. What a Ragnarok plugin is

A plugin is a **frontend-only extension** installed in the browser. It is
distributed as a `.zip` containing a JSON manifest (`module.json`) and a
JavaScript entry file (`index.js`). The browser unzips it, stores the
files in `localStorage`, renders the configuration GUI from the manifest
schema, and runs the JavaScript hooks when the user clicks "Apply to model"
or "Connect" (or similar action buttons you declare).

Plugins never execute inside the Ragnarok backend process. There is no
backend hook, no pipeline stage, and no server-side Python the plugin
controls. If a plugin needs heavy computation (building a network, running
PyPSA), it hosts its own separate local server and its JavaScript talks to
that server directly over `localhost`.

There is no enable/disable toggle. A plugin is either installed (present
and active in the Plugins tab) or uninstalled.

---

## 2. Communication topology

```
plugin JS  <-->  Ragnarok frontend    (model data, constraints, analytics)
                      |
                      v
               Ragnarok backend       (solver, PyPSA — Ragnarok-only)
                      |
                      v
               Ragnarok frontend

plugin JS  <-->  plugin's own server  (the plugin's private HTTP API)
```

Rules:

- Plugin JS may call the Ragnarok frontend (by returning values from hooks).
- Plugin JS may call the **plugin's own** backend server.
- Plugin JS must **never** call the Ragnarok backend (`/api/*`).
- The Ragnarok backend never loads, runs, or is aware of plugin code.

---

## 3. Package layout

The installable artifact is a `.zip`. Its only required contents are:

```
module.json        # manifest: metadata, GUI schema, optional server block
index.js           # CommonJS JS entry exporting hook functions
```

`module.json` and `index.js` may be at the zip root or one directory deep;
both are resolved relative to the manifest's location automatically.

A plugin that needs its own compute server ships a `backend/` directory
alongside the zip (not inside it). The browser cannot read or start that
directory — only the user does, by hand or via `plugins.env`.

```
my-plugin/
  module.json          # the manifest
  index.js             # the JS entry
  backend/
    server.py          # the plugin's own server (FastAPI, Flask, etc.)
    start.command      # self-provisioning launcher (optional but recommended)
    requirements.txt
    .venv/             # created by start.command on first run
```

When distributing the installable zip, zip only `module.json` and `index.js`
(plus any other text assets the JS needs). The `backend/` directory is not
in the zip.

---

## 4. Manifest reference (`module.json`)

```jsonc
{
  // --- Required ---
  "id": "my-plugin",           // unique identifier; used as localStorage key
  "name": "My Plugin",         // display name in the Plugins rail

  // --- Recommended ---
  "version": "1.0.0",
  "sdkVersion": "2",
  "entry": "index.js",         // entry filename; defaults to "index.js"
  "description": "One-sentence summary shown in the plugin detail pane.",

  // --- Capabilities and permissions (informational) ---
  "capabilities": ["data-importer", "constraint-pack"],
  "permissions": ["workbook.read", "workbook.write", "constraints.register"],

  // --- Panel layout ---
  "panel": {
    "inputLayout": "2x1"       // "single" | "2x1" | "1x2" | "2x2"
  },

  // --- Config schema (the GUI) ---
  "config": { /* see section 5 */ },

  // --- Optional: plugin's own local server ---
  "server": {
    "run": "python server.py --port 8765",  // command run from cwd
    "cwd": "backend",                        // relative to the plugin dir
    "port": 8765,
    "health": "/health"                      // health-check path
  }
}
```

### Top-level fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Must be unique across installed plugins. Changing it after installation creates a new plugin entry. |
| `name` | string | yes | Shown in the Plugins rail and detail header. |
| `version` | string | no | Displayed alongside the name. |
| `sdkVersion` | string | no | Use `"2"` for current plugins. |
| `entry` | string | no | Filename of the JS entry inside the zip. Defaults to `index.js`. |
| `description` | string | no | Shown under the name; also used as the Description tab body if no `panel.descriptionSections` are defined. |
| `capabilities` | string[] | no | Informational. Valid values: `data-importer`, `data-manipulator`, `analytics-pack`, `constraint-pack`. |
| `permissions` | string[] | no | Informational. Valid values: `workbook.read`, `workbook.write`, `network.access`, `filesystem.read`, `filesystem.write`, `results.read`, `ui.panel`, `ui.action`, `constraints.register`, `analytics.register`. |
| `panel` | object | no | Controls the GUI grid layout (see below). |
| `config` | object | no | The GUI schema (see section 5). |
| `server` | object | no | Declares the plugin's own local server (see section 8). |

### `panel.inputLayout`

The Input tab renders `group`-delimited sections of config fields. The
`inputLayout` value places those sections in a CSS grid:

| Value | Grid |
|---|---|
| `"single"` (default) | one column |
| `"2x1"` | two columns, left taller |
| `"1x2"` | two columns, right taller |
| `"2x2"` | two equal columns |

The typical pattern for a plugin with settings on the left and reference
tables on the right is to declare `"inputLayout": "2x1"`, put a `group`
field labelled "Settings" first, add the scalar settings, then add another
`group` labelled "Reference tables", and put `table` fields after it.

---

## 5. Config schema

The `config` object is a map of field keys to field descriptors. Order
matters: fields render top to bottom in declaration order. `group` fields
act as section dividers.

### Field descriptor common properties

| Property | Type | Notes |
|---|---|---|
| `type` | string | Required. One of the types listed below. |
| `label` | string | Display label. Defaults to the field key. |
| `description` | string | Hint text shown below the control. |
| `default` | any | Value used when the user has not set the field. |
| `unit` | string | Displayed after the value (e.g. `"TWh"`). |
| `visibleWhen` | object | `{ "field": "<key>", "equals": <value> }`. The field is hidden unless the named sibling field equals the given value. |

### Field types

**`group`** — a section heading, not a value-bearing field. Splits the
`inputLayout` grid into named sections. Config and hooks never see a
`group` key in the `config` object passed to them.

```jsonc
"sec_settings": { "type": "group", "label": "Settings" }
```

**`string`** — a single-line text input.

```jsonc
"model_path": {
  "type": "string",
  "label": "Model path",
  "default": ""
}
```

**`number`** — a numeric input. When both `min` and `max` are present,
renders as a labelled slider; otherwise renders as a plain number input.

```jsonc
"carbon_price": {
  "type": "number",
  "label": "Carbon price",
  "unit": "USD/tCO2",
  "min": 0, "max": 200, "step": 5,
  "default": 0
}
```

**`boolean`** — a checkbox.

```jsonc
"aggregate": { "type": "boolean", "label": "Aggregate by region", "default": false }
```

**`select`** — a searchable dropdown.

```jsonc
"grid_mode": {
  "type": "select",
  "label": "Grid mode",
  "default": "as-is",
  "options": [
    { "value": "as-is",   "label": "as-is — keep original topology" },
    { "value": "single",  "label": "single — collapse to one node" }
  ]
}
```

**`carrier-select`** — a multi-checkbox list populated from the carriers
currently defined in the open workbook. Falls back to `default` (an array
of carrier strings) when the workbook has no carriers yet.

```jsonc
"renewable_carriers": {
  "type": "carrier-select",
  "label": "Renewable carriers",
  "default": ["solar", "wind_onshore"]
}
```

**`file`** — a file picker. The hook receives an object
`{ name, content, mime }` where `content` is the UTF-8 text of the file.
For binary files (xlsx, parquet, png), add `"binary": true`; `content`
will then be a `data:<mime>;base64,<payload>` string.

```jsonc
"workbook": {
  "type": "file",
  "label": "Model workbook (upload)",
  "accept": ".xlsx,.xlsm",
  "binary": true
}
```

**`table`** — an editable grid with add/delete-row controls. The `columns`
array is required. Each column has `key`, optional `label`, optional `type`
(`"string"` | `"number"` | `"select"`), optional `options` (for select
cells), and optional `width` (CSS value or px number). The hook receives
the value as `Array<Record<string, string | number>>`.

```jsonc
"cf_limits": {
  "type": "table",
  "label": "CF limits",
  "maxHeight": 260,
  "columns": [
    { "key": "carrier",   "label": "Carrier",   "width": 120 },
    { "key": "attribute", "label": "Attribute",  "type": "select",
      "options": [{ "value": "max_cf" }, { "value": "min_cf" }] },
    { "key": "value",     "label": "Value",      "type": "number", "width": 80 }
  ],
  "default": []
}
```

**`action`** — a button that invokes a named hook when clicked. The
`hook` property names the exported function to call (see section 6). Use
`"hook": "transform"` to run the apply path (same as clicking "Apply to
model"). Any other name (e.g. `"connect"`) invokes the same-named export
and toasts its returned `{ ok, message }`.

```jsonc
"connect_btn": {
  "type": "action",
  "label": "Connect to build server",
  "hook": "connect",
  "variant": "secondary",
  "description": "Checks that the plugin's own server is reachable.",
  "successMessage": "Connected."
}
```

`variant` is `"primary"` (default) or `"secondary"`.

### `visibleWhen` example

```jsonc
"single_bus_name": {
  "type": "string",
  "label": "Single bus name",
  "default": "KR",
  "visibleWhen": { "field": "grid_mode", "equals": "single" }
}
```

The field is shown only when `grid_mode` equals `"single"`. Equality is
coerced: a string `"true"` matches a boolean `true` for select-to-boolean
gates, so prefer `"equals": true` for boolean siblings.

---

## 6. The JS entry (`index.js`)

The entry file is evaluated as CommonJS in the browser. Export any subset
of three hooks plus any named action functions:

```js
module.exports = {

  // Replace the whole workbook model.
  // Return value: WorkbookModel — { sheetName: GridRow[] }
  // Runs when the user clicks "Apply to model" (or an action with hook:"transform").
  async transform(model, config) {
    // model is the current workbook; return a completely new one.
    return newModel;
  },

  // Contribute inputs without replacing the whole model.
  // Return: { sheets?, constraints? }
  //   sheets:      { sheetName: GridRow[] }  — merged (not replaced) into model
  //   constraints: string[]                  — DSL lines appended to the
  //                                            Advanced Constraints code box
  contribute(model, config) {
    return {
      sheets: {
        generators: [{ name: 'solar_farm', carrier: 'solar', bus: 'A', p_nom: 500 }],
      },
      constraints: [`cf("solar") >= ${config.min_solar_cf}`],
    };
  },

  // Post-run analytics.
  // result is the full RunResults object from the Ragnarok backend.
  // Return: Record<string, unknown> — displayed in the Output tab.
  async analyze(result, config) {
    const total = result.summary?.[0]?.value ?? '—';
    return { total_cost: total };
  },

  // Named action hook — invoked by an action field with hook:"connect".
  // Return: { ok: boolean, message?: string } — drives a success/error toast.
  async connect(config) {
    try {
      const r = await fetch(`${config.backendUrl}/health`);
      return r.ok
        ? { ok: true,  message: 'Server reachable.' }
        : { ok: false, message: `Server returned ${r.status}.` };
    } catch (e) {
      return { ok: false, message: 'Cannot reach server — is it running?' };
    }
  },

};
```

Rules:

- Any hook may be `async`. The UI shows a spinner while the promise is pending.
- `transform` and `contribute` are mutually exclusive: if both are exported,
  `transform` wins.
- If neither `transform` nor `contribute` is exported, "Apply to model" is
  not shown. If `analyze` is not exported, the Output tab shows nothing.
- Throw on bad input. The runtime catches the error and surfaces it as a
  toast without crashing the app.
- No Ragnarok globals are injected. Only `module` and `exports` are
  available (standard CommonJS).

### WorkbookModel shape

```ts
type WorkbookModel = Record<string, GridRow[]>;
type GridRow       = Record<string, string | number | boolean | null>;
```

Sheet names follow the PyPSA schema: `buses`, `generators`, `loads`,
`lines`, `links`, `storage_units`, `stores`, `carriers`,
`global_constraints`, `snapshots`, and `*-<attr>` time-series sheets
(e.g. `generators-p_max_pu`). A `transform` return value is passed through
as-is; the frontend validates nothing beyond the presence of `buses`.

---

## 7. Own-server pattern

When your plugin needs computation that cannot run in the browser (parsing
a large Excel file, running a PyPSA build pipeline, calling a licensed
solver), host it in your own local HTTP server. The plugin's JavaScript
calls that server over `localhost`:

```js
async transform(model, config) {
  const base = String(config.backendUrl || 'http://127.0.0.1:8765').replace(/\/+$/, '');
  const resp = await fetch(base + '/build', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config }),
  });
  if (!resp.ok) {
    const j = await resp.json().catch(() => ({}));
    throw new Error('Build failed: ' + (j.detail ?? resp.status));
  }
  return await resp.json();   // must be a WorkbookModel
}
```

The server speaks plain HTTP JSON. A minimal FastAPI example:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

class BuildRequest(BaseModel):
    config: dict = {}

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/build")
def build(req: BuildRequest) -> dict:
    # return a WorkbookModel: { sheetName: [{"col": val, ...}, ...] }
    return my_build_pipeline(req.config)
```

The server must enable CORS for all origins because the Ragnarok frontend
runs at a different port (`localhost:3000`) from the plugin server.

Never route requests through the Ragnarok backend (`localhost:8000`). The
plugin server is entirely separate.

---

## 8. Server registration and launch

### `plugins.env`

Create a file called `plugins.env` in the Ragnarok project root (next to
`run.command`). Each non-comment line is:

```
<absolute path to server directory>|<run command>
```

Example:

```
# Dashboard Importer
/Users/you/simplePyPSA_KR/plugins_V2/ragnarok-dashboard-importer/backend|python server.py --port 8765
```

Blank lines and lines starting with `#` are ignored. Copy
`plugins.env.example` to `plugins.env` to get the annotated template.

### How `run.command` uses it

When you start Ragnarok with `run.command` (double-click on macOS or run
from a terminal), after launching the Ragnarok backend and waiting for it
to be ready, `run.command` reads `plugins.env` line by line. For each
entry whose directory exists on disk, it `cd`s into that directory and
runs the command in a subprocess.

If the server directory contains a `.venv/bin/activate`, `run.command`
activates that virtual environment first (so the plugin's own dependencies
win). Otherwise it falls back to Ragnarok's own venv. An explicit
interpreter path in the command (e.g. `.venv/bin/python server.py`)
always takes precedence.

All plugin servers are killed automatically when `run.command` exits.

### "Server setup" advisory in the Plugins tab

When the manifest declares a `server` block, the plugin detail pane shows
a "Server setup" section below the config GUI. It displays the exact
`plugins.env` line to add, with a path placeholder
(`/absolute/path/to/<plugin-id>/...`), because the browser cannot discover
where on disk the plugin is installed. You fill in the real path.

Click "Copy entry" to copy the advisory text to the clipboard, then paste
it into `plugins.env`.

### `backend/start.command` (standalone launcher)

For development or on-demand use, the plugin can also ship a
`backend/start.command` that self-provisions its own virtual environment
and starts the server without `run.command`. This is a plain Bash script:

```bash
#!/bin/bash
set -e
cd "$(dirname "$0")"
VENV=".venv"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q -r requirements.txt
exec "$VENV/bin/python" server.py --port "${PORT:-8765}"
```

The same `.venv` is reused by `run.command` when the plugin is registered
in `plugins.env`.

---

## 9. How plugin constraints reach the solver

There are two paths:

**Path A — `contribute().constraints` (DSL lines)**

Your `contribute` hook returns an array of DSL constraint strings:

```js
contribute(model, config) {
  return {
    constraints: [
      `cf("coal") <= ${config.max_coal_cf}`,
      'emissions <= 0.4 * gen',
    ],
  };
}
```

These lines are appended to the Advanced Constraints code box in
Settings. The frontend compiles all DSL lines to a structured
`constraintSpecs` JSON object which is sent to the Ragnarok backend on
Run. The plugin never sends anything to the backend itself.

**Path B — `RAGNAROK_CustomDSL` sheet**

A `transform` hook can embed DSL text directly in the workbook by
returning a sheet named `RAGNAROK_CustomDSL` containing rows of
`{ text: "..." }`. The frontend loads this sheet into the Advanced
Constraints code box when it replaces the model.

**Path C — `global_constraints` sheet (native)**

System-level caps (CO2 budget, technology expansion limits) belong in the
`global_constraints` sheet, not in DSL. These are rendered in Settings
as Standard Constraints and are passed to PyPSA natively.

### DSL grammar

One linear constraint per line. `#` starts a comment.

| Atom | Meaning |
|---|---|
| `gen` | total system energy generation (MWh) |
| `gen("carrier")` | energy from a specific carrier (MWh) |
| `cap("carrier")` | total installed capacity of a carrier (MW) |
| `cf("carrier")` | capacity factor of a carrier (fraction 0-1) |
| `emissions` | total system emissions (tCO2) |
| `load_shed` | total unserved energy (MWh) |

Operators: `<=`, `>=`, `==`. Arithmetic: `+`, `-`, `*` with numeric
constants. One constraint per line.

```
cf("coal") <= 0.4
gen("coal") <= 200000
emissions <= 0.4 * gen
load_shed <= 0
cap("wind_onshore") >= 5000
```

---

## 10. Install and uninstall

**Install:**
1. Open the Plugins tab in Ragnarok.
2. Click "Install plugin".
3. Select the plugin `.zip` file.
4. The GUI renders immediately from the manifest schema.

There is no enable/disable toggle. An installed plugin is active.
Installing a plugin with the same `id` as an existing one replaces it.

**Uninstall:**
Click the plugin name in the Plugins rail, scroll to the bottom of the
detail pane, and click "Uninstall". The plugin's config is also removed
from `localStorage`.

Config values persist across page refreshes and browser restarts because
they are stored in `localStorage` under a key derived from the plugin `id`.
Uninstalling clears them.

---

## 11. Examples

### Minimal transform plugin (15 lines)

A plugin that forces every generator in a chosen carrier to `p_nom = 0`.

**`module.json`:**

```json
{
  "id": "zero-out-carrier",
  "name": "Zero Out Carrier",
  "version": "1.0.0",
  "sdkVersion": "2",
  "entry": "index.js",
  "description": "Sets p_nom = 0 for all generators of the selected carrier.",
  "capabilities": ["data-manipulator"],
  "permissions": ["workbook.read", "workbook.write"],
  "config": {
    "carrier": {
      "type": "string",
      "label": "Carrier to zero out",
      "default": "coal"
    }
  }
}
```

**`index.js`:**

```js
module.exports = {
  transform(model, config) {
    const carrier = String(config.carrier || '');
    const generators = (model.generators || []).map((row) =>
      row.carrier === carrier ? { ...row, p_nom: 0 } : row
    );
    return { ...model, generators };
  },
};
```

Zip both files, install the zip. Click "Apply to model" after selecting
the carrier. The workbook's generators sheet updates in memory; click Run
to solve.

### Dashboard Importer — full real-world example

The `ragnarok-dashboard-importer` plugin in
`simplePyPSA_KR/plugins_V2/ragnarok-dashboard-importer/` is the canonical
reference implementation. The following describes its architecture.

**GUI schema (`module.json` highlights):**

- `"inputLayout": "2x1"` produces a two-column panel: a "Settings" column
  on the left and a "Reference tables" column on the right.
- The Settings column contains scalar fields (`string`, `boolean`,
  `select`) and two `action` buttons: "Connect to build server"
  (`hook: "connect"`) and "Send model to Ragnarok" (`hook: "transform"`).
- The Reference tables column contains `table` fields (CC merge rules,
  province mapping, region aggregation rules, carrier aggregation rules,
  CF constraint values, carbon price curves, emission intensities), each
  gated with `visibleWhen` so they appear only when the relevant feature
  is enabled.

**Hooks (`index.js`):**

- `connect(config)` — GETs `/health` on the plugin's own build server at
  `config.backendUrl` (default `http://127.0.0.1:8765`) and returns
  `{ ok, message }`. Surfaced as a toast.
- `transform(model, config)` — POSTs the entire config object to `/build`
  on the same server. The server runs the PyPSA build pipeline and returns
  a `WorkbookModel` JSON object. The frontend replaces the current workbook
  with it. Does not call the Ragnarok backend.

**Own server (`backend/server.py`):**

A FastAPI application with two routes: `GET /health` and `POST /build`.
The `/build` route calls the existing `transform()` build pipeline from
`main.py` and returns its output (sheets of rows) as JSON.

CORS is open to all origins so the browser plugin on `localhost:3000` can
reach the server on `localhost:8765`.

**Self-provisioning launcher (`backend/start.command`):**

Creates `backend/.venv` on first run, installs `requirements.txt` with a
hash-based change detection to skip reinstalls, then starts `server.py`.
Double-click on macOS or run from a terminal.

**Registration in `plugins.env`:**

```
# Dashboard Importer
/Users/you/simplePyPSA_KR/plugins_V2/ragnarok-dashboard-importer/backend|python server.py --port 8765
```

`run.command` detects `backend/.venv`, activates it, and runs the command.
Ragnarok and the build server start together.

**CF-constraint flow:**

The "CF constraints enabled" boolean in the GUI enables a `constraints_rows`
table (carrier, attribute, year, value). When "Send model to Ragnarok" is
clicked, the build pipeline reads that table, filters to `target_year`, and
returns a `RAGNAROK_CustomDSL` sheet embedding DSL lines such as
`cf("coal") <= 0.4`. The frontend loads those lines into the Advanced
Constraints code box. On Run, they are compiled to `constraintSpecs` JSON
and sent to the Ragnarok backend.

---

## Troubleshooting

### "Entry file not found in the plugin package"

**Cause:** The `entry` field in `module.json` names a file that is not in
the zip.
**Fix:** Check that the filename matches exactly (case-sensitive) and is at
the same directory level as `module.json`.

### "module.json is missing an id"

**Cause:** The `id` field is absent or empty.
**Fix:** Add a non-empty `"id"` string to `module.json`.

### Action button does nothing / "Plugin has no X hook"

**Cause:** A field declares `hook: "connect"` but `index.js` does not
export a `connect` function.
**Fix:** Add `module.exports.connect = async function(config) { ... }` to
`index.js`.

### Build server not reachable

**Cause:** The plugin's own server is not running, or is on a different
port than `config.backendUrl`.
**Fix:** Start the server manually (`backend/start.command` or
`python server.py`). Check that the port matches. Click "Connect" to verify
the health check passes before clicking "Send model".

### Config values lost after reinstall

**Cause:** Uninstalling clears the `localStorage` config for that plugin id.
**Fix:** Export the config values before uninstalling (or note them down).
Reinstalling restores the GUI defaults, not the previous user values.

### Plugin server not started by `run.command`

**Cause:** The directory path in `plugins.env` does not exist on disk, or
`plugins.env` is not in the Ragnarok project root.
**Fix:** Verify the absolute path, restart Ragnarok with `run.command`,
and check the terminal output for "Starting plugin server" or "Skip plugin
server" messages.
