/**
 * Merge a backend-built `WorkbookFragment` into the current in-memory model.
 *
 * Rules:
 *  - Static sheets get the new rows appended with name dedupe (existing rows
 *    win; new rows with colliding names get a `_2` / `_3` / … suffix).
 *  - The `carriers` sheet is unioned by name. When a carrier already exists
 *    its attributes are MERGED: an existing non-empty value wins and only
 *    empty/missing cells are filled from the fragment — except for the
 *    fuel-price importer (`provenance.database_id === 'fuel_prices'`), whose
 *    values deliberately overwrite (the user just typed fresh prices).
 *  - Fuel-price fragments also set, for every existing generator whose
 *    `carrier` has a `fuel_cost_thermal`, `marginal_cost = fuel_cost_thermal /
 *    efficiency` (efficiency blank/<=0 -> 1). Provenance stays on the carrier
 *    row (`raw_price`, `raw_unit`, `fuel_cost_basis`) and the provenance sheet.
 *  - The `RAGNAROK_Provenance` sheet picks up one new row per fetch.
 *  - When the fragment carries `snapshots`, the workbook's `snapshots` sheet
 *    is unioned with the imported range (lexical sort on ISO-`T` strings)
 *    and temporal sheets are widened to cover the union. For snapshot
 *    hours the importer doesn't cover, columns are padded based on the
 *    temporal-sheet kind: `loads-p_set` constant-extends from the nearest
 *    known value (so the optimiser can still solve), `generators-p_max_pu`
 *    pads with 1.0 (no curtailment), everything else stays empty.
 *
 * Used by `App.handleApplyWorkbookFragment` when the user clicks
 * "Add to workbook" in the Data view.
 *
 * The authoritative implementation is the backend's
 * (`POST /api/session/merge-fragment`, `backend/app/fragment_merge.py`), shared
 * with the MCP server: the UI calls `mergeWorkbookFragmentRemote`. The local
 * `mergeWorkbookFragment` below is only the fallback for an unreachable backend.
 */
import { GridRow, Primitive, WorkbookModel } from '../types';
import { WorkbookFragment, ProvenanceRow } from '../api/databases';
import { PROVENANCE_SHEET } from 'lib/workbook/workbook';
import { API_BASE } from 'lib/constants';

const CARRIERS_SHEET = 'carriers';
const SNAPSHOTS_SHEET = 'snapshots';

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

const FUEL_PRICES_DB = 'fuel_prices';

function isFilled(v: unknown): boolean {
  return v !== undefined && v !== null && v !== '';
}

/** Union by name. An existing carrier is merged attribute-wise: existing
 *  non-empty values win, empty ones are filled from the fragment; with
 *  `overwrite` (fuel-price importer) the fragment's non-empty values win. */
function unionCarriers(
  existing: GridRow[],
  incoming: Array<Record<string, unknown>>,
  overwrite = false,
): GridRow[] {
  const byName = new Map<string, GridRow>();
  for (const r of existing) {
    const name = typeof r.name === 'string' ? r.name : null;
    if (name) byName.set(name, { ...r });
  }
  const unnamed = existing.filter((r) => typeof r.name !== 'string' || !r.name);
  for (const raw of incoming) {
    const name = typeof raw.name === 'string' ? raw.name : null;
    if (!name) continue;
    const row = byName.get(name);
    if (!row) {
      const fresh: GridRow = {};
      for (const [k, v] of Object.entries(raw)) fresh[k] = v as Primitive;
      byName.set(name, fresh);
      continue;
    }
    for (const [k, v] of Object.entries(raw)) {
      if (k === 'name' || !isFilled(v)) continue;
      if (overwrite || !isFilled(row[k])) row[k] = v as Primitive;
    }
  }
  return [...Array.from(byName.values()), ...unnamed];
}

/** Fuel-price fragments: every generator of a priced carrier gets
 *  `marginal_cost = fuel_cost_thermal / efficiency`. */
