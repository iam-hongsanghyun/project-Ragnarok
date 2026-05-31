/**
 * Browser-direct importer registry.
 *
 * Every database module is a TypeScript object implementing `DatabaseModule`.
 * The Data view bootstraps via:
 *
 *   const dbs       = listDatabases();              // metas, for the rails
 *   const countries = listCountries();              // ISO-A3 + name + centroid
 *   const region    = await resolveRegion(iso);     // polygon for fetch + cull
 *   const result    = await mod.fetch(region, ...); // upstream → parsed
 *   const preview   = mod.preview(result);          // counts + samples + overlay
 *   const fragment  = mod.toSheets(result, opts);   // workbook rows
 *
 * No backend round-trip. Conversion runs in the browser; the only network
 * traffic per import is the upstream fetch itself.
 *
 * Boundaries come from Natural Earth 10m Admin-0 (public domain), fetched
 * once per session from a CORS-friendly raw GitHub URL and held in module
 * scope. The same `FeatureCollection` is reused for the Leaflet basemap.
 */
import type {
  CountryMeta,
  DatabaseMeta,
  GeoJSONFeatureCollection,
} from '../../../shared/api/databases';
import type { DatabaseModule, GeoJSONPolygonLike, Region } from './types';

import { osmModule } from './osm';
import { wriGppdModule } from './wri_gppd';
import { worldbankDemandModule } from './worldbank_demand';

// ── Module list (order = display order in the tree) ─────────────────────────

// Modules declare their own payload type for internal type-checking inside
// each module file. The registry doesn't care about the payload — it just
// chains fetch → preview → toSheets — so it stores them as opaque values.
const MODULES: DatabaseModule<unknown>[] = [
  osmModule as DatabaseModule<unknown>,
  wriGppdModule as DatabaseModule<unknown>,
  worldbankDemandModule as DatabaseModule<unknown>,
];

// ── Module access ───────────────────────────────────────────────────────────

export function listDatabases(): DatabaseMeta[] {
  return MODULES.map((m) => m.meta);
}

export function getModule(id: string): DatabaseModule<unknown> {
  const m = MODULES.find((mod) => mod.meta.id === id);
  if (!m) throw new Error(`unknown database id: ${id}`);
  return m;
}

// ── Country boundaries (Natural Earth) ──────────────────────────────────────

const BOUNDARIES_URL =
  process.env.REACT_APP_RAGNAROK_BOUNDARIES_URL ||
  'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson';

// Same key precedence as the previous backend region.py.
const ISO_KEYS = ['ADM0_A3', 'ISO_A3_EH', 'ISO_A3', 'SOV_A3'] as const;
const NAME_KEYS = ['ADMIN', 'NAME', 'NAME_LONG', 'SOVEREIGNT'] as const;

interface FeatureLike {
  type: 'Feature';
  geometry: GeoJSONPolygonLike | { type: string; coordinates: unknown };
  properties: Record<string, unknown> | null;
}

interface CountryEntry {
  iso: string;
  name: string;
  polygon: GeoJSONPolygonLike;
  bbox: [number, number, number, number];
  centroid: [number, number];
}

let _geojson: GeoJSONFeatureCollection | null = null;
let _index: Map<string, CountryEntry> | null = null;
let _fetchPromise: Promise<void> | null = null;

function featureIso(props: Record<string, unknown> | null): string | null {
  if (!props) return null;
  for (const k of ISO_KEYS) {
    const v = props[k];
    if (typeof v === 'string' && v && v !== '-99') return v.toUpperCase();
  }
  return null;
}

function featureName(props: Record<string, unknown> | null): string {
  if (!props) return '(unknown)';
  for (const k of NAME_KEYS) {
    const v = props[k];
    if (typeof v === 'string' && v) return v;
  }
  return '(unknown)';
}

/**
 * Compute (bbox, centroid) for a Polygon/MultiPolygon. Centroid is the
 * centroid of the *largest* ring (matches what shapely.centroid returns for
 * simple shapes; "good enough" for picking a default zoom location).
 */
