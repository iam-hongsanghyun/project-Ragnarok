/**
 * Importer HTTP client.
 *
 * The Data view's entire outside world is the backend's `/api/import/*`
 * endpoints. The browser sends a filter blob (+ any BYOK API keys) and
 * the backend fetches the upstream, converts it, and returns the preview
 * + workbook fragment. No third-party host is ever contacted from the
 * browser — heavy datasets, CORS-blocked sources, and per-user keys are
 * all handled server-side.
 *
 * The JSON shapes (DatabaseMeta, PreviewSummary, WorkbookFragment, …)
 * match what the backend serves, so the rest of the Data view
 * (FilterPanel, CategoryDatabaseList, mergeWorkbookFragment) needs no
 * rework.
 */

import { API_BASE } from 'lib/constants';
import { collectSecretsFor } from 'lib/api/secrets';

export type FilterKind = 'number' | 'select' | 'multiselect' | 'range' | 'toggle' | 'date';

export interface FilterOption {
  value: string | number | boolean;
  label: string;
}

export interface FilterSchema {
  id: string;
  label: string;
  kind: FilterKind;
  default?: unknown;
  options?: FilterOption[];
  /** Numeric min for `number` / `range`; ISO YYYY-MM-DD for `date`. */
  min?: number | string;
  /** Numeric max for `number` / `range`; ISO YYYY-MM-DD for `date`. */
  max?: number | string;
  step?: number;
  unit?: string;
  description?: string;
}

export type ImporterCategory = 'transmission' | 'generation' | 'demand' | string;

export interface DatabaseMeta {
  id: string;
  /** Full name — shown in the right rail's header and the metadata block. */
  name: string;
  /** Short label — what the left-rail tree leaf displays. Falls back to
   *  `name` when absent. Keep this under ~16 chars so it fits in the
   *  narrow tree column without truncation. */
  short_name?: string;
  category: ImporterCategory;
  /** Optional second-level grouping inside `category`. Empty means the
   * database sits directly under the category in the tree. */
  subcategory?: string;
  license: string;
  homepage: string;
  version_hint: string;
  targets: string[];
  filters: FilterSchema[];
  available: boolean;
  unavailable_reason?: string;
  description?: string;
  /** `"global"` for sources that work for any country, or a list of
   *  ISO-A3 codes when the upstream only covers a subset (e.g. OPSD = EU). */
  country_coverage?: string[] | 'global';
  /** Names of user-supplied API keys this database needs (BYOK). The
   *  frontend collects them from the Settings store and ships them in the
   *  `/api/import/run` body; the backend uses them per-request only. */
  requires_secrets?: string[];
}

export interface CountryMeta {
  iso: string;
  name: string;
  bbox: [number, number, number, number];   // [minLon, minLat, maxLon, maxLat]
  centroid: [number, number];                // [lon, lat]
}

export interface PreviewSummary {
  counts: Record<string, number>;
  samples: Record<string, Array<Record<string, unknown>>>;
  notes: string[];
  overlay?: GeoJSONFeatureCollection | null;
}

/**
 * Combined response from /api/import/run. Carries both the preview
 * (counts / samples / overlay) and the full WorkbookFragment so the
 * frontend can render the preview in the right rail immediately and hold
 * the fragment in React state until the user clicks "Add to workbook" —
 * no second network call.
 */
export interface RunImportResponse {
  database_id: string;
  country_iso: string;
  preview: PreviewSummary;
  fragment: WorkbookFragment;
}

export interface ProvenanceRow {
  database_id: string;
  country_iso: string;
  country_name: string;
  filters_json: string;
  convert_options_json: string;
  fetch_timestamp: string;
  row_counts_json: string;
}

export interface WorkbookFragment {
  sheets: Record<string, Array<Record<string, unknown>>>;
  provenance?: ProvenanceRow;
  /** Ordered ISO-`T` snapshot strings the importer's time-series cover.
   *  When present the frontend merger unions this with the workbook's
   *  existing snapshot range. Static-only sources omit the field. */
  snapshots?: string[];
}

export interface GeoJSONFeature {
  type: 'Feature';
  geometry: { type: string; coordinates: unknown };
  properties: Record<string, unknown> | null;
}

export interface GeoJSONFeatureCollection {
  type: 'FeatureCollection';
  features: GeoJSONFeature[];
}

// ── Backend HTTP entry points ────────────────────────────────────────────────
//
// All four hit the backend's /api/import/* router. API_BASE is '' in dev
// (CRA proxies /api to the backend) and the deployed origin in prod.

async function jsonOrThrow<T>(resp: Response, action: string): Promise<T> {
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body?.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`${action} failed (${resp.status}): ${detail}`);
  }
  return (await resp.json()) as T;
}

export async function listDatabases(): Promise<DatabaseMeta[]> {
  const resp = await fetch(`${API_BASE}/api/import/databases`);
  const body = await jsonOrThrow<{ databases: DatabaseMeta[] }>(resp, 'list databases');
  return body.databases;
}

export async function listCountries(): Promise<CountryMeta[]> {
  const resp = await fetch(`${API_BASE}/api/import/countries`);
  const body = await jsonOrThrow<{ countries: CountryMeta[] }>(resp, 'list countries');
  return body.countries;
}

export async function fetchCountryBoundaries(): Promise<GeoJSONFeatureCollection> {
  const resp = await fetch(`${API_BASE}/api/import/boundaries/countries.geojson`);
  return jsonOrThrow<GeoJSONFeatureCollection>(resp, 'fetch country boundaries');
}

export interface RunImportRequest {
  databaseId: string;
  countryIso: string;
  filters: Record<string, unknown>;
  convertOptions?: Record<string, unknown>;
  /** Names of the API keys this database declares it needs; collected
   *  from the browser secret store and sent in the request body. */
  requiresSecrets?: string[];
}

/**
 * One-trip import: POST the filter blob (+ any BYOK keys) to the backend,
 * which fetches the upstream, converts it, and returns the preview
 * summary AND the workbook fragment together. The caller renders the
 * preview in the right rail and holds the fragment until the user clicks
 * Add to workbook — no second network call.
 */
export async function runImport(req: RunImportRequest): Promise<RunImportResponse> {
  const secrets = collectSecretsFor(req.requiresSecrets ?? []);
  const resp = await fetch(`${API_BASE}/api/import/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      database_id: req.databaseId,
      country_iso: req.countryIso,
      filters: req.filters,
      convert_options: req.convertOptions ?? {},
      secrets,
    }),
  });
  return jsonOrThrow<RunImportResponse>(resp, 'run import');
}
