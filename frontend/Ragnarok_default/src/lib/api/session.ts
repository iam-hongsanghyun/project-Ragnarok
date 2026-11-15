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

/**
 * The working-model session this screen shows: `?session=<id>` in its address, else `default`.
 * A host that keeps several sessions side by side (bridge, one per owner) opens the screen on its
 * own; the MCP server reaches the same session through `RAGNAROK_SESSION_ID`.
 */
export const DEFAULT_SESSION_ID: string = (() => {
  try {
    return new URLSearchParams(window.location.search).get('session') || 'default';
  } catch {
    return 'default';
  }
})();

export interface SessionSheetMeta {
  name: string;
  kind: 'static' | 'series';
  rowCount: number;
  columns: string[];
}

/** One row the cost-basis migration converted (an OLD workbook's overnight `capital_cost` moved to
 *  PyPSA's `overnight_cost`). */
export interface CostBasisChangedRow {
  sheet: string;
  name: string;
  extendable: boolean;
  capital_cost_was: number;
  overnight_cost: number;
  discount_rate: number;
  lifetime: number | null;
  lifetimeDefaulted: boolean;
}

/** The one-off cost-basis migration of a workbook written before schema 2, shown to the user once. */
export interface CostBasisMigration {
  fromVersion: number;
  toVersion: number;
  discountRate: number | null;
  discountRateSource: string;
  changedRows: CostBasisChangedRow[];
  /** Annual `e_sum_*` values moved into the RAGNAROK_AnnualBudgets sheet (schema 2 -> 3). */
  budgets?: { component: string; name: string; attribute: string; annual: number }[];
  review: { sheet: string; name: string; reason: string }[];
  notes: string[];
}

export interface SessionMeta {
  sessionId?: string;
  /** Present until the user acknowledges the migration notice. */
  costBasisMigration?: CostBasisMigration;
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
  opts: {
    filename?: string;
    scenarioName?: string;
    sessionId?: string;
    /** 'legacy' = an OLD Ragnarok workbook (no ragnarok_schema_version): the server runs the one-off
     *  cost-basis migration and answers with `costBasisMigration`. Anything else is stamped as current. */
    origin?: 'legacy';
    /** Settings -> Discount rate; used by that migration only when the workbook states none. */
    discountRate?: number;
  } = {},
): Promise<SessionMeta> {
  const resp = await fetch(`${API_BASE}/api/session/model`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      filename: opts.filename ?? '',
      scenarioName: opts.scenarioName ?? '',
      sessionId: opts.sessionId ?? DEFAULT_SESSION_ID,
      origin: opts.origin ?? '',
      discountRate: opts.discountRate ?? null,
    }),
  });
  return asJson<SessionMeta>(resp);
}

