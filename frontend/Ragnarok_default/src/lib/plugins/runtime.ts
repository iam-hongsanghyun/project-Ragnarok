/**
 * In-browser plugin runtime.
 *
 * Mirrors the previous backend contract (module.json manifest + an entry file
 * exporting hook functions) but runs entirely in the frontend. The entry file
 * is evaluated as CommonJS in the browser; it exports any of:
 *
 *   module.exports = {
 *     // Replace the whole workbook model (e.g. an importer).
 *     transform(model, config) { return newModel; },
 *     // Contribute inputs without replacing: extra/updated sheets + constraint
 *     // DSL lines that land in the Advanced Constraints code box before Run.
 *     contribute(model, config) { return { sheets?, constraints? }; },
 *     // Post-run: receive the result JSON and return display analytics.
 *     analyze(result, config) { return { ...analytics }; },
 *   }
 *
 * The plugin's own backend (if any) is reached by this code over its own HTTP;
 * it never calls the Ragnarok backend.
 */
import { GridRow, WorkbookModel } from 'lib/types';
import type { InstalledPlugin } from 'lib/plugins/types';

export interface PluginContribution {
  sheets?: Record<string, GridRow[]>;
  constraints?: string[];
}

// Hooks may be sync or async (a plugin with its own backend will `await fetch`).
export interface PluginModule {
  transform?: (model: WorkbookModel, config: Record<string, unknown>) => WorkbookModel | Promise<WorkbookModel>;
  contribute?: (model: WorkbookModel, config: Record<string, unknown>) => PluginContribution | Promise<PluginContribution>;
  analyze?: (result: unknown, config: Record<string, unknown>) => Record<string, unknown> | Promise<Record<string, unknown>>;
}

/** Evaluate a plugin's entry file (CommonJS) and return its exports. */
export function loadPluginModule(plugin: InstalledPlugin): PluginModule {
  const entry = String(plugin.manifest.entry ?? 'index.js');
  const src = plugin.files[entry];
  if (typeof src !== 'string') {
    throw new Error(`Entry file "${entry}" not found in the plugin package.`);
  }
  const moduleObj: { exports: Record<string, unknown> } = { exports: {} };
  // Local/single-user app: plugins are user-installed and trusted. Run the
  // entry as CommonJS. No Ragnarok internals are injected — only module/exports.
  // eslint-disable-next-line no-new-func
  const factory = new Function('module', 'exports', src);
  factory(moduleObj, moduleObj.exports);
  return moduleObj.exports as PluginModule;
}

export interface CapabilityFlags {
  transform: boolean;
  contribute: boolean;
  analyze: boolean;
}

export function pluginCapabilities(plugin: InstalledPlugin): CapabilityFlags {
  try {
    const mod = loadPluginModule(plugin);
    return {
      transform: typeof mod.transform === 'function',
      contribute: typeof mod.contribute === 'function',
      analyze: typeof mod.analyze === 'function',
    };
  } catch {
    return { transform: false, contribute: false, analyze: false };
  }
}
