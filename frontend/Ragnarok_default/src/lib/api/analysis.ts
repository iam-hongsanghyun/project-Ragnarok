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
