/**
 * Operations-module steps (backend/app/routers/operations_modules.py): visible workbook steps with a preview.
 *
 *  - `POST /api/model/relax-maintenance`: `maintainable` False on every generator / link / process (the Force-LP companion).
 *  - `POST /api/demand-response/preview` and `/apply`: the `dr_*` rows the demand-response module writes.
 *
 * Both read the SESSION workbook; the caller pushes the browser's working model first and reloads it after an apply.
 */
import { API_BASE } from 'lib/constants';
import { DEFAULT_SESSION_ID } from 'lib/api/session';
import type { DemandResponseConfig } from 'lib/types';

async function post<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId: DEFAULT_SESSION_ID, ...body }),
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json())?.detail ?? detail; } catch { /* non-JSON */ }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

export interface RelaxMaintenanceResult {
  changed: { sheet: string; name: string }[];
  sheetsWritten: string[];
  applied: boolean;
}

/** `apply: false` previews: lists what would change and writes nothing. */
export const relaxMaintenance = (apply: boolean) =>
  post<RelaxMaintenanceResult>('/api/model/relax-maintenance', { apply });

type SheetRows = Record<string, Record<string, unknown>[]>;

/** Row names by sheet. */
type SheetNames = Record<string, string[]>;

export interface DemandResponsePreview {
  /** Names of the dr_* rows a previous apply already wrote, by sheet. */
  existing: SheetNames;
  /** Rows the module would write for the config, by sheet. */
  rows: SheetRows;
  /** Names of the rows an apply would remove (a disabled config removes the module's rows), by sheet. */
  removed: SheetNames;
  /** Sheets an apply would change (empty when the workbook already holds exactly these rows). */
  sheets: string[];
  notes: string[];
}

export interface DemandResponseApplied {
  rows: SheetRows;
  removed: SheetNames;
  sheetsWritten: string[];
  notes: string[];
}

export const previewDemandResponse = (config: DemandResponseConfig) =>
  post<DemandResponsePreview>('/api/demand-response/preview', { config });

export const applyDemandResponse = (config: DemandResponseConfig) =>
  post<DemandResponseApplied>('/api/demand-response/apply', { config });
