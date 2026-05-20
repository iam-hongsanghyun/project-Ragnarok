# Authoring Ragnarok Modules

## Who this is for

This guide is written so a human developer or another AI system can create a Ragnarok module
without needing private knowledge of the host codebase.

This guide assumes the Ragnarok module system described in
[`docs/module-system-v1.md`](./module-system-v1.md).

Current host reality:

- the host already discovers local modules and validates manifests
- the host already exposes a sidebar module manager and persisted enable/disable state
- enabled plugins execute through the backend run pipeline
- the main Plugins workspace renders Description / Input / Output tabs for each enabled plugin

## Module types in v1

Ragnarok v1 supports four module categories:

- `data-importer`
- `data-manipulator`
- `analytics-pack`
- `constraint-pack`

A single module may declare more than one category if the manifest and exported capabilities stay
consistent.

## Directory layout

Recommended local module layout:

```text
my-ragnarok-module/
  module.json
  README.md
  dist/
    index.js
```

You may keep source files elsewhere, but the host only cares about the shipped bundle and manifest.

## Required files

### `module.json`

Every module must include a manifest at the root.

Example:

```json
{
  "id": "acme-demand-import",
  "name": "ACME Demand Import",
  "version": "0.1.0",
  "sdkVersion": "1",
  "entry": "dist/index.js",
  "description": "Imports ACME planning demand data into Ragnarok.",
  "capabilities": ["data-importer"],
  "permissions": ["filesystem.read", "workbook.write", "ui.action"]
}
```

### `dist/index.js`

The entrypoint must export a module object that the host can load.

Minimal shape:

```ts
export const module = {
  manifest,
  async activate(context) {},
  async deactivate() {},
  capabilities: {}
}
```

## Required manifest fields

- `id`: stable machine-readable module identifier
- `name`: user-facing module name
- `version`: semantic version string
- `sdkVersion`: currently `"1"`
- `entry`: relative path to the built entrypoint
- `capabilities`: one or more supported module categories

## Optional panel metadata

Plugins can declare an optional `panel` object in `module.json` to control how the main
Plugins workspace lays out each plugin's Description, Input, and Output views.

Example:

```json
{
  "panel": {
    "descriptionLayout": "single",
    "inputLayout": "2x1",
    "outputLayout": "2x2",
    "descriptionSections": [
      { "title": "Purpose", "body": "What this plugin does." },
      { "title": "Assumptions", "body": "How to interpret the outputs." }
    ]
  }
}
```

Supported layout values:

- `single`
- `2x1`
- `1x2`
- `2x2`

The host uses:

- `descriptionSections` for the Description tab
- grouped config fields for the Input tab
- result-field `ui.section` hints for the Output tab

## Choosing a module category

Use `data-importer` when the module's job is to load external data and convert it into a Ragnarok
workbook.

Use `data-manipulator` when the module's job is to transform an already loaded workbook.

Use `analytics-pack` when the module's job is to add reusable input or output analysis views.

Use `constraint-pack` when the module's job is to define additional solver-facing constraints.

If your module does several of these things, declare all required capabilities and keep each
capability implementation independent.

## Runtime model

Modules are orchestrated by the Ragnarok frontend host.

That means:

- user interaction starts in the app UI
- the host loads the module
- the host calls capability hooks
- the host decides whether returned payloads are accepted

Your module should behave as a guest, not as the application owner.

## Capability contracts

### `data-importer`

Use this when converting external source data into a `WorkbookModel`.

Expected hooks:

```ts
const dataImporter = {
  async getConfigSchema() {
    return {
      type: 'object',
      properties: {
        sourcePath: { type: 'string', title: 'Source path' }
      },
      required: ['sourcePath']
    }
  },

  async validateSource(input) {
    return []
  },

  async load(input) {
    return {
      workbook,
      diagnostics: [],
      metadata: {
        title: 'Imported workbook'
      }
    }
  }
}
```

### `data-manipulator`

Use this when operating on the active workbook.

Expected hooks:

```ts
const dataManipulator = {
  async getActions() {
    return [
      {
        id: 'scale-demand',
        label: 'Scale demand',
        description: 'Multiply all load time series by a factor.'
      }
    ]
  },

  async run(actionId, input) {
    return {
      workbook: input.workbook,
      diagnostics: []
    }
  }
}
```

