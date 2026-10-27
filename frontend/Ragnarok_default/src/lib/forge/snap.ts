/**
 * Forge — spatial snap: connect components to their nearest bus.
 *
 * The snap itself (haversine nearest-bus within a km buffer) runs on the backend
 * — `POST /api/forge/snap`, `backend/app/forge_helpers.py` — so the GUI and the
 * MCP `snap_to_buses` tool agree. This module keeps only the synchronous,
 * render-time helpers (which sheets carry coordinates, the target count) and the
 * response types.
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

/** Whether any row in the sheet carries a usable coordinate anchor. */
export function sheetSnappable(rows: GridRow[]): boolean {
  return rows.some((row) => SNAP_ANCHORS.some((a) => anchorCoord(row, a.x, a.y) !== null));
}
