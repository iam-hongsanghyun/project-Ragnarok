/**
 * Client for the server-side working-model "session" (backend = source of truth).
 *
 * The thin frontend imports a model once (`putSessionModel`) and thereafter
 * fetches only what it shows: a page of static rows (`getSheetPage`) or a
 * windowed, downsampled time-series slice (`getSeriesWindow`). The heavy model
 * never lives in browser memory. See backend `app/routers/session.py`.
 */
import { API_BASE } from 'lib/constants';
import type { GridRow, WorkbookModel } from 'lib/types';

/** Single active session today; a first-class id so remote/multi-session is a flip later. */
export const DEFAULT_SESSION_ID = 'default';

export interface SessionSheetMeta {
  name: string;
  kind: 'static' | 'series';
  rowCount: number;
  columns: string[];
}

export interface SessionMeta {
  sessionId?: string;
  filename?: string;
  scenarioName?: string;
  savedAt?: string;
  sheets?: SessionSheetMeta[];
  snapshotCount?: number;
  snapshotStart?: string | null;
  snapshotEnd?: string | null;
  scenarioYear?: number | null;
  componentCounts?: Record<string, number>;
}

export interface SheetPage {
  name: string;
  kind: 'static' | 'series';
  total: number;
  offset: number;
  limit: number;
  columns: string[];
  rows: GridRow[];
}

export type DownsampleAgg = 'mean' | 'point' | 'max' | 'min';

export interface SeriesWindow {
  name: string;
  indexCol: string;
  total: number;
  window: { start: number; end: number };
  returned: number;
  agg: DownsampleAgg;
  columns: string[];
  rows: GridRow[];
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

/** Ingest a full model into the session; returns meta only (model stays server-side). */
export async function putSessionModel(
  model: WorkbookModel,
  opts: { filename?: string; scenarioName?: string; sessionId?: string } = {},
): Promise<SessionMeta> {
  const resp = await fetch(`${API_BASE}/api/session/model`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      filename: opts.filename ?? '',
      scenarioName: opts.scenarioName ?? '',
      sessionId: opts.sessionId ?? DEFAULT_SESSION_ID,
    }),
  });
  return asJson<SessionMeta>(resp);
}

/** Merge the model's STATIC sheets into the session, keeping the backend's
 *  time-series untouched. The thin client syncs its in-memory static edits this
 *  way before a run (it never holds the heavy series, so a full put would wipe them). */
export async function putStaticModel(
  model: WorkbookModel,
  opts: { sessionId?: string } = {},
): Promise<SessionMeta> {
  const resp = await fetch(`${API_BASE}/api/session/model/static`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, sessionId: opts.sessionId ?? DEFAULT_SESSION_ID }),
  });
  return asJson<SessionMeta>(resp);
}

/** Return the session meta ({} when nothing is loaded). */
export async function getSessionMeta(sessionId = DEFAULT_SESSION_ID): Promise<SessionMeta> {
  const resp = await fetch(`${API_BASE}/api/session/meta?session_id=${encodeURIComponent(sessionId)}`);
  return asJson<SessionMeta>(resp);
}

/** Working model from the session ({sheet: rows}), or null if none.
 *  With staticOnly, the heavy time-series sheets are omitted — used to rehydrate
 *  the editor cheaply on boot (series are paged on demand). */
export async function getSessionFullModel(
  opts: { sessionId?: string; staticOnly?: boolean } = {},
): Promise<WorkbookModel | null> {
  const params = new URLSearchParams({ session_id: opts.sessionId ?? DEFAULT_SESSION_ID });
  if (opts.staticOnly) params.set('staticOnly', 'true');
  const resp = await fetch(`${API_BASE}/api/session/model/full?${params}`);
  const body = await asJson<{ model: WorkbookModel | null }>(resp);
  return body.model ?? null;
}

/** One page of a sheet's rows (static or series). */
export async function getSheetPage(
  name: string,
  opts: { offset?: number; limit?: number; sessionId?: string } = {},
): Promise<SheetPage> {
  const params = new URLSearchParams({ session_id: opts.sessionId ?? DEFAULT_SESSION_ID });
  if (opts.offset != null) params.set('offset', String(opts.offset));
  if (opts.limit != null) params.set('limit', String(opts.limit));
  const resp = await fetch(`${API_BASE}/api/session/sheet/${encodeURIComponent(name)}?${params}`);
  return asJson<SheetPage>(resp);
}

