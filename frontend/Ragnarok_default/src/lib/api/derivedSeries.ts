/**
 * Server-side derived chart-series (X1).
 *
 * Fetch an aggregated system chart series for a stored run computed on the
 * backend (dispatch by carrier, total load, mean nodal price), so the browser
 * doesn't aggregate thousands of raw per-asset columns for a large network.
 */
import { API_BASE } from 'lib/constants';

export type DerivedMetric = 'dispatch_by_carrier' | 'load' | 'system_price';

export interface DerivedSeries {
  metric: DerivedMetric;
  indexCol: string;
  labels: (string | number)[];
  series: { key: string; values: number[] }[];
  window: { start: number; end: number };
  total: number;
}

export async function fetchDerivedSeries(
  run: string,
  metric: DerivedMetric,
  opts: { start?: number; end?: number; maxPoints?: number } = {},
): Promise<DerivedSeries> {
  const q = new URLSearchParams();
  if (opts.start != null) q.set('start', String(opts.start));
  if (opts.end != null) q.set('end', String(opts.end));
  if (opts.maxPoints != null) q.set('maxPoints', String(opts.maxPoints));
  const qs = q.toString();
  const url = `${API_BASE}/api/runs/${encodeURIComponent(run)}/derived/${metric}${qs ? `?${qs}` : ''}`;
  const resp = await fetch(url);
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json())?.detail ?? detail; } catch { /* non-JSON */ }
    throw new Error(`Derived series failed (${resp.status}): ${detail}`);
  }
  return resp.json();
}
