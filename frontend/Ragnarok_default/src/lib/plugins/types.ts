/**
 * Plugin type definitions — split from `features/plugins/frontendPlugins.ts`
 * so lib code (runtime, manifest helpers) can reference the shape without
 * pulling in the React hook that manages plugin install state.
 */

export interface InstalledPlugin {
  id: string;
  name: string;
  version?: string;
  description?: string;
  /** Raw manifest (module.json) as parsed. */
  manifest: Record<string, unknown>;
  /** Plain-text files from the package, keyed by path (e.g. the JS entry). */
  files: Record<string, string>;
}