/** The user has seen the cost-basis migration notice. */
export async function acknowledgeCostBasisMigration(sessionId = DEFAULT_SESSION_ID): Promise<void> {
  await fetch(`${API_BASE}/api/session/migration/ack?session_id=${encodeURIComponent(sessionId)}`, { method: 'POST' });
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

/** Module-owned wide temporal sheets whose names carry no dash. Mirrors `timeseries.MODULE_SERIES_SHEETS`
 *  (backend/app/timeseries.py): `RAGNAROK_CarrierOutputCap` = snapshot + one MW cap column per carrier;
 *  `RAGNAROK_FuelPrices` = snapshot + one currency/MWh_thermal price column per fuel carrier. */
export const MODULE_SERIES_SHEETS: ReadonlySet<string> = new Set(['RAGNAROK_CarrierOutputCap', 'RAGNAROK_FuelPrices']);

/** A PyPSA time-series sheet is ``<component>-<attribute>`` (e.g. generators-p_max_pu);
 *  ``snapshots`` is the time axis, treated as static. Mirrors the backend rule. */
export function isSeriesSheet(name: string): boolean {
  if (MODULE_SERIES_SHEETS.has(name)) return true;
  // `<list>-<attr>-pw` is a piecewise-curve table (one row per breakpoint): static.
  return name !== 'snapshots' && name.includes('-') && !name.endsWith('-pw');
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

/** One working-model session on the server (`GET /api/sessions`). */
export interface ServerSession {
  id: string;
  filename: string;
  scenarioName: string;
  savedAt: string;
  snapshotCount?: number | null;
  componentCounts: Record<string, number>;
}

/** The sessions on this server that hold a project, newest first. */
export async function listServerSessions(): Promise<ServerSession[]> {
  const resp = await fetch(`${API_BASE}/api/sessions`);
  if (!resp.ok) throw new Error(`Could not list sessions (${resp.status}).`);
  const body = (await resp.json()) as { sessions?: ServerSession[] };
  return Array.isArray(body.sessions) ? body.sessions : [];
}

/** One Ragnarok backend on this machine with its sessions (`GET /api/backends`). */
export interface ServerBackend {
  apiBase: string;
  port: number;
  pid?: number | null;
  dataDir: string;
  /** The backend this screen is talking to. */
  self: boolean;
  sessions: ServerSession[];
  queue: { running: number; queued: number };
  /** Opened from Ragnarok (a working folder): Ragnarok may shut it down. */
  startedFromRagnarok?: boolean;
}

/** Every backend running on this machine, the one this screen talks to first. */
export async function listServerBackends(): Promise<ServerBackend[]> {
  const resp = await fetch(`${API_BASE}/api/backends`);
  if (!resp.ok) throw new Error(`Could not list backends (${resp.status}).`);
  const body = (await resp.json()) as { backends?: ServerBackend[] };
  return Array.isArray(body.backends) ? body.backends : [];
}

/**
 * The address of this screen opened on another session, optionally of another backend.
 * `apiBase` empty = the app's own backend (the `api` parameter is dropped); `default` drops `session`.
 */
export function sessionUrl(sessionId: string, apiBase = '', href: string = window.location.href): string {
  const url = new URL(href);
  if (sessionId === 'default') url.searchParams.delete('session');
  else url.searchParams.set('session', sessionId);
  if (apiBase) url.searchParams.set('api', apiBase);
  else url.searchParams.delete('api');
  return url.toString();
}

/**
 * Stop the solves of a backend: cancel every running and queued job in its queue (they can be re-run from
 * the queue). The backend itself keeps running - an agent using it stays connected. Returns how many were
 * cancelled.
 */
export async function stopBackendSolves(apiBase: string): Promise<number> {
  const base = apiBase || API_BASE;
  const resp = await fetch(`${base}/api/queue`);
  if (!resp.ok) throw new Error(`Could not read the queue (${resp.status}).`);
  const body = (await resp.json()) as { jobs?: Array<{ id: string; status: string }> };
  const active = (body.jobs ?? []).filter((j) => j.status === 'running' || j.status === 'queued');
  let stopped = 0;
  for (const job of active) {
    const cancel = await fetch(`${base}/api/queue/${encodeURIComponent(job.id)}/cancel`, { method: 'POST' });
    if (cancel.ok) stopped += 1;
  }
  return stopped;
}

/** This backend's working folder and the one a plain start uses (`GET /api/data-folder`). */
export interface DataFolderInfo {
  current: string;
  default: string;
  savedInEnvFile: boolean;
  envFile: string;
}

async function jsonOrThrow<T>(resp: Response, what: string): Promise<T> {
  if (!resp.ok) {
    let detail = `${what} (${resp.status})`;
    try {
      const body = (await resp.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch { /* keep the status text */ }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

export async function getDataFolder(): Promise<DataFolderInfo> {
  return jsonOrThrow<DataFolderInfo>(await fetch(`${API_BASE}/api/data-folder`), 'Could not read the working folder');
}

/** Make `path` the working folder of the next plain start (`backend/.env`); empty restores `backend/data`. */
export async function setDefaultDataFolder(path: string): Promise<DataFolderInfo> {
  return jsonOrThrow<DataFolderInfo>(await fetch(`${API_BASE}/api/data-folder`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }),
  }), 'Could not save the default folder');
}

/** The backend working in `path`: the one already there, or one started on it. */
export async function openDataFolder(path: string): Promise<{ apiBase: string; port: number; dataDir: string; started: boolean }> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/backends/open-folder`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }),
  }), 'Could not open the folder');
}

/** Shut down a backend opened from Ragnarok (by port). */
export async function stopServerBackend(port: number): Promise<void> {
  await jsonOrThrow(await fetch(`${API_BASE}/api/backends/stop`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ port }),
  }), 'Could not stop the backend');
}

/** The newest session of a backend that holds a project, else `default`. */
export async function newestSessionOf(apiBase: string): Promise<string> {
  try {
    const resp = await fetch(`${apiBase}/api/sessions`);
    if (!resp.ok) return 'default';
    const body = (await resp.json()) as { sessions?: ServerSession[] };
    return body.sessions?.[0]?.id ?? 'default';
  } catch {
    return 'default';
  }
}

/** Open the system folder picker on this machine (the backend runs here); `null` when cancelled. */
export async function pickDataFolder(start = ''): Promise<string | null> {
  const body = await jsonOrThrow<{ path: string | null }>(await fetch(`${API_BASE}/api/data-folder/pick`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: start }),
  }), 'Could not open the folder picker');
  return body.path;
}
