# Ragnarok Module System v1

## Status

This document defines the first full module system for Ragnarok. It is a design and contract
proposal only. This PR does not implement runtime loading, UI injection, or any bundled modules.

The trust model for v1 is:

- `user-installed`
- `trusted`
- `local`

That means modules are installed from the local filesystem by the user, are assumed to be trusted
by that user, and are not fetched from a remote registry by Ragnarok itself.

## Goals

- Let users extend Ragnarok without modifying core frontend or backend code.
- Keep the host app in control of UI, workbook state, solver execution, and compatibility checks.
- Support a narrow, versioned contract so modules remain understandable to both humans and AI.
- Start with four module categories:
  - `data-importer`
  - `data-manipulator`
  - `analytics-pack`
  - `constraint-pack`

## Non-goals for v1

- No online marketplace or registry.
- No arbitrary code execution inside core app state.
- No direct module patching of frontend routes or backend endpoints.
- No remote module download by Ragnarok.
- No bundled first-party modules in the initial implementation.
- No promise of sandboxing beyond host-level validation and explicit trust by the local user.

## Architecture

The module system has three layers:

1. `host`
   - discovers installed modules
   - validates manifests
   - enables or disables modules
   - exposes approved APIs
   - mounts module-defined surfaces in allowed UI slots
2. `runtime`
   - loads module entrypoints
   - calls lifecycle hooks
   - isolates failures per module
   - mediates access to host capabilities
3. `sdk`
   - defines manifest format
   - defines lifecycle hooks
   - defines capabilities and data contracts
   - defines authoring rules for third-party modules

Core rule:

`modules contribute through contracts, never through internal reach-through`

Modules must not import private React components, mutate internal application state directly, or
depend on unpublished backend functions.

## Trust and installation model

v1 uses `trusted local modules`.

- The user installs a module from a local folder.
- The host copies or references that folder in a managed local modules directory.
- The host validates the module manifest before enabling it.
- The host may warn about requested permissions before activation.
- The user can enable, disable, reload, or uninstall a module from the UI.

Recommended managed directory:

```text
~/.ragnarok/modules/
  <module-id>/
    module.json
    dist/index.js
    README.md
```

## Initial module categories

### `data-importer`

Purpose:

- ingest external data from files, folders, APIs, or prepared exports
- validate source shape
- normalize source data into a Ragnarok `WorkbookModel`

Allowed outputs:

- workbook payload
- diagnostics
- import metadata

Examples:

- import from CSV pack
- import from an API-backed planning system
- import a prepared PyPSA-Earth export

### `data-manipulator`

Purpose:

- transform an existing workbook
- apply repeatable mapping, cleanup, expansion, or templating logic

Allowed outputs:

- modified workbook payload
- diagnostics
- action summary

Examples:

- clone a scenario and scale demand
- map generator metadata from carrier rules
- harmonize technology names and units

### `analytics-pack`

Purpose:

- contribute reusable analysis definitions
- add charts, tables, or report sections built on top of input or output data

Allowed outputs:

- chart definitions
- analysis descriptors
- diagnostics

Examples:

- system planning KPI pack
- emissions and dispatch storytelling pack
- project-specific input QA views

### `constraint-pack`

Purpose:

- declare additional custom constraints and their schemas
- validate user input for those constraints
- translate approved settings into host-recognized solver directives

Allowed outputs:

- constraint definitions
- validation results
- serialized constraint payloads understood by the core backend

Examples:

- renewable build floor pack
- reserve margin pack
- carrier capacity factor pack

## Module lifecycle

Every module must export a single module object that conforms to the v1 lifecycle:

```ts
export interface RagnarokModuleV1 {
  manifest: ModuleManifest
  activate(context: ModuleContext): Promise<void>
  deactivate(): Promise<void>
  capabilities?: ModuleCapabilities
}
```

Lifecycle expectations:

- `activate()` is called after manifest validation and permission approval.
- `deactivate()` must release held resources and unregister listeners.
- Module activation failure must not crash the host application.
- The host may deactivate and reload a module during development or upgrade flows.

## Manifest

Each module must include a `module.json` file at its root.

```json
{
  "id": "example-module",
  "name": "Example Module",
  "version": "0.1.0",
  "sdkVersion": "1",
  "entry": "dist/index.js",
  "description": "Example Ragnarok module.",
  "capabilities": ["data-importer"],
  "permissions": ["filesystem.read", "workbook.write", "ui.panel"],
  "hostCompatibility": {
    "minAppVersion": "0.1.0"
  }
}
```

Required fields:

- `id`
- `name`
- `version`
- `sdkVersion`
- `entry`
- `capabilities`

Optional fields:

- `description`
- `permissions`
- `hostCompatibility`
- `author`
- `homepage`

Manifest validation rules:

- `id` must be stable and unique.
- `sdkVersion` must match the host-supported major SDK version.
- `capabilities` must be a subset of the host-known capability list.
- Unknown permissions must cause rejection.

## Permissions

Permissions must be explicit in `module.json`.

Initial permission set:

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

Rules:

- Modules only receive host APIs matching granted permissions.
- The host should surface permission prompts during install or first enable.
- Permissions are capability-level declarations, not a blanket trust bypass.

## Host API

The host must expose a versioned runtime context to modules.

