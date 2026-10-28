/**
 * Time-units module client (backend/app/routers/operations_modules.py, backend/pypsa/network/time_units.py).
 *
 * Ramps and unit-commitment times are stated in time units (per hour / per minute, hours / minutes) in the
 * `RAGNAROK_TimeUnits` sheet; the server converts them to PyPSA's per-snapshot values at solve time. The browser edits
 * the sheet like any other and only DISPLAYS the converted table the server returns.
 */
import { API_BASE } from 'lib/constants';
import { DEFAULT_SESSION_ID } from 'lib/api/session';

export const TIME_UNITS_SHEET = 'RAGNAROK_TimeUnits';

/** One row of the sheet. `value` is in `unit`; blank cells read back as `null`. */
export interface TimeUnitRow {
  component: string;
  name: string;
  attribute: string;
  value: number | null;
  unit: string;
}

/** `GET /api/time-units`: the vocabulary the editor offers (nothing is hard-coded in the browser). */
export interface TimeUnitsVocabulary {
  sheet: string;
  rows: TimeUnitRow[];
  components: string[];
  attributes: { ramps: string[]; times: string[] };
  units: { ramps: string[]; times: string[] };
}

/** One converted row of `POST /api/time-units/preview` (`time_units.apply_to_network`'s table). */
export interface TimeUnitPreviewRow extends TimeUnitRow {
  stepHours: number;
  /** The per-snapshot value PyPSA receives; `null` when it is left blank (a ramp of at least 100 % per snapshot). */
  pypsaValue: number | null;
  blank: boolean;
  note: string;
}

export interface TimeUnitsPreview {
  table: TimeUnitPreviewRow[];
  stepHours: number | null;
}

async function call<T>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json())?.detail ?? detail; } catch { /* non-JSON */ }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

export function getTimeUnits(): Promise<TimeUnitsVocabulary> {
  return call<TimeUnitsVocabulary>(`/api/time-units?session_id=${encodeURIComponent(DEFAULT_SESSION_ID)}`);
}

/** What a run would write for PyPSA, per snapshot step. Reads the SESSION model, so push local edits first. */
export function previewTimeUnits(options: Record<string, unknown> = {}): Promise<TimeUnitsPreview> {
  return call<TimeUnitsPreview>('/api/time-units/preview', { sessionId: DEFAULT_SESSION_ID, options });
}
