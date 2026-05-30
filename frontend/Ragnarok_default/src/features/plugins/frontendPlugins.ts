/**
 * Frontend-only plugin host (Phase 3 foundation).
 *
 * Plugins are a FRONTEND concern: a plugin produces constraints/model inputs in
 * the browser and hands them to the Ragnarok frontend as DSL lines (which the
 * frontend turns into structured `constraintSpecs` JSON before sending to the
 * Ragnarok backend). The Ragnarok backend never sees or runs plugin code.
 *
 * Built-in plugins live here; installed plugins live in a frontend "plugin
 * location" (browser localStorage), loaded the same way. Each plugin exposes a
 * pure `toConstraintLines(config, model)` that returns human-readable DSL lines
 * shown in the Advanced Constraints code box before Run.
 */
import { useCallback, useState } from 'react';
import { WorkbookModel } from '../../shared/types';

export interface FrontendPluginField {
  key: string;
  label: string;
  type: 'number' | 'carriers';
  default?: unknown;
  unit?: string;
}

export interface FrontendPlugin {
  id: string;
  name: string;
  description: string;
  fields: FrontendPluginField[];
  /** Pure: config + current model → DSL constraint lines for the code box. */
  toConstraintLines: (config: Record<string, unknown>, model: WorkbookModel) => string[];
}

// ── Built-in plugins ──────────────────────────────────────────────────────────
const renewableFloor: FrontendPlugin = {
  id: 'renewable-cf-floor',
  name: 'Renewable CF floor',
  description: 'Force selected carriers to run at or above a minimum capacity factor.',
  fields: [
    { key: 'carriers', label: 'Carriers', type: 'carriers', default: [] },
    { key: 'minCf', label: 'Min capacity factor', type: 'number', default: 0.2, unit: 'fraction 0–1' },
  ],
  toConstraintLines: (config) => {
    const carriers = Array.isArray(config.carriers) ? (config.carriers as string[]) : [];
    const minCf = Number(config.minCf ?? 0);
    return carriers
      .filter(Boolean)
      .map((c) => `cf(${/\s/.test(c) ? `"${c}"` : c}) >= ${minCf}`);
  },
};

export const BUILTIN_FRONTEND_PLUGINS: FrontendPlugin[] = [renewableFloor];

// ── Persistence (the frontend "plugin location") ──────────────────────────────
const ENABLED_KEY = 'ragnarok:fe-plugins:enabled';
const CONFIG_KEY = 'ragnarok:fe-plugins:configs';

function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

function defaultConfig(plugin: FrontendPlugin): Record<string, unknown> {
  const cfg: Record<string, unknown> = {};
  plugin.fields.forEach((f) => { cfg[f.key] = f.default ?? (f.type === 'carriers' ? [] : 0); });
  return cfg;
}

export type FrontendPluginHost = ReturnType<typeof useFrontendPlugins>;

export function useFrontendPlugins() {
  const plugins = BUILTIN_FRONTEND_PLUGINS;
  const [enabledIds, setEnabledIds] = useState<string[]>(() => loadJson<string[]>(ENABLED_KEY, []));
  const [configs, setConfigs] = useState<Record<string, Record<string, unknown>>>(
    () => loadJson<Record<string, Record<string, unknown>>>(CONFIG_KEY, {}),
  );

  const persistEnabled = (next: string[]) => {
    setEnabledIds(next);
    try { window.localStorage.setItem(ENABLED_KEY, JSON.stringify(next)); } catch { /* ignore */ }
  };
  const persistConfigs = (next: Record<string, Record<string, unknown>>) => {
    setConfigs(next);
    try { window.localStorage.setItem(CONFIG_KEY, JSON.stringify(next)); } catch { /* ignore */ }
  };

  const toggle = useCallback((id: string, on: boolean) => {
    persistEnabled(on ? Array.from(new Set([...enabledIds, id])) : enabledIds.filter((x) => x !== id));
  }, [enabledIds]);

  const getConfig = useCallback((plugin: FrontendPlugin): Record<string, unknown> => (
    { ...defaultConfig(plugin), ...(configs[plugin.id] ?? {}) }
  ), [configs]);

  const setConfigField = useCallback((pluginId: string, key: string, value: unknown) => {
    persistConfigs({ ...configs, [pluginId]: { ...(configs[pluginId] ?? {}), [key]: value } });
  }, [configs]);

  /** DSL lines contributed by one plugin given the current model. */
  const linesFor = useCallback((plugin: FrontendPlugin, model: WorkbookModel): string[] => {
    try {
      return plugin.toConstraintLines(getConfig(plugin), model);
    } catch {
      return [];
    }
  }, [getConfig]);

  return {
    plugins,
    enabledIds,
    isEnabled: (id: string) => enabledIds.includes(id),
    toggle,
    getConfig,
    setConfigField,
    linesFor,
  };
}
