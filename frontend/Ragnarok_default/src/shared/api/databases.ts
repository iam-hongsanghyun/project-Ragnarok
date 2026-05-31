/**
 * Typed client for the Data view's external-data importer endpoints.
 *
 * The backend lives under `backend/app/importers/`; this client only walks
 * the public-facing JSON shapes. See `docs/TODO.md` items `I1` / `I2`.
 */

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
  name: string;
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

// ── HTTP helpers ─────────────────────────────────────────────────────────────

async function jsonOrThrow<T>(resp: Response, action: string): Promise<T> {
  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    throw new Error(`${action} failed (${resp.status}): ${text || resp.statusText}`);
  }
  return (await resp.json()) as T;
}

// ── Public endpoints ─────────────────────────────────────────────────────────

export async function listDatabases(): Promise<DatabaseMeta[]> {
  const resp = await fetch('/api/import/databases');
  const body = await jsonOrThrow<{ databases: DatabaseMeta[] }>(resp, 'list databases');
  return body.databases;
}

export async function listCountries(): Promise<CountryMeta[]> {
  const resp = await fetch('/api/import/countries');
  const body = await jsonOrThrow<{ countries: CountryMeta[] }>(resp, 'list countries');
  return body.countries;
}

export async function fetchCountryBoundaries(): Promise<GeoJSONFeatureCollection> {
  const resp = await fetch('/api/import/boundaries/countries.geojson');
  return jsonOrThrow<GeoJSONFeatureCollection>(resp, 'fetch country boundaries');
}

export interface RunImportRequest {
  databaseId: string;
  countryIso: string;
  filters: Record<string, unknown>;
  convertOptions?: Record<string, unknown>;
}

/**
 * One-trip import: returns both the preview summary AND the workbook
 * fragment. Caller renders the preview in the right rail and holds the
 * fragment until the user clicks Add to workbook — no second network call.
 */
export async function runImport(req: RunImportRequest): Promise<RunImportResponse> {
  const resp = await fetch('/api/import/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      database_id: req.databaseId,
      country_iso: req.countryIso,
      filters: req.filters,
      convert_options: req.convertOptions || {},
    }),
  });
  return jsonOrThrow<RunImportResponse>(resp, 'run import');
}
