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

/**
 * A single dataset — one fetchable unit. Many datasets can belong to one
 * source (`source_id`); the tree groups by source and the user multi-selects
 * datasets to fetch together (Country → Database → Datasets).
 */
export interface DatabaseMeta {
  id: string;
  /** Full name — shown in the right rail's header and the metadata block. */
  name: string;
  /** Short label — the dataset's name in the tree (e.g. "Network",
   *  "Demand profile"). Falls back to `name` when absent. */
  short_name?: string;
  /** The source this dataset belongs to (e.g. "kpg193"). Singletons use their
   *  own `id`. The tree groups by this. */
  source_id?: string;
  /** Human label for the source (e.g. "KPG193 — Korean reference grid"). */
  source_label?: string;
  /** Other dataset ids this one references; auto-included by the backend when
   *  fetched so a profile is never imported without its static anchor. */
  depends_on?: string[];
  category: ImporterCategory;
  /** Optional second-level grouping inside `category`. */
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
   *  ISO-A3 codes when the upstream only covers a subset. */
  country_coverage?: string[] | 'global';
  /** Names of user-supplied API keys this dataset needs (BYOK). */
  requires_secrets?: string[];
}

/**
 * A source groups the datasets a user can multi-select and fetch together.
 * `common_filters` are the settings declared by ≥2 of the source's datasets
 * (e.g. version / year / profile window); the right rail renders them once as
 * a shared "Common settings" group and each dataset's remaining filters
 * (`filters` minus `common_filter_ids`) under that dataset's own group.
 */
export interface Source {
  source_id: string;
  source_label: string;
  category: ImporterCategory;
  categories: string[];
  country_coverage?: string[] | 'global';
  common_filter_ids: string[];
  common_filters: FilterSchema[];
  datasets: DatabaseMeta[];
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
  source_id: string;
  /** The datasets actually fetched (the user's selection expanded with
   *  dependencies, in dependency-first order). */
  dataset_ids: string[];
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

export async function listSources(): Promise<Source[]> {
  const resp = await fetch(`${API_BASE}/api/import/sources`);
  const body = await jsonOrThrow<{ sources: Source[] }>(resp, 'list sources');
  return body.sources;
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
  /** The datasets the user multi-selected (same source). The backend expands
   *  dependencies and fetches them together into one aligned fragment. */
  datasetIds: string[];
  countryIso: string;
  filters: Record<string, unknown>;
  convertOptions?: Record<string, unknown>;
  /** Union of the API-key names the selected datasets declare; collected from
   *  the browser secret store and sent in the request body. */
  requiresSecrets?: string[];
}

/**
 * One-trip import: POST the selected dataset ids + shared filter blob (+ any
 * BYOK keys) to the backend, which fetches each dataset, combines them into
 * one aligned, PyPSA-ready fragment, and returns the preview + fragment
 * together. The caller renders the preview and holds the fragment until the
 * user clicks Add to workbook — no second network call.
 */
export async function runImport(req: RunImportRequest): Promise<RunImportResponse> {
  const secrets = collectSecretsFor(req.requiresSecrets ?? []);
  const resp = await fetch(`${API_BASE}/api/import/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      dataset_ids: req.datasetIds,
      country_iso: req.countryIso,
      filters: req.filters,
      convert_options: req.convertOptions ?? {},
      secrets,
    }),
  });
  return jsonOrThrow<RunImportResponse>(resp, 'run import');
}
