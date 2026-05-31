/**
 * Browser-direct importer client.
 *
 * The Data view fetches and converts external data **in the browser** —
 * the backend has no `importers/` package and no `/api/import/*` routes.
 * The functions below delegate to `src/features/data/databases/registry.ts`
 * and the per-database TypeScript modules under that directory.
 *
 * The JSON shapes (DatabaseMeta, PreviewSummary, WorkbookFragment, …) are
 * preserved from when the importers lived on the backend so the rest of
 * the Data view code (FilterPanel, CategoryDatabaseList, mergeWorkbookFragment)
 * needs no rework.
 */

import {
  fetchCountryBoundaries as fetchCountryBoundariesLocal,
  getModule,
  listCountries as listCountriesLocal,
  listDatabases as listDatabasesLocal,
  resolveRegion,
} from 'lib/importers/registry';
import { defaultConvertOptions } from 'lib/importers/types';

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
  /** `"global"` for sources that work for any country, or a list of
   *  ISO-A3 codes when the upstream only covers a subset (e.g. OPSD = EU). */
  country_coverage?: string[] | 'global';
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

// ── Browser-direct entry points ─────────────────────────────────────────────
//
// The four functions below are pure wrappers around the in-process registry
// in `src/features/data/databases/registry.ts`. They keep the function names
// the Data view already calls, so the rewire was a one-import swap.

export async function listDatabases(): Promise<DatabaseMeta[]> {
  return listDatabasesLocal();
}

export async function listCountries(): Promise<CountryMeta[]> {
  return listCountriesLocal();
}

export async function fetchCountryBoundaries(): Promise<GeoJSONFeatureCollection> {
  return fetchCountryBoundariesLocal();
}

export interface RunImportRequest {
  databaseId: string;
  countryIso: string;
  filters: Record<string, unknown>;
  convertOptions?: Record<string, unknown>;
}

/**
 * One-trip import: returns both the preview summary AND the workbook
 * fragment. The flow lives entirely in the browser — fetch from upstream,
 * preview, convert, hand back. The caller renders the preview in the right
 * rail and holds the fragment until the user clicks Add to workbook.
 *
 * Errors propagate as thrown `Error`s, identical to the old HTTP path.
 */
export async function runImport(req: RunImportRequest): Promise<RunImportResponse> {
  const mod = getModule(req.databaseId);
  const region = await resolveRegion(req.countryIso);
  const options = { ...defaultConvertOptions, ...(req.convertOptions || {}) };
  const result = await mod.fetch(region, req.filters);
  const preview = mod.preview(result);
  const fragment = mod.toSheets(result, options);
  return {
    database_id: req.databaseId,
    country_iso: region.countryIso,
    preview,
    fragment,
  };
}
