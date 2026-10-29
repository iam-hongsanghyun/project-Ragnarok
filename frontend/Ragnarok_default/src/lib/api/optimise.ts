/**
 * Optimise-adjacent client: `POST /api/optimise/export-lp` (backend/app/routers/optimise.py).
 *
 * The export builds the session model exactly as a run would and writes the LP file on the server without solving;
 * `downloadExportedLp` then fetches that file so the browser saves it.
 */
import { API_BASE } from 'lib/constants';
import { DEFAULT_SESSION_ID } from 'lib/api/session';

export interface ExportLpInfo {
  /** Server path of the written file. */
  path: string;
  bytes: number;
  variables: number;
  constraints: number;
  seconds: number;
}

async function fail(resp: Response): Promise<never> {
  let detail = resp.statusText;
  try { detail = (await resp.json())?.detail ?? detail; } catch { /* non-JSON */ }
  throw new Error(detail);
}

/** Write the LP of the session model for `{scenario, options}` (the run body) without solving. */
export async function exportLp(
  body: { scenario: Record<string, unknown>; options: Record<string, unknown> },
  fileName: string,
): Promise<ExportLpInfo> {
  const resp = await fetch(`${API_BASE}/api/optimise/export-lp`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId: DEFAULT_SESSION_ID, ...body, fileName }),
  });
  if (!resp.ok) await fail(resp);
  return resp.json() as Promise<ExportLpInfo>;
}

/** The file name the server used (its last path segment). */
export function exportedFileName(info: ExportLpInfo): string {
  return info.path.split(/[\\/]/).pop() || 'model.lp';
}

export async function fetchExportedLp(name: string): Promise<Blob> {
  const resp = await fetch(`${API_BASE}/api/optimise/export-lp/file?fileName=${encodeURIComponent(name)}`);
  if (!resp.ok) await fail(resp);
  return resp.blob();
}

/** Export, then save the file through the browser. */
export async function exportAndDownloadLp(
  body: { scenario: Record<string, unknown>; options: Record<string, unknown> },
  fileName = 'model.lp',
): Promise<ExportLpInfo> {
  const info = await exportLp(body, fileName);
  const name = exportedFileName(info);
  const blob = await fetchExportedLp(name);
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return info;
}
