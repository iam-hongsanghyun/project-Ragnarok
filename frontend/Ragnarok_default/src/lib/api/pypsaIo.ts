/**
 * PyPSA-native file I/O client (`backend/app/routers/pypsa_io.py`).
 *
 * The four importers answer `{model}` and do NOT touch the session, so an import is its own preview: the returned
 * workbook is summarised for the user and only replaces the working model on confirm. pandapower may answer 202
 * `{status: "setting_up", retryAfterSeconds}` while its isolated environment is built (first use); the same request
 * is retried after that delay.
 */
import { API_BASE } from 'lib/constants';
import type { GridRow, WorkbookModel } from 'lib/types';

export type PypsaImportKind = 'pypsa-excel' | 'pypsa-csv' | 'matpower' | 'pandapower';
export type PypsaExportKind = 'pypsa-excel' | 'pypsa-csv';

export interface PandapowerSetup {
  state: 'ready' | 'setting_up' | 'failed' | 'disabled' | 'absent' | string;
  stage?: string;
  error?: string;
  retryAfterSeconds?: number;
}

export interface PypsaIoCapabilities {
  import: string[];
  export: string[];
  pandapowerInstalled: boolean;
  pandapowerSetup: PandapowerSetup;
  exportOptions: string[];
}

/** Query-string options per importer (names as the backend reads them). */
export interface PypsaImportOptions {
  skipTime?: boolean;
  overwriteZeroSNom?: number;
  extraLineData?: boolean;
  usePandapowerIndex?: boolean;
}

export const IMPORT_ENDPOINT: Record<PypsaImportKind, string> = {
  'pypsa-excel': '/api/import/pypsa-excel',
  'pypsa-csv': '/api/import/pypsa-csv',
  matpower: '/api/import/matpower',
  pandapower: '/api/import/pandapower',
};

export const EXPORT_ENDPOINT: Record<PypsaExportKind, string> = {
  'pypsa-excel': '/api/export/pypsa-excel',
  'pypsa-csv': '/api/export/pypsa-csv',
};

async function errorDetail(resp: Response, fallback: string): Promise<string> {
  try {
    const body = await resp.json();
    if (typeof body?.detail === 'string' && body.detail) return body.detail;
  } catch { /* non-JSON body */ }
  return `${fallback} (HTTP ${resp.status})`;
}

export async function getPypsaIoCapabilities(): Promise<PypsaIoCapabilities> {
  const resp = await fetch(`${API_BASE}/api/import/pypsa-io/capabilities`);
  if (!resp.ok) throw new Error(await errorDetail(resp, 'Could not read the PyPSA I/O capabilities'));
  return resp.json() as Promise<PypsaIoCapabilities>;
}

/** Query string for one importer; only the options that importer reads are sent. */
export function importQuery(kind: PypsaImportKind, o: PypsaImportOptions): string {
  const q = new URLSearchParams();
  if ((kind === 'pypsa-excel' || kind === 'pypsa-csv') && o.skipTime) q.set('skipTime', 'true');
  if (kind === 'matpower' && o.overwriteZeroSNom !== undefined && Number.isFinite(o.overwriteZeroSNom)) {
    q.set('overwriteZeroSNom', String(o.overwriteZeroSNom));
  }
  if (kind === 'pandapower') {
    if (o.extraLineData) q.set('extraLineData', 'true');
    if (o.usePandapowerIndex) q.set('usePandapowerIndex', 'true');
  }
  const s = q.toString();
  return s ? `?${s}` : '';
}

export type ImportOutcome =
  | { status: 'ok'; model: WorkbookModel }
  | { status: 'setting_up'; detail: string; retryAfterSeconds: number };

/** One import attempt. A 202 comes back as `setting_up` so the caller can wait and retry. */
export async function postPypsaImport(
  kind: PypsaImportKind, file: File, options: PypsaImportOptions = {},
): Promise<ImportOutcome> {
  const form = new FormData();
  form.append('file', file);
  const resp = await fetch(`${API_BASE}${IMPORT_ENDPOINT[kind]}${importQuery(kind, options)}`, { method: 'POST', body: form });
  if (resp.status === 202) {
    const body = (await resp.json()) as { detail?: string; retryAfterSeconds?: number };
    return { status: 'setting_up', detail: body.detail ?? 'Preparing the pandapower environment.', retryAfterSeconds: body.retryAfterSeconds ?? 10 };
  }
  if (!resp.ok) throw new Error(await errorDetail(resp, 'Import failed'));
  const body = (await resp.json()) as { model: WorkbookModel };
  return { status: 'ok', model: body.model };
}

export interface ModelSummaryRow { sheet: string; rows: number }

/** Row count per non-empty sheet, largest component sheets first: what the import will create. */
export function summariseModel(model: WorkbookModel): ModelSummaryRow[] {
  return Object.entries(model as Record<string, GridRow[]>)
    .filter(([, rows]) => Array.isArray(rows) && rows.length > 0)
    .map(([sheet, rows]) => ({ sheet, rows: rows.length }))
    .sort((a, b) => b.rows - a.rows || a.sheet.localeCompare(b.sheet));
}
