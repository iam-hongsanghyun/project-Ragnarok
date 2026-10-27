/**
 * Piecewise-linear cost / efficiency curves (PyPSA >= 1.3) for the Forge editor and
 * the workbook / CSV-folder I/O.
 *
 * Sheet format (mirrors `backend/pypsa/network/piecewise.py`): one sheet per
 * `<list>-<attribute>-pw`, LONG form, one row per breakpoint of one component:
 *
 *     name | breakpoint | p_pu | marginal_cost
 *     g1   | 0          | 0    | 0
 *     g1   | 1          | 0.5  | 10
 *     g1   | 2          | 1    | 40
 *
 * Meaning of y — cost curves (`marginal_cost`, `capital_cost`): the y at breakpoint
 * i >= 1 is the price per unit of x on the segment (x[i-1], x[i]]; y[0] is ignored.
 *
 *     C(x) = sum_i y_i * max(0, min(x, x_i) - x_{i-1})
 *
 * so the curve is convex (an LP) iff y_1 <= y_2 <= ...; any other shape needs
 * binaries (a MIP). Efficiency / rate curves are equalities and are a MIP unless the
 * curve is a straight line. ASCII: C(x) = sum y_i * len(segment_i below x).
 *
 * Pure and unit-tested; `CostCurvePanel` is the thin UI around it.
 */
import type { GridRow } from 'lib/types';

export const PW_SUFFIX = '-pw';

/** What PyPSA allows for one curve (`pypsa/data/piecewise.csv`, via the schema bundle). */
export interface PiecewiseSpec {
  attribute: string;
  x: string;
  kind: 'cost' | 'efficiency';
  /** `efficiency2`, `rate1` ...: the y attribute carries a port number. */
  ported: boolean;
  /** Per-unit curves (marginal_cost, efficiency, rate) need fixed capacity. */
  allow_extendable: boolean;
  output: string | null;
  sheet: string;
}

export interface Breakpoint {
  x: number;
  y: number;
}

export type CurveShape = 'convex' | 'linear' | 'nonconvex';

export interface CurveCheck {
  /** Blocking problems: the backend would refuse this curve. */
  errors: string[];
  /** Non-blocking advice (MIP warning, ignored y[0], ...). */
  warnings: string[];
  shape: CurveShape;
  /** True when PyPSA must add binaries (non-convex). */
  isMip: boolean;
}

/** `generators` + `marginal_cost` -> `generators-marginal_cost-pw`. */
export const piecewiseSheetName = (listSheet: string, attribute: string): string =>
  `${listSheet}-${attribute}${PW_SUFFIX}`;

/** `generators-marginal_cost-pw` -> { listSheet, attribute }; null when it is not a curve sheet. */
export function parsePiecewiseSheetName(sheet: string): { listSheet: string; attribute: string } | null {
  if (!sheet.endsWith(PW_SUFFIX)) return null;
  const body = sheet.slice(0, -PW_SUFFIX.length);
  const dash = body.indexOf('-');
  if (dash <= 0 || dash === body.length - 1) return null;
  return { listSheet: body.slice(0, dash), attribute: body.slice(dash + 1) };
}

export const isPiecewiseSheet = (sheet: string): boolean => parsePiecewiseSheetName(sheet) !== null;

/** Base attribute with its port number dropped (`efficiency2` -> `efficiency`, `rate0` -> `rate`). */
export function baseAttribute(attribute: string): string {
  const stripped = attribute.replace(/\d+$/, '');
  return stripped === 'efficiency' || stripped === 'rate' ? stripped : attribute;
}

/**
 * Attribute names a ported curve can take for a component row set: `efficiency` and
 * `efficiency{k}` for every bus{k} in use on a Link; `rate{k}` (k from 0) on a Process.
 */
export function portAttributes(spec: PiecewiseSpec, rows: GridRow[]): string[] {
  if (!spec.ported) return [spec.attribute];
  const ports = new Set<number>();
  rows.forEach((r) =>
    Object.keys(r).forEach((key) => {
      const m = /^bus(\d+)$/.exec(key);
      if (m && String(r[key] ?? '').trim() !== '') ports.add(Number(m[1]));
    }),
  );
  if (spec.attribute === 'rate') {
    const list = Array.from(ports).sort((a, b) => a - b);
    return (list.length ? list : [0, 1]).map((k) => `rate${k}`);
  }
  // Link: port 1 is plain `efficiency`
  return ['efficiency', ...Array.from(ports).filter((k) => k >= 2).sort((a, b) => a - b).map((k) => `efficiency${k}`)];
}

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || (typeof v === 'string' && v.trim() === '')) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

/** Breakpoints of one component read from long-form sheet rows, sorted by x. */
export function curveFromRows(rows: GridRow[], name: string, xAttr: string, attribute: string): Breakpoint[] {
  const out: Breakpoint[] = [];
  rows.forEach((r) => {
    if (String(r.name ?? '').trim() !== name) return;
    const x = num(r[xAttr] ?? r.x);
    const y = num(r[attribute] ?? r.y);
    if (x !== null && y !== null) out.push({ x, y });
  });
  return out.sort((a, b) => a.x - b.x);
}

