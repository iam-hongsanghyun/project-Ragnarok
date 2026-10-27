/** P31 — `POST /api/statistics/query`: one parametrised `n.statistics` metric on a stored run. */
import { API_BASE } from 'lib/constants';
import type { StatisticsQueryResponse } from 'lib/types';

export interface StatisticsQueryParams {
  runName: string;
  metric: string;
  groupby?: string[];
  busCarrier?: string[];
  /** 'sum' | 'mean', or false for a time series. */
  aggregateTime: string | boolean;
  atPort: boolean;
  components?: string[];
  carrier?: string[];
}

/** Split a comma/space separated field into trimmed, non-empty tokens. */
export function splitList(text: string): string[] {
  return text.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean);
}

/** Request body: empty lists are omitted so the backend applies PyPSA's defaults. */
export function buildStatisticsBody(p: StatisticsQueryParams): Record<string, unknown> {
  const body: Record<string, unknown> = {
    runName: p.runName,
    metric: p.metric,
    aggregateTime: p.aggregateTime,
    atPort: p.atPort,
  };
  if (p.groupby?.length) body.groupby = p.groupby;
  if (p.busCarrier?.length) body.busCarrier = p.busCarrier;
  if (p.components?.length) body.components = p.components;
  if (p.carrier?.length) body.carrier = p.carrier;
  return body;
}

export async function postStatisticsQuery(p: StatisticsQueryParams): Promise<StatisticsQueryResponse> {
  const resp = await fetch(`${API_BASE}/api/statistics/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(buildStatisticsBody(p)),
  });
  if (!resp.ok) {
    let detail = '';
    try { detail = (await resp.json()).detail ?? ''; } catch { /* non-JSON body */ }
    throw new Error(typeof detail === 'string' && detail ? detail : `Statistics query failed (HTTP ${resp.status})`);
  }
  return resp.json();
}
