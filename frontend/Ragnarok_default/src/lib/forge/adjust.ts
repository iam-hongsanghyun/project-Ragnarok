import { GridRow, WorkbookModel } from 'lib/types';

/**
 * Bulk value adjustment for the Forge workspace.
 *
 * An {@link Adjustment} targets one sheet, narrows its rows with zero or more
 * equality {@link AdjustFilter}s (ANDed; e.g. carrier = "gas" AND province =
 * "경상남도"), and rescales one numeric attribute (e.g. `p_nom`) by an action:
 * multiply by a percentage, add a delta, or set an absolute value.
 *
 * The logic is pure so it is unit-tested directly; the panel in
 * `ForgeView.features/AdjustPanel.tsx` is the thin UI around it.
 */

export type AdjustAction = 'multiply' | 'add' | 'set';

/** Equality match on a column's (stringified) value. Blank column/value = no-op. */
export interface AdjustFilter {
  column: string;
  value: string;
}

export interface Adjustment {
  id: string;
  sheet: string;
  filters: AdjustFilter[];
  /** Numeric attribute to change (e.g. `p_nom`). */
  attribute: string;
  action: AdjustAction;
  /** multiply: percent (100 = unchanged); add: delta; set: absolute value. */
  amount: number;
}

/** Union of all column keys present across the rows, sorted. */
export function columnsOf(rows: GridRow[]): string[] {
  const keys = new Set<string>();
  for (const row of rows) {
    if (row && typeof row === 'object') for (const k of Object.keys(row)) keys.add(k);
  }
  return Array.from(keys).sort();
}

/** Distinct, non-blank stringified values of `column` across the rows, sorted. */
export function uniqueValues(rows: GridRow[], column: string): string[] {
  if (!column) return [];
  const seen = new Set<string>();
  for (const row of rows) {
    const v = row?.[column];
    if (v === undefined || v === null) continue;
    const s = String(v).trim();
    if (s) seen.add(s);
  }
  return Array.from(seen).sort((a, b) => a.localeCompare(b));
}

/** Row passes when it equals every filter that has both a column and a value. */
export function rowMatches(row: GridRow, filters: AdjustFilter[]): boolean {
  return filters.every((f) => {
    if (!f.column || f.value === '' || f.value === undefined || f.value === null) return true;
    return String(row?.[f.column] ?? '').trim() === String(f.value).trim();
  });
}

/** Apply one action to a numeric current value. */
export function applyAction(current: number, action: AdjustAction, amount: number): number {
  switch (action) {
    case 'multiply': return current * (amount / 100);
    case 'add': return current + amount;
    default: return amount; // 'set'
  }
}

export interface AdjustResult {
  /** Only the sheets that changed, ready for `onApplySheets`. */
  sheets: Record<string, GridRow[]>;
  /** Total cells changed across all adjustments. */
  changed: number;
  /** Cells changed per adjustment, in input order. */
  perAdjustment: number[];
}

/**
 * Apply adjustments in order onto a copy of the model — later adjustments see
 * earlier ones' results (so stacked edits on the same sheet compose). Rows are
 * never mutated in place. For multiply/add a row is skipped when its attribute
 * isn't a finite number; `set` always writes.
 */
export function applyAdjustments(model: WorkbookModel, adjustments: Adjustment[]): AdjustResult {
  const working: Record<string, GridRow[]> = {};
  const perAdjustment: number[] = [];
  let changed = 0;

  for (const adj of adjustments) {
    if (!adj.sheet || !adj.attribute) { perAdjustment.push(0); continue; }
    const rows = working[adj.sheet] ?? (model[adj.sheet] ?? []).map((r) => ({ ...r }));
    working[adj.sheet] = rows;

    let count = 0;
    for (const row of rows) {
      if (!rowMatches(row, adj.filters)) continue;
      const current = Number(row[adj.attribute]);
      if (adj.action !== 'set' && !Number.isFinite(current)) continue;
      const next = applyAction(Number.isFinite(current) ? current : 0, adj.action, adj.amount);
      if (next !== current || !Number.isFinite(current)) {
        row[adj.attribute] = next;
        count += 1;
      }
    }
    perAdjustment.push(count);
    changed += count;
  }

  // Drop sheets that ended up unchanged so callers merge only real edits.
  const touched: Record<string, GridRow[]> = {};
  adjustments.forEach((adj, i) => {
    if (perAdjustment[i] > 0 && working[adj.sheet]) touched[adj.sheet] = working[adj.sheet];
  });
  return { sheets: touched, changed, perAdjustment };
}

/** How many rows the adjustment's filters currently match (for the UI preview). */
export function matchCount(model: WorkbookModel, sheet: string, filters: AdjustFilter[]): number {
  const rows = model[sheet] ?? [];
  return rows.reduce((n, row) => (rowMatches(row, filters) ? n + 1 : n), 0);
}
