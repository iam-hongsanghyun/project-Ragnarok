/**
 * Network-operation clients (`backend/app/routers/optimise.py`, `operations_modules.py`): topology / consistency
 * analysis, snapshot-window and bus slice, network merge, and the written test-run sample. Each acts on the session
 * model, so the caller pushes the working model first (`onSessionSync`).
 */
import { API_BASE } from 'lib/constants';
import { DEFAULT_SESSION_ID } from './session';
import type { SamplingConfig, WorkbookModel } from 'lib/types';

export const ANALYSIS_PARTS = ['subnetworks', 'ptdf', 'bodf', 'cycles', 'adjacency', 'incidence'] as const;
export type AnalysisPart = (typeof ANALYSIS_PARTS)[number];
export type CycleBasisMethod = 'bfs-refined' | 'paton';

/** A labelled matrix, or the reason the backend left it out / failed to build it. */
export interface MatrixPayload {
  rows?: string[];
  columns?: string[];
  data?: number[][];
  shape?: number[];
  omitted?: string;
  error?: string;
}

export interface SubNetworkInfo {
  name: string;
  carrier: string;
  buses: string[];
  branches: string[];
  slackBus: string;
  slackGenerator: string;
  ptdf?: MatrixPayload;
  bodf?: MatrixPayload;
}

export interface NetworkAnalysis {
  parts: string[];
  cycleBasisMethod: string;
  subNetworks?: SubNetworkInfo[];
  cycleMatrix?: MatrixPayload;
  adjacency?: MatrixPayload;
  incidence?: MatrixPayload;
}

export interface ConsistencyReport {
  valid: boolean;
  errors: string[];
  warnings: string[];
  strict: string[] | null;
}

export interface Counts { snapshots: number; buses: number; weightedHours: number }

export interface TransformResult {
  model: WorkbookModel;
  before: Counts;
  after: Counts;
  /** merge only: what was merged in. */
  merged?: Counts;
}

export interface SampleResult {
  model: WorkbookModel;
  notes: string[];
  before: { snapshots: number };
  after: { snapshots: number };
  factor: number;
}

async function post<T>(path: string, body: Record<string, unknown>, fallback: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let detail = '';
    try { detail = (await resp.json()).detail ?? ''; } catch { /* non-JSON body */ }
    throw new Error(typeof detail === 'string' && detail ? detail : `${fallback} (HTTP ${resp.status})`);
  }
  return resp.json() as Promise<T>;
}

export function postNetworkAnalysis(
  include: AnalysisPart[], cycleBasisMethod: CycleBasisMethod, sessionId: string = DEFAULT_SESSION_ID,
): Promise<NetworkAnalysis> {
  return post('/api/analysis/network', { sessionId, include, cycleBasisMethod }, 'Network analysis failed');
}

export function postConsistency(
  strictAll: boolean, checkDtypes: boolean, sessionId: string = DEFAULT_SESSION_ID,
): Promise<ConsistencyReport> {
  return post('/api/analysis/consistency', { sessionId, strict: strictAll ? ['all'] : null, checkDtypes }, 'Consistency check failed');
}

export interface SliceRequest { start?: string; end?: string; buses?: string[] }

/** Window ends are snapshot labels (inclusive); an empty field leaves that side open. */
export function buildSliceBody(r: SliceRequest, sessionId: string = DEFAULT_SESSION_ID): Record<string, unknown> {
  const body: Record<string, unknown> = { sessionId };
  if (r.start?.trim()) body.start = r.start.trim();
  if (r.end?.trim()) body.end = r.end.trim();
  if (r.buses && r.buses.length > 0) body.buses = r.buses;
  return body;
}

export function postSlice(r: SliceRequest, sessionId: string = DEFAULT_SESSION_ID): Promise<TransformResult> {
  return post('/api/transform/slice', buildSliceBody(r, sessionId), 'Slice failed');
}

export interface MergeRequest {
  source: { otherRun: string } | { otherSessionId: string };
  componentsToSkip?: string[];
  withTime: boolean;
}

export function postMerge(r: MergeRequest, sessionId: string = DEFAULT_SESSION_ID): Promise<TransformResult> {
  const body: Record<string, unknown> = { sessionId, ...r.source, withTime: r.withTime };
  if (r.componentsToSkip && r.componentsToSkip.length > 0) body.componentsToSkip = r.componentsToSkip;
  return post('/api/transform/merge', body, 'Merge failed');
}

export interface SampleRequest { sampling: SamplingConfig; snapshotStart?: number; snapshotCount?: number }

/** Sampling is always switched on for this action: writing the sample is the point. */
export function buildSampleBody(r: SampleRequest, sessionId: string = DEFAULT_SESSION_ID): Record<string, unknown> {
  const options: Record<string, unknown> = { samplingConfig: { ...r.sampling, enabled: true } };
  if (r.snapshotStart !== undefined) options.snapshotStart = r.snapshotStart;
  if (r.snapshotCount !== undefined) options.snapshotCount = r.snapshotCount;
  return { sessionId, options };
}

export function postSample(r: SampleRequest, sessionId: string = DEFAULT_SESSION_ID): Promise<SampleResult> {
  return post('/api/transform/sample', buildSampleBody(r, sessionId), 'Sampling failed');
}

/** One line for the status bar / preview: what a transform did to the model. */
export function describeChange(before: Counts, after: Counts): string {
  return `${before.snapshots} to ${after.snapshots} snapshots, ${before.buses} to ${after.buses} buses, `
    + `weighted hours ${before.weightedHours} to ${after.weightedHours}`;
}
