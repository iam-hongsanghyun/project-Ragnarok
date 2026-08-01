/**
 * External tab-module store — parse, validate, persist (localStorage).
 *
 * Mirrors the frontend plugin host's storage idiom (`frontendPlugins.ts`):
 * user-supplied packages are trusted local code in a single-user app, kept in
 * localStorage so an installed module survives reloads without a backend.
 */
import { unzipSync, strFromU8 } from 'fflate';
import { TAB_MODULES } from '../registry';
import type { ExternalModuleManifest, ExternalTabModule } from './types';

const STORE_KEY = 'ragnarok:tab-modules:installed';

export const MANIFEST_NAME = 'tabmodule.json';

/** Tab ids an external module may never take: core tabs + built-in modules. */
const RESERVED_IDS: ReadonlySet<string> = new Set([
  'Welcome', 'Build', 'Model', 'Market', 'Settings', 'Analytics', 'History', 'Plugins',
  ...TAB_MODULES.map((m) => m.id),
]);

/** Where external modules land on the bar when the manifest names no order. */
const DEFAULT_EXTERNAL_ORDER = 200;

export function loadInstalled(): ExternalTabModule[] {
  try {
    const raw = window.localStorage.getItem(STORE_KEY);
    return raw === null ? [] : (JSON.parse(raw) as ExternalTabModule[]);
  } catch {
    return [];
  }
}

export function saveInstalled(modules: ExternalTabModule[]): void {
  try {
    window.localStorage.setItem(STORE_KEY, JSON.stringify(modules));
  } catch {
    /* quota — an oversized module simply won't survive a reload */
  }
}

function validateManifest(raw: Record<string, unknown>): ExternalModuleManifest {
  const id = String(raw.id ?? '').trim();
  if (!id) throw new Error(`${MANIFEST_NAME} is missing an "id".`);
  if (!/^[A-Za-z][A-Za-z0-9_-]*$/.test(id)) {
    throw new Error(`Module id "${id}" must be alphanumeric (dashes/underscores allowed).`);
  }
  if (RESERVED_IDS.has(id)) {
    throw new Error(`Module id "${id}" collides with a built-in tab.`);
  }
  const label = String(raw.label ?? id).trim();
  const order = Number(raw.order);
  return {
    id,
    label,
    hint: typeof raw.hint === 'string' ? raw.hint : label,
    description: typeof raw.description === 'string' ? raw.description : '',
    order: Number.isFinite(order) ? order : DEFAULT_EXTERNAL_ORDER,
    entry: typeof raw.entry === 'string' && raw.entry.trim() ? raw.entry.trim() : 'index.js',
  };
}

function buildModule(files: Record<string, string>): ExternalTabModule {
  const manifestSrc = files[MANIFEST_NAME];
  if (manifestSrc === undefined) {
    throw new Error(`The package has no ${MANIFEST_NAME} manifest.`);
  }
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(manifestSrc) as Record<string, unknown>;
  } catch {
    throw new Error(`${MANIFEST_NAME} is not valid JSON.`);
  }
  const manifest = validateManifest(parsed);
  if (files[manifest.entry ?? 'index.js'] === undefined) {
    throw new Error(`Entry file "${manifest.entry}" not found in the package.`);
  }
  return { manifest, files, enabled: true, installedAt: new Date().toISOString() };
}

/**
 * Build a module from picked files — a directory selection (webkitdirectory),
 * a multi-file selection, or a single `.zip`. Paths are re-based to the
 * directory that holds `tabmodule.json`, so a nested folder works too.
 */
export async function parseModuleFiles(picked: readonly File[]): Promise<ExternalTabModule> {
  if (picked.length === 1 && picked[0].name.toLowerCase().endsWith('.zip')) {
    const buf = new Uint8Array(await picked[0].arrayBuffer());
    const entries = unzipSync(buf);
    const names = Object.keys(entries);
    const manifestPath = names.find((p) => p === MANIFEST_NAME || p.endsWith(`/${MANIFEST_NAME}`));
    if (!manifestPath) throw new Error(`The .zip has no ${MANIFEST_NAME} manifest.`);
    const prefix = manifestPath.slice(0, manifestPath.length - MANIFEST_NAME.length);
    const files: Record<string, string> = {};
    for (const [path, data] of Object.entries(entries)) {
      if (!path.startsWith(prefix) || path.endsWith('/')) continue;
      files[path.slice(prefix.length)] = strFromU8(data);
    }
    return buildModule(files);
  }

  // Directory / multi-file selection. webkitRelativePath is set for directory
  // picks ("dir/sub/file.js"); plain multi-file picks fall back to file names.
  const relPath = (f: File): string => {
    const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath;
    return rel && rel.length > 0 ? rel : f.name;
  };
  // File.text() is Blob API level 2 — present in every real browser, absent in
  // jsdom. Fall back to FileReader so the store is testable.
  const readText = (f: File): Promise<string> =>
    typeof f.text === 'function'
      ? f.text()
      : new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result ?? ''));
          reader.onerror = () => reject(reader.error ?? new Error('Could not read file.'));
          reader.readAsText(f);
        });
  const manifestFile = picked.find((f) => relPath(f).split('/').pop() === MANIFEST_NAME);
  if (!manifestFile) throw new Error(`The selection has no ${MANIFEST_NAME} manifest.`);
  const manifestRel = relPath(manifestFile);
  const prefix = manifestRel.slice(0, manifestRel.length - MANIFEST_NAME.length);
  const files: Record<string, string> = {};
  for (const f of picked) {
    const rel = relPath(f);
    if (!rel.startsWith(prefix)) continue;
    files[rel.slice(prefix.length)] = await readText(f);
  }
  return buildModule(files);
}