/** Names that have at least one breakpoint row. */
export function curveNames(rows: GridRow[]): string[] {
  const seen = new Set<string>();
  rows.forEach((r) => {
    const n = String(r.name ?? '').trim();
    if (n) seen.add(n);
  });
  return Array.from(seen);
}

/** Long-form rows for one curve (what `replaceCurve` writes). */
export function rowsFromCurve(name: string, xAttr: string, attribute: string, pts: Breakpoint[]): GridRow[] {
  return [...pts]
    .sort((a, b) => a.x - b.x)
    .map((p, i) => ({ name, breakpoint: i, [xAttr]: p.x, [attribute]: p.y }) as GridRow);
}

/** Replace (or, with `pts = []`, clear) the curve of `name`, leaving every other component untouched. */
export function replaceCurve(
  rows: GridRow[],
  name: string,
  xAttr: string,
  attribute: string,
  pts: Breakpoint[],
): GridRow[] {
  const kept = rows.filter((r) => String(r.name ?? '').trim() !== name);
  return [...kept, ...rowsFromCurve(name, xAttr, attribute, pts)];
}

/** Apply the same curve to several components (the editor's "apply to matched rows"). */
export function replaceCurves(
  rows: GridRow[],
  names: string[],
  xAttr: string,
  attribute: string,
  pts: Breakpoint[],
): GridRow[] {
  const drop = new Set(names);
  const kept = rows.filter((r) => !drop.has(String(r.name ?? '').trim()));
  return [...kept, ...names.flatMap((n) => rowsFromCurve(n, xAttr, attribute, pts))];
}

const TOL = 1e-9;

/**
 * Classify a curve. Mirrors `backend.pypsa.network.piecewise.curve_shape`.
 *
 * Algorithm: cost curves — convex iff y_1 <= y_2 <= ... (y_i = price on segment i);
 * efficiency / rate — values Y_i = y_i * x_i (a Generator's primary energy is
 * x_i / y_i); LP-expressible only when every segment slope is equal (`linear`).
 */
export function curveShape(kind: 'cost' | 'efficiency', pts: Breakpoint[], invert = false): CurveShape {
  const sorted = [...pts].sort((a, b) => a.x - b.x);
  if (sorted.length < 2) return 'linear';
  if (kind === 'cost') {
    const slopes = sorted.slice(1).map((p) => p.y);
    if (slopes.every((s) => Math.abs(s - slopes[0]) <= TOL)) return 'linear';
    return slopes.every((s, i) => i === 0 || s >= slopes[i - 1] - TOL) ? 'convex' : 'nonconvex';
  }
  const values = sorted.map((p) => (invert ? (p.x === 0 || p.y === 0 ? 0 : p.x / p.y) : p.x * p.y));
  const slopes: number[] = [];
  for (let i = 1; i < sorted.length; i += 1) {
    const dx = sorted[i].x - sorted[i - 1].x;
    if (dx > 0) slopes.push((values[i] - values[i - 1]) / dx);
  }
  if (!slopes.length) return 'linear';
  return slopes.every((s) => Math.abs(s - slopes[0]) <= 1e-9 * Math.max(1, Math.abs(slopes[0]))) ? 'linear' : 'nonconvex';
}

export interface CheckOptions {
  /** Per-unit x axis (`p_pu`, `p_dispatch_pu`): must run 0 -> 1. */
  perUnit: boolean;
  /** Component the curve is applied to is extendable (not allowed on a per-unit axis). */
  anyExtendable?: boolean;
  /** Generator efficiency: primary energy is x / y. */
  invert?: boolean;
  kind: 'cost' | 'efficiency';
}

/**
 * Validate a curve before it is written. Errors are exactly the conditions the
 * backend refuses (so Apply never produces a run-time 400); warnings are advice.
 */
export function checkCurve(pts: Breakpoint[], opts: CheckOptions): CurveCheck {
  const errors: string[] = [];
  const warnings: string[] = [];
  const sorted = [...pts].sort((a, b) => a.x - b.x);
  if (pts.some((p) => !Number.isFinite(p.x) || !Number.isFinite(p.y))) {
    errors.push('Every breakpoint needs a numeric x and y.');
  }
  if (pts.length < 2) errors.push('A curve needs at least 2 breakpoints (start at x = 0).');
  if (sorted.some((p, i) => i > 0 && p.x === sorted[i - 1].x)) {
    errors.push('x must be strictly increasing — two breakpoints share the same x.');
  }
  if (sorted.length && sorted[0].x !== 0) {
    errors.push(`The curve must start at x = 0 (first breakpoint is at ${sorted[0].x}); add a (0, 0) point.`);
  }
  if (opts.perUnit && sorted.length && sorted[sorted.length - 1].x !== 1) {
    errors.push(`A per-unit curve must end at x = 1 (last breakpoint is at ${sorted[sorted.length - 1].x}).`);
  }
  if (opts.perUnit && opts.anyExtendable) {
    errors.push('A per-unit curve needs a fixed capacity: untick *_extendable on the target rows, or use a capital_cost curve.');
  }
  if (opts.kind === 'efficiency') {
    const signs = new Set(pts.map((p) => Math.sign(p.y)).filter((s) => s !== 0));
    if (signs.size > 1) errors.push('An efficiency / rate curve cannot mix positive and negative values.');
  }
  if (opts.kind === 'cost' && sorted.length && sorted[0].y !== 0) {
    warnings.push('The y at x = 0 is ignored (it spans zero width): put the first segment price on the second breakpoint.');
  }
  const shape = curveShape(opts.kind, pts, opts.invert);
  const isMip = shape === 'nonconvex';
  if (isMip) {
    warnings.push(
      opts.kind === 'cost'
        ? 'Non-convex (the price falls along the curve): PyPSA adds binaries, so the run becomes a MIP.'
        : 'Not a straight line: PyPSA adds binaries for this curve, so the run becomes a MIP.',
    );
  } else if (shape === 'convex') {
    warnings.push('Convex: solved as an LP with tangent cuts.');
  }
  return { errors, warnings, shape, isMip };
}

