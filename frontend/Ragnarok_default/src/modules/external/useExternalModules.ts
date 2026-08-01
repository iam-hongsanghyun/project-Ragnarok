/**
 * External tab-modules — React state over the localStorage store.
 *
 * The hook owns the installed list; install/remove/toggle persist immediately
 * so the workspace composition survives reloads, exactly like settings.
 */
import { useCallback, useState } from 'react';
import { loadInstalled, parseModuleFiles, saveInstalled } from './store';
import type { ExternalTabModule } from './types';

export interface ExternalModulesApi {
  installed: ExternalTabModule[];
  /** Parse + register a picked package. Replaces an existing same-id module. */
  install: (files: readonly File[]) => Promise<ExternalTabModule>;
  remove: (id: string) => void;
  setEnabled: (id: string, enabled: boolean) => void;
}

export function useExternalModules(): ExternalModulesApi {
  const [installed, setInstalled] = useState<ExternalTabModule[]>(loadInstalled);

  const install = useCallback(async (files: readonly File[]) => {
    const mod = await parseModuleFiles(files);
    setInstalled((prev) => {
      // Re-installing an id updates in place (an iteration workflow), keeping
      // its position and enablement.
      const existing = prev.find((m) => m.manifest.id === mod.manifest.id);
      const next = existing
        ? prev.map((m) => (m.manifest.id === mod.manifest.id ? { ...mod, enabled: m.enabled } : m))
        : [...prev, mod];
      saveInstalled(next);
      return next;
    });
    return mod;
  }, []);

  const remove = useCallback((id: string) => {
    setInstalled((prev) => {
      const next = prev.filter((m) => m.manifest.id !== id);
      saveInstalled(next);
      return next;
    });
  }, []);

  const setEnabled = useCallback((id: string, enabled: boolean) => {
    setInstalled((prev) => {
      const next = prev.map((m) => (m.manifest.id === id ? { ...m, enabled } : m));
      saveInstalled(next);
      return next;
    });
  }, []);

  return { installed, install, remove, setEnabled };
}
