/**
 * Geometry + naming helpers shared by both topology pipelines.
 * Kept side-effect-free so the two convert paths can pull from the same
 * implementations without re-deriving them.
 */
import lineTypesData from './line_types.json';

const EARTH_KM = 6371.0;
const NAME_RE = /[^A-Za-z0-9_]+/g;

export function slug(raw: string | null | undefined, fallback: string = 'asset'): string {
  if (!raw) return fallback;
  const s = String(raw).trim().replace(NAME_RE, '_').replace(/^_+|_+$/g, '');
  return s || fallback;
}

export function dedupe(name: string, taken: Set<string>): string {
  if (!taken.has(name)) {
    taken.add(name);
    return name;
  }
  let i = 2;
  while (taken.has(`${name}_${i}`)) i++;
  const final = `${name}_${i}`;
  taken.add(final);
  return final;
}

export function haversineKm(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const lat1r = (lat1 * Math.PI) / 180;
  const lat2r = (lat2 * Math.PI) / 180;
  const dlat = lat2r - lat1r;
  const dlon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dlat / 2) ** 2 +
    Math.cos(lat1r) * Math.cos(lat2r) * Math.sin(dlon / 2) ** 2;
  return 2 * EARTH_KM * Math.asin(Math.sqrt(a));
}

export function polylineLengthKm(points: Array<[number, number]>): number {
  let total = 0;
  for (let i = 0; i < points.length - 1; i++) {
    const [lat1, lon1] = points[i];
    const [lat2, lon2] = points[i + 1];
    total += haversineKm(lat1, lon1, lat2, lon2);
  }
  return total;
}

export function endpointKey(osmId: number, kv: number): string {
  return `${osmId}|${kv}`;
}

export function lineTypeMapping(): Record<number, string> {
  const raw = (lineTypesData as { voltage_kv_to_type?: Record<string, string> })
    .voltage_kv_to_type || {};
  const out: Record<number, string> = {};
  for (const [k, v] of Object.entries(raw)) {
    out[parseInt(k, 10)] = String(v);
  }
  return out;
}

export function lineTypeFor(
  voltageKv: number,
  mapping: Record<number, string>,
): string {
  return mapping[Math.round(voltageKv)] || '';
}
