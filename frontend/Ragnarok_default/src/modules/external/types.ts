/**
 * External tab-modules — third-party MODULES, not plugins.
 *
 * A module is something big: a whole tab. Built-in modules are compiled in
 * (src/modules/<id>/manifest.tsx); an EXTERNAL module is a directory (or .zip)
 * the user adds from Settings → Modules. It ships a `tabmodule.json` manifest
 * plus a CommonJS entry file whose exports mount the tab's UI:
 *
 *   // tabmodule.json
 *   { "id": "my-analysis", "label": "My analysis", "entry": "index.js",
 *     "hint": "...", "description": "...", "order": 130 }
 *
 *   // index.js
 *   module.exports = {
 *     // Render into `el`; return a cleanup function (called on unmount).
 *     mount(el, ctx) { ...; return () => {...}; },
 *   };
 *
 * `ctx` gives the module the same reach a native tab has — the Ragnarok
 * backend HTTP API: `ctx.apiBase` + `ctx.sessionId` are enough to read the
 * working model (`GET {apiBase}/api/session/...`), submit runs
 * (`POST {apiBase}/api/queue`) and read analytics (`GET {apiBase}/api/runs/...`).
 *
 * Plugins (`lib/plugins/`, the Plugins tab) are the SMALL extension system —
 * panels and hooks. The two vocabularies stay disjoint: different manifest
 * name (tabmodule.json vs module.json), different stores, different tabs.
 */

export interface ExternalModuleManifest {
  /** Unique tab id. Must not collide with a core tab or a built-in module. */
  id: string;
  label: string;
  hint?: string;
  description?: string;
  /** Activity-bar position; external modules default to after Training. */
  order?: number;
  /** Entry file inside the package (default "index.js"). */
  entry?: string;
}

export interface ExternalTabModule {
  manifest: ExternalModuleManifest;
  /** Text files of the package, keyed by path relative to the manifest. */
  files: Record<string, string>;
  /** Shown on the activity bar when true (per-install, localStorage). */
  enabled: boolean;
  installedAt: string;
}

/** What the entry file's exports must look like. */
export interface ExternalModuleExports {
  mount?: (el: HTMLElement, ctx: ExternalModuleContext) => void | (() => void);
}

export interface ExternalModuleContext {
  /** Ragnarok backend origin ('' when same-origin) — the full HTTP API. */
  apiBase: string;
  /** The working session id the app itself uses. */
  sessionId: string;
}
