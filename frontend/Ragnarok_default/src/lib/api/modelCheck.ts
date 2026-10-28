/**
 * Model check client (`POST /api/model-check`, backend/app/model_check/checks.py): the back-brief and the trap
 * findings read from the workbook the session holds. Read-only; a finding may carry the visible workbook step that
 * resolves it (`action`), which the UI offers as a button and never runs by itself.
 */
import { API_BASE } from 'lib/constants';
import { DEFAULT_SESSION_ID } from 'lib/api/session';

/** Finding `code`s this UI knows an action for; an unknown code is listed without a button. */
export type ModelCheckActionId = 'set_weightings_from_spacing' | 'clean_placeholder_bounds';

export interface ModelCheckAction {
  id: string;
  label: string;
  /** e.g. `POST /api/model/set-weightings-from-spacing` (informational; the UI calls its own client). */
  endpoint: string;
}

export interface ModelCheckFinding {
  level: 'warn' | 'note';
  code: string;
  message: string;
  fix: string;
  action?: ModelCheckAction;
}

export interface ModelCheckResult {
  findings: ModelCheckFinding[];
  warnCount: number;
  noteCount: number;
  verdict: string;
}

export async function runModelCheck(): Promise<ModelCheckResult> {
  const resp = await fetch(`${API_BASE}/api/model-check`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId: DEFAULT_SESSION_ID }),
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json())?.detail ?? detail; } catch { /* non-JSON */ }
    throw new Error(detail);
  }
  return resp.json() as Promise<ModelCheckResult>;
}
