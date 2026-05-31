/**
 * Merge a backend-built `WorkbookFragment` into the current in-memory model.
 *
 * Rules:
 *  - Static sheets get the new rows appended with name dedupe (existing rows
 *    win; new rows with colliding names get a `_2` / `_3` / … suffix).
 *  - The `carriers` sheet is unioned by name.
 *  - The `RAGNAROK_Provenance` sheet picks up one new row per fetch.
 *
 * Used by `App.handleApplyWorkbookFragment` when the user clicks
 * "Add to workbook" in the Data view.
 */
import { GridRow, Primitive, WorkbookModel } from '../types';
import { WorkbookFragment, ProvenanceRow } from '../api/databases';
import { PROVENANCE_SHEET } from './workbook';

const CARRIERS_SHEET = 'carriers';

function takenNames(rows: GridRow[]): Set<string> {
  const out = new Set<string>();
  for (const r of rows) {
    const name = r.name;
    if (typeof name === 'string' && name) out.add(name);
  }
  return out;
}

function dedupeName(name: string, taken: Set<string>): string {
  if (!taken.has(name)) {
    taken.add(name);
    return name;
  }
  let i = 2;
  while (taken.has(`${name}_${i}`)) i++;
  const out = `${name}_${i}`;
  taken.add(out);
  return out;
}

function appendWithDedupe(
  existing: GridRow[],
  incoming: Array<Record<string, unknown>>,
  rename: Map<string, string>,
  sheetKey: string,
): GridRow[] {
  const taken = takenNames(existing);
  const out = [...existing];
  for (const raw of incoming) {
    const row: GridRow = {};
    for (const [k, v] of Object.entries(raw)) {
      row[k] = v as Primitive;
    }
    const name = typeof row.name === 'string' ? row.name : null;
    if (name) {
      const finalName = dedupeName(name, taken);
      if (finalName !== name) rename.set(`${sheetKey}::${name}`, finalName);
      row.name = finalName;
    }
    out.push(row);
  }
  return out;
}

function unionCarriers(existing: GridRow[], incoming: Array<Record<string, unknown>>): GridRow[] {
  const byName = new Map<string, GridRow>();
  for (const r of existing) {
    const name = typeof r.name === 'string' ? r.name : null;
    if (name) byName.set(name, r);
  }
  for (const raw of incoming) {
    const name = typeof raw.name === 'string' ? raw.name : null;
    if (!name || byName.has(name)) continue;
    const row: GridRow = {};
    for (const [k, v] of Object.entries(raw)) {
      row[k] = v as Primitive;
    }
    byName.set(name, row);
  }
  return Array.from(byName.values());
}

function appendProvenanceRow(existing: GridRow[], provenance: ProvenanceRow): GridRow[] {
  const row: GridRow = {
    database_id: provenance.database_id,
    country_iso: provenance.country_iso,
    country_name: provenance.country_name,
    filters_json: provenance.filters_json,
    convert_options_json: provenance.convert_options_json,
    fetch_timestamp: provenance.fetch_timestamp,
    row_counts_json: provenance.row_counts_json,
    kind: 'data-import',
  };
  return [...existing, row];
}

/**
 * Pure merge. Returns a new model; does not mutate `model`. Renamed component
 * names are propagated through bus / bus0 / bus1 references in the same
 * fragment (so a generator whose bus gets renamed still points at the new
 * name).
 */
export function mergeWorkbookFragment(
  model: WorkbookModel,
  fragment: WorkbookFragment,
): WorkbookModel {
  const out: WorkbookModel = { ...model };
  const rename = new Map<string, string>();

  // Process buses first so generator/line references can rewrite to renamed buses.
  const sheetOrder = ['buses', ...Object.keys(fragment.sheets).filter((s) => s !== 'buses' && s !== CARRIERS_SHEET)];
  for (const sheet of sheetOrder) {
    const incoming = fragment.sheets[sheet];
    if (!incoming || incoming.length === 0) continue;
    const rewritten = incoming.map((raw) => {
      const row: Record<string, unknown> = { ...raw };
      for (const ref of ['bus', 'bus0', 'bus1', 'bus2', 'bus3', 'bus4']) {
        const v = row[ref];
        if (typeof v === 'string') {
          const renamed = rename.get(`buses::${v}`);
          if (renamed) row[ref] = renamed;
        }
      }
      return row;
    });
    const existing = (out[sheet] || []) as GridRow[];
    out[sheet] = appendWithDedupe(existing, rewritten, rename, sheet);
  }

  if (fragment.sheets[CARRIERS_SHEET]) {
    out[CARRIERS_SHEET] = unionCarriers(
      (out[CARRIERS_SHEET] || []) as GridRow[],
      fragment.sheets[CARRIERS_SHEET],
    );
  }

  if (fragment.provenance) {
    out[PROVENANCE_SHEET] = appendProvenanceRow(
      (out[PROVENANCE_SHEET] || []) as GridRow[],
      fragment.provenance,
    );
  }

  return out;
}
