import { LatLngBoundsExpression } from 'leaflet';
import { DEFAULT_SHEET_ROWS } from '../../constants';
import { GridRow, Primitive, SheetName, WorkbookModel } from '../../types';

const DEFAULT_CARRIER_PALETTE = [
  '#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f',
  '#edc948', '#b07aa1', '#ff9da7', '#9c755f', '#bab0ab',
  '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
  '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
  '#393b79', '#637939', '#8c6d31', '#843c39', '#7b4173',
  '#3182bd', '#31a354', '#756bb1', '#636363', '#e6550d',
];

let carrierColorOverrides: Record<string, string> = {};

export function numberValue(value: Primitive | string | number | undefined): number {
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0;
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  if (typeof value === 'boolean') return value ? 1 : 0;
  return 0;
}

export function stringValue(value: Primitive | undefined): string {
  if (value === null || value === undefined) return '';
  return String(value);
}

export function hashColor(value: string): string {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = value.charCodeAt(index) + ((hash << 5) - hash);
  }
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue} 65% 46%)`;
}

function hashIndex(value: string, size: number): number {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = value.charCodeAt(index) + ((hash << 5) - hash);
  }
  return Math.abs(hash) % size;
}

function normalizeCarrierKey(value: string): string {
  return value.trim().toLowerCase();
}

function paletteColor(value: string): string {
  return DEFAULT_CARRIER_PALETTE[hashIndex(normalizeCarrierKey(value), DEFAULT_CARRIER_PALETTE.length)];
}

export function setCarrierColorOverrides(rows: GridRow[]): void {
  const next: Record<string, string> = {};
  rows.forEach((row) => {
    const name = String(row.name ?? '').trim();
    const color = String(row.color ?? '').trim();
    if (!name || !color) return;
    next[normalizeCarrierKey(name)] = color;
  });
  carrierColorOverrides = next;
}

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export function inferInputValue(raw: string, current: Primitive): Primitive {
  if (raw === '') return '';
  if (typeof current === 'number') {
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : current;
  }
  if (typeof current === 'boolean') return raw.toLowerCase() === 'true';
  if (raw.toLowerCase() === 'true') return true;
  if (raw.toLowerCase() === 'false') return false;
  const parsed = Number(raw);
  if (Number.isFinite(parsed) && /^-?\d+(\.\d+)?$/.test(raw.trim())) return parsed;
  return raw;
}

export function getColumns(rows: GridRow[], sheet: SheetName): string[] {
  const ordered = new Set<string>(Object.keys(DEFAULT_SHEET_ROWS[sheet]));
  rows.forEach((row) => Object.keys(row).forEach((key) => ordered.add(key)));
  const cols = Array.from(ordered);
  // Pin 'name' as the first data column on every static sheet
  const nameIdx = cols.indexOf('name');
  if (nameIdx > 0) {
    cols.splice(nameIdx, 1);
    cols.unshift('name');
  }
  return cols;
}

/** For temporal (_t) sheets the first column is the snapshot/timestamp key. */
export function getTsFirstCol(rows: GridRow[]): string {
  if (!rows.length) return 'snapshot';
  const keys = Object.keys(rows[0]);
  // Prefer explicit timestamp-like names; fall back to the very first key
  return (
    keys.find((k) => ['snapshot', 'datetime', 'timestamp', 'time'].includes(k.toLowerCase())) ??
    keys[0] ??
    'snapshot'
  );
}

export function carrierColor(carrier: string): string {
  const raw = String(carrier || '').trim();
  if (!raw) return '#94a3b8';
  return carrierColorOverrides[normalizeCarrierKey(raw)] ?? paletteColor(raw);
}

/**
 * Map a line loading percentage (0–100+) to a colour on a
 * green → yellow → red traffic-light scale.
 */
/** Diverging blue → light-grey → red scale for nodal price maps. */
export function priceColor(value: number, min: number, max: number): string {
  if (min >= max) return '#2563eb';
  const t = Math.max(0, Math.min(1, (value - min) / (max - min)));
  const lerp = (a: number, b: number, s: number) => Math.round(a + (b - a) * s);
  const [r1, g1, b1] = [37,  99,  235]; // #2563eb  (low price)
  const [rm, gm, bm] = [241, 245, 249]; // #f1f5f9  (mid / average)
  const [r2, g2, b2] = [220, 38,  38];  // #dc2626  (high price)
  if (t <= 0.5) {
    const s = t * 2;
    return `rgb(${lerp(r1, rm, s)},${lerp(g1, gm, s)},${lerp(b1, bm, s)})`;
  }
  const s = (t - 0.5) * 2;
  return `rgb(${lerp(rm, r2, s)},${lerp(gm, g2, s)},${lerp(bm, b2, s)})`;
}

export function loadingColor(pct: number): string {
  const t = Math.max(0, Math.min(1, pct / 100));
  if (t <= 0.5) {
    // green (#22c55e) → yellow (#f59e0b)
    const u = t * 2;
    const r = Math.round(34 + (245 - 34) * u);
    const g = Math.round(197 + (158 - 197) * u);
    const b = Math.round(94 + (11 - 94) * u);
    return `rgb(${r},${g},${b})`;
  } else {
    // yellow (#f59e0b) → red (#dc2626)
    const u = (t - 0.5) * 2;
    const r = Math.round(245 + (220 - 245) * u);
    const g = Math.round(158 + (38 - 158) * u);
    const b = Math.round(11 + (38 - 11) * u);
    return `rgb(${r},${g},${b})`;
  }
}

/** Return [lat, lng] from a row if x and y are both non-empty, else null. */
export function rowCoords(row: GridRow): [number, number] | null {
  const x = row.x; const y = row.y;
  if (x === undefined || x === null || x === '' || y === undefined || y === null || y === '') return null;
  return [numberValue(y), numberValue(x)];
}

export function getBounds(model: WorkbookModel): LatLngBoundsExpression | null {
  // Include buses with explicit coords AND generators with their own coords
  const busPoints = model.buses.flatMap((bus) => { const c = rowCoords(bus); return c ? [c] : []; });
  const genPoints = model.generators.flatMap((g) => { const c = rowCoords(g); return c ? [c] : []; });
  const points = [...busPoints, ...genPoints];
  return points.length ? points : null;
}

export function getBusIndex(model: WorkbookModel): Record<string, GridRow> {
  const index: Record<string, GridRow> = {};
  model.buses.forEach((bus) => {
    index[stringValue(bus.name)] = bus;
  });
  return index;
}

export function formatTimestamp(raw?: string) {
  if (!raw) return '';
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function snapshotMaxFromWorkbook(rows: GridRow[]): number {
  if (!rows || rows.length === 0) return 1;
  for (const row of rows) {
    const label = String(row.snapshot ?? row.name ?? row.datetime ?? '').trim().toLowerCase();
    if (label === 'now' || label === '') return 1;
  }
  return rows.length;
}
