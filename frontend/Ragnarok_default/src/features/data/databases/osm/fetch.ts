/**
 * Overpass query builder + HTTP client (browser-direct).
 *
 * Ported from `backend/app/importers/databases/osm/overpass.py`. The public
 * Overpass mirror is rate-limited (429 / 504 under load); we wrap the call
 * with exponential backoff and surface a clear error to the caller after a
 * small number of retries. Identifies via a User-Agent header — the main
 * mirror returns 406 to requests without one.
 *
 * Polygon → `poly:"lat lon …"` clause matching the Python implementation:
 * pick the largest ring of the (Multi)Polygon and serialise it. Sliver
 * islands outside the chosen ring are filtered client-side by the
 * voltage / point-in-polygon checks downstream.
 */
import type { GeoJSONPolygonLike } from '../types';

const DEFAULT_URL = 'https://overpass-api.de/api/interpreter';
const DEFAULT_TIMEOUT_S = 180;
const DEFAULT_RETRY = 3;
const DEFAULT_UA = 'Ragnarok/0.1 (+https://github.com/PyPSA/PyPSA)';

function overpassUrl(): string {
  return process.env.REACT_APP_RAGNAROK_OVERPASS_URL || DEFAULT_URL;
}

function overpassUa(): string {
  return process.env.REACT_APP_RAGNAROK_OVERPASS_UA || DEFAULT_UA;
}

/** Largest exterior ring of a (Multi)Polygon, as `[(lat, lon), …]`. */
function largestRing(geom: GeoJSONPolygonLike): Array<[number, number]> {
  const rings: number[][][] =
    geom.type === 'Polygon' ? [geom.coordinates[0]] : geom.coordinates.map((p) => p[0]);
  if (rings.length === 0) throw new Error('region polygon has no exterior ring');
  let best: number[][] = rings[0];
  for (const r of rings) {
    if (r.length > best.length) best = r;
  }
  if (best.length < 3) throw new Error('region polygon ring has fewer than 3 vertices');
  // Overpass expects "lat lon" pairs; GeoJSON stores [lon, lat].
  return best.map(([lon, lat]) => [lat, lon] as [number, number]);
}

function polyFilter(geom: GeoJSONPolygonLike): string {
  return largestRing(geom)
    .map(([lat, lon]) => `${lat} ${lon}`)
    .join(' ');
}

export function buildQuery(
  geom: GeoJSONPolygonLike,
  opts: {
    includeCables: boolean;
    includeDc: boolean;
    minVoltageV: number;
    timeoutS?: number;
  },
): string {
  const poly = polyFilter(geom);
  const timeout = opts.timeoutS ?? DEFAULT_TIMEOUT_S;
  // Tag-presence filter (`["voltage"]`) is enough — voltage normalisation
  // and the user's min_voltage threshold are re-applied client-side.
  const voltageFilter = '["voltage"]';
  // HVDC opt-out: drop lines where `frequency` is explicitly "0".
  const dcClause = opts.includeDc ? '' : '["frequency"!="0"]';
  const lines = [
    `way["power"="line"]${voltageFilter}${dcClause}(poly:"${poly}");`,
  ];
  if (opts.includeCables) {
    lines.push(`way["power"="cable"]${voltageFilter}${dcClause}(poly:"${poly}");`);
  }
  lines.push(`node["power"="substation"](poly:"${poly}");`);
  lines.push(`way["power"="substation"](poly:"${poly}");`);
  return `[out:json][timeout:${timeout}];(${lines.join('')});out body geom;`;
}

export class OverpassError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'OverpassError';
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

export interface OverpassResponse {
  elements: Array<Record<string, unknown>>;
  [k: string]: unknown;
}

export async function postQuery(
  query: string,
  opts: {
    url?: string;
    retries?: number;
    backoffMs?: number;
  } = {},
): Promise<OverpassResponse> {
  const target = opts.url || overpassUrl();
  const retries = opts.retries ?? DEFAULT_RETRY;
  const backoffMs = opts.backoffMs ?? 2000;
  let lastErr: Error | null = null;
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      // Overpass accepts `data=<query>` as URL-encoded form data.
      const body = new URLSearchParams({ data: query }).toString();
      const resp = await fetch(target, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          // Browser will set User-Agent automatically; passing it as a
          // custom header is no-op for fetch but harmless for environments
          // that allow it. The 406 hazard described in the Python client
          // does not apply to browser-issued requests.
          'User-Agent': overpassUa(),
          Accept: 'application/json',
        },
        body,
      });
      if (!resp.ok) {
        if ([429, 502, 503, 504].includes(resp.status) && attempt < retries) {
          await sleep(backoffMs * attempt);
          continue;
        }
        throw new OverpassError(`Overpass HTTP ${resp.status}: ${resp.statusText}`);
      }
      return (await resp.json()) as OverpassResponse;
    } catch (exc) {
      lastErr = exc instanceof Error ? exc : new Error(String(exc));
      if (attempt < retries) {
        await sleep(backoffMs * attempt);
        continue;
      }
    }
  }
  throw new OverpassError(lastErr ? lastErr.message : 'Overpass request failed');
}