function applyFuelCostToGenerators(
  generators: GridRow[],
  carriers: Array<Record<string, unknown>>,
): GridRow[] {
  const thermal = new Map<string, number>();
  for (const c of carriers) {
    const n = typeof c.name === 'string' ? c.name : null;
    const t = Number(c.fuel_cost_thermal);
    if (n && isFilled(c.fuel_cost_thermal) && Number.isFinite(t)) thermal.set(n, t);
  }
  if (thermal.size === 0) return generators;
  return generators.map((g) => {
    const carrier = typeof g.carrier === 'string' ? g.carrier : '';
    const t = thermal.get(carrier);
    if (t === undefined) return g;
    let eff = isFilled(g.efficiency) ? Number(g.efficiency) : 1;
    if (!(eff > 0)) eff = 1;
    return { ...g, marginal_cost: Math.round((t / eff) * 1e4) / 1e4 };
  });
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

// ── Snapshot / temporal-sheet helpers ───────────────────────────────────────

/** True when the sheet name follows the PyPSA `<list>-<attr>` convention
 * and at least one row carries a `snapshot` column. */
function isTemporalSheet(name: string, rows: Array<Record<string, unknown>>): boolean {
  if (!name.includes('-')) return false;
  for (const r of rows) {
    if ('snapshot' in r) return true;
  }
  return false;
}

type PadMode = 'constant' | 'one' | 'empty';

function padModeForSheet(sheet: string): PadMode {
  // `<componentSheet>-<attribute>`
  const [component, attribute] = sheet.split('-');
  if (component === 'loads' && attribute === 'p_set') return 'constant';
  if (component === 'generators' && attribute === 'p_max_pu') return 'one';
  return 'empty';
}

function existingSnapshots(model: WorkbookModel): string[] {
  const rows = (model[SNAPSHOTS_SHEET] || []) as GridRow[];
  const out: string[] = [];
  for (const r of rows) {
    const s = r.snapshot;
    if (typeof s === 'string' && s) out.push(s);
  }
  return out;
}

function unionAndSort(a: string[], b: string[]): string[] {
  const set = new Set<string>(a);
  for (const x of b) set.add(x);
  return Array.from(set).sort();
}

function indexBySnapshot(rows: Array<Record<string, unknown>>): Map<string, Record<string, unknown>> {
  const out = new Map<string, Record<string, unknown>>();
  for (const r of rows) {
    const s = r.snapshot;
    if (typeof s === 'string' && s) out.set(s, r);
  }
  return out;
}

/** Constant-extend: find the nearest defined value for `column` in `imported`
 *  relative to `snap`. Searches backwards then forwards in the sorted
 *  imported snapshot list. Returns null when the column has no values at all. */
function nearestImportedValue(
  imported: Map<string, Record<string, unknown>>,
  importedSorted: string[],
  snap: string,
  column: string,
): Primitive | null {
  // Binary-walk for nearest above-or-equal.
  let lo = 0;
  let hi = importedSorted.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (importedSorted[mid] < snap) lo = mid + 1;
    else hi = mid - 1;
  }
  const after = importedSorted[lo];
  const before = importedSorted[lo - 1];
  const candidates = [before, after].filter((s) => typeof s === 'string');
  for (const cand of candidates) {
    const row = imported.get(cand);
    if (row && row[column] !== undefined && row[column] !== null && row[column] !== '') {
      return row[column] as Primitive;
    }
  }
  // Fall back to scanning (covers the case where the nearest two are missing).
  for (const cand of importedSorted) {
    const row = imported.get(cand);
    if (row && row[column] !== undefined && row[column] !== null && row[column] !== '') {
      return row[column] as Primitive;
    }
  }
  return null;
}

function mergeTemporalSheet(
  existing: GridRow[],
  incoming: Array<Record<string, unknown>>,
  union: string[],
  padMode: PadMode,
): GridRow[] {
  const existingMap = indexBySnapshot(existing);
  const incomingMap = indexBySnapshot(incoming);
  const incomingSorted = Array.from(incomingMap.keys()).sort();

  const columnsExisting = new Set<string>();
  for (const r of existing) {
    for (const k of Object.keys(r)) if (k !== 'snapshot') columnsExisting.add(k);
  }
  const columnsIncoming = new Set<string>();
  for (const r of incoming) {
    for (const k of Object.keys(r)) if (k !== 'snapshot') columnsIncoming.add(k);
  }

  const out: GridRow[] = [];
  for (const snap of union) {
    const row: GridRow = { snapshot: snap };
    const eRow = existingMap.get(snap);
    const iRow = incomingMap.get(snap);
    Array.from(columnsExisting).forEach((col) => {
      const v = eRow ? eRow[col] : undefined;
      if (v !== undefined && v !== null && v !== '') row[col] = v as Primitive;
    });
    for (const col of Array.from(columnsIncoming)) {
      const v = iRow ? iRow[col] : undefined;
      if (v !== undefined && v !== null && v !== '') {
        row[col] = v as Primitive;
        continue;
      }
      if (row[col] !== undefined) continue; // existing already filled
      if (padMode === 'one') {
        row[col] = 1.0;
      } else if (padMode === 'constant') {
        const pad = nearestImportedValue(incomingMap, incomingSorted, snap, col);
        if (pad !== null) row[col] = pad;
      }
      // padMode 'empty' → column stays out
    }
    out.push(row);
  }
  return out;
}

