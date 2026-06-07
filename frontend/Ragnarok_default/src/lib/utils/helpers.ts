import type { LatLngBoundsExpression } from 'leaflet';
import { getDefaultRowForSheet } from 'lib/constants';
import { GridRow, Primitive, SheetName, WorkbookModel } from '../types';
import type { DateFormat } from 'lib/settings/types';

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

export function setCarrierColorOverrides(rows: GridRow[] | undefined | null): void {
  const next: Record<string, string> = {};
  (rows ?? []).forEach((row) => {
    const name = String(row.name ?? '').trim();
    const color = String(row.color ?? '').trim();
    if (!name || !color) return;
    next[normalizeCarrierKey(name)] = color;
  });
  carrierColorOverrides = next;
}

function normalizeHexColor(value: string): string {
  const raw = value.trim();
  if (!raw) return '';
  if (/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(raw)) return raw;
  return '';
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
  const ordered = new Set<string>(Object.keys(getDefaultRowForSheet(sheet)));
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

export function resolvedColor(explicitColor: Primitive | undefined, carrier?: Primitive | undefined): string {
  const direct = normalizeHexColor(String(explicitColor ?? ''));
  if (direct) return direct;
  return carrierColor(String(carrier ?? ''));
}

export function orderByCarrierRows(carrierRows: GridRow[], keys: string[]): string[] {
  const ordered = carrierRows
    .map((row) => stringValue(row.name).trim())
    .filter((name) => name && keys.includes(name));
  const remainder = keys.filter((key) => !ordered.includes(key));
  return [...ordered, ...remainder];
}

/**
 * Map a line loading percentage (0–100+) to a colour on a
 * green → yellow → red traffic-light scale.
 */
/** Diverging teal → light-grey → red scale for nodal price maps. */
export function priceColor(value: number, min: number, max: number): string {
  if (min >= max) return '#0f766e';
  const t = Math.max(0, Math.min(1, (value - min) / (max - min)));
  const lerp = (a: number, b: number, s: number) => Math.round(a + (b - a) * s);
  const [r1, g1, b1] = [15, 118, 110]; // #0f766e (low price)
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
  // WorkbookModel is a Record<string, GridRow[]>, but a workbook freshly
  // loaded from localStorage (or built before the schema bootstrap
  // populated SHEETS) can be missing required keys. Coalesce with [] so
  // the readers never throw — getBounds returning null on an empty
  // model is the right shape for the map layer anyway.
  const buses = model.buses ?? [];
  const generators = model.generators ?? [];
  const busPoints = buses.flatMap((bus) => { const c = rowCoords(bus); return c ? [c] : []; });
  const genPoints = generators.flatMap((g) => { const c = rowCoords(g); return c ? [c] : []; });
  const points = [...busPoints, ...genPoints];
  return points.length ? points : null;
}

export function getBusIndex(model: WorkbookModel): Record<string, GridRow> {
  const index: Record<string, GridRow> = {};
  (model.buses ?? []).forEach((bus) => {
    index[stringValue(bus.name)] = bus;
  });
  return index;
}

const pad2 = (n: number): string => String(n).padStart(2, '0');

/** Canonical ISO date portion (YYYY-MM-DD) from local components — never UTC, so the calendar day never shifts. */
export function isoDate(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

/** Canonical 24h time portion (HH:MM) from local components. */
export function isoTime(d: Date): string {
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

/** ISO `YYYY-MM-DDTHH:MM` (the `T` separator, never a space or locale form). */
export function formatTimestamp(raw?: string) {
  if (!raw) return '';
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  return `${isoDate(date)}T${isoTime(date)}`;
}

const DATE_RE = /^(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})(?:[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?$/;

/**
 * Convert a date string written in the user's declared INPUT format (`fmt`)
 * into the canonical ISO target (YYYY-MM-DD, plus THH:MM:SS when a time part
 * is present). Strings that don't match a numeric date are returned unchanged,
 * so non-date cells pass through safely.
 */
export function normalizeDateToIso(raw: string, fmt: DateFormat = 'auto'): string {
  const m = DATE_RE.exec(raw.trim());
  if (!m) return raw;
  const parts = [parseInt(m[1], 10), parseInt(m[2], 10), parseInt(m[3], 10)];
  let order: DateFormat = fmt;
  // A 4-digit leading component is unambiguously the year (no real date has a
  // 4-digit day or month), so it always wins over the user's input-format
  // setting. Without this, plugin output (always ISO/YMD via
  // `pd.Timestamp.isoformat`) silently fails to canonicalise when the user's
  // Date format setting is dmy/mdy: `[d,m,y] = [2024,1,1]` → d=2024 fails the
  // `<= 31` guard and the function returns the raw string unchanged.
  if (m[1].length === 4) order = 'ymd';
  else if (order === 'auto') {
    if (m[3].length === 4) order = parts[0] > 12 ? 'dmy' : 'mdy';
    else order = 'mdy';
  }
  let y: number, mo: number, d: number;
  if (order === 'ymd') [y, mo, d] = parts;
  else if (order === 'dmy') [d, mo, y] = parts;
  else [mo, d, y] = parts; // mdy
  if (y < 100) y += 2000;
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return raw;
  let iso = `${y}-${pad2(mo)}-${pad2(d)}`;
  if (m[4] !== undefined) {
    iso += `T${pad2(parseInt(m[4], 10))}:${pad2(parseInt(m[5], 10))}:${pad2(m[6] ? parseInt(m[6], 10) : 0)}`;
  }
  return iso;
}

export function snapshotMaxFromWorkbook(rows: GridRow[]): number {
  if (!rows || rows.length === 0) return 1;
  for (const row of rows) {
    const label = String(row.snapshot ?? row.name ?? row.datetime ?? '').trim().toLowerCase();
    if (label === 'now' || label === '') return 1;
  }
  return rows.length;
}
