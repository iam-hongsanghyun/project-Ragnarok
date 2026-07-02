/**
 * PyPSA-Earth network builder (I9) — async job client.
 *
 * Unlike the synchronous importers (`/api/import/run`), building a whole-country
 * network is a long-running queued job: submit a build, poll status, then fetch
 * the ingested workbook fragment. All gated behind server availability
 * (`RAGNAROK_PYPSA_EARTH_DIR` — else `available` is false with setup guidance).
 */
import { API_BASE } from 'lib/constants/config';
import type { WorkbookFragment } from 'lib/api/databases';

export interface PypsaEarthAvailability {
  available: boolean;
  detail: string;
  docs: string;
  dir?: string;
  /** Valid pypsa-earth checkouts found on the server, for one-click selection. */
  candidates?: string[];
}

export interface BuildJobStatus {
  jobId: string;
  status: 'queued' | 'running' | 'done' | 'error' | 'stopped';
  phase: string;
  detail: string;
  error: string | null;
  counts?: Record<string, number>;
  countryIso?: string;
  countryName?: string;
  /** Coarse Snakemake progress (0–100) when available. */
  progress?: number;
  /** Recent Snakemake log lines (tail), streamed while the build runs. */
  log?: string[];
}

export interface BuildRequest {
  countryIso: string;
  countryName?: string;
  horizonYear?: number;
  clusters?: number;
  carriers?: string[];
}

async function j<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const text = await resp.text();
    let msg = text;
    try {
      const body = JSON.parse(text);
      if (body && typeof body.detail === 'string') msg = body.detail;
    } catch { /* not JSON — use the raw text */ }
    throw new Error(msg || `HTTP ${resp.status}`);
  }
  return resp.json() as Promise<T>;
}

export async function checkAvailable(): Promise<PypsaEarthAvailability> {
  return j(await fetch(`${API_BASE}/api/pypsa-earth/available`));
}

/** Point Ragnarok at a pypsa-earth checkout dir (empty string clears it). */
export async function configureEnv(dir: string): Promise<PypsaEarthAvailability> {
  return j(await fetch(`${API_BASE}/api/pypsa-earth/configure`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dir }),
  }));
}

export async function startBuild(req: BuildRequest): Promise<BuildJobStatus> {
  return j(await fetch(`${API_BASE}/api/pypsa-earth/build`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  }));
}

export async function getBuildStatus(jobId: string): Promise<BuildJobStatus> {
  return j(await fetch(`${API_BASE}/api/pypsa-earth/build/${jobId}`));
}

export async function getBuildResult(jobId: string): Promise<{ jobId: string; fragment: WorkbookFragment; counts: Record<string, number> }> {
  return j(await fetch(`${API_BASE}/api/pypsa-earth/build/${jobId}/result`));
}

/** All builds this backend knows about — lets the panel re-attach after a
 *  tab switch / reload instead of losing track of a running build. */
export async function listBuilds(): Promise<{ jobs: BuildJobStatus[] }> {
  return j(await fetch(`${API_BASE}/api/pypsa-earth/builds`));
}

/** Explicitly stop a running build (the ONLY way a build is meant to stop). */
export async function stopBuild(jobId: string): Promise<BuildJobStatus> {
  return j(await fetch(`${API_BASE}/api/pypsa-earth/build/${jobId}/stop`, { method: 'POST' }));
}
