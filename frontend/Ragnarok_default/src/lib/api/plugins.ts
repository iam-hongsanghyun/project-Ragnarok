/**
 * Client for BACKEND (server-side) plugins — see backend `app/routers/plugins.py`.
 *
 * Backend plugins run inside the Ragnarok backend and import the bundled PyPSA
 * source directly. A `build` plugin writes its model straight into the session
 * (the source of truth), so the produced model never travels through the
 * browser — the frontend just kicks it off and then rehydrates from the session.
 */
import { API_BASE } from 'lib/constants';
import type { ModuleConfigSchema } from 'lib/types';
import { DEFAULT_SESSION_ID, type SessionMeta } from './session';

export interface BackendPluginManifest {
  id: string;
  name: string;
  version: string;
  kind: 'backend';
  description: string;
  capabilities: string[];
  config: ModuleConfigSchema;
  hooks: { build: boolean; analyze: boolean };
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

/** Run a backend plugin's `build(config)`; the model lands in the session. */
export async function buildBackendPlugin(
  id: string,
  config: Record<string, unknown>,
  opts: { sessionId?: string; filename?: string; scenarioName?: string } = {},
): Promise<SessionMeta> {
  const resp = await fetch(`${API_BASE}/api/plugins/${encodeURIComponent(id)}/build`, {
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
