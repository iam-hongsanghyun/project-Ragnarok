/**
 * Forge — numeric attribute transforms (round / ceil / floor).
 *
 * Pure, model-agnostic functions over workbook rows so they are unit-testable
 * and reusable by the Forge view. Non-numeric or empty cells are always left
 * untouched; only cells that actually change are rewritten.
 */
import type { GridRow, WorkbookModel } from 'lib/types';

export type RoundOp = 'round' | 'ceil' | 'floor';

/** Component counts before/after a clustering reduction. */
export interface ClusterCounts {
  buses: number;
  lines: number;
  transformers: number;
  links: number;
  generators: number;
  loads: number;
  storageUnits: number;
}

/** Result of POST /api/transform/cluster — the reduced model + a busmap. */
export interface ClusterResult {
  model: WorkbookModel;
  busmap: Record<string, string>;
  method: string;
  before: ClusterCounts;
  after: ClusterCounts;
}

/** A cell as a finite number, or null when it is empty / non-numeric. */
function asFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'string' && value.trim() !== '') {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/**
 * Columns whose every non-empty value parses as a finite number (so that a
 * round / ceil / floor is meaningful). `name` is always excluded. Result is
 * sorted for stable UI ordering.
 */
export function numericColumns(rows: GridRow[]): string[] {
  if (!rows.length) return [];
  const cols = new Set<string>();
  for (const row of rows) for (const key of Object.keys(row)) cols.add(key);
  cols.delete('name');

  const out: string[] = [];
  for (const col of Array.from(cols)) {
    let sawNumber = false;
    let allNumeric = true;
    for (const row of rows) {
      const raw = row[col];
      if (raw === '' || raw === null || raw === undefined) continue;
      if (asFiniteNumber(raw) === null) {
        allNumeric = false;
        break;
      }
      sawNumber = true;
    }
    if (allNumeric && sawNumber) out.push(col);
  }
  return out.sort();
}

function applyOp(value: number, op: RoundOp, decimals: number): number {
  const factor = 10 ** decimals;
  if (op === 'ceil') return Math.ceil(value * factor) / factor;
  if (op === 'floor') return Math.floor(value * factor) / factor;
  return Math.round(value * factor) / factor;
}

export interface RoundResult {
  rows: GridRow[];
  /** Number of cells whose value actually changed. */
  changed: number;
}

/**
 * Apply round / ceil / floor to `attrs` across all rows.
 *
 * Algorithm: for d decimals and f = 10^d,
 *   round → round(x·f)/f,   ceil → ceil(x·f)/f,   floor → floor(x·f)/f.
 * Empty / non-numeric cells are skipped. A new rows array is returned;
 * untouched rows keep their object identity (cheap React diffing).
 */
export function applyRounding(
  rows: GridRow[],
  attrs: string[],
  op: RoundOp,
  decimals: number,
): RoundResult {
  const d = Math.max(0, Math.trunc(decimals));
  let changed = 0;
  const out = rows.map((row) => {
    let next: GridRow | null = null;
    for (const attr of attrs) {
      const n = asFiniteNumber(row[attr]);
      if (n === null) continue;
      const v = applyOp(n, op, d);
      if (v !== n) {
        if (!next) next = { ...row };
        next[attr] = v;
        changed += 1;
      }
    }
    return next ?? row;
  });
  return { rows: out, changed };
}
