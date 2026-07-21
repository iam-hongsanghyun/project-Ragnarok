/**
 * Client for the master-model slot (`/api/session/master/*`).
 *
 * The master is a full (typically multi-year) model imported once from an
 * Excel project and stored server-side BESIDE the working model. Deriving
 * filters it (years + attribute filters) and REPLACES the working model with
 * the result — the master itself is never touched by editing or solving.
 * See backend `app/routers/master.py` / `app/model_derive.py`.
 */
import { API_BASE } from 'lib/constants';
import { DEFAULT_SESSION_ID, SessionMeta } from './session';

export interface MasterMeta extends SessionMeta {
  /** Distinct calendar years available in the master's snapshots. */
  years?: number[];
}

export interface MasterFilter {
  sheet: string;
  column: string;
  values: string[];
}

export interface DeriveReport {
  years: number[];
  snapshots: number;
  /** 'deactivate' (default: excluded components get PyPSA `active = false`) or 'remove'. */
  mode: 'deactivate' | 'remove';
  /** Per-sheet count of components deactivated (or removed). */
  excluded: Record<string, number>;
  components: Record<string, number>;
}

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

/** Upload a project (.zip/.xlsx) into the master slot; the working model is untouched. */
export async function importMasterModel(file: File, sessionId = DEFAULT_SESSION_ID): Promise<MasterMeta> {
  const form = new FormData();
  form.append('file', file);
  const resp = await fetch(
    `${API_BASE}/api/session/master/import?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'POST', body: form },
  );
  return asJson<MasterMeta>(resp);
}

/** Master meta + years, or {} when no master is stored. */
export async function getMasterMeta(sessionId = DEFAULT_SESSION_ID): Promise<MasterMeta> {
  const resp = await fetch(
    `${API_BASE}/api/session/master/meta?session_id=${encodeURIComponent(sessionId)}`,
  );
  return asJson<MasterMeta>(resp);
}

/** Sorted distinct non-empty values of one master-sheet column (filter value picker). */
export async function getMasterDistinct(
  sheet: string,
  column: string,
  sessionId = DEFAULT_SESSION_ID,
): Promise<string[]> {
  const params = new URLSearchParams({ sheet, column, session_id: sessionId });
  const resp = await fetch(`${API_BASE}/api/session/master/distinct?${params}`);
  const body = await asJson<{ values: string[] }>(resp);
  return body.values ?? [];
}

/** Filter the master (years + attribute filters) and REPLACE the working model.
 *  Excluded components are marked `active = false` (PyPSA skips them in the
 *  solve) rather than deleted, unless mode 'remove' is requested. */
export async function deriveFromMaster(
  opts: { years?: number[]; filters?: MasterFilter[]; mode?: 'deactivate' | 'remove'; sessionId?: string } = {},
): Promise<{ meta: SessionMeta; report: DeriveReport }> {
  const resp = await fetch(`${API_BASE}/api/session/master/derive`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      years: opts.years ?? null,
      filters: opts.filters ?? [],
      mode: opts.mode ?? 'deactivate',
      sessionId: opts.sessionId ?? DEFAULT_SESSION_ID,
    }),
  });
  return asJson(resp);
}

/** Remove the stored master model (the working model is untouched). */
export async function clearMasterModel(sessionId = DEFAULT_SESSION_ID): Promise<boolean> {
  const resp = await fetch(
    `${API_BASE}/api/session/master/clear?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'POST' },
  );
  const body = await asJson<{ cleared: boolean }>(resp);
  return body.cleared;
}
