/**
 * External tab-module HTTP client — `/api/modules/*`.
 *
 * Installed modules live on the SERVER (`backend/data/modules/`), not in
 * localStorage: the build-id reset in `index.tsx` (every app update) and the
 * "Clear cache" button both wipe `ragnarok:*` keys, which would silently
 * uninstall a module. A module is project content, so the backend owns it —
 * including its enabled flag.
 */
import { zipSync, strToU8 } from 'fflate';
import { API_BASE } from 'lib/constants';
import type { ExternalTabModule } from './types';

export const MANIFEST_NAME = 'tabmodule.json';

async function asJson<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      detail = (body && (body.detail as string)) || detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

export async function fetchModules(): Promise<ExternalTabModule[]> {
  const body = await asJson<{ modules: ExternalTabModule[] }>(
    await fetch(`${API_BASE}/api/modules`),
  );
  return body.modules ?? [];
}

/**
 * Install from a picked directory / multi-file / .zip selection.
 *
 * A directory pick is zipped in the browser (paths re-based to the folder that
 * holds the manifest) and posted as one archive, so the backend has a single
 * install path and is the only authority on manifest validity.
 */
export async function installModule(picked: readonly File[]): Promise<ExternalTabModule> {
  const archive = picked.length === 1 && picked[0].name.toLowerCase().endsWith('.zip')
    ? picked[0]
    : await zipPickedFiles(picked);
  const form = new FormData();
  form.append('file', archive, archive.name || 'module.zip');
  return asJson<ExternalTabModule>(
    await fetch(`${API_BASE}/api/modules/install`, { method: 'POST', body: form }),
  );
}

export async function setModuleEnabled(id: string, enabled: boolean): Promise<void> {
  await asJson(await fetch(`${API_BASE}/api/modules/${encodeURIComponent(id)}/enabled`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  }));
}

export async function removeModule(id: string): Promise<void> {
  await asJson(await fetch(`${API_BASE}/api/modules/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  }));
}

/** Zip a directory/multi-file pick, re-based to the manifest's directory. */
export async function zipPickedFiles(picked: readonly File[]): Promise<File> {
  const relPath = (f: File): string => {
    const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath;
    return rel && rel.length > 0 ? rel : f.name;
  };
  const manifestFile = picked.find((f) => relPath(f).split('/').pop() === MANIFEST_NAME);
  if (!manifestFile) {
    throw new Error(`The selection has no ${MANIFEST_NAME} manifest.`);
  }
  const manifestRel = relPath(manifestFile);
  const prefix = manifestRel.slice(0, manifestRel.length - MANIFEST_NAME.length);
  const entries: Record<string, Uint8Array> = {};
  for (const f of picked) {
    const rel = relPath(f);
    if (!rel.startsWith(prefix)) continue;
    entries[rel.slice(prefix.length)] = new Uint8Array(await f.arrayBuffer());
  }
  if (Object.keys(entries).length === 0) {
    throw new Error('The selection contained no files.');
  }
  // A tiny marker so a zip built here is recognisable in a bug report.
  entries['.ragnarok-packed'] = strToU8('packed by the Ragnarok module installer\n');
  return new File([zipSync(entries)], 'module.zip', { type: 'application/zip' });
}
