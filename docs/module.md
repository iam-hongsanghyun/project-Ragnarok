# Ragnarok Modules — Configuration and Authoring Guide

Ragnarok's tabs are split into **core** and **modules**. This document is the
authoritative reference for that split, for configuring which modules a
workspace shows, and for writing your own module.

> **Module ≠ plugin.** A **plugin** is a *small* extension — an importer, a
> panel, an analytics card — loaded through the plugin host and configured on
> the Plugins tab ([plugin.md](./plugin.md)). A **module** is *big*: a whole
> tab, which can run the model and analyse results exactly like a native
> Ragnarok tab. Modules may be first-party (shipped in the app) or third-party
> (added by the user from a folder or `.zip`).

## Table of contents

1. [Core vs module](#1-core-vs-module)
2. [Configuring modules (Settings → Modules)](#2-configuring-modules-settings--modules)
3. [How the setting is stored and shared](#3-how-the-setting-is-stored-and-shared)
4. [Writing an external module](#4-writing-an-external-module)
5. [The module context (what a module can do)](#5-the-module-context-what-a-module-can-do)
6. [Installing, updating, removing](#6-installing-updating-removing)
7. [Where modules are stored (and why it survives a cache clear)](#7-where-modules-are-stored-and-why-it-survives-a-cache-clear)
8. [Managing modules over MCP](#8-managing-modules-over-mcp)
9. [Adding a first-party module](#9-adding-a-first-party-module)
10. [Limits and roadmap](#10-limits-and-roadmap)

---

## 1. Core vs module

**Core** is everything the modelling loop needs: the workbook you edit, the run
you submit, the results you read, and the app chrome. Core tabs are always
present and cannot be switched off.

| Core tab | Role |
|---|---|
| Welcome | shell / entry point |
| Build | model authoring (map-driven) |
| Model | model authoring (sheet-level) |
| Market & Policy | inputs that change the solve — carbon price, constraints |
| Settings | run configuration, scenarios, solver, preferences |
| Analytics | the native results surface |
| History | run lifecycle — queue, stored runs, comparison |
| Plugins | the plugin manager (a *core* tab; plugins are not modules) |

**Modules** are tools that consume the core through its APIs. Remove one and the
loop still works end to end.

| Module tab | id | What it adds |
|---|---|---|
| Data | `Data` | importers for public data sources, country starter packs |
| Forge | `Forge` | model transforms: reduction, capacity targets, retargeting, profiles |
| Physical Risk | `PhysicalRisk` | CLIMADA physical climate risk, adaptation, outage coupling |
| Siting | `Siting` | location optimisation for new capacity |
| Post-analysis | `PostAnalysis` | tools that read a finished run without re-solving |
| Training | `Training` | the guided course / interactive walkthroughs |

Each first-party module declares a manifest at
`frontend/Ragnarok_default/src/modules/<id>/manifest.tsx`; the registry that
aggregates them is `src/modules/registry.ts`.

## 2. Configuring modules (Settings → Modules)

**Settings → Modules** (the *App* group in the section rail) is the module
manager. It has two halves:

- **Built-in modules** — a checkbox per module. Unchecking one removes its tab
  from the activity bar immediately. Nothing is uninstalled and no data is
  touched: the model, settings, run history and results are unaffected, and
  re-checking brings the tab straight back.
- **External modules** — *Add module from folder* / *Add module from .zip*,
  plus a per-module enable checkbox and **Remove**.

Turning a module off only hides the tab. If something navigates to a disabled
tab programmatically (a resumed walkthrough, a cross-tab link), the shell
redirects to Welcome rather than render a hidden tab.

## 3. How the setting is stored and shared

The enabled set lives in `AppSettings.enabledModules` as a **comma-separated id
string**, e.g.:

```
"Data,Forge,PhysicalRisk,Siting,PostAnalysis,Training"
```

A string, not an array, on purpose: it is a primitive, so it survives the
key/value `RAGNAROK_Settings` sheet of a project export — **share a project file
and the recipient opens it with the same tabs on the bar.**

Semantics:

| Value | Meaning |
|---|---|
| absent / `null` | every module enabled — the behaviour before modules existed, so old settings and old project files are unaffected |
| `""` (empty) | a deliberate "no modules" — core tabs only |
| `"Data,Forge"` | exactly those two |
| unknown ids | silently dropped (a renamed module, or a file from a newer version) |

Defaults live in `src/config/app_config.json` under `settings.defaults`; the
per-install value is in `localStorage` (`project_ragnarok_settings`, which
neither cache reset clears). **External module packages are not stored in the
browser at all** — they live on the server, with their own enabled flag; see §7.

## 4. Writing an external module

An external module is a directory (or a `.zip` of it) with two files:

```
my-analysis/
  tabmodule.json     the manifest
  index.js           CommonJS entry — exports mount(el, ctx)
```

`tabmodule.json`:

```json
{
  "id": "my-analysis",
  "label": "My analysis",
  "hint": "One line for the activity-bar tooltip",
  "description": "A sentence shown in Settings → Modules.",
  "order": 130,
  "entry": "index.js"
}
```

| Field | Required | Notes |
|---|---|---|
| `id` | yes | alphanumeric (dashes/underscores allowed); must not collide with a core tab or a built-in module id |
| `label` | no | tab name; defaults to `id` |
| `hint` | no | tooltip second line |
| `description` | no | shown in the module manager |
| `order` | no | activity-bar position; core sits at 10–110, built-in modules interleave, external defaults to 200 (after everything) |
| `entry` | no | entry file inside the package; defaults to `index.js` |

`index.js` — mount your UI into the element you are handed, and return a cleanup
function:

```js
module.exports = {
  mount(el, ctx) {
    el.innerHTML = '<h2>My analysis</h2><pre id="out">loading…</pre>';
    let disposed = false;

    (async () => {
      const meta = await fetch(
        ctx.apiBase + '/api/session/meta?session_id=' + encodeURIComponent(ctx.sessionId),
      ).then((r) => r.json());
      if (!disposed) el.querySelector('#out').textContent = JSON.stringify(meta, null, 1);
    })();

    return () => { disposed = true; };   // called when the tab unmounts
  },
};
```

A runnable example ships at [`example_modules/hello-tab/`](../example_modules/hello-tab/):
it reads the working session and run history, and shows the call that submits a
solve.

The module owns everything inside `el`; Ragnarok owns everything outside it. If
`mount` throws, the tab shows an error card naming the module — the app keeps
running.

## 5. The module context (what a module can do)

`mount(el, ctx)` receives:

| Field | Meaning |
|---|---|
| `ctx.apiBase` | the Ragnarok backend origin (`''` when same-origin) |
| `ctx.sessionId` | the working session id the app itself uses |

That is deliberately the *whole* backend HTTP API — the same reach a native tab
has, which is what makes a module able to "run the model and analyse like native
Ragnarok functions":

| Task | Call |
|---|---|
| what is loaded | `GET {apiBase}/api/session/meta?session_id={sessionId}` |
| read a sheet (paged) | `GET {apiBase}/api/session/sheet/{name}?session_id={sessionId}` |
| read a time series (windowed) | `GET {apiBase}/api/session/series/{name}?session_id={sessionId}` |
| edit a sheet | `PATCH {apiBase}/api/session/sheet/{name}` with `{ops, sessionId}` |
| **submit a solve** | `POST {apiBase}/api/queue` with `{sessionId, scenario, options}` |
| watch the queue | `GET {apiBase}/api/queue` |
| list finished runs | `GET {apiBase}/api/runs` |
| **read a run's analytics** | `GET {apiBase}/api/runs/{name}/analytics` |
| derived chart series | `GET {apiBase}/api/runs/{name}/derived/{metric}` |
| export a project | `POST {apiBase}/api/export/project` |

See [backend.md](./backend.md) for the full API. A module runs with the app's
privileges — an installed module is trusted local code, exactly like a plugin
entry file.

## 6. Installing, updating, removing

- **Install** — Settings → Modules → *Add module from folder* (pick the
  directory containing `tabmodule.json`) or *Add module from .zip*. Paths are
  re-based to wherever the manifest sits, so a nested folder inside the archive
  is fine.
- **Update** — add the same `id` again: it replaces the package in place and
  keeps its enabled state. This is the iteration loop while developing.
- **Disable** — uncheck it. The tab disappears; the package stays installed.
- **Remove** — uninstalls the package. Nothing else in the app changes.

Packages live on the **server** — see the next section.

## 7. Where modules are stored (and why it survives a cache clear)

An installed module is **project content, not browser cache**, so the backend
owns it:

```
backend/data/modules/
  <id>/
    tabmodule.json
    index.js
    …
  .state.json          {"<id>": {"enabled": true}}
```

Both the package and its shown/hidden flag live there (gitignored; overridable
with `RAGNAROK_TAB_MODULES_DIR`). That is deliberate. Two separate wipes clear
`localStorage`:

| Wipe | When | What it clears |
|---|---|---|
| build-id reset ([`index.tsx`](../frontend/Ragnarok_default/src/index.tsx)) | **every app update / dev-server restart** | all `pypsa.*`, `ragnarok:*`, `ui:*` keys |
| "Clear cache" button | on demand | the same set |

A module kept in `localStorage` would therefore be uninstalled by the next
update. On the server it survives an update, a "Clear cache", and opening the app
in a different browser. Nothing module-related is written to `localStorage`.

The HTTP surface (also what the UI uses):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/modules` | list installed modules (manifest, files, enabled) |
| `POST` | `/api/modules/install` | install/update from an uploaded `.zip` |
| `POST` | `/api/modules/install-path` | install/update from a server-side directory |
| `POST` | `/api/modules/{id}/enabled` | show/hide the tab |
| `DELETE` | `/api/modules/{id}` | uninstall |

Built-in module enablement is separate: it stays in `AppSettings.enabledModules`
(§3), which is not wiped by either reset and rides along in a project export.

Guards on install: ids must be alphanumeric and may not collide with a core tab
or built-in module; zip entries with `..`/absolute paths are refused; there are
size limits on the archive and its unpacked contents
(`RAGNAROK_MAX_MODULE_ZIP_MB`, `RAGNAROK_MAX_MODULE_UNZIPPED_MB`); a malformed
module already on disk is logged and skipped rather than breaking startup.

## 8. Managing modules over MCP

The MCP server exposes the same operations, so an agent can scaffold a module in
a directory and register it without touching the UI:

| Tool | Effect |
|---|---|
| `list_tab_modules` | inventory (read-only): id, label, order, enabled, file names |
| `install_tab_module(path)` | install/update from a directory on this machine |
| `set_tab_module_enabled(id, enabled)` | show/hide the tab |
| `remove_tab_module(id)` | uninstall (flagged destructive) |

The three mutating tools respect the autonomy guard
(`RAGNAROK_MCP_AUTONOMY`): under the default `guided` they return a preview and
need `confirm=true` to apply. `list_plugins` remains the separate, unrelated
plugin inventory.

## 9. Adding a first-party module

To ship a module in the app itself:

1. Create `src/modules/<id>/manifest.tsx` exporting a `TabModuleDefinition`
   (`id`, `label`, `hint`, `description`, `icon` via `lineIcon`, `order`).
2. Register it in the `TAB_MODULES` array in `src/modules/registry.ts`.
3. Add the id to `TabModuleId` in `src/modules/types.ts` and to
   `settings.defaults.enabledModules` in `src/config/app_config.json`.
4. Render the tab in `App.tsx` gated on `enabledModules.has('<id>')`.

`src/modules/registry.test.ts` pins the core/module split — add the id there
too, which is what stops a tab silently changing sides.

## 10. Limits and roadmap

Today:

- Module tabs still receive their data through `App.tsx` props (first-party) or
  the backend HTTP API (external). A typed **ModuleContext** — one object giving
  model access, run submission, results and events to both kinds — is the next
  step, after which a first-party module folder owns its own state.
- External modules render into a plain DOM element. They may use any technique
  that works on a DOM node; no React version is imposed or shared.
- Only TEXT files in a package are handed to the browser host; binary assets are
  stored but not inlined, so fetch them at runtime if you need them.
- There is no module marketplace and no signing. A module runs with the app's
  privileges — add only modules you trust.
