/**
 * Run-options reference client (`GET /api/run-options?key=...`, backend/app/run_options_reference.py).
 *
 * The reference states, once, every run key's type, unit, default, allowed values and meaning. Settings editors read
 * their labels' units and help text from it instead of carrying a second copy in the browser.
 */
import { API_BASE } from 'lib/constants';

/** One documented field. `path` is dotted from `options.` / `scenario.`; `[]` marks a list item. */
export interface RunOptionField {
  path: string;
  type: string;
  meaning: string;
  default?: unknown;
  unit?: string;
  allowed?: unknown[];
}

export type RunOptionFields = Record<string, RunOptionField>;

const cache = new Map<string, Promise<RunOptionFields>>();

/** Every field of one key (e.g. `options.cofiringConfig`), by path. Cached per key for the session. */
export function getRunOptionFields(key: string): Promise<RunOptionFields> {
  const hit = cache.get(key);
  if (hit) return hit;
  const pending = (async () => {
    const resp = await fetch(`${API_BASE}/api/run-options?key=${encodeURIComponent(key)}`);
    if (!resp.ok) {
      let detail = resp.statusText;
      try { detail = (await resp.json())?.detail ?? detail; } catch { /* non-JSON */ }
      throw new Error(detail);
    }
    const body = (await resp.json()) as { fields: RunOptionField[] };
    return Object.fromEntries(body.fields.map((f) => [f.path, f]));
  })();
  cache.set(key, pending);
  pending.catch(() => cache.delete(key));
  return pending;
}

/** Test seam: forget cached references. */
export function clearRunOptionFieldCache(): void {
  cache.clear();
}
