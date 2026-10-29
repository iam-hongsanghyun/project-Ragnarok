/** Importer registry, upstream health and the import provenance log (`backend/app/routers/importers.py`). */
import { API_BASE } from 'lib/constants';

export interface RegistryEntry {
  id: string;
  name: string;
  short_name?: string;
  source_id?: string;
  source_label?: string;
  category: string;
  license: string;
  version_hint: string;
  available: boolean;
  unavailable_reason?: string;
  requires_secrets?: string[];
}

export interface SourceHealth {
  ok: boolean;
  status: number | null;
  latencyMs: number;
  checkedAt: string;
  error?: string;
}

/** One line of the append-only provenance log; `filters` and `rowCounts` are JSON strings. */
export interface ProvenanceEntry {
  version: number;
  recordedAt: string;
  sourceId: string;
  datasetIds: string[];
  databaseId: string;
  countryIso: string;
  countryName: string;
  filters: string;
  fetchedAt: string;
  rowCounts: string;
}

async function getJson<T>(path: string, what: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`);
  if (!resp.ok) {
    let detail = '';
    try { detail = (await resp.json()).detail ?? ''; } catch { /* non-JSON body */ }
    throw new Error(typeof detail === 'string' && detail ? detail : `${what} failed (HTTP ${resp.status})`);
  }
  return resp.json() as Promise<T>;
}

export async function listImportDatabases(): Promise<RegistryEntry[]> {
  return (await getJson<{ databases: RegistryEntry[] }>('/api/import/databases', 'Database registry')).databases;
}

/** Probes every upstream (a few seconds); the result is keyed by source id. */
export async function getImportHealth(): Promise<Record<string, SourceHealth>> {
  return (await getJson<{ sources: Record<string, SourceHealth> }>('/api/import/health', 'Source health')).sources;
}

export async function getImportProvenance(limit = 50): Promise<ProvenanceEntry[]> {
  return (await getJson<{ imports: ProvenanceEntry[] }>(`/api/import/provenance?limit=${limit}`, 'Import provenance')).imports;
}
