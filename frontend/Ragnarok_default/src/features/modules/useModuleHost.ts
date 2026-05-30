import { useCallback, useEffect, useMemo, useState } from 'react';
import { API_BASE, MODULES_CONFIG } from '../../constants';
import { ModuleDescriptor, ModuleHostInventory } from '../../shared/types';

const STORAGE_KEY = MODULES_CONFIG.storageKey;
const CONFIGS_KEY = `${MODULES_CONFIG.storageKey}_configs`;

function loadEnabledIds(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : [];
  } catch {
    return [];
  }
}

function saveEnabledIds(ids: string[]): void {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(ids)); } catch { /* ignore */ }
}

function loadModuleConfigs(): Record<string, Record<string, unknown>> {
  try {
    const raw = localStorage.getItem(CONFIGS_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return typeof parsed === 'object' && parsed !== null ? parsed : {};
  } catch {
    return {};
  }
}

function isFileValue(v: unknown): boolean {
  return typeof v === 'object' && v !== null && 'content' in (v as object) && 'name' in (v as object);
}

function saveModuleConfigs(configs: Record<string, Record<string, unknown>>): void {
  // File values are in-memory only — strip them before persisting so localStorage
  // never holds large binary blobs. Users re-select files after a page refresh.
  const stripped: Record<string, Record<string, unknown>> = {};
  for (const [moduleId, fields] of Object.entries(configs)) {
    const safe: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(fields)) {
      if (!isFileValue(v)) safe[k] = v;
    }
    stripped[moduleId] = safe;
  }
  try { localStorage.setItem(CONFIGS_KEY, JSON.stringify(stripped)); } catch { /* ignore */ }
}

function isEnableEligible(module: ModuleDescriptor): boolean {
  return module.status === 'ready' && module.valid && module.compatible && module.entryExists;
}

export function useModuleHost() {
  const [inventory, setInventory] = useState<ModuleHostInventory | null>(null);
  const [enabledIds, setEnabledIds] = useState<string[]>(loadEnabledIds);
  const [moduleConfigs, setModuleConfigsState] = useState<Record<string, Record<string, unknown>>>(loadModuleConfigs);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchInventory = useCallback(async () => {
    // Plugins are a frontend-only concern now (the Ragnarok backend no longer
    // hosts or executes them, so /api/modules is gone). The frontend plugin
    // host (features/plugins) owns plugins instead; this reports an empty
    // backend inventory without a network call.
    setInventory(null);
    setError(null);
    setLoading(false);
  }, []);

  const installFromFile = useCallback(async (file: File): Promise<{ ok: boolean; error?: string; moduleId?: string }> => {
    const form = new FormData();
    form.append('file', file);
    try {
      const resp = await fetch(`${API_BASE}/api/modules/install`, {
        method: 'POST',
        body: form,
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        return { ok: false, error: typeof data.detail === 'string' ? data.detail : `Install failed with status ${resp.status}.` };
      }
      await fetchInventory();
      return { ok: true, moduleId: data.id as string | undefined };
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : 'Install failed.' };
    }
  }, [fetchInventory]);

  const uninstall = useCallback(async (moduleId: string) => {
    try {
      const resp = await fetch(`${API_BASE}/api/modules/${encodeURIComponent(moduleId)}`, {
        method: 'DELETE',
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        return { ok: false, error: typeof data.detail === 'string' ? data.detail : `Uninstall failed with status ${resp.status}.` };
      }
      setEnabledIds((prev) => {
        const next = prev.filter((id) => id !== moduleId);
        saveEnabledIds(next);
        return next;
      });
      await fetchInventory();
      return { ok: true };
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : 'Uninstall failed.' };
    }
  }, [fetchInventory]);

  useEffect(() => {
    fetchInventory();
  }, [fetchInventory]);

  useEffect(() => {
    if (!inventory) return;
    const eligibleIds = new Set(inventory.modules.filter(isEnableEligible).map((item) => item.id));
    setEnabledIds((prev) => {
      const next = prev.filter((id) => eligibleIds.has(id));
      if (next.length !== prev.length) saveEnabledIds(next);
      return next;
    });
  }, [inventory]);

  const setModuleConfig = useCallback((moduleId: string, key: string, value: unknown) => {
    setModuleConfigsState((prev) => {
      const next = { ...prev, [moduleId]: { ...(prev[moduleId] ?? {}), [key]: value } };
      saveModuleConfigs(next);
      return next;
    });
  }, []);

  const toggleEnabled = useCallback((moduleId: string, enabled: boolean) => {
    setEnabledIds((prev) => {
      const next = enabled
        ? Array.from(new Set([...prev, moduleId]))
        : prev.filter((id) => id !== moduleId);
      saveEnabledIds(next);
      return next;
    });
  }, []);

  const discoveredModules = useMemo(() => inventory?.modules ?? [], [inventory]);
  const enabledSet = useMemo(() => new Set(enabledIds), [enabledIds]);
  const effectiveEnabledIds = useMemo(
    () => discoveredModules.filter((module) => enabledSet.has(module.id) && isEnableEligible(module)).map((module) => module.id),
    [discoveredModules, enabledSet],
  );

  return {
    inventory,
    modules: discoveredModules,
    loading,
    error,
    enabledIds: effectiveEnabledIds,
    moduleConfigs,
    isEnabled: (moduleId: string) => enabledSet.has(moduleId),
    isEnableEligible,
    toggleEnabled,
    setModuleConfig,
    installFromFile,
    uninstall,
  };
}
