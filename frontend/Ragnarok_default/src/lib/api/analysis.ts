/**
 * Server-side import analysis (X2) — column statistics.
 *
 * The backend crunches the full sheet and returns only the per-column summary,
 * so the browser renders KPIs without processing thousands of rows.
 */
import { API_BASE } from 'lib/constants';

export interface NumericColumnStats {
  name: string;
  kind: 'numeric';
  count: number;
  nulls: number;
  min: number;
  max: number;
  mean: number;
  median: number;
  std: number;
  sum: number;
  p25: number;
  p75: number;
  histogram: { counts: number[]; edges: number[] };
}

export interface CategoricalColumnStats {
  name: string;
  kind: 'categorical';
  count: number;
  nulls: number;
  distinct: number;
  top: { value: string; count: number }[];
}

export type ColumnStats = NumericColumnStats | CategoricalColumnStats;

export interface SheetStats {
  sheet: string;
  kind?: string;
  total: number;
  columns: ColumnStats[];
}

/** Analyser chart-series derived server-side (X2) — duration curve, daily
 *  profile, or grouped aggregate — so the browser needn't crunch the whole sheet. */
export interface DurationResult { mode: 'duration'; column: string; values: number[] }
export interface DailyProfileResult { mode: 'daily_profile'; hours: number[]; series: { key: string; values: number[] }[] }
export interface GroupedResult { mode: 'grouped'; groupBy: string; value: string; agg: string; bars: { label: string; value: number }[] }

async function deriveGet(sheet: string, params: Record<string, string>, sessionId: string): Promise<any> {
  const q = new URLSearchParams({ ...params, session_id: sessionId }).toString();
  const resp = await fetch(`${API_BASE}/api/session/sheet/${encodeURIComponent(sheet)}/derive?${q}`);
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json())?.detail ?? detail; } catch { /* non-JSON */ }
    throw new Error(`Derive failed (${resp.status}): ${detail}`);
  }
  return resp.json();
}

export const fetchDurationCurve = (sheet: string, column: string, maxPoints = 800, sessionId = 'default') =>
  deriveGet(sheet, { mode: 'duration', column, maxPoints: String(maxPoints) }, sessionId) as Promise<DurationResult>;

export const fetchDailyProfile = (sheet: string, columns: string[], sessionId = 'default') =>
  deriveGet(sheet, { mode: 'daily_profile', columns: columns.join(',') }, sessionId) as Promise<DailyProfileResult>;

export const fetchGroupedAggregate = (sheet: string, groupBy: string, column: string, agg = 'sum', sessionId = 'default') =>
  deriveGet(sheet, { mode: 'grouped', groupBy, column, agg }, sessionId) as Promise<GroupedResult>;

export async function fetchColumnStats(sheet: string, sessionId = 'default'): Promise<SheetStats> {
  const resp = await fetch(
    `${API_BASE}/api/session/sheet/${encodeURIComponent(sheet)}/stats?session_id=${encodeURIComponent(sessionId)}`,
  );
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json())?.detail ?? detail; } catch { /* non-JSON */ }
    throw new Error(`Column stats failed (${resp.status}): ${detail}`);
  }
  return resp.json();
}
