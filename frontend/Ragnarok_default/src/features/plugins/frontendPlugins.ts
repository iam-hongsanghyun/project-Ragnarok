/**
 * Frontend-only plugin host (Phase 3).
 *
 * Plugins are a pure FRONTEND concern: they are installed into a frontend
 * "plugin location" (browser localStorage), configured in the Plugins tab, and
 * run in the browser. A plugin produces inputs for the model and/or reads the
 * run output — it never communicates with the Ragnarok backend. The Ragnarok
 * frontend is the only thing that talks to the Ragnarok backend.
 *
 * A plugin package is a `.zip` containing a `module.json` manifest. No sample
 * plugins are bundled — the user installs their own.
 */
import { useCallback, useState } from 'react';
import { unzipSync, strFromU8 } from 'fflate';
import type { InstalledPlugin } from 'lib/plugins/types';

export type { InstalledPlugin } from 'lib/plugins/types';

const STORE_KEY = 'ragnarok:fe-plugins:installed';
const CONFIG_KEY = 'ragnarok:fe-plugins:configs';

function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}
function saveJson(key: string, value: unknown): void {
  try { window.localStorage.setItem(key, JSON.stringify(value)); } catch { /* quota — ignore */ }
}

/** Parse a plugin .zip (manifest + text files) without touching the backend. */
async function parsePackage(file: File): Promise<InstalledPlugin> {
  const buf = new Uint8Array(await file.arrayBuffer());
  const entries = unzipSync(buf);
  // module.json may sit at the root or one directory deep.
  const manifestPath = Object.keys(entries).find((p) => p.replace(/^[^/]+\//, '') === 'module.json' || p === 'module.json');
  if (!manifestPath) throw new Error('Package has no module.json manifest.');
  const prefix = manifestPath.includes('/') ? manifestPath.slice(0, manifestPath.lastIndexOf('/') + 1) : '';
  let manifest: Record<string, unknown>;
  try {
    manifest = JSON.parse(strFromU8(entries[manifestPath])) as Record<string, unknown>;
  } catch {
    throw new Error('module.json is not valid JSON.');
  }
  const id = String(manifest.id ?? '').trim();
  const name = String(manifest.name ?? id).trim();
  if (!id) throw new Error('module.json is missing an "id".');
  // Keep the (text) files under the manifest's directory for later execution.
  const files: Record<string, string> = {};
  for (const [path, bytes] of Object.entries(entries)) {
    if (prefix && !path.startsWith(prefix)) continue;
    const rel = prefix ? path.slice(prefix.length) : path;
    if (!rel || rel.endsWith('/')) continue;
    try { files[rel] = strFromU8(bytes); } catch { /* skip binary */ }
  }
  return {
    id,
    name,
    version: manifest.version ? String(manifest.version) : undefined,
    description: manifest.description ? String(manifest.description) : undefined,
    manifest,
    files,
  };
}

export type FrontendPluginHost = ReturnType<typeof useFrontendPlugins>;

export function useFrontendPlugins() {
  const [installed, setInstalled] = useState<InstalledPlugin[]>(() => loadJson<InstalledPlugin[]>(STORE_KEY, []));
  const [configs, setConfigs] = useState<Record<string, Record<string, unknown>>>(
    () => loadJson<Record<string, Record<string, unknown>>>(CONFIG_KEY, {}),
  );

  const persistInstalled = (next: InstalledPlugin[]) => { setInstalled(next); saveJson(STORE_KEY, next); };

  const install = useCallback(async (file: File): Promise<{ ok: boolean; error?: string; id?: string }> => {
    try {
      const plugin = await parsePackage(file);
      setInstalled((prev) => {
        const next = [...prev.filter((p) => p.id !== plugin.id), plugin];
        saveJson(STORE_KEY, next);
        return next;
      });
      return { ok: true, id: plugin.id };
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : 'Install failed.' };
    }
  }, []);

  const uninstall = useCallback((id: string) => {
    persistInstalled(installed.filter((p) => p.id !== id));
  }, [installed]);

  const setConfigField = useCallback((id: string, key: string, value: unknown) => {
    const next = { ...configs, [id]: { ...(configs[id] ?? {}), [key]: value } };
    setConfigs(next);
    saveJson(CONFIG_KEY, next);
  }, [configs]);

  const setConfig = useCallback((id: string, value: Record<string, unknown>) => {
    const next = { ...configs, [id]: value };
    setConfigs(next);
    saveJson(CONFIG_KEY, next);
  }, [configs]);

  /** Replace every installed plugin's config in one shot (used by Import
   *  Project so the workbook's pluginConfigs sheet drives the state). The
   *  passed map fully replaces any existing config entries — anything
   *  absent from the map is wiped, matching the workbook-is-truth model. */
  const setAllConfigs = useCallback((next: Record<string, Record<string, unknown>>) => {
    setConfigs(next);
    saveJson(CONFIG_KEY, next);
  }, []);

  return {
    installed,
    install,
    uninstall,
    getConfig: (id: string): Record<string, unknown> => configs[id] ?? {},
    /** Snapshot of every plugin's stored config — used by Export Project so
     *  the workbook can carry the user's plugin form values. */
    getAllConfigs: (): Record<string, Record<string, unknown>> => configs,
    setConfigField,
    setConfig,
    setAllConfigs,
  };
}
