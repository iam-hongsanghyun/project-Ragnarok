/**
 * Client for BACKEND (server-side) plugins — see backend `app/routers/plugins.py`.
 *
 * Backend plugins run inside the Ragnarok backend and import the bundled PyPSA
 * source directly. They share the unified hook contract with frontend plugins:
 * `transform` (replace model), `contribute` (add sheets/constraints), `analyze`
 * (read-only output). `transform`/`contribute` write straight into the session
 * (the source of truth), so the produced model never travels through the browser
 * — the frontend kicks it off and then rehydrates from the session.
 *
 * Plugins are installed by uploading a `.zip` (`installBackendPlugin`) and removed
 * with `uninstallBackendPlugin` — Ragnarok ships none.
 */
import { API_BASE } from 'lib/constants';
import type { ModuleConfigSchema } from 'lib/types';
import { DEFAULT_SESSION_ID, type SessionMeta } from './session';

export type BackendHook = 'transform' | 'contribute' | 'analyze';

export interface BackendPluginManifest {
  id: string;
  name: string;
  version: string;
  kind: 'backend';
  description: string;
  capabilities: string[];
  config: ModuleConfigSchema;
  hooks: { transform: boolean; contribute: boolean; analyze: boolean };
}

async function asJson<T>(resp: Response): Promise<T> {
  if (!resp.ok) throw new Error((await resp.text()) || `Request failed (${resp.status}).`);
  return resp.json() as Promise<T>;
}

/** List the backend plugins the server has loaded. Empty when none/unreachable. */
export async function listBackendPlugins(): Promise<BackendPluginManifest[]> {
  const resp = await fetch(`${API_BASE}/api/plugins`);
  const body = await asJson<{ plugins: BackendPluginManifest[] }>(resp);
  return Array.isArray(body.plugins) ? body.plugins : [];
}

/** Install a backend plugin from a `.zip` (manifest.json + plugin.py). */
export async function installBackendPlugin(file: File): Promise<BackendPluginManifest> {
  const form = new FormData();
  form.append('file', file, file.name);
  const resp = await fetch(`${API_BASE}/api/plugins/install`, { method: 'POST', body: form });
  return asJson<BackendPluginManifest>(resp);
}

/** Remove an installed backend plugin (deletes its server-side folder). */
export async function uninstallBackendPlugin(id: string): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/plugins/${encodeURIComponent(id)}`, { method: 'DELETE' });
  if (!resp.ok) throw new Error((await resp.text()) || `Uninstall failed (${resp.status}).`);
}

/** Run a backend `transform`/`contribute` hook; the model lands in the session. */
export async function runBackendHook(
  id: string,
  hook: 'transform' | 'contribute',
  config: Record<string, unknown>,
  opts: { sessionId?: string; filename?: string; scenarioName?: string } = {},
): Promise<SessionMeta> {
  const resp = await fetch(`${API_BASE}/api/plugins/${encodeURIComponent(id)}/${hook}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      config,
      sessionId: opts.sessionId ?? DEFAULT_SESSION_ID,
      filename: opts.filename ?? '',
      scenarioName: opts.scenarioName ?? '',
    }),
  });
  return asJson<SessionMeta>(resp);
}

/** Run a backend plugin's `analyze(result, config)` and return its output. */
export async function analyzeBackendPlugin(
  id: string,
  result: unknown,
  config: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const resp = await fetch(`${API_BASE}/api/plugins/${encodeURIComponent(id)}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ result, config }),
  });
  return asJson<Record<string, unknown>>(resp);
}
