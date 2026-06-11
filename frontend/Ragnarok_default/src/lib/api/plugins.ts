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
  hooks: { transform: boolean; contribute: boolean; analyze: boolean; options?: boolean };
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

export interface PluginFile {
  name: string;
  size: number;
}

/** List the data files uploaded to a backend plugin's server-side scratch dir. */
export async function listPluginFiles(id: string): Promise<PluginFile[]> {
  const resp = await fetch(`${API_BASE}/api/plugins/${encodeURIComponent(id)}/files`);
  const body = await asJson<{ files: PluginFile[] }>(resp);
  return Array.isArray(body.files) ? body.files : [];
}

/** Upload a data file to a backend plugin's scratch dir (streamed, NOT base64
 *  into config — the bytes never live in the browser config / memory). */
export async function uploadPluginFile(id: string, file: File): Promise<PluginFile> {
  const form = new FormData();
  form.append('file', file, file.name);
  const resp = await fetch(`${API_BASE}/api/plugins/${encodeURIComponent(id)}/files`, { method: 'POST', body: form });
  return asJson<PluginFile>(resp);
}

/** Delete one uploaded data file. */
export async function deletePluginFile(id: string, name: string): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/plugins/${encodeURIComponent(id)}/files/${encodeURIComponent(name)}`, { method: 'DELETE' });
  if (!resp.ok) throw new Error((await resp.text()) || `Delete failed (${resp.status}).`);
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

/**
 * Fetch on-demand dropdown rows from a backend plugin's `options(name, …)` hook.
 *
 * Replaces the old per-plugin `localhost:8765` POST for backend plugins — the
 * rows are resolved into options client-side (filter/label) exactly like the
 * other option sources. Returns `[]` on any error so a dropdown degrades to its
 * static options instead of throwing.
 */
export async function getPluginOptions(
  id: string,
  name: string,
  config: Record<string, unknown>,
  sessionId: string = DEFAULT_SESSION_ID,
): Promise<Array<Record<string, unknown>>> {
  try {
    const resp = await fetch(`${API_BASE}/api/plugins/${encodeURIComponent(id)}/options`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, config, sessionId }),
    });
    if (!resp.ok) return [];
    const body = (await resp.json()) as { rows?: Array<Record<string, unknown>> };
    return Array.isArray(body.rows) ? body.rows : [];
  } catch {
    return [];
  }
}

export interface PluginActionResult {
  ok: boolean;
  message: string;
  /** Optional patch of field → value the host writes back into the form
   *  (e.g. a "Fill table" button populating an editable table). */
  config?: Record<string, unknown>;
}

/** Run a named action hook `hook(config)` exported by a backend plugin —
 *  the server-side counterpart of the frontend-plugin action contract. */
export async function runBackendAction(
  id: string,
  hook: string,
  config: Record<string, unknown>,
): Promise<PluginActionResult> {
  const resp = await fetch(`${API_BASE}/api/plugins/${encodeURIComponent(id)}/action`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ hook, config }),
  });
  return asJson<PluginActionResult>(resp);
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
