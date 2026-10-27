/**
 * Merge freshly imported time-series rows INTO a series sheet that already exists.
 *
 * A profile CSV usually carries only some of a sheet's component columns (one
 * generator's profile, one year of a longer axis). Replacing the sheet with it
 * silently deleted every other column. This keeps all existing rows and columns:
 * a row whose snapshot label matches an existing row has the imported cells
 * written over it; labels the sheet does not have yet are appended as new rows.
 */
import type { GridRow } from 'lib/types';

/**
 * @param existing - rows currently in the session sheet (authoritative).
 * @param imported - rows parsed from the file; `labelKey` names its snapshot column.
 * @param labelKey - snapshot column name in BOTH row sets (callers rename first).
 */
export function mergeSeriesRows(existing: GridRow[], imported: GridRow[], labelKey: string): GridRow[] {
  const indexByLabel = new Map<string, number>();
  const out: GridRow[] = existing.map((row, i) => {
    indexByLabel.set(String(row[labelKey] ?? ''), i);
    return { ...row };
  });
  for (const row of imported) {
    const label = String(row[labelKey] ?? '');
    const at = indexByLabel.get(label);
    if (at === undefined) {
      indexByLabel.set(label, out.length);
      out.push({ ...row });
    } else {
      out[at] = { ...out[at], ...row };
    }
  }
  return out;
}