```ts
export interface ModuleContext {
  sdkVersion: '1'
  app: {
    version: string
    getActiveWorkbook(): Promise<WorkbookModel | null>
    setActiveWorkbook(workbook: WorkbookModel): Promise<void>
    getLatestResults(): Promise<RunResults | null>
    showNotification(input: NotificationInput): void
  }
  files: {
    openFileDialog(options?: FileDialogOptions): Promise<SelectedFile[]>
    openFolderDialog(): Promise<SelectedFolder | null>
    readText(path: string): Promise<string>
    readBinary(path: string): Promise<ArrayBuffer>
  }
  ui: {
    registerPanel(panel: PanelDefinition): void
    registerAction(action: ActionDefinition): void
  }
  backend: {
    validateModulePayload(type: string, payload: unknown): Promise<ValidationResult>
  }
}
```

The host API must stay smaller than the internal app surface. If a module needs something the host
does not expose yet, the API should be extended intentionally instead of letting modules reach into
private code.

## Capability interfaces

### `data-importer`

```ts
export interface DataImporterCapability {
  getConfigSchema?(): JsonSchema
  validateSource(input: ModuleInput): Promise<Diagnostic[]>
  load(input: ModuleInput): Promise<ModuleLoadResult>
}
```

### `data-manipulator`

```ts
export interface DataManipulatorCapability {
  getActions(): Promise<ManipulatorActionDefinition[]>
  run(actionId: string, input: ManipulatorRunInput): Promise<ManipulatorRunResult>
}
```

### `analytics-pack`

```ts
export interface AnalyticsPackCapability {
  getPanels(): Promise<PanelDefinition[]>
  getChartDefinitions(): Promise<ChartDefinition[]>
}
```

### `constraint-pack`

```ts
export interface ConstraintPackCapability {
  getConstraintDefinitions(): Promise<ConstraintDefinition[]>
  validateConstraint(input: ConstraintInput): Promise<Diagnostic[]>
}
```

Combined container:

```ts
export interface ModuleCapabilities {
  dataImporter?: DataImporterCapability
  dataManipulator?: DataManipulatorCapability
  analyticsPack?: AnalyticsPackCapability
  constraintPack?: ConstraintPackCapability
}
```

## Data contracts

The most important stable contract is the normalized workbook handoff.

```ts
export interface ModuleLoadResult {
  workbook: WorkbookModel
  diagnostics?: Diagnostic[]
  metadata?: ModuleMetadata
}
```

Additional shared contracts:

- `WorkbookModel`
- `RunResults`
- `Diagnostic`
- `NotificationInput`
- `PanelDefinition`
- `ActionDefinition`
- `ConstraintDefinition`
- `ChartDefinition`

Rules:

- `WorkbookModel` is the canonical input to Ragnarok.
- A module may prepare or transform workbook data, but the host owns storage and persistence.
- `RunResults` are read-only to modules.

## Frontend vs backend call path

The module system should be orchestrated from the frontend.

Call flow:

1. frontend discovers installed modules
2. frontend shows modules in a `Modules` or `Connector` surface
3. user selects and configures a module
4. frontend activates the module through the runtime
5. module runs capability logic
6. module returns normalized payloads
7. frontend writes workbook state or registers UI surfaces
8. backend is called only through approved host APIs when heavy or privileged work is needed

This keeps the user interaction model in the frontend while avoiding backend-led UI behavior.

## UI extension points

v1 should use narrow extension points instead of arbitrary layout injection.

Allowed slots:

- left sidebar module panel
- import/action dialogs
- analytics panel registration
- constraint definition registration

v1 should not allow:

- arbitrary route creation
- unrestricted React tree injection
- uncontrolled style or layout overrides

## Error isolation

The runtime must isolate failures per module.

Required behaviors:

- failed activation marks the module as disabled for the session
- a broken module panel does not crash the rest of the app
- capability timeouts surface a visible error
- diagnostics are attributable to a specific module id and version

## Compatibility and versioning

The SDK version must be explicit and major-versioned.

Rules:

- host supports one or more `sdkVersion` majors
- module declares exactly one `sdkVersion`
- incompatible modules are shown as installed but disabled
- capability changes that break existing modules require a new SDK major

## Recommended implementation sequence

1. Add module manifest schema and validation.
2. Add managed local module directory and discovery.
3. Add enable, disable, reload, and uninstall flows.
4. Add runtime loader and lifecycle hooks.
5. Add permission prompt and persistence.
6. Add `data-importer` capability.
7. Add `data-manipulator` capability.
8. Add `analytics-pack` capability.
9. Add `constraint-pack` capability.
10. Add diagnostics, logging, and failure isolation.
11. Add module management UI in the sidebar.

## Acceptance criteria for v1

Ragnarok has a real v1 module system when all of the following are true:

- a user can install a local module without editing core source code
- the host validates `module.json`
- the host can enable or disable modules
- the host can call module lifecycle hooks
- at least the four initial module categories are supported by contract
- modules can contribute workbook, analytics, or constraint definitions only through host APIs
- a broken module cannot take down the rest of the application

## Out of scope follow-ups

- remote registry
- signed modules
- sandboxed third-party execution
- backend worker isolation for untrusted code
- module billing or marketplace
- cloud-hosted module deployment
