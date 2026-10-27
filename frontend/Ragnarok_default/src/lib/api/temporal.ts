/** P35 — `POST /api/transform/temporal`: PyPSA native temporal clustering of the session model. */
import { API_BASE } from 'lib/constants';
import { DEFAULT_SESSION_ID } from './session';
import type { WorkbookModel } from 'lib/types';

export type TemporalMethod = 'resample' | 'downsample' | 'segment';

export interface TemporalOptions {
  method: TemporalMethod;
  /** resample: pandas offset such as "3h" or "1D". */
  offset?: string;
  dropLeapDay?: boolean;
  /** downsample: keep every stride-th snapshot (>= 2). */
  stride?: number;
  /** segment: number of segments (needs the optional tsam package). */
  numSegments?: number;
  solver?: string;
}

export interface TemporalCounts { snapshots: number; buses: number; weightedHours: number }

export interface TemporalResult {
  model: WorkbookModel;
  method: TemporalMethod;
  before: TemporalCounts;
  after: TemporalCounts;
}

/** Request body carrying only the parameters the chosen method reads. */
export function buildTemporalBody(o: TemporalOptions, sessionId: string = DEFAULT_SESSION_ID): Record<string, unknown> {
  const body: Record<string, unknown> = { sessionId, method: o.method };
  if (o.method === 'resample') {
    body.offset = o.offset;
    body.dropLeapDay = !!o.dropLeapDay;
  } else if (o.method === 'downsample') {
    body.stride = o.stride;
  } else {
    body.numSegments = o.numSegments;
    if (o.solver) body.solver = o.solver;
  }
  return body;
}

export async function postTemporalCluster(o: TemporalOptions, sessionId: string = DEFAULT_SESSION_ID): Promise<TemporalResult> {
  const resp = await fetch(`${API_BASE}/api/transform/temporal`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(buildTemporalBody(o, sessionId)),
  });
  if (!resp.ok) {
    // 400 carries the reason (e.g. "segment needs the optional 'tsam' package"): show it verbatim.
    let detail = '';
    try { detail = (await resp.json()).detail ?? ''; } catch { /* non-JSON body */ }
    throw new Error(typeof detail === 'string' && detail ? detail : `Temporal clustering failed (HTTP ${resp.status})`);
  }
  return resp.json();
}