### `analytics-pack`

Use this when contributing reusable analysis views.

Expected hooks:

```ts
const analyticsPack = {
  async getPanels() {
    return [
      {
        id: 'planning-kpis',
        title: 'Planning KPIs',
        slot: 'analytics'
      }
    ]
  },

  async getChartDefinitions() {
    return []
  }
}
```

### `constraint-pack`

Use this when defining custom constraints for the solver pipeline.

Expected hooks:

```ts
const constraintPack = {
  async getConstraintDefinitions() {
    return [
      {
        metric: 'example_constraint',
        label: 'Example Constraint',
        unit: '%'
      }
    ]
  },

  async validateConstraint(input) {
    return []
  }
}
```

## Minimal module example

```ts
export const manifest = {
  id: 'acme-demand-import',
  name: 'ACME Demand Import',
  version: '0.1.0',
  sdkVersion: '1',
  entry: 'dist/index.js',
  capabilities: ['data-importer'],
  permissions: ['filesystem.read', 'workbook.write', 'ui.action']
}

export const module = {
  manifest,

  async activate(context) {
    context.app.showNotification({
      level: 'info',
      message: 'ACME Demand Import activated'
    })
  },

  async deactivate() {},

  capabilities: {
    dataImporter: {
      async validateSource(input) {
        return []
      },

      async load(input) {
        return {
          workbook: {
            network: [],
            snapshots: [],
            carriers: [],
            buses: [],
            generators: [],
            loads: [],
            lines: [],
            links: [],
            stores: [],
            storage_units: [],
            transformers: [],
            shunt_impedances: [],
            global_constraints: [],
            shapes: [],
            processes: []
          },
          diagnostics: []
        }
      }
    }
  }
}
```

## What your module is allowed to assume

You may assume:

- the host will validate your manifest
- the host will provide a versioned context object
- the host will own the active workbook state
- the host will decide where your UI surfaces appear

You must not assume:

- access to private React components
- access to internal backend Python functions
- ability to modify host routes or layout arbitrarily
- that every permission request will be granted

## Permissions

Declare only what you need.

Known permissions in v1:

- `filesystem.read`
- `filesystem.write`
- `network.access`
- `workbook.read`
- `workbook.write`
- `results.read`
- `ui.panel`
- `ui.action`
- `constraints.register`
- `analytics.register`

Over-requesting permissions should be treated as a quality problem.

## Validation rules for module authors

Your module should validate early and fail clearly.

Recommended validation order:

1. validate manifest completeness
2. validate external source inputs
3. validate transformed workbook structure
4. return diagnostics with actionable messages

Good diagnostics are:

- explicit
- tied to a source field or file when possible
- non-ambiguous

## Output rules

If your module returns a workbook:

- it must match Ragnarok's `WorkbookModel`
- sheet names must follow host conventions exactly
- row objects must use stable keys
- time-series sheets must be normalized before handoff

If your module contributes analytics or constraints:

- definitions must be declarative and host-readable
- labels and units must be explicit
- module output must not require patching core source files

## AI authoring checklist

If another AI is generating a Ragnarok module, it should be able to succeed with this checklist:

1. create `module.json`
2. set `sdkVersion` to `"1"`
3. choose one or more allowed capability names
4. implement `activate()` and `deactivate()`
5. implement only the capability hooks required by the manifest
6. keep all outputs inside the published host contracts
7. return clear diagnostics when source inputs are invalid
8. avoid imports from Ragnarok private application code

## Recommended first modules

Good candidates for early third-party modules:

- CSV-based planning model importer
- scenario scaling manipulator
- KPI analytics pack
- sector-specific policy or reserve constraint pack

Not good candidates for the first wave:

- modules that require arbitrary backend monkey-patching
- modules that assume direct control of the full UI
- modules that depend on unpublished host internals

## Versioning expectations

Your module should treat the SDK as the stable dependency, not the entire Ragnarok codebase.

If the host upgrades from SDK `1` to SDK `2`, expect to update your module manifest and possibly
its exported capability handlers.