/** Marginal price at output x for a cost curve (the staircase the chart draws). */
export function priceAt(pts: Breakpoint[], x: number): number {
  const sorted = [...pts].sort((a, b) => a.x - b.x);
  for (let i = 1; i < sorted.length; i += 1) if (x <= sorted[i].x) return sorted[i].y;
  return sorted.length > 1 ? sorted[sorted.length - 1].y : 0;
}

/** Total cost C(x) of a cost curve at output x. */
export function costAt(pts: Breakpoint[], x: number): number {
  const sorted = [...pts].sort((a, b) => a.x - b.x);
  let total = 0;
  for (let i = 1; i < sorted.length; i += 1) {
    const lo = sorted[i - 1].x;
    total += sorted[i].y * Math.max(0, Math.min(x, sorted[i].x) - lo);
  }
  return total;
}

/** A sensible starting curve for a spec: 3 convex breakpoints (per-unit) or sized from `nominal`. */
export function defaultCurve(spec: PiecewiseSpec, nominal = 100): Breakpoint[] {
  if (spec.kind === 'efficiency') return [{ x: 0, y: 0 }, { x: 0.5, y: 0.9 }, { x: 1, y: 0.8 }];
  if (spec.x.endsWith('_pu')) return [{ x: 0, y: 0 }, { x: 0.5, y: 10 }, { x: 1, y: 40 }];
  return [{ x: 0, y: 0 }, { x: nominal / 2, y: 1e5 }, { x: nominal, y: 2e5 }];
}

// ── PyPSA-native CSV layout (wide, three header rows) <-> long rows ────────────

/**
 * PyPSA's own `<list>-<attr>-pw.csv` is WIDE: header rows `name,g,g,h,h` /
 * `attribute,p_pu,marginal_cost,p_pu,marginal_cost` / `breakpoint,,,,` then one row
 * per breakpoint. Convert long rows -> that table (array of string rows).
 */
export function longToNativeTable(rows: GridRow[], xAttr: string, attribute: string): string[][] {
  const names = curveNames(rows);
  const curves = names.map((n) => curveFromRows(rows, n, xAttr, attribute));
  const depth = Math.max(0, ...curves.map((c) => c.length));
  const header1 = ['name'];
  const header2 = ['attribute'];
  const header3 = ['breakpoint'];
  names.forEach((n) => {
    header1.push(n, n);
    header2.push(xAttr, attribute);
    header3.push('', '');
  });
  const body: string[][] = [];
  for (let i = 0; i < depth; i += 1) {
    const line = [String(i)];
    curves.forEach((c) => line.push(i < c.length ? String(c[i].x) : '', i < c.length ? String(c[i].y) : ''));
    body.push(line);
  }
  return [header1, header2, header3, ...body];
}

/** Inverse of {@link longToNativeTable}; also accepts an already-long table (header `name,...`). */
export function nativeTableToLong(table: string[][], xAttr: string, attribute: string): GridRow[] {
  if (table.length === 0) return [];
  const head = table[0].map((h) => h.trim());
  const isNative = head[0] === 'name' && table[1]?.[0]?.trim() === 'attribute';
  if (!isNative) return [];
  const names = table[0];
  const attrs = table[1].map((a) => a.trim());
  const out: GridRow[] = [];
  const perName = new Map<string, Breakpoint[]>();
  for (let c = 1; c < names.length; c += 1) {
    if (attrs[c] !== xAttr) continue;
    const name = names[c].trim();
    const yCol = attrs.findIndex((a, i) => i > 0 && a === attribute && names[i].trim() === name);
    if (!name || yCol < 0) continue;
    const pts: Breakpoint[] = [];
    for (let r = 3; r < table.length; r += 1) {
      const x = num(table[r][c]);
      const y = num(table[r][yCol]);
      if (x !== null && y !== null) pts.push({ x, y });
    }
    perName.set(name, pts);
  }
  perName.forEach((pts, name) => out.push(...rowsFromCurve(name, xAttr, attribute, pts)));
  return out;
}
