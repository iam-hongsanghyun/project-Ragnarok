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
}

export interface BuildJobStatus {
  jobId: string;
  status: 'queued' | 'running' | 'done' | 'error';
  phase: string;
  detail: string;
  error: string | null;
  counts?: Record<string, number>;
}

export interface BuildRequest {
  countryIso: string;
  countryName?: string;
  horizonYear?: number;
  clusters?: number;
  carriers?: string[];
}

async function j<T>(resp: Response): Promise<T> {
  if (!resp.ok) throw new Error((await resp.text()) || `HTTP ${resp.status}`);
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
