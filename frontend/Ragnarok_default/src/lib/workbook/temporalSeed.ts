/**
 * Seed an empty time-series sheet so a profile can be WRITTEN, not only imported.
 *
 * A temporal sheet's shape is not something a blank "add row" can invent: it needs
 * the model's own time axis in the `snapshot` column and one column per component
 * of its parent sheet. Without those rows the grid has nothing to render, so the
 * only way to create a profile was to import a CSV — you could not type one in.
 *
 * The time axis comes from the `snapshots` sheet rather than being generated, so a
 * seeded profile lines up with every other series in the model by construction.
 * `build_network` reindexes each series onto the snapshot index, and a row whose
 * label is not on that index is dropped — inventing timestamps here would produce
 * a profile that silently vanishes at solve time.
 */
import { GridRow } from 'lib/types';

/** Column names a workbook may use for the snapshot label, in priority order.
 *  Mirrors the backend's `_snapshots_index` / `_apply_ts_sheet`. */
const SNAPSHOT_KEYS = ['snapshot', 'name', 'datetime', 'timestep', 'index'] as const;

/** The snapshot label of one `snapshots` row, or '' when it carries none. */
export function snapshotLabel(row: GridRow): string {
  for (const key of SNAPSHOT_KEYS) {
    const value = (row as Record<string, unknown>)[key];
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      return String(value);
    }
  }
  return '';
}

/**
 * One seed row per snapshot: the label plus a blank cell per component.
 *
 * Cells are left EMPTY rather than zero-filled. A zero is a real value — a
 * zero-filled `p_max_pu` pins every generator to no output, and a zero `p_set`
 * silently deletes demand — whereas a blank reads as "not set yet", which is
 * what a sheet the user is about to fill in actually means.
 *
 * @param snapshotRows - the model's `snapshots` sheet.
 * @param componentNames - `name` of every row in the parent component sheet.
 * @returns rows ready to send as `addRow` ops, or `[]` when there is no time axis.
 */
export function seedTemporalRows(
  snapshotRows: readonly GridRow[] | undefined,
  componentNames: readonly string[],
): GridRow[] {
  if (!snapshotRows || snapshotRows.length === 0) return [];
  // Duplicate labels would make the series unreindexable (a pathway workbook
  // lists each timestep once per period); keep the first of each, as the
  // backend's single-period path does.
  const seen = new Set<string>();
  const rows: GridRow[] = [];
  for (const snapshotRow of snapshotRows) {
    const label = snapshotLabel(snapshotRow);
    if (!label || seen.has(label)) continue;
    seen.add(label);
    const row: Record<string, unknown> = { snapshot: label };
    for (const name of componentNames) {
      if (name) row[name] = '';
    }
    rows.push(row as GridRow);
  }
  return rows;
}
