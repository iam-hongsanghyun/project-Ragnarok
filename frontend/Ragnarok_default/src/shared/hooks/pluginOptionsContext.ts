import { createContext, useContext } from 'react';
import type { PluginOptionsResolver } from 'lib/plugins/options';

/**
 * Carries a backend-plugin options resolver down to the shared config-field
 * renderer.
 *
 * Provided by `BackendPluginDetail` (bound to that plugin's id + the active
 * session) and consumed deep inside `ModuleManagerSection` when a field declares
 * `optionsFrom: { source: 'plugin', name }`. This is how a BACKEND plugin fills
 * its dropdowns WITHOUT the old per-plugin `localhost:8765` server: the resolver
 * POSTs to `/api/plugins/{id}/options` and returns option rows, which the
 * renderer then filters/labels client-side like any other source.
 *
 * `null` when not inside a backend-plugin panel (frontend plugins keep their own
 * `source: 'server'` path), so the renderer falls back to static options.
 *
 * Lives in shared/ (not lib/) because lib/ is the pure-logic, no-React layer —
 * the `PluginOptionsResolver` type itself stays in `lib/plugins/options`.
 */
export const PluginOptionsContext = createContext<PluginOptionsResolver | null>(null);

export function usePluginOptionsResolver(): PluginOptionsResolver | null {
  return useContext(PluginOptionsContext);
}