/**
 * Sorted distinct non-empty values of one column in a static sheet.
 *
 * Server-side (`SELECT DISTINCT` on the SQLite store, row-scan on legacy) so the
 * model never loads into the browser. Backs unique-value pickers (Forge targets,
 * grid column filters) on demand — never per-keystroke.
 */
export async function getSheetDistinct(
  name: string,
  column: string,
  opts: { sessionId?: string } = {},
): Promise<string[]> {
  const params = new URLSearchParams({
    session_id: opts.sessionId ?? DEFAULT_SESSION_ID,
    column,
  });
  const resp = await fetch(
    `${API_BASE}/api/session/sheet/${encodeURIComponent(name)}/distinct?${params}`,
  );
  const data = await asJson<{ values: string[] }>(resp);
  return data.values ?? [];
}

/** A windowed, server-downsampled slice of a time-series sheet. */
export async function getSeriesWindow(
  name: string,
  opts: {
    start?: number;
    end?: number;
    columns?: string[];
    maxPoints?: number;
    agg?: DownsampleAgg;
    sessionId?: string;
  } = {},
): Promise<SeriesWindow> {
  const params = new URLSearchParams({ session_id: opts.sessionId ?? DEFAULT_SESSION_ID });
  if (opts.start != null) params.set('start', String(opts.start));
  if (opts.end != null) params.set('end', String(opts.end));
  if (opts.columns?.length) params.set('columns', opts.columns.join(','));
  if (opts.maxPoints != null) params.set('maxPoints', String(opts.maxPoints));
  if (opts.agg) params.set('agg', opts.agg);
  const resp = await fetch(`${API_BASE}/api/session/series/${encodeURIComponent(name)}?${params}`);
  return asJson<SeriesWindow>(resp);
}

/** A PyPSA time-series sheet is ``<component>-<attribute>`` (e.g. generators-p_max_pu);
 *  ``snapshots`` is the time axis, treated as static. Mirrors the backend rule. */
export function isSeriesSheet(name: string): boolean {
  return name !== 'snapshots' && name.includes('-');
}

/** Map of `<series sheet> → row count` from a session meta. Time-series sheets
 *  aren't held in the in-memory model (they page on demand), so this is what
 *  makes them visible + selectable in the Model tree. */
export function seriesSheetCounts(meta: SessionMeta): Record<string, number> {
  const out: Record<string, number> = {};
  for (const s of meta.sheets ?? []) {
    if (s.kind === 'series' && s.rowCount > 0) out[s.name] = s.rowCount;
  }
  return out;
}

export type SheetEditOp =
  | { op: 'set'; row: number; column: string; value: unknown }
  | { op: 'addRow'; values?: Record<string, unknown>; index?: number }
  | { op: 'deleteRows'; rows: number[] };

/** Apply a batch of edits to a session sheet (backend = source of truth). */
export async function patchSheet(
  name: string,
  ops: SheetEditOp[],
  sessionId = DEFAULT_SESSION_ID,
): Promise<{ name: string; kind: string; total: number; columns: string[] }> {
  const resp = await fetch(`${API_BASE}/api/session/sheet/${encodeURIComponent(name)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ops, sessionId }),
  });
  return asJson(resp);
}

export type SeriesTransformOp = 'scale' | 'offset' | 'shift' | 'interpolate' | 'clip' | 'grow';

export interface SeriesTransformParams {
  op: SeriesTransformOp;
  /** Restrict to a subset of asset columns; omit for all value columns. */
  columns?: string[] | null;
  factor?: number;
  delta?: number;
  shift?: number;
  wrap?: boolean;
  minValue?: number | null;
  maxValue?: number | null;
  /** Total % growth ramped first→last snapshot (op 'grow'). */
  growthPct?: number;
}

/** Apply a bulk transform to a temporal sheet server-side (T1). */
export async function transformSeries(
  name: string,
  params: SeriesTransformParams,
  sessionId = DEFAULT_SESSION_ID,
): Promise<{ name: string; kind: string; total: number; columns: string[] }> {
  const resp = await fetch(`${API_BASE}/api/session/series/${encodeURIComponent(name)}/transform`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...params, sessionId }),
  });
  return asJson(resp);
}

/** Clear the session's working model server-side (keeps frontend settings). */
export async function clearSessionModel(sessionId = DEFAULT_SESSION_ID): Promise<boolean> {
  const resp = await fetch(
    `${API_BASE}/api/session/clear?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'POST' },
  );
  const body = await asJson<{ cleared: boolean }>(resp);
  return body.cleared;
}
