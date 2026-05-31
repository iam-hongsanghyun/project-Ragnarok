/**
 * Browser-side importer module contract.
 *
 * Each database directory under `databases/<id>/` exports a `DatabaseModule`
 * matching this interface — its own meta, fetch, preview, and convert. The
 * registry composes them into a list the Data view consumes. Conversion lives
 * here in the browser; the backend never sees external-data requests.
 *
 * Mirrors `backend/app/importers/protocol.py` (now deleted in favour of this
 * browser-direct pipeline), so the wire-shape used by the Data view is the
 * same `WorkbookFragment` / `PreviewSummary` shape it always was.
 */
import type {
  DatabaseMeta,
  GeoJSONFeatureCollection,
  PreviewSummary,
  WorkbookFragment,
} from 'lib/api/databases';

/**
 * Geographic selection passed into every fetch. The polygon is the
 * Natural Earth country polygon for the chosen ISO-A3 code. Modules use
 * `polygon` for point-in-polygon culling and `bbox` for cheap upstream
 * pre-filters (e.g. Overpass `poly:`, CSV bbox skip).
 */
export interface Region {
  countryIso: string;
  countryName: string;
  /** Single Polygon or MultiPolygon in WGS84 lat/lon. Always GeoJSON shape. */
  polygon: GeoJSONPolygonLike;
  /** [minLon, minLat, maxLon, maxLat], derived from `polygon`. */
  bbox: [number, number, number, number];
}

export type GeoJSONPolygonLike =
  | { type: 'Polygon'; coordinates: number[][][] }
  | { type: 'MultiPolygon'; coordinates: number[][][][] };

/** Untyped container the converter consumes; shape is per-module. */
export interface FetchResult<P = unknown> {
  databaseId: string;
  region: Region;
  filters: Record<string, unknown>;
  payload: P;
  notes?: string[];
}

/** Cross-database conversion knobs — currently a small set, kept for parity
 *  with the previous backend `ConvertOptions`. */
export interface ConvertOptions {
  createBusesForPlants?: boolean;
  plantBusSuffix?: string;
  plantBusSnapKm?: number;
}

export const defaultConvertOptions: Required<ConvertOptions> = {
  createBusesForPlants: true,
  plantBusSuffix: '_bus',
  plantBusSnapKm: 25.0,
};

/**
 * The browser-side per-database module. Every module's `meta` is also the
 * exact JSON shape the existing right-rail form expects — no extra mapping.
 */
export interface DatabaseModule<P = unknown> {
  meta: DatabaseMeta;
  fetch: (region: Region, filters: Record<string, unknown>) => Promise<FetchResult<P>>;
  preview: (result: FetchResult<P>) => PreviewSummary;
  toSheets: (
    result: FetchResult<P>,
    options: Required<ConvertOptions>,
  ) => WorkbookFragment;
}

/** Convenience aggregator returned by the registry. */
export interface RegistryEntry {
  module: DatabaseModule<unknown>;
  /** Same object as `module.meta`, exposed for the Data view's list-databases
   *  bootstrap call so it never has to read the module to render the rail. */
  meta: DatabaseMeta;
}

// ── Re-exports used widely by modules ───────────────────────────────────────

export type { DatabaseMeta, GeoJSONFeatureCollection, PreviewSummary, WorkbookFragment };
