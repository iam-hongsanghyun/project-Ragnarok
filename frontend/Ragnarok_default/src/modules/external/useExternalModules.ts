/**
 * External tab-modules — React state over the SERVER's module store.
 *
 * The backend owns installed modules (`/api/modules`, files under
 * `backend/data/modules/`) so they belong to the project: a "Clear cache", an
 * app update (which resets `localStorage` on a build-id change) and a different
 * browser all keep them. Nothing module-related is persisted client-side.
 */
import { useCallback, useEffect, useState } from 'react';
import { fetchModules, installModule, removeModule, setModuleEnabled } from './api';
import type { ExternalTabModule } from './types';

export interface ExternalModulesApi {
  installed: ExternalTabModule[];
  /** True until the first list has come back (the bar waits rather than flickers). */
  loading: boolean;
  /** Parse + register a picked package server-side. Same id ⇒ update in place. */
  install: (files: readonly File[]) => Promise<ExternalTabModule>;
  remove: (id: string) => Promise<void>;
  setEnabled: (id: string, enabled: boolean) => Promise<void>;
  refresh: () => Promise<void>;
}

export function useExternalModules(): ExternalModulesApi {
  const [installed, setInstalled] = useState<ExternalTabModule[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setInstalled(await fetchModules());
    } catch {
      // A backend that is still booting must not break the shell — the activity
      // bar simply shows core + built-in modules until the next refresh.
      setInstalled([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const install = useCallback(async (files: readonly File[]) => {
    const mod = await installModule(files);
    await refresh();
    return mod;
  }, [refresh]);

  const remove = useCallback(async (id: string) => {
    await removeModule(id);
    await refresh();
  }, [refresh]);

  const setEnabled = useCallback(async (id: string, enabled: boolean) => {
    // Optimistic: the toggle should feel instant; refresh reconciles.
    setInstalled((prev) => prev.map((m) => (m.manifest.id === id ? { ...m, enabled } : m)));
    await setModuleEnabled(id, enabled);
    await refresh();
  }, [refresh]);

  return { installed, loading, install, remove, setEnabled, refresh };
}
