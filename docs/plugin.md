# Ragnarok Plugin System — Authoritative Guide

This document is the single authoritative reference for Ragnarok's plugin system.
It covers the concept, the communication contract, the manifest schema, the
rendered GUI, every JS hook, the own-server pattern, constraint flow,
install/uninstall, a minimal worked example, a walkthrough of the Dashboard
Importer, and a troubleshooting section.

For the internals of `useFrontendPlugins` and `PluginPanel` (host-side React
code) see `docs/frontend.md`. Everything else is here.

---

## Table of contents

1. [What a plugin is](#1-what-a-plugin-is)
2. [Communication topology](#2-communication-topology)
3. [Package layout](#3-package-layout)
4. [Manifest reference (`module.json`)](#4-manifest-reference-modulejson)
   - 4.1 [Top-level fields](#41-top-level-fields)
   - 4.2 [`panel` block](#42-panel-block)
   - 4.3 [`server` block](#43-server-block)
5. [Config schema and field types](#5-config-schema-and-field-types)
   - 5.1 [Common properties](#51-common-properties)
   - 5.2 [Field type catalogue](#52-field-type-catalogue)
   - 5.3 [`visibleWhen` gates](#53-visiblewhen-gates)
6. [The rendered GUI](#6-the-rendered-gui)
   - 6.1 [Description tab](#61-description-tab)
   - 6.2 [Input tab and grid layout](#62-input-tab-and-grid-layout)
   - 6.3 [Output tab](#63-output-tab)
   - 6.4 [Footer "Apply to model" button](#64-footer-apply-to-model-button)
   - 6.5 ["Server setup" advisory](#65-server-setup-advisory)
7. [JS entry file (`index.js`)](#7-js-entry-file-indexjs)
   - 7.1 [Hook signatures](#71-hook-signatures)
   - 7.2 [WorkbookModel shape](#72-workbookmodel-shape)
   - 7.3 [Named action hooks](#73-named-action-hooks)
   - 7.4 [Runtime rules](#74-runtime-rules)
8. [Own local server pattern](#8-own-local-server-pattern)
   - 8.1 [Minimal FastAPI server](#81-minimal-fastapi-server)
   - 8.2 [CORS requirement](#82-cors-requirement)
9. [Server registration and launch](#9-server-registration-and-launch)
   - 9.1 [`plugins.env` format](#91-pluginsenv-format)
   - 9.2 [How `run.command` uses `plugins.env`](#92-how-runcommand-uses-pluginsenv)
   - 9.3 [Virtual-environment resolution order](#93-virtual-environment-resolution-order)
   - 9.4 [`backend/start.command` standalone launcher](#94-backendstartcommand-standalone-launcher)
   - 9.5 [In-GUI "Server setup" advisory](#95-in-gui-server-setup-advisory)
10. [Constraint flow](#10-constraint-flow)
    - 10.1 [Path A — `contribute().constraints`](#101-path-a--contributeconstraints)
    - 10.2 [Path B — `RAGNAROK_CustomDSL` sheet](#102-path-b--ragnarok_customdsl-sheet)
    - 10.3 [Path C — `global_constraints` sheet (native)](#103-path-c--global_constraints-sheet-native)
    - 10.4 [DSL grammar reference](#104-dsl-grammar-reference)
11. [Install and uninstall](#11-install-and-uninstall)
12. [Minimal end-to-end example](#12-minimal-end-to-end-example)
13. [Dashboard Importer — full walkthrough](#13-dashboard-importer--full-walkthrough)
14. [Troubleshooting](#14-troubleshooting)
15. [SDK changelog](#15-sdk-changelog)
16. [Backend (server-side) plugins](#16-backend-server-side-plugins)

---

## 1. What a plugin is

Ragnarok has **two kinds** of plugin:

| Kind | Runs in | Distributed as | Discovered via | Own server? |
|---|---|---|---|---|
| **Frontend plugin** | the browser (evaluated JS) | a `.zip` you install in the Plugins tab | `localStorage` | optionally its own local HTTP server, registered in `plugins.env` |
| **Backend plugin** | the Ragnarok **backend** process | a `.zip` (manifest.json + plugin.py) you install in the Plugins tab | `GET /api/plugins` (installed into the gitignored `backend/data/plugins/`) | no — it imports the bundled PyPSA source directly; nothing in `plugins.env` |

**Sections 1–15 of this guide describe FRONTEND plugins.** Backend plugins —
the server-side kind that imports PyPSA directly and writes its model straight
into the session — are covered in [section 16](#16-backend-server-side-plugins).
Use a backend plugin when you want the build to run on the server (the
server-side / iPad-thin-client deployment) with no separate process to launch;
use a frontend plugin when the logic is light enough for the browser or when
you want to keep an existing own-server build pipeline.

A **frontend plugin** runs entirely in the browser. You distribute it as a
`.zip` containing a JSON manifest (`module.json`) and a JavaScript entry file
(`index.js`). When you install the zip, the browser unpacks it, stores the
files in `localStorage`, renders a configuration GUI from the manifest schema,
and invokes the JavaScript hooks when you click "Apply to model", "Connect", or
any other action button declared in the manifest.

A frontend plugin never executes inside the Ragnarok backend process. If it
needs heavy computation — building a network, running PyPSA, parsing a large
Excel file — it either hosts its **own** separate local HTTP server (the
own-server pattern in section 8, registered in `plugins.env`) **or** is
re-implemented as a backend plugin (section 16). Either way the plugin never
calls the Ragnarok backend's own `/api/*` routes.

There is no enable/disable toggle. A plugin is either installed (present and
active in the Plugins tab) or uninstalled. Installing a plugin with an `id`
that matches an existing plugin replaces it in place.

---

## 2. Communication topology

```
plugin JS  <-->  Ragnarok frontend    (model data, constraints, analytics)
                      |
                      v
               Ragnarok backend       (solver, PyPSA — Ragnarok only)
                      |
                      v
               Ragnarok frontend

plugin JS  <-->  plugin's own server  (the plugin's private HTTP API)
```

The rules enforced by this topology:

- Plugin JS may call the Ragnarok **frontend** by returning values from hooks
  (`transform`, `contribute`, `analyze`). The frontend receives the return
  value and applies it to the workbook or displays it.
- Plugin JS may call the plugin's **own** backend server (any local HTTP
  endpoint the plugin controls).
- Plugin JS must **never** call the Ragnarok backend (`/api/*`). The Ragnarok
  backend never loads, evaluates, or is aware of plugin code.

This boundary is architectural, not merely advisory. The Ragnarok backend is
designed to be unaware that plugins exist.

---

## 3. Package layout

The installable artifact is a `.zip`. The only required contents are:

```
module.json        # manifest: metadata, GUI schema, optional server block
index.js           # CommonJS JS entry exporting hook functions
```

Both files may sit at the zip root or one directory deep. The runtime resolves
`index.js` relative to wherever `module.json` is found.

A plugin that needs its own compute server ships a `backend/` directory
alongside the zip, not inside it. The browser cannot read or start that
directory. The user starts it manually or registers it in `plugins.env` so
`run.command` starts it automatically.

```
my-plugin/
  module.json          # the manifest (goes in the zip)
  index.js             # the JS entry (goes in the zip)
  backend/
    server.py          # the plugin's own HTTP server — NOT in the zip
    start.command      # self-provisioning launcher (optional but recommended)
    requirements.txt
    .venv/             # created by start.command on first run
```

When distributing the installable zip, include only `module.json` and
`index.js` (plus any other text assets the JS needs). The `backend/` directory
is not zipped.

---

## 4. Manifest reference (`module.json`)

A complete annotated manifest:

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
    "inputLayout": "2x1",
    "descriptionLayout": "single",
    "outputLayout": "single",
    "descriptionSections": [
      { "title": "What it does", "body": "Longer description..." }
    ]
  },

  // --- Config schema (the GUI) ---
  "config": { /* see section 5 */ },

  // --- Optional: plugin's own local server ---
  "server": {
    "run": "python server.py --port 8765",
    "cwd": "backend",
    "port": 8765,
    "health": "/health"
  }
}
```

### 4.1 Top-level fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Must be unique across installed plugins. Changing it after installation creates a separate new entry. |
| `name` | string | yes | Shown in the Plugins rail and detail header. |
| `version` | string | no | Displayed alongside the name. |
| `sdkVersion` | string | no | Use `"2"` for all current plugins. |
| `entry` | string | no | Filename of the JS entry inside the zip, resolved relative to `module.json`. Defaults to `"index.js"`. |
| `description` | string | no | Single-sentence summary. Used as the Description tab body when no `panel.descriptionSections` are declared. |
| `capabilities` | string[] | no | Informational. Valid values: `"data-importer"`, `"data-manipulator"`, `"analytics-pack"`, `"constraint-pack"`. |
| `permissions` | string[] | no | Informational. Valid values: `"workbook.read"`, `"workbook.write"`, `"network.access"`, `"filesystem.read"`, `"filesystem.write"`, `"results.read"`, `"ui.panel"`, `"ui.action"`, `"constraints.register"`, `"analytics.register"`. |
| `panel` | object | no | Controls GUI layout for Description, Input, and Output tabs. See section 4.2. |
| `config` | object | no | The GUI schema. See section 5. |
| `server` | object | no | Declares the plugin's own local server for the "Server setup" advisory. See section 4.3. |

### 4.2 `panel` block

```jsonc
"panel": {
  "inputLayout": "2x1",             // grid for the Input tab
  "descriptionLayout": "single",    // grid for the Description tab
  "outputLayout": "single",         // grid for the Output tab
  "descriptionSections": [          // overrides the plain `description` string
    { "title": "Overview", "body": "..." },
    { "body": "Second section, no title." }
  ]
}
```

The layout values control the CSS grid that wraps the plugin panel sections:

| Value | Grid |
|---|---|
| `"single"` (default) | one column, full width |
| `"2x1"` | two columns; left column is taller / gets more space |
| `"1x2"` | two columns; right column is taller / gets more space |
| `"2x2"` | two roughly equal columns |

The typical pattern for a plugin with scalar settings on the left and editable
reference tables on the right: set `"inputLayout": "2x1"`, declare a `group`
field labelled "Settings" first, add the scalar fields after it, then declare
another `group` labelled "Reference tables" and put `table` fields after that.
Each `group` field starts a new grid section.

`descriptionSections` is an array of `{ title?, body }` objects. When
provided, it replaces the plain `description` string as the Description tab
content and allows structured multi-section descriptions.

### 4.3 `server` block

```jsonc
"server": {
  "run": "python server.py --port 8765",  // command run from cwd
  "cwd": "backend",                        // relative to the plugin dir on disk
  "port": 8765,
  "health": "/health"                      // health-check path; shown in advisory
}
```

| Field | Type | Notes |
|---|---|---|
| `run` | string | Required. Shell command that starts the server. |
| `cwd` | string | Optional. Subdirectory to `cd` into before running, relative to the plugin's disk directory. Typically `"backend"`. |
| `port` | number | Optional. Port the server listens on. Used only for display in the advisory. |
| `health` | string | Optional. Health-check path shown in the advisory (default `/health`). |

The `server` block does not launch anything. It only drives the "Server setup"
advisory shown in the plugin detail pane (see section 9.5). Actual launch is
controlled by `plugins.env` and `run.command`.

---

## 5. Config schema and field types

The `config` object in `module.json` is a map of field keys to field
descriptors. Fields render top to bottom in declaration order. `group` fields
act as section dividers and do not appear in the config object passed to hooks.

### 5.1 Common properties

Every field descriptor (regardless of type) may include:

| Property | Type | Notes |
|---|---|---|
| `type` | string | Required. One of the types listed in section 5.2. |
| `label` | string | Display label. Defaults to the field key if absent. |
| `description` | string | Hint text rendered below the control. |
| `default` | any | Value pre-filled when the user has not set the field. Also used as the fallback value when `visibleWhen` prevents a sibling field from being evaluated. |
| `unit` | string | Displayed after the value (e.g. `"TWh"`, `"USD/tCO2"`). |
| `visibleWhen` | object | Conditional visibility gate. See section 5.3. |

### 5.2 Field type catalogue

**`group`**

A section heading, not a value-bearing field. Each `group` creates a new
section in the `inputLayout` grid. Config objects and hook arguments never
contain a key for a `group` field.

```jsonc
"sec_settings": { "type": "group", "label": "Settings" }
```

---

**`string`**

A single-line text input.

```jsonc
"model_path": {
  "type": "string",
  "label": "Model path",
  "description": "Absolute path to the workbook on the build server.",
  "default": ""
}
```

A `string` field with no `min`/`max` renders as `<input type="text">`.

---

**`number`**

A numeric input. When both `min` and `max` are present, renders as a labelled
slider. Without them, renders as `<input type="number">`.

```jsonc
"carbon_price": {
  "type": "number",
  "label": "Carbon price",
  "unit": "USD/tCO2",
  "min": 0,
  "max": 200,
  "step": 5,
  "default": 0
}
```

Additional properties: `min` (number), `max` (number), `step` (number).

---

**`boolean`**

A checkbox.

```jsonc
"aggregate": {
  "type": "boolean",
  "label": "Aggregate by region",
  "default": false
}
```

---

**`select`**

A searchable dropdown. Requires an `options` array.

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

Each option requires a `value` property. The `label` property is optional and
defaults to `value` when absent. Instead of a static `options` array, a `select`
field may declare [`optionsFrom`](#dynamic-options-optionsfrom) to source its
options from the model or a sibling config table.

---

**`multi-select`**

A checkbox list over an `options` array — pick zero or more. The general
form of `carrier-select` (which is hard-wired to workbook carriers); use this
when the choices are anything other than carriers. Like `select`, it may use
[`optionsFrom`](#dynamic-options-optionsfrom) instead of a static `options` array.

```jsonc
"sectors": {
  "type": "multi-select",
  "label": "Sectors to include",
  "default": ["power", "heat"],
  "options": [
    { "value": "power",     "label": "Electricity" },
    { "value": "heat",      "label": "Heat" },
    { "value": "hydrogen",  "label": "Hydrogen" },
    { "value": "transport", "label": "Transport" }
  ]
}
```

The hook receives the value as a `string[]` of the selected `value`s. As with
`select`, each option's `label` defaults to its `value`.

---

**`carrier-select`**

A multi-checkbox list populated from the carriers defined in the currently open
workbook. When the workbook has no carriers defined yet, falls back to the
`default` array.

```jsonc
"renewable_carriers": {
  "type": "carrier-select",
  "label": "Renewable carriers",
  "default": ["solar", "wind_onshore"]
}
```

The hook receives the value as a `string[]` of selected carrier names.

---

**`file`**

A file picker. The hook receives an object `{ name, content, mime }` where
`name` is the filename, `mime` is the MIME type, and `content` is:
- the UTF-8 text of the file when `binary` is absent or `false`
- a `data:<mime>;base64,<payload>` string when `binary: true`

Use `binary: true` for xlsx, parquet, png and any other format that would be
corrupted by UTF-8 decoding.

```jsonc
"workbook": {
  "type": "file",
  "label": "Model workbook (upload)",
  "accept": ".xlsx,.xlsm",
  "binary": true
}
```

Additional properties: `accept` (string, passed to `<input accept>`),
`binary` (boolean).

---

**`table`**

An editable grid with add-row and delete-row controls. The `columns` array is
required. Each column descriptor:

| Property | Type | Notes |
|---|---|---|
| `key` | string | Required. Property name on each row object. |
| `label` | string | Column header. Defaults to `key`. |
| `type` | string | Cell input type: `"string"` (default), `"number"`, or `"select"`. |
| `options` | array | For `"select"` cells: `[{ "value": "...", "label": "..." }]`. |
| `optionsFrom` | object | For `"select"` cells: a dynamic option source. Overrides `options`. See [dynamic options](#dynamic-options-optionsfrom). |
| `width` | string or number | Optional CSS width. Numbers are treated as px. |

The hook receives the value as `Array<Record<string, string | number>>`. Empty
cells default to `""` for string columns and `0` for number columns.

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

Additional property: `maxHeight` (number, pixels, default 260). When the table
body exceeds this height, it scrolls.

---

### Dynamic options (`optionsFrom`)

A `select` / `multi-select` **field**, and a `"select"` **table column**, may
declare `optionsFrom` instead of (or alongside) a static `options` array. The
host resolves it to an option list at render time. When `optionsFrom` resolves
to at least one option it wins; if it resolves to nothing (e.g. no model is
loaded yet), the static `options` are used as a fallback.

| Property | Type | Notes |
|---|---|---|
| `source` | string | `"model"` or `"config"`. Required. |
| `sheet` | string | For `source: "model"`: the workbook sheet to read (e.g. `"buses"`). |
| `field` | string | For `source: "config"`: the sibling config field key whose `table` rows to read (e.g. `"province_mapping"`). |
| `column` | string | Row property used as the option **value**. Defaults to `"name"`. |
| `labelColumn` | string | Row property used as the option **label**. Defaults to `column`. |

Both sources read distinct values (blank values dropped, duplicates collapse to
the first occurrence).

- **`source: "model"`** pulls from the currently open workbook — e.g. bus names:

  ```jsonc
  { "key": "bus", "label": "Bus", "type": "select",
    "optionsFrom": { "source": "model", "sheet": "buses" } }
  ```

- **`source: "config"`** pulls from another `table` field the user is editing,
  live — e.g. the provinces typed into a `province_mapping` table:

  ```jsonc
  { "key": "province", "label": "Province", "type": "select",
    "optionsFrom": { "source": "config", "field": "province_mapping", "column": "province" } }
  ```

**Switching options by another field's value.** `optionsFrom` itself does not
branch on a sibling value; use the field-level [`visibleWhen`](#53-visiblewhen-gates)
gate for that. Declare one `table` field per case, each gated on the controlling
field, each with its own `optionsFrom`. For example, a `resolution` selector
with a bus-keyed table when `resolution = "bus"` and a province-keyed table when
`resolution = "province"`:

```jsonc
"resolution": {
  "type": "select", "label": "Resolution", "default": "bus",
  "options": [{ "value": "bus" }, { "value": "province" }]
},
"bus_table": {
  "type": "table", "label": "By bus",
  "visibleWhen": { "field": "resolution", "equals": "bus" },
  "columns": [
    { "key": "bus", "type": "select", "optionsFrom": { "source": "model", "sheet": "buses" } },
    { "key": "value", "type": "number" }
  ]
},
"province_table": {
  "type": "table", "label": "By province",
  "visibleWhen": { "field": "resolution", "equals": "province" },
  "columns": [
    { "key": "province", "type": "select",
      "optionsFrom": { "source": "config", "field": "province_mapping", "column": "province" } },
    { "key": "value", "type": "number" }
  ]
}
```

---

**`action`**

A button that invokes a named hook when clicked. The button shows a spinner
while the hook is pending.

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

Additional properties:

| Property | Type | Notes |
|---|---|---|
| `hook` | string | Name of the exported function to call. `"transform"` runs the apply path (same as the footer "Apply to model" button). Any other name (e.g. `"connect"`) invokes that export and surfaces its returned `{ ok, message }` as a toast. Defaults to `"transform"`. |
| `variant` | string | `"primary"` (default, solid button) or `"secondary"` (outlined button). |
| `successMessage` | string | Toast text shown on success. |

When the manifest declares at least one `action` field, the footer "Apply to
model" button is hidden to avoid duplicating the trigger.

### 5.3 `visibleWhen` gates

A field is hidden unless the gate condition is satisfied. Gates are evaluated
against the live config values of sibling fields.

```jsonc
"visibleWhen": { "field": "<sibling-key>", "equals": <value> }
```

Type coercion rules:

- When `equals` is `true` or `false`, the sibling value is coerced with
  `Boolean()` before comparison.
- When `equals` is a number, the sibling is coerced with `Number()`.
- Otherwise both sides are coerced to strings.

This means a `boolean`-typed sibling stores a native `true`/`false`, and you
should write `"equals": true` (not `"equals": "true"`) in the gate.

```jsonc
"single_bus_name": {
  "type": "string",
  "label": "Single bus name",
  "default": "KR",
  "visibleWhen": { "field": "grid_mode", "equals": "single" }
}
```

When a field is hidden by its gate, its value is still stored and passed to
hooks; it is only hidden in the GUI.

---

## 6. The rendered GUI

Each installed plugin renders in a detail pane with three inner tabs:
**Description**, **Input**, and **Output**. The pane also shows a "Server
setup" advisory section below the tabs when the manifest declares a `server`
block.

### 6.1 Description tab

When `panel.descriptionSections` is defined in the manifest, each entry
renders as a titled section in the grid specified by `panel.descriptionLayout`.
When no `descriptionSections` are provided, the plain `description` string
renders as a single block.

### 6.2 Input tab and grid layout

The Input tab renders all config fields that are not `group`-typed (and whose
`visibleWhen` gate is satisfied). Fields are grouped into sections by `group`
markers:

- Each `group` field ends the preceding section and starts a new one.
- Fields before the first `group` are collected into a default "General"
  section.
- Each section renders as a `<section>` element inside the `inputLayout` CSS
  grid.

The `inputLayout` value on `panel` (or `"single"` by default) sets the grid
class applied to the section container, allowing multi-column layouts.

Field renderers by type:

| Type | Rendered as |
|---|---|
| `group` | Section heading (separator, not in the grid flow) |
| `string` | `<input type="text">` |
| `number` (with `min`+`max`) | Range slider with numeric readout |
| `number` (without `min`+`max`) | `<input type="number">` |
| `boolean` | Checkbox |
| `select` | Searchable dropdown |
| `multi-select` | Checkbox list over a fixed `options` array (returns `string[]`) |
| `carrier-select` | Multi-checkbox list populated from workbook carriers |
| `file` | File picker button + filename display |
| `table` | Editable grid with add/delete row controls |
| `action` | Button (primary or secondary variant) with spinner |

### 6.3 Output tab

The Output tab is populated automatically after each solver run. If the plugin
exports an `analyze` hook, the runtime calls it with the full `RunResults`
object and the current config, then displays the returned key-value pairs in a
results table. The tab shows "No results yet" before the first run.

The `analyze` return value is `Record<string, unknown>`. Each key becomes a
row in the results table. You can optionally attach display hints using the
`PluginFieldHint` type — but hints are a host-side convention; the only way to
provide them today is via the `PluginAnalyticsEntry.ui` field, which the host
populates from the `analyze` return object. In practice, returning a flat
key-value map is sufficient for most plugins.

A hint's `format` controls how the value renders: `'number'` / `'currency'`
(localized numeric), `'table'` (an array of row objects, or a plain object, as
a table), `'text'` (default), or `'chart'`.

**Chart output (`format: 'chart'`).** The host owns rendering — a plugin emits
a *data spec*, never markup. When a value's hint has `format: 'chart'`, that
value must be a `PluginChartSpec`:

```jsonc
// kind: 'line' | 'area' | 'bar' | 'donut'

// line / area / bar — series over rows:
{
  "kind": "bar",
  "description": "Annual revenue by source",
  "stacked": true,
  "series": [
    { "key": "energy",   "label": "Energy market" },
    { "key": "capacity", "label": "Capacity payment", "color": "#f28e2b" }
  ],
  "rows": [
    { "label": "2030", "energy": 120, "capacity": 30 },
    { "label": "2031", "energy": 135, "capacity": 28 }
  ]
}

// donut — slices:
{
  "kind": "donut",
  "slices": [
    { "label": "Solar", "value": 40 },
    { "label": "Wind",  "value": 35, "color": "#76b7b2" }
  ]
}
```

Notes:
- For line/area/bar, each row keys its values by the series `key`; the
  category axis comes from the row's `label` (or `x`, or the row index). A
  `timestamp` field, if present, is used for time-aware axis formatting.
- `color` is optional everywhere — a stable palette colour is assigned by
  default. Missing/non-numeric series values are treated as `0`.
- `stacked`, `xAxisTitle`, `yAxisTitle`, and `showLegend` apply to
  line/area/bar only. The hint's `label` is used as the chart title.

### 6.4 Footer "Apply to model" button

When the manifest has no `action`-typed fields and the plugin exports
`transform` or `contribute`, a footer "Apply to model" button is rendered
below the tab panel. Clicking it invokes the apply path: `transform` if
exported (replaces the whole workbook), `contribute` otherwise (merges sheets
and appends constraint DSL lines).

When at least one `action` field is declared in the config, the footer button
is suppressed. The assumption is that action buttons in the Input tab serve
that role.

### 6.5 "Server setup" advisory

When the manifest declares a `server` block, a "Server setup" section is
rendered below the tab panel. It contains:

1. Instructions to add the correct line to `plugins.env`.
2. A pre-formatted entry with a path placeholder
   `/absolute/path/to/<plugin-id>/...` because the browser cannot discover
   the install path on disk.
3. A "Copy entry" button that copies the advisory text to the clipboard.
4. Numbered follow-on steps: start Ragnarok with `run.command`, then click
   Connect and the transform action.

The path placeholder must be replaced with the real absolute path to the
plugin's server directory before adding it to `plugins.env`.

---

## 7. JS entry file (`index.js`)

The entry file is evaluated as CommonJS in the browser using
`new Function('module', 'exports', src)`. Only `module` and `exports` are
injected. No Ragnarok globals, no Node built-ins, no DOM injections beyond
what the browser already provides (`fetch`, `console`, etc.).

### 7.1 Hook signatures

Export any subset of three hooks:

```js
module.exports = {

  // Replace the whole workbook model.
  // Runs when "Apply to model" is clicked or an action field has hook:"transform".
  // model:  current WorkbookModel (see section 7.2)
  // config: current plugin config with schema defaults merged in
  // Return: WorkbookModel  — the new complete workbook state
  async transform(model, config) {
    return newModel;
  },

  // Contribute data without replacing the whole model.
  // Return: { sheets?, constraints? }
  //   sheets:      Record<string, GridRow[]>  — merged into model (additive)
  //   constraints: string[]                   — DSL lines appended to the
  //                                             Advanced Constraints code box
  contribute(model, config) {
    return {
      sheets: {
        generators: [{ name: 'solar_farm', carrier: 'solar', bus: 'A', p_nom: 500 }],
      },
      constraints: [`cf("solar") >= ${config.min_solar_cf}`],
    };
  },

  // Post-run analytics.
  // result: full RunResults object from the Ragnarok backend
  // Return: Record<string, unknown> — displayed in the Output tab
  async analyze(result, config) {
    const total = result.summary?.[0]?.value ?? '—';
    return { total_cost: total };
  },

};
```

`transform` and `contribute` are mutually exclusive. When both are exported,
`transform` wins and `contribute` is never called.

### 7.2 WorkbookModel shape

```ts
type WorkbookModel = Record<string, GridRow[]>;
type GridRow       = Record<string, string | number | boolean | null>;
```

Sheet names follow the PyPSA schema: `buses`, `generators`, `loads`, `lines`,
`links`, `storage_units`, `stores`, `carriers`, `global_constraints`,
`snapshots`, and time-series sheets using the `<component>-<attr>` convention
(e.g. `generators-p_max_pu`). The frontend validates nothing beyond the
presence of a `buses` key in the `transform` return value.

A `transform` return that omits a sheet silently drops it from the workbook.
To keep existing sheet content while modifying only selected sheets, spread
the incoming `model` and override only the sheets you want to change:

```js
return { ...model, generators: updatedGenerators };
```

### 7.3 Named action hooks

Any function exported from `index.js` can be invoked as an action hook by
declaring an `action`-typed config field with a matching `hook` property. The
function receives the current config (with defaults merged) and must return
`{ ok: boolean, message?: string }`:

```js
module.exports = {

  async connect(config) {
    const base = String(config.backendUrl || 'http://127.0.0.1:8765').replace(/\/+$/, '');
    try {
      const r = await fetch(base + '/health');
      return r.ok
        ? { ok: true,  message: 'Server reachable at ' + base + '.' }
        : { ok: false, message: 'Server returned ' + r.status + '.' };
    } catch (e) {
      return { ok: false, message: 'Cannot reach server — is it running?' };
    }
  },

};
```

The runtime calls `fn(config)` (not `fn(model, config)`) for named action
hooks. If the function is not exported, the button triggers an error toast
"Plugin has no `<hook>` hook."

The returned `ok` field determines whether the toast is styled as success or
error. The `message` field is shown as the toast body. If neither `ok` nor
`message` is returned, the runtime uses a generic success message.

### 7.4 Runtime rules

- Any hook may be `async`. The UI shows a spinner while the promise is pending.
- Throw on bad input. The runtime catches the error and surfaces it as a toast
  without crashing the app.
- Config defaults from the schema are merged into the `config` argument before
  it reaches the hook, so hooks can rely on `config.someField` being present
  even if the user has never opened the Input tab.
- If neither `transform` nor `contribute` is exported, the "Apply to model"
  button and any `action` field with `hook: "transform"` are disabled.
- If `analyze` is not exported, the Output tab always shows "No results yet."

---

## 8. Own local server pattern

When your plugin needs computation that cannot run in the browser, host it in
your own local HTTP server. The plugin's JavaScript calls that server over
`localhost`. The server is entirely separate from the Ragnarok backend — it is
your code, running on your machine, speaking plain HTTP JSON.

```js
async transform(model, config) {
  const base = String(config.backendUrl || 'http://127.0.0.1:8765').replace(/\/+$/, '');
  let resp;
  try {
    resp = await fetch(base + '/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config }),
    });
  } catch (e) {
    throw new Error(
      'Cannot reach the build server at ' + base +
      '. Start backend/start.command, then try again.'
    );
  }
  if (!resp.ok) {
    let detail = 'HTTP ' + resp.status;
    try { const j = await resp.json(); detail = j.detail || JSON.stringify(j); } catch (_) {}
    throw new Error('Build failed: ' + detail);
  }
  return await resp.json(); // must be a WorkbookModel
}
```

### 8.1 Minimal FastAPI server

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class BuildRequest(BaseModel):
    config: dict = {}

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/build")
def build(req: BuildRequest) -> dict:
    # Return a WorkbookModel: { sheetName: [{"col": val, ...}, ...] }
    return my_build_pipeline(req.config)
```

Start it with:

```bash
uvicorn server:app --host 127.0.0.1 --port 8765
```

### 8.2 CORS requirement

The Ragnarok frontend runs at `localhost:3000` (or another port), and the
plugin server runs at a different port (e.g. `localhost:8765`). The browser
enforces same-origin policy, so the server must return CORS headers that allow
requests from any `localhost` origin. The simplest approach is `allow_origins=["*"]`
as shown above.

Never proxy requests through the Ragnarok backend (`localhost:8000`). The
plugin server is self-contained and does not need Ragnarok's involvement.

---

## 9. Server registration and launch

### 9.1 `plugins.env` format

> `plugins.env` is **only** for a *frontend* plugin's own local server. A
> **backend plugin** ([section 16](#16-backend-server-side-plugins)) needs no
> entry here — it runs inside the Ragnarok backend and imports PyPSA directly.

Create a file named `plugins.env` in the Ragnarok project root (the same
directory as `run.command`). Each non-comment line has the format:

```
<absolute path to server directory>|<run command>
```

Blank lines and lines beginning with `#` are ignored. Lines are trimmed of
leading and trailing whitespace.

Example:

```
# Dashboard Importer build server
/Users/you/simplePyPSA_KR/plugins_V3/ragnarok-dashboard-importer/backend|python server.py --port 8765
```

Copy `plugins.env.example` from the project root to get the annotated template.

You can override the path to `plugins.env` with the `RAGNAROK_PLUGINS_ENV`
environment variable before running `run.command`.

### 9.2 How `run.command` uses `plugins.env`

When you start Ragnarok by double-clicking `run.command` on macOS or running
it from a terminal, the script:

1. Creates and activates Ragnarok's own Python virtual environment
   (`.venv-pypsa`).
2. Installs backend dependencies if `requirements.txt` has changed.
3. Installs frontend Node modules if `node_modules/` is absent.
4. Starts the Ragnarok backend on port 8000 and waits for its health check.
5. Reads `plugins.env` line by line. For each valid entry whose directory
   exists on disk:
   - Prints "Starting plugin server: `<dir>` -> `<cmd>`".
   - Launches the server as a background subprocess (see section 9.3).
6. Opens the frontend in the browser.
7. On exit, kills the Ragnarok backend and all plugin server subprocesses.

If a plugin directory is listed in `plugins.env` but does not exist on disk,
`run.command` prints "Skip plugin server (directory not found): `<dir>`" and
continues. This means a misconfigured path is non-fatal.

### 9.3 Virtual-environment resolution order

Each plugin server subprocess runs in an isolated shell. The Python
environment resolved for that subprocess follows this order:

1. If the server directory contains `.venv/bin/activate`, activate that
   virtual environment. The plugin's own dependencies take priority.
2. Otherwise, fall back to Ragnarok's own `.venv-pypsa` that is already active
   in the outer shell.
3. An explicit interpreter path in the run command (e.g.
   `.venv/bin/python server.py`) always takes precedence via exec resolution,
   regardless of the activated venv.

To keep the run command in `plugins.env` simple (`python server.py ...`), use
`backend/start.command` to create `backend/.venv` once (see section 9.4).
From then on, `run.command` auto-detects and activates it.

### 9.4 `backend/start.command` standalone launcher

For development or on-demand use without registering in `plugins.env`, a plugin
can ship a self-provisioning launcher. This is a plain Bash script:

```bash
#!/bin/bash
set -e
cd "$(dirname "$0")"

PORT="${PORT:-8765}"
VENV=".venv"

pick_python() {
  for c in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$c" >/dev/null 2>&1 \
       && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      echo "$c"; return 0
    fi
  done
  return 1
}

if [ ! -x "$VENV/bin/python" ]; then
  PY="$(pick_python)" || { echo "ERROR: need Python 3.11+ on PATH."; exit 1; }
  echo "Creating virtual environment..."
  "$PY" -m venv "$VENV"
fi

PYBIN="$VENV/bin/python"

REQ_HASH="$(md5 -q requirements.txt 2>/dev/null || md5sum requirements.txt | cut -d' ' -f1)"
STAMP="$VENV/.req_hash"
if [ "$REQ_HASH" != "$(cat "$STAMP" 2>/dev/null || echo '')" ]; then
  echo "Installing dependencies..."
  "$PYBIN" -m pip install --upgrade pip -q
  "$PYBIN" -m pip install -r requirements.txt
  echo "$REQ_HASH" > "$STAMP"
fi

echo "Starting server on http://127.0.0.1:${PORT}"
exec "$PYBIN" server.py --port "$PORT"
```

On macOS, mark it executable and double-click it, or run it from a terminal.
The `.venv` it creates in the `backend/` directory is then automatically
detected and reused by `run.command` when the plugin is registered in
`plugins.env`. Dependencies are only reinstalled when `requirements.txt`
changes (hash-based detection).

### 9.5 In-GUI "Server setup" advisory

When the manifest declares a `server` block, the plugin detail pane renders a
"Server setup" section below the inner tabs. The section:

- Shows the exact `plugins.env` line to add, with the path placeholder
  `/absolute/path/to/<plugin-id>/...` filled from the manifest `server.cwd`
  and `server.run` values.
- Provides a "Copy entry" button to copy the advisory to the clipboard.
- Lists the three follow-up steps: add to `plugins.env`, restart Ragnarok with
  `run.command`, then click Connect and the transform action.

Because the browser cannot discover the absolute path where the plugin's
`backend/` directory lives on disk, the user must replace the path placeholder
with the real path before pasting the line into `plugins.env`.

---

## 10. Constraint flow

Plugins can inject linear constraints into the Ragnarok solver via three paths.

### 10.1 Path A — `contribute().constraints`

Return an array of DSL strings from the `contribute` hook:

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

The frontend appends these lines to the Advanced Constraints code box in
Settings, prefixed with a comment `# <plugin name> (plugin)`. All DSL text in
that code box is compiled to a structured `constraintSpecs` JSON object before
the Run request is sent to the Ragnarok backend. The plugin never sends
anything to the backend directly.

### 10.2 Path B — `RAGNAROK_CustomDSL` sheet

A `transform` hook can embed DSL text directly in the workbook by returning a
sheet named `RAGNAROK_CustomDSL` whose rows have a `text` column:

```js
transform(model, config) {
  const dslLines = buildDslLines(config);
  return {
    ...model,
    RAGNAROK_CustomDSL: dslLines.map((line) => ({ text: line })),
  };
}
```

When the frontend loads this model, it reads the `RAGNAROK_CustomDSL` sheet
and populates the Advanced Constraints code box with those lines. On Run, they
are compiled to `constraintSpecs` and sent to the backend along with the rest
of the solver inputs.

This path is useful when the DSL content depends on data assembled by the
build pipeline (e.g. CF constraint values filtered to a target year).

### 10.3 Path C — `global_constraints` sheet (native)

System-level caps such as a CO2 budget or technology expansion limits belong in
the `global_constraints` sheet, not in DSL. These are passed to PyPSA natively
by the Ragnarok backend and appear in Settings under "Standard Constraints".

```js
transform(model, config) {
  return {
    ...model,
    global_constraints: [
      { name: 'co2_limit', type: 'primary_energy', carrier_attribute: 'co2_emissions',
        sense: '<=', constant: config.co2_budget_tco2 },
    ],
  };
}
```

Use Path C for hard budget constraints that PyPSA models as `GlobalConstraint`
objects. Use Paths A or B for carrier-level operational constraints (CF bounds,
generation shares) expressed in the Ragnarok DSL.

### 10.4 DSL grammar reference

One linear constraint per line. `#` starts a comment.

**Atoms:**

| Atom | Meaning | Unit |
|---|---|---|
| `gen` | total system energy generation | MWh |
| `gen("carrier")` | energy from a specific carrier | MWh |
| `cap("carrier")` | total installed capacity of a carrier | MW |
| `cf("carrier")` | capacity factor of a carrier | fraction 0–1 |
| `emissions` | total system emissions | tCO2 |
| `load_shed` | total unserved energy | MWh |

**Operators:** `<=`, `>=`, `==`

**Arithmetic:** `+`, `-`, `*` with numeric constants. One constraint per line.

**Examples:**

```
cf("coal") <= 0.4
gen("coal") <= 200000
emissions <= 0.4 * gen
load_shed <= 0
cap("wind_onshore") >= 5000
# CO2 intensity cap: emissions per MWh generation
emissions <= 0.1 * gen
```

The frontend compiles each line to a `ConstraintSpec` object:

```ts
interface ConstraintSpec {
  id?: string;
  lhs: ConstraintTerm[];
  sense: '<=' | '>=' | '==';
  rhs: ConstraintTerm[];
}

interface ConstraintTerm {
  coef: number;
  kind: 'gen' | 'cap' | 'cf' | 'emissions' | 'load_shed' | 'const';
  carrier?: string;
}
```

---

## 11. Install and uninstall

**Installing a plugin:**

1. Open the **Plugins** tab in Ragnarok.
2. Click **Install plugin**.
3. Select the plugin `.zip` file.
4. The GUI renders immediately from the manifest schema.

There is no enable/disable toggle. An installed plugin is active. Installing a
plugin whose `id` matches an existing installed plugin replaces it in place
without requiring an uninstall first.

Config values are stored in `localStorage` under a key derived from the plugin
`id`. They persist across page refreshes and browser restarts.

**Uninstalling a plugin:**

Click the plugin name in the Plugins rail to open its detail pane. Scroll to
the bottom and click **Uninstall**. The plugin entry and its stored config are
removed from `localStorage`.

Note: uninstalling clears all saved config values for that plugin. If you plan
to reinstall, note down any non-default values you want to preserve.

---

## 12. Minimal end-to-end example

This example creates a plugin that forces all generators of a user-selected
carrier to `p_nom = 0`. It has no own server.

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

**Package and install:**

```bash
zip zero-out-carrier.zip module.json index.js
```

Open the Plugins tab in Ragnarok, click "Install plugin", select
`zero-out-carrier.zip`. Type the carrier name in the Input tab, then click
"Apply to model". The workbook's `generators` sheet is updated in memory. Click
Run to solve.

---

## 13. Dashboard Importer — full walkthrough

The `ragnarok-dashboard-importer` plugin in
`simplePyPSA_KR/plugins_V3/ragnarok-dashboard-importer/` is the canonical
real-world reference implementation. It uses every feature of the plugin system:
own server, `action` buttons, binary file upload, `table` fields with
`visibleWhen` gates, and the `RAGNAROK_CustomDSL` constraint path.

**Repository layout:**

```
ragnarok-dashboard-importer/
  module.json          # manifest (goes in the installable zip)
  index.js             # frontend hooks: connect + transform
  backend/
    server.py          # FastAPI server: GET /health, POST /build
    main.py            # build pipeline called by /build
    dashboard_lib/     # topology, region, scaling, snapshot logic
    start.command      # self-provisioning standalone launcher
    requirements.txt
```

**Manifest highlights:**

- `"inputLayout": "2x1"` produces a two-column Input tab. The left column
  ("Settings") holds scalar fields and action buttons. The right column
  ("Reference tables") holds the `table` fields.
- Two `action` fields are declared:
  - `connect_build_server` — `hook: "connect"`, secondary variant. Calls the
    `connect` export which GETs `/health` on the build server.
  - `send_to_ragnarok` — `hook: "transform"`, primary variant. Calls the
    `transform` export which POSTs config to `/build`.
- Because both `action` fields are declared, the footer "Apply to model" button
  is suppressed.
- The `server` block points at `backend/` with `python server.py --port 8765`,
  which drives the "Server setup" advisory.

**`index.js` hooks:**

- `connect(config)` — reads `config.backendUrl` (defaults to
  `http://127.0.0.1:8765`), GETs `/health`, returns `{ ok, message }`.
- `transform(model, config)` — POSTs the entire config object to `/build`.
  The server runs the build pipeline and returns a `WorkbookModel` JSON object.
  The frontend replaces the current workbook with it. Never touches the
  Ragnarok backend.

**Own server (`backend/server.py`):**

A FastAPI application with two routes:

- `GET /health` — returns `{"ok": true, "plugin": "ragnarok-dashboard-importer"}`.
- `POST /build {config: {...}}` — calls `transform({}, {}, {"moduleConfig": config})`
  from `main.py` and returns the result as a `WorkbookModel` JSON object.

CORS is set to `allow_origins=["*"]` so the browser plugin on `localhost:3000`
can reach the server on `localhost:8765`.

**Self-provisioning launcher (`backend/start.command`):**

Creates `backend/.venv` on first run using a Python 3.11+ search loop.
Installs `requirements.txt` using an `md5`-based hash stamp to skip reinstalls
when the file has not changed. Then starts `server.py` with `exec` so the
process replaces the shell cleanly. Double-click on macOS or run from a
terminal.

**Registration in `plugins.env`:**

```
# Dashboard Importer
/Users/you/simplePyPSA_KR/plugins_V3/ragnarok-dashboard-importer/backend|python server.py --port 8765
```

`run.command` detects `backend/.venv`, activates it, then runs
`python server.py --port 8765`. The Ragnarok frontend and the build server
start together and are both shut down when `run.command` exits.

**CF-constraint flow:**

The "CF constraints enabled" boolean in the GUI enables a `constraints_rows`
table with columns: carrier, attribute (max_cf/min_cf), year, value. When
"Send model to Ragnarok" is clicked, the build pipeline reads that table,
filters rows to `target_year`, and assembles DSL lines such as
`cf("coal") <= 0.4`. Those lines are returned as a `RAGNAROK_CustomDSL` sheet
in the WorkbookModel. The frontend loads them into the Advanced Constraints
code box. On Run, they are compiled to `constraintSpecs` and sent to the
Ragnarok backend as part of the standard run request.

**Install the plugin (zip only `module.json` + `index.js`):**

```bash
cd /Users/you/simplePyPSA_KR/plugins_V3/ragnarok-dashboard-importer
zip -j ragnarok-dashboard-importer.zip module.json index.js
```

Then in Ragnarok: Plugins tab → Install plugin → select the zip. The full
Settings + Reference tables GUI renders immediately.

---

## 14. Troubleshooting

### Error: "Package has no module.json manifest."

**Cause:** The `.zip` does not contain a file named `module.json`, or it is
more than one directory deep inside the zip.

**Fix:** Ensure `module.json` is at the zip root or exactly one directory deep.
Rebuild the zip:

```bash
zip my-plugin.zip module.json index.js
```

### Error: "module.json is not valid JSON."

**Cause:** A syntax error in `module.json` (trailing comma, unquoted key, etc.)

**Fix:** Validate with `python -m json.tool module.json` or any JSON linter
before zipping.

### Error: "module.json is missing an id."

**Cause:** The `id` field is absent or an empty string.

**Fix:** Add a non-empty `"id"` string to `module.json`.

### Error: "Entry file `index.js` not found in the plugin package."

**Cause:** The `entry` field names a file that is not in the zip, or the
filename casing does not match (case-sensitive).

**Fix:** Confirm the filename matches exactly and is at the same directory
level as `module.json`.

### Action button does nothing / "Plugin has no `connect` hook."

**Cause:** An `action` field declares `hook: "connect"` but `index.js` does
not export a `connect` function.

**Fix:** Add the export: `module.exports.connect = async function(config) { ... }`.

### Build server not reachable (Connect returns an error)

**Cause:** The plugin's own server is not running, or the port in
`config.backendUrl` does not match the server's listening port.

**Fix:**
1. Start the server manually: `cd backend && python server.py --port 8765` or
   double-click `backend/start.command`.
2. Confirm the port matches what `config.backendUrl` resolves to (default
   `http://127.0.0.1:8765`).
3. Click "Connect" again — a successful health check toasts "Server reachable."

### Plugin server not started by `run.command`

**Cause:** The directory path in `plugins.env` does not exist on disk, the
path is relative rather than absolute, or `plugins.env` is not in the Ragnarok
project root.

**Fix:**
1. Verify the path is absolute and points to an existing directory.
2. Check that `plugins.env` is in the same directory as `run.command`.
3. Restart with `run.command` and look for "Starting plugin server:" or
   "Skip plugin server (directory not found):" in the terminal output.

### Dependencies missing when plugin server starts via `run.command`

**Cause:** The plugin's `backend/` directory has no `.venv`, so `run.command`
falls back to Ragnarok's Python, which may not have the plugin's dependencies.

**Fix:** Run `backend/start.command` once to create `backend/.venv` and install
dependencies. `run.command` will then detect and activate it automatically.

### Constraints not appearing in the Advanced Constraints code box

**Cause:** The `contribute` hook returned `constraints` but the workbook was
not refreshed, or `transform` returned a `RAGNAROK_CustomDSL` sheet but the
model was not loaded into the workbook.

**Fix:**
1. For `contribute`: click "Apply to model". The constraints are appended to
   the Advanced Constraints code box in Settings. Open Settings to confirm.
2. For `RAGNAROK_CustomDSL`: confirm the `transform` return value includes the
   sheet and that rows have a `text` column.
3. Verify the DSL syntax: each line must contain exactly one constraint using
   the atoms in section 10.4.

### Config values lost after reinstall

**Cause:** Clicking "Uninstall" clears the `localStorage` config for that
plugin `id`.

**Fix:** Note down non-default values before uninstalling. Reinstalling
restores schema defaults, not the previous user values.

### `transform` returns a model but the workbook shows the old data

**Cause:** The return value is missing the `buses` key, which the frontend uses
as a minimal validity check.

**Fix:** Ensure the returned object includes at least `{ buses: [...] }`.
Spreading the incoming model (`{ ...model, ... }`) is the safest pattern.

### Plugin JS crashes with a syntax error toast

**Cause:** The `index.js` entry file contains a syntax error or uses
ES-module syntax (`import`/`export`) instead of CommonJS (`module.exports`).

**Fix:** Use only CommonJS syntax. Verify with Node.js: `node -e "require('./index.js')"`.

---

## 15. SDK changelog

All entries below are **SDK 2** and **backward-compatible** — they are additive
manifest features, so existing `"sdkVersion": "2"` plugins keep working
unchanged and there is no version bump. Keep declaring `"sdkVersion": "2"`.

### Config inputs

- **`multi-select` field** — a checkbox list over an `options` array returning
  `string[]`; the general form of `carrier-select`. See
  [field type catalogue](#52-field-type-catalogue).
- **`optionsFrom` (dynamic options)** — a `select` / `multi-select` field or a
  `"select"` table column can source its options at render time from the
  workbook model (`source: "model"`) or from a sibling `table` field
  (`source: "config"`) instead of a static `options` array. Combine with
  field-level [`visibleWhen`](#53-visiblewhen-gates) to switch option sets by
  another field's value. See [dynamic options](#dynamic-options-optionsfrom).

### Output (`analyze`)

- **`chart` output format** — a `PluginFieldHint` with `format: "chart"` renders
  its value (a `PluginChartSpec`: `line` / `area` / `bar` / `donut`) as a chart
  drawn by the host. Plugins emit a data spec, never markup. See
  [Output tab](#63-output-tab).

---

## 16. Backend (server-side) plugins

A **backend plugin** runs inside the Ragnarok backend process and may import the
bundled PyPSA source directly (`backend.pypsa`). It is the right kind for the
server-side / thin-client deployment: the build happens on the server, the
result is written straight into the session (the source of truth), the model
**never enters the browser**, and **nothing is launched from `plugins.env`** —
there is no separate server, because the plugin *is* part of the backend.

**Ragnarok ships ZERO plugins.** Plugins are purely 3rd-party. Reference examples
live in `example_plugins/` (not auto-loaded); you install one from the Plugins tab.

### 16.1 The unified hook contract (both kinds)

Frontend and backend plugins share ONE contract (for the system-level
involvement map — every touchpoint, what the plugin sees, and what contains
it — see [architecture.md §9.0](architecture.md#90-where-a-plugin-can-touch-the-system)):

| Hook | Signature | Meaning |
|---|---|---|
| `transform` | `transform(model, config) -> model` | replace the working model |
| `contribute` | `contribute(model, config) -> {sheets, constraints}` | add sheets / DSL constraints |
| `analyze` | `analyze(result, config) -> data` | read-only Output-tab data |
| `options` | `options(name, config, ctx) -> [rows]` | on-demand dropdown values (backend; `ctx` gives read-only session access) |
| *named action* | `<hook>(config) -> {ok, message, config?}` | a manifest `action` field whose hook is not transform/contribute — e.g. a "Fill table" button; a returned `config` patch is written back into the form |

For a backend plugin these are Python functions in `plugin.py`; for a frontend
plugin they are JS exports in `index.js` (section 7). `transform`/`contribute`
write into the session.

**Model handoff is one-way and return-value-only.** A backend plugin's
`transform`/`contribute` receives a **defensive copy** of the session model
(sheets and rows are copied before the call). Mutating the `model` argument in
place is never persisted — only the dict returned by `transform` is saved, and
only the fragment returned by `contribute` is merged. Plugin exceptions are
contained: any error inside a hook surfaces as a clean HTTP `400`, never a
crashed request, and one broken plugin never breaks discovery of the others.

Use a **backend plugin** for heavy Python that belongs on the server (network
build, PyPSA construction, large-file parsing). Use a **frontend plugin** for
browser-light transforms/analytics, or when you must keep an existing own-server
build pipeline (sections 8–9, registered in `plugins.env`). `plugins.env` is
**only** for a frontend plugin's own server — a backend plugin needs no entry.

### 16.2 Layout, install, and discovery

A backend plugin is a directory:

```
<id>/
  manifest.json    # {id, name, version, kind:"backend", description?, capabilities?, config?}
  plugin.py        # exposes transform / contribute / analyze (any subset)
  ...              # any supporting modules (e.g. a vendored build engine)
```

It is distributed as a **`.zip`** (manifest.json + plugin.py at the root) and
**installed by upload** from the Plugins tab. The backend extracts it (zip-slip
safe) into the install dir `RAGNAROK_BACKEND_PLUGINS_DIR` (default
`backend/data/plugins/`, **gitignored** — runtime/user content, never in the
project tree) and refreshes the registry. Discovery is isolated: a missing dir
yields no plugins, and a plugin that fails to import (or exposes no hook) is
logged and skipped — the backend always starts.

> **Security:** install accepts a `.zip` of runnable Python that the backend
> imports — i.e. remote code execution by design. Acceptable single-user/local;
> a multi-user remote deployment must gate this behind auth/sandboxing.

The reference example is `example_plugins/dashboard-importer/`.

### 16.3 The `plugin.py` contract

```python
def transform(model: dict, config: dict) -> dict:
    """Return a model dict {sheet: [rows]} — written into the session."""
    from backend.pypsa.network import build_network   # the bundled source
    new_model = {...}
    build_network(new_model, {"discountRate": 0.0, "carbonPrice": 0.0}, None)  # validate
    return new_model

def contribute(model: dict, config: dict) -> dict:
    """Optional: {sheets: {...}, constraints: ["cf(\"wind\") <= 0.5", ...]}."""
    return {"sheets": {"carriers": [{"name": "wind"}]}, "constraints": []}

def analyze(result: dict, config: dict) -> dict:
    """Optional: analytics dict for a solved run (Output tab)."""
    return {"total_cost": result.get("summary", [{}])[0].get("value")}
```

A plugin may export any subset. Raising inside a hook is safe — the router
surfaces the message as a clean `400`.

**Vendoring a library: load it under a plugin-unique alias.** `plugin.py`
itself is imported by the host under a synthetic per-id module name, so two
installed plugins never collide on `plugin.py`. A plugin that ships its own
package (a vendored build engine, a `*_lib/` directory) must extend the same
discipline: **never put your plugin directory on `sys.path` and never register
your package in `sys.modules` under its bare name.** Plugins get copy-pasted
from each other — if two installed plugins both ship a package called
`my_lib` and either imports it by that bare name, whichever imports first wins
and the other plugin silently runs foreign code. Load the package under an
alias derived from your install directory instead:

```python
import importlib, importlib.util, re, sys, threading
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent
_LIB_ALIAS = "_ragnarok_plugin_lib_" + re.sub(r"\W", "_", PLUGIN_ROOT.name)
_IMPORT_LOCK = threading.Lock()  # hooks run in a threadpool

def _lib(submodule: str):
    """Import a bundled my_lib submodule under a plugin-unique alias."""
    with _IMPORT_LOCK:
        if _LIB_ALIAS not in sys.modules:
            init = PLUGIN_ROOT / "my_lib" / "__init__.py"
            spec = importlib.util.spec_from_file_location(
                _LIB_ALIAS, init, submodule_search_locations=[str(init.parent)]
            )
            pkg = importlib.util.module_from_spec(spec)
            sys.modules[_LIB_ALIAS] = pkg  # register BEFORE exec: relative imports
            try:
                spec.loader.exec_module(pkg)
            except BaseException:
                sys.modules.pop(_LIB_ALIAS, None)
                raise
        return importlib.import_module(f"{_LIB_ALIAS}.{submodule}")
```

Inside the vendored package use **relative imports** (`from . import x`) —
they resolve within the alias. The dashboard-importer's `pipeline.py` is the
reference implementation of this pattern (its `_lib()` loader).

### 16.4 The `manifest.json`

Same `config` schema as a frontend manifest (section 5), so the Plugins tab
renders the identical form. Note that `capabilities` is **freeform display
taxonomy** (e.g. `"data-importer"`, `"constraint-pack"`) — it never controls
dispatch; the hooks a plugin actually exposes are introspected from
`plugin.py` and reported in the manifest's `hooks` field. An `action` field
with `"hook": "transform"` (or `"contribute"`) triggers the server hook:

```json
{
  "id": "demo-network-builder",
  "name": "Demo Network Builder",
  "version": "1.0.0",
  "kind": "backend",
  "description": "Builds a PyPSA model server-side.",
  "config": {
    "grp": { "type": "group", "label": "Demo network" },
    "buses": { "type": "number", "label": "Buses", "default": 1, "min": 1, "max": 50 },
    "build": { "type": "action", "label": "Build & load into Ragnarok",
               "hook": "transform", "variant": "primary" }
  }
}
```

### 16.5 Endpoints

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/plugins` | list installed backend plugins (manifests) |
| `GET` | `/api/plugins/{id}` | one manifest |
| `POST` | `/api/plugins/install` | install from an uploaded `.zip` (multipart) → manifest |
| `DELETE` | `/api/plugins/{id}` | uninstall (remove the dir + its uploaded data files) → `{removed}` |
| `POST` | `/api/plugins/{id}/transform` | run `transform(model, config)` → save into session → meta |
| `POST` | `/api/plugins/{id}/contribute` | run `contribute(model, config)` → merge into session → meta |
| `POST` | `/api/plugins/{id}/analyze` | run `analyze(result, config)` → its dict |
| `POST` | `/api/plugins/{id}/options` | run `options(name, config, ctx)` → `{name, rows}` (on-demand dropdowns) |
| `POST` | `/api/plugins/{id}/action` | run a named action hook `hook(config)` → `{ok, message, config?}` |
| `POST` | `/api/plugins/{id}/files` | upload a data file into the plugin's server-side scratch dir (multipart) |
| `GET` | `/api/plugins/{id}/files` | list the plugin's uploaded data files |
| `DELETE` | `/api/plugins/{id}/files/{name}` | delete one uploaded data file |

`transform`/`contribute` body: `{config, sessionId, filename?, scenarioName?}`.
The model is persisted server-side; the response is the lightweight session meta.

**Per-plugin data files.** A plugin's heavy input (e.g. a model workbook) is
uploaded once into a server-side scratch dir (`backend/data/plugin_files/<id>/`,
gitignored) and thereafter referenced by *filename* in the config — the bytes
never live in the browser. The framework injects the reserved config key
`__plugin_data_dir__` into every hook call so the plugin can resolve those
filenames to absolute server paths. The scratch dir is removed on uninstall.

### 16.6 The frontend side

The single **"Install plugin…"** button auto-detects the package kind (a `.zip`
with `plugin.py` / manifest `kind:"backend"` → backend upload; `index.js` /
`module.json` → frontend localStorage). Backend plugins appear under a
**"Backend (server-side)"** rail group, each with an **uninstall "x"** (DELETE).
Selecting one renders its config form; the action runs `transform`/`contribute`,
then the editor rehydrates from the session and switches to the Model tab. The
model never enters the browser. If the backend is unreachable the list is simply
empty — frontend plugins still work. See `src/lib/api/plugins.ts`,
`src/features/plugins/BackendPluginDetail.tsx`, and `peekPackageKind` in
`src/features/plugins/frontendPlugins.ts`.
