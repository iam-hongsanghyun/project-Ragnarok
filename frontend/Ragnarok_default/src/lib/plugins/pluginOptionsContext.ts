import { createContext, useContext } from 'react';

/**
 * Resolves a backend-plugin dropdown's rows on demand.
 *
 * Provided by `BackendPluginDetail` (bound to that plugin's id + the active
 * session) and consumed deep inside the shared config-field renderer when a field
 * declares `optionsFrom: { source: 'plugin', name }`. This is how a BACKEND plugin
 * fills its dropdowns WITHOUT the old per-plugin `localhost:8765` server: the
 * resolver POSTs to `/api/plugins/{id}/options` and returns option rows, which the
 * renderer then filters/labels client-side like any other source.
 *
 * `null` when not inside a backend-plugin panel (frontend plugins keep their own
 * `source: 'server'` path), so the renderer falls back to static options.
 */
export type PluginOptionsResolver = (
  name: string,
  config: Record<string, unknown>,
) => Promise<Array<Record<string, unknown>>>;

export const PluginOptionsContext = createContext<PluginOptionsResolver | null>(null);

export function usePluginOptionsResolver(): PluginOptionsResolver | null {
  return useContext(PluginOptionsContext);
}