function geometryStats(
  geom: GeoJSONPolygonLike,
): { bbox: [number, number, number, number]; centroid: [number, number] } {
  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;

  let bestRing: number[][] | null = null;
  let bestArea = -1;

  const rings: number[][][] =
    geom.type === 'Polygon' ? geom.coordinates : geom.coordinates.flat();

  for (const ring of rings) {
    let signedArea = 0;
    for (let i = 0; i < ring.length - 1; i++) {
      const [x1, y1] = ring[i];
      const [x2, y2] = ring[i + 1];
      signedArea += x1 * y2 - x2 * y1;
      if (x1 < minLon) minLon = x1;
      if (x1 > maxLon) maxLon = x1;
      if (y1 < minLat) minLat = y1;
      if (y1 > maxLat) maxLat = y1;
    }
    const area = Math.abs(signedArea) / 2;
    if (area > bestArea) {
      bestArea = area;
      bestRing = ring;
    }
  }

  let cx = (minLon + maxLon) / 2;
  let cy = (minLat + maxLat) / 2;
  // Centroid by ring area weighting (single-ring approximation).
  if (bestRing && bestRing.length > 2) {
    let signed = 0;
    let xSum = 0;
    let ySum = 0;
    for (let i = 0; i < bestRing.length - 1; i++) {
      const [x1, y1] = bestRing[i];
      const [x2, y2] = bestRing[i + 1];
      const cross = x1 * y2 - x2 * y1;
      signed += cross;
      xSum += (x1 + x2) * cross;
      ySum += (y1 + y2) * cross;
    }
    const area6 = signed * 3;
    if (Math.abs(area6) > 1e-9) {
      cx = xSum / area6;
      cy = ySum / area6;
    }
  }

  return {
    bbox: [minLon, minLat, maxLon, maxLat],
    centroid: [cx, cy],
  };
}

function ensureBoundariesLoaded(): Promise<void> {
  if (_index) return Promise.resolve();
  if (_fetchPromise) return _fetchPromise;
  _fetchPromise = (async () => {
    const resp = await fetch(BOUNDARIES_URL);
    if (!resp.ok) {
      throw new Error(
        `boundaries fetch failed (${resp.status}): ${resp.statusText}`,
      );
    }
    const gj = (await resp.json()) as GeoJSONFeatureCollection;
    if (gj?.type !== 'FeatureCollection') {
      throw new Error('boundaries response is not a FeatureCollection');
    }
    const index = new Map<string, CountryEntry>();
    for (const f of gj.features as unknown as FeatureLike[]) {
      const iso = featureIso(f.properties);
      if (!iso) continue;
      const geom = f.geometry;
      if (!geom || (geom.type !== 'Polygon' && geom.type !== 'MultiPolygon')) {
        continue;
      }
      const polyLike = geom as GeoJSONPolygonLike;
      const stats = geometryStats(polyLike);
      index.set(iso, {
        iso,
        name: featureName(f.properties),
        polygon: polyLike,
        bbox: stats.bbox,
        centroid: stats.centroid,
      });
    }
    if (index.size === 0) {
      throw new Error('boundaries response produced an empty country index');
    }
    _geojson = gj;
    _index = index;
  })();
  return _fetchPromise;
}

export async function fetchCountryBoundaries(): Promise<GeoJSONFeatureCollection> {
  await ensureBoundariesLoaded();
  if (!_geojson) throw new Error('boundaries not loaded');
  return _geojson;
}

export async function listCountries(): Promise<CountryMeta[]> {
  await ensureBoundariesLoaded();
  if (!_index) throw new Error('boundaries not loaded');
  return Array.from(_index.values())
    .map((entry) => ({
      iso: entry.iso,
      name: entry.name,
      bbox: entry.bbox,
      centroid: entry.centroid,
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

export async function resolveRegion(countryIso: string): Promise<Region> {
  await ensureBoundariesLoaded();
  const iso = countryIso.trim().toUpperCase();
  const entry = _index?.get(iso);
  if (!entry) throw new Error(`unknown country ISO-A3: ${countryIso}`);
  return {
    countryIso: entry.iso,
    countryName: entry.name,
    polygon: entry.polygon,
    bbox: entry.bbox,
  };
}

/** Drop cached boundaries (used by tests). */
export function resetBoundariesCache(): void {
  _geojson = null;
  _index = null;
  _fetchPromise = null;
}
