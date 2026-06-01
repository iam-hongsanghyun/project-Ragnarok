/**
 * Forge — spatial snap: connect components to their nearest bus.
 *
 * Each overlay component carrying coordinates (x/y, and optionally x0/y0,
 * x1/y1 for branch endpoints) gets its bus / bus0 / bus1 set to the nearest
 * target bus by great-circle distance, when that bus is within a km buffer.
 * Components whose nearest bus is beyond the buffer are left unchanged and
 * reported, so nothing is silently mis-connected.
 *
 * Coordinates follow the PyPSA convention: x = longitude, y = latitude
 * (degrees). Distances are therefore haversine, not Euclidean.
 */
import type { GridRow } from 'lib/types';
import { numberValue, stringValue } from 'lib/utils/helpers';

const EARTH_RADIUS_KM = 6371.0088; // IUGG mean Earth radius

/**
 * Great-circle distance between two lat/lon points, in km.
 *
 * Algorithm (haversine):
 *   a = sin²(Δφ/2) + cos φ₁ · cos φ₂ · sin²(Δλ/2)
 *   d = 2R · asin(min(1, √a))
 * where φ = latitude, λ = longitude (radians), R = Earth radius (km).
 */
export function haversineKm(latA: number, lonA: number, latB: number, lonB: number): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(latB - latA);
  const dLon = toRad(lonB - lonA);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(latA)) * Math.cos(toRad(latB)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(a)));
}

export interface Target {
  name: string;
  lat: number;
  lon: number;
}

export function anchorCoord(row: GridRow, xKey: string, yKey: string): { lat: number; lon: number } | null {
  const x = row[xKey];
  const y = row[yKey];
  if (x === '' || x === null || x === undefined) return null;
  if (y === '' || y === null || y === undefined) return null;
  const lon = numberValue(x);
  const lat = numberValue(y);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return { lat, lon };
}

/** Rows carrying a finite x/y, as snap targets (x = lon, y = lat). */
export function buildTargets(rows: GridRow[]): Target[] {
  const out: Target[] = [];
  for (const row of rows) {
    const c = anchorCoord(row, 'x', 'y');
    const name = stringValue(row.name).trim();
    if (c && name) out.push({ name, lat: c.lat, lon: c.lon });
  }
  return out;
}

/** Coordinate anchor → the bus field it drives. */
export const SNAP_ANCHORS: ReadonlyArray<{ x: string; y: string; bus: string }> = [
  { x: 'x', y: 'y', bus: 'bus' },
  { x: 'x0', y: 'y0', bus: 'bus0' },
  { x: 'x1', y: 'y1', bus: 'bus1' },
];

export interface OutsideEntry {
  name: string;
  field: string;
  km: number;
  nearest: string;
}

export interface SnapResult {
  rows: GridRow[];
  /** Bus fields connected (within the buffer). */
  assigned: number;
  /** Anchors whose nearest target was beyond the buffer (left unchanged). */
  outside: OutsideEntry[];
  /** Rows with no usable coordinate anchor. */
  noCoords: number;
  /** Bus fields this sheet actually drove (e.g., ['bus'] or ['bus0','bus1']). */
  anchors: string[];
}

function nearest(targets: Target[], lat: number, lon: number): { target: Target; km: number } | null {
  let best: Target | null = null;
  let bestKm = Infinity;
  for (const t of targets) {
    const km = haversineKm(lat, lon, t.lat, t.lon);
    if (km < bestKm) {
      bestKm = km;
      best = t;
    }
  }
  return best ? { target: best, km: bestKm } : null;
}

/**
 * Snap each overlay row's bus / bus0 / bus1 to the nearest target bus within
 * `bufferKm`. Out-of-buffer anchors are reported in `outside` and left
 * unchanged. A new rows array is returned; untouched rows keep their identity.
 */
export function snapSheet(rows: GridRow[], targets: Target[], bufferKm: number): SnapResult {
  const outside: OutsideEntry[] = [];
  const anchorsUsed = new Set<string>();
  let assigned = 0;
  let noCoords = 0;

  const out = rows.map((row, i) => {
    let next: GridRow | null = null;
    let hadAnchor = false;
    for (const anchor of SNAP_ANCHORS) {
      const c = anchorCoord(row, anchor.x, anchor.y);
      if (!c) continue;
      hadAnchor = true;
      const near = nearest(targets, c.lat, c.lon);
      if (!near) continue;
      const label = stringValue(row.name).trim() || `row ${i + 1}`;
      if (near.km <= bufferKm) {
        if (stringValue(row[anchor.bus]).trim() !== near.target.name) {
          if (!next) next = { ...row };
          next[anchor.bus] = near.target.name;
        }
        assigned += 1;
        anchorsUsed.add(anchor.bus);
      } else {
        outside.push({ name: label, field: anchor.bus, km: near.km, nearest: near.target.name });
      }
    }
    if (!hadAnchor) noCoords += 1;
    return next ?? row;
  });

  return { rows: out, assigned, outside, noCoords, anchors: Array.from(anchorsUsed) };
}

/** Whether any row in the sheet carries a usable coordinate anchor. */
export function sheetSnappable(rows: GridRow[]): boolean {
  return rows.some((row) => SNAP_ANCHORS.some((a) => anchorCoord(row, a.x, a.y) !== null));
}