function rewriteSnapshotsSheet(model: WorkbookModel, union: string[]): GridRow[] {
  const existing = (model[SNAPSHOTS_SHEET] || []) as GridRow[];
  const byName = new Map<string, GridRow>();
  for (const r of existing) {
    const s = r.snapshot;
    if (typeof s === 'string') byName.set(s, r);
  }
  return union.map((s) => byName.get(s) || { snapshot: s });
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

  // Separate static vs temporal sheets so we can apply different merge rules.
  const sheetNames = Object.keys(fragment.sheets);
  const temporalSheets = sheetNames.filter((s) =>
    isTemporalSheet(s, fragment.sheets[s]),
  );
  const staticSheets = sheetNames.filter((s) => !temporalSheets.includes(s));

  // ── Static sheets first ────────────────────────────────────────────────
  // Process buses ahead of others so bus references in the same fragment can
  // rewrite to renamed buses.
  const staticOrder = [
    'buses',
    ...staticSheets.filter((s) => s !== 'buses' && s !== CARRIERS_SHEET),
  ];
  for (const sheet of staticOrder) {
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
    const fuelPrices = fragment.provenance?.database_id === FUEL_PRICES_DB;
    out[CARRIERS_SHEET] = unionCarriers(
      (out[CARRIERS_SHEET] || []) as GridRow[],
      fragment.sheets[CARRIERS_SHEET],
      fuelPrices,
    );
    if (fuelPrices && Array.isArray(out.generators)) {
      out.generators = applyFuelCostToGenerators(
        out.generators as GridRow[],
        fragment.sheets[CARRIERS_SHEET],
      );
    }
  }

  // ── Snapshots + temporal sheets ────────────────────────────────────────
  if (fragment.snapshots && fragment.snapshots.length > 0) {
    const importedSnapshots = fragment.snapshots;
    const existing = existingSnapshots(out);
    const union = unionAndSort(existing, importedSnapshots);
    out[SNAPSHOTS_SHEET] = rewriteSnapshotsSheet(out, union);

    for (const sheet of temporalSheets) {
      const incoming = fragment.sheets[sheet];
      const existingRows = (out[sheet] || []) as GridRow[];
      out[sheet] = mergeTemporalSheet(existingRows, incoming, union, padModeForSheet(sheet));
    }
  } else {
    // Static-only fragment: temporal sheets (rare for non-hourly imports)
    // get appended row-wise.
    for (const sheet of temporalSheets) {
      const incoming = fragment.sheets[sheet];
      const existing = (out[sheet] || []) as GridRow[];
      out[sheet] = [...existing, ...(incoming as GridRow[])];
    }
  }

  if (fragment.provenance) {
    out[PROVENANCE_SHEET] = appendProvenanceRow(
      (out[PROVENANCE_SHEET] || []) as GridRow[],
      fragment.provenance,
    );
  }

  return out;
}


/** Sheets a fragment merge can read or write: the fragment's own sheets plus the
 *  ones the merge rules touch implicitly (carriers/snapshots/provenance, buses
 *  for renames, generators for fuel-price re-pricing). Sending only these keeps
 *  the request small. */
function touchedSheets(fragment: WorkbookFragment): string[] {
  return Array.from(new Set([
    ...Object.keys(fragment.sheets),
    'buses', CARRIERS_SHEET, SNAPSHOTS_SHEET, 'generators', PROVENANCE_SHEET,
  ]));
}

/**
 * Merge a fragment via the backend (the single implementation shared with MCP).
 * Returns `model` with the merged sheets replaced. Falls back to the local
 * merge only when the backend cannot be reached (network error); an HTTP error
 * from the backend is thrown, not papered over.
 */
export async function mergeWorkbookFragmentRemote(
  model: WorkbookModel,
  fragment: WorkbookFragment,
): Promise<WorkbookModel> {
  const subset: Record<string, unknown> = {};
  for (const sheet of touchedSheets(fragment)) {
    const rows = (model as Record<string, unknown>)[sheet];
    if (Array.isArray(rows)) subset[sheet] = rows;
  }
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}/api/session/merge-fragment`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: subset, fragment }),
    });
  } catch {
    return mergeWorkbookFragment(model, fragment);
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json())?.detail ?? detail; } catch { /* non-JSON */ }
    throw new Error(`Merge failed (${resp.status}): ${detail}`);
  }
  const body = (await resp.json()) as { model: Record<string, GridRow[]> };
  return { ...model, ...body.model } as WorkbookModel;
}
