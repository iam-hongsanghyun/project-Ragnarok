import * as XLSX from 'xlsx';
import { PYPSA_SCHEMA_META, SHEETS, TS_SHEETS } from 'lib/constants';
import {
  isInputTemporalSheet,
  normalizeSheetName,
  stripOutputStaticAttributes,
  PYPSA_COMPONENT_BY_SHEET,
} from 'lib/constants/pypsa_schema';
import type { AppSettings, DateFormat } from 'lib/settings/types';
import { CustomConstraint, GridRow, Primitive, ProjectImportProvenance, ProjectRunState, RunResults, WorkbookModel } from '../types';
import { normalizeDateToIso } from 'lib/utils/helpers';
import { PATHWAY_CONFIG_SHEET, PATHWAY_PERIODS_SHEET } from 'lib/results/pathway';
import { ROLLING_CONFIG_SHEET } from 'lib/results/rolling';
import { SCENARIO_SHEET } from 'lib/results/scenarios';
import { CARBON_LIBRARY_SHEET } from 'lib/results/carbonLibrary';

export const RESULT_META_SHEET = 'RAGNAROK_ResultMeta';
export const PLUGIN_ANALYTICS_SHEET = 'RAGNAROK_PluginAnalytics';
export const PLUGIN_CONFIGS_SHEET = 'RAGNAROK_PluginConfigs';
export const SETTINGS_SHEET = 'RAGNAROK_Settings';
export const CONSTRAINTS_SHEET = 'RAGNAROK_Constraints';
export const RUN_STATE_SHEET = 'RAGNAROK_RunState';
export const RUN_HISTORY_SHEET = 'RAGNAROK_RunHistory';
export const PROVENANCE_SHEET = 'RAGNAROK_Provenance';

export function normalizeCell(value: unknown): Primitive {
  if (value === undefined || value === null) return null;
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return value;
  // SheetJS returns Date instances for cells of type 'd' when raw:true. Emit
  // ISO-`T` directly so downstream canonicalisation is a no-op and the data
  // table displays the canonical form.
  if (value instanceof Date) {
    const d = value as Date;
    const pad = (n: number) => (n < 10 ? `0${n}` : String(n));
    return (
      `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
      `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
    );
  }
  return String(value);
}

// Excel hard-limits any single cell to 32,767 characters. Long JSON payloads
// (results, plugin data, run history) are split into chunks written across
// multiple rows (with a `part` index) and reassembled in order on import.
const MAX_CELL_CHARS = 30000;

function chunkText(text: string): string[] {
  if (text.length <= MAX_CELL_CHARS) return [text];
  const parts: string[] = [];
  for (let i = 0; i < text.length; i += MAX_CELL_CHARS) parts.push(text.slice(i, i + MAX_CELL_CHARS));
  return parts;
}

// Central temporal normalisation/export config.
const TEMPORAL_CONFIG = {
  snapshotColumn: 'snapshot',
  periodColumn: 'period',
  defaultTimeSuffix: 'T00:00:00',
} as const;
const SNAPSHOT_COL = TEMPORAL_CONFIG.snapshotColumn;
const PERIOD_COL = TEMPORAL_CONFIG.periodColumn;

function normalizeSnapshotIso(raw: string, fmt: DateFormat): string {
  const iso = normalizeDateToIso(raw, fmt);
  return /^\d{4}-\d{2}-\d{2}$/.test(iso)
    ? `${iso}${TEMPORAL_CONFIG.defaultTimeSuffix}`
    : iso;
}

/**
 * True iff ANY row in the set carries a ``snapshot`` column. We do not look
 * only at the first row — a malformed plugin sheet might have an empty first
 * row but still be temporal. Detection is by column existence only (no
 * heuristic name list); the canonical PyPSA index name is ``snapshot``.
 */
export function hasSnapshotColumn(rows: GridRow[] | undefined): boolean {
  if (!rows || rows.length === 0) return false;
  for (const row of rows) {
    if (SNAPSHOT_COL in row) return true;
  }
  return false;
}

/**
 * Pin ``period`` (when present) then ``snapshot`` as the leading columns so
 * SheetJS / Excel column order is stable and PyPSA-conventional across input
 * and output sheets.
 */
export function orderTemporalRow(row: GridRow): GridRow {
  const ordered: GridRow = {};
  if (row[PERIOD_COL] !== undefined && row[PERIOD_COL] !== null && row[PERIOD_COL] !== '') {
    ordered[PERIOD_COL] = row[PERIOD_COL];
  }
  if (SNAPSHOT_COL in row) {
    ordered[SNAPSHOT_COL] = row[SNAPSHOT_COL];
  }
  for (const [key, value] of Object.entries(row)) {
    if (key === PERIOD_COL || key === SNAPSHOT_COL) continue;
    ordered[key] = value;
  }
  return ordered;
}

/**
 * Canonicalise a temporal sheet to the PyPSA shape: ISO-8601 (`T`-separated)
 * ``snapshot`` values, with ``period?`` then ``snapshot`` as the leading
 * columns. Sheets without a ``snapshot`` column (every static sheet) are
 * returned unchanged.
 *
 * Accepts any plausible source type for the ``snapshot`` value (string from
 * SheetJS-with-raw:false, JavaScript Date from raw cells of type 'd', or an
 * Excel serial number) and emits an ISO-`T` string regardless.
 */
export function canonicalizeTemporalRows(rows: GridRow[], fmt: DateFormat): GridRow[] {
  if (!hasSnapshotColumn(rows)) return rows;
  return rows.map((row) => {
    const copy = { ...row };
    const v: unknown = copy[SNAPSHOT_COL];
    if (typeof v === 'string') {
      copy[SNAPSHOT_COL] = normalizeSnapshotIso(v, fmt);
    } else if (v instanceof Date) {
      copy[SNAPSHOT_COL] = isoFromDate(v);
    } else if (typeof v === 'number' && Number.isFinite(v)) {
      // Excel date serial → JS Date → ISO-T.
      const d = excelSerialToDate(v);
      if (d) copy[SNAPSHOT_COL] = isoFromDate(d);
    }
    return orderTemporalRow(copy);
  });
}

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

function isoFromDate(d: Date): string {
  return (
    `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}` +
    `T${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`
  );
}

/** Convert an Excel date serial (days since 1899-12-30, fractional = time-of-day). */
function excelSerialToDate(serial: number): Date | null {
  if (!Number.isFinite(serial) || serial <= 0) return null;
  const epoch = Date.UTC(1899, 11, 30);
  const ms = epoch + Math.round(serial * 86400 * 1000);
  const d = new Date(ms);
  // Render in local time (xlsx serials carry no zone); shift back.
  return new Date(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds());
}

/** Back-compat alias: every temporal sheet (input, output, or `snapshots`) is
 *  canonicalised by the same `snapshot`-gated transform. */
export const prepareTemporalRowsForExport = canonicalizeTemporalRows;

/** Stable temporal column header for SheetJS export (`period?`, `snapshot`, then data cols). */
export function temporalHeader(rows: GridRow[]): string[] {
  if (!rows.length) return [];
  const ordered = new Set<string>();
  rows.forEach((row) => Object.keys(row).forEach((key) => ordered.add(key)));
  const keys = Array.from(ordered);
  const rest = keys.filter((key) => key !== PERIOD_COL && key !== SNAPSHOT_COL);
  const header: string[] = [];
  if (keys.includes(PERIOD_COL)) header.push(PERIOD_COL);
  if (keys.includes(SNAPSHOT_COL)) header.push(SNAPSHOT_COL);
  return [...header, ...rest];
}

function temporalSheetRowsForExport(_sheet: string, rows: GridRow[], fmt: DateFormat): GridRow[] {
  // Self-gated: rows without a `snapshot` column (static sheets) pass through
  // untouched. Temporal sheets get ISO-`T` snapshot values and `period?` /
  // `snapshot` leading columns. No heuristic label-column fallback — by the
  // time data reaches export, every temporal sheet has been canonicalised at
  // the entry boundary (model load / project import / plugin / backend).
  return canonicalizeTemporalRows(rows, fmt);
}

function temporalSheetToWorksheet(rows: GridRow[]): XLSX.WorkSheet {
  const header = temporalHeader(rows);
  return header.length > 0
    ? XLSX.utils.json_to_sheet(rows, { header })
    : XLSX.utils.json_to_sheet(rows);
}

/**
 * Canonicalise every temporal dataset in a sheet-map IN PLACE: ISO-`T`
 * ``snapshot`` values and ``period?``, ``snapshot``, …rest column order. Each
 * sheet self-gates on the presence of a ``snapshot`` column, so static sheets
 * pass through untouched and no schema lookup is required. Idempotent.
 *
 * Applied at every boundary where temporal data enters the frontend — model
 * load, project import, plugin-produced file, backend run result, CSV import —
 * so the in-memory representation is uniformly canonical before display,
 * derivation, the backend POST, or an export.
 */
export function canonicalizeTemporalSheets(
  sheets: Record<string, GridRow[] | undefined>,
  fmt: DateFormat,
): void {
  for (const sheet of Object.keys(sheets)) {
    const rows = sheets[sheet];
    if (!hasSnapshotColumn(rows)) continue;
    sheets[sheet] = canonicalizeTemporalRows(rows as GridRow[], fmt);
  }
}

/** Canonicalise backend/imported output time-series (`outputs.series`) in place. */
export function canonicalizeOutputSeries(
  series: Record<string, GridRow[]>,
  fmt: DateFormat,
): void {
  canonicalizeTemporalSheets(series, fmt);
}

/**
 * Canonicalise every temporal sheet of a workbook model in place: ISO-`T`
 * ``snapshot`` values + ``period?``/``snapshot`` leading column order. A sheet
 * is considered temporal iff it carries a ``snapshot`` column. Sheets without
 * one are NEVER mutated — we do not invent a snapshot index. No schema lookup,
 * no input/output gate: any in-memory sheet-map (raw model, plugin preview,
 * backend output series) flows through the same transform.
 */
export function normalizeInputDatesToIso(model: WorkbookModel, fmt: DateFormat): void {
  canonicalizeTemporalSheets(model as unknown as Record<string, GridRow[] | undefined>, fmt);
}

/**
 * Standard PyPSA component sheets the UI references directly
 * (`model.buses`, `model.generators`, …). This is a STRUCTURAL SAFETY
 * NET, not a schema source — the live PyPSA schema from the backend
 * remains the only authority for each sheet's attributes, columns,
 * ordering, defaults, and validation. This list exists purely so that
 * a freshly-created model always has an array (never `undefined`) for
 * each universal component, even in the brief window before the boot
 * schema is applied or if a model is built from an unexpectedly-empty
 * schema. Without it, every `model.<sheet>.map()` in the views throws.
 */
export const CORE_COMPONENT_SHEETS: readonly string[] = [
  'buses',
  'carriers',
  'generators',
  'loads',
  'lines',
  'links',
  'transformers',
  'storage_units',
  'stores',
  'global_constraints',
  'shunt_impedances',
  'shapes',
  'sub_networks',
  'snapshots',
];

export function createEmptyWorkbook(): WorkbookModel {
  // Core sheets first (always present), then whatever the live schema
  // declares (which normally is a superset). Spreading SHEETS last means
  // the schema-driven set wins when both define a sheet, but the core
  // floor guarantees the universal components exist regardless of schema
  // load timing.
  const core = Object.fromEntries(CORE_COMPONENT_SHEETS.map((s) => [s, []]));
  const base = Object.fromEntries(SHEETS.map((s) => [s, []]));
  const ts = Object.fromEntries(TS_SHEETS.map((s) => [s, []]));
  return {
    ...core,
    ...base,
    ...ts,
    [PATHWAY_CONFIG_SHEET]: [],
    [PATHWAY_PERIODS_SHEET]: [],
    [ROLLING_CONFIG_SHEET]: [],
    [SCENARIO_SHEET]: [],
    [CARBON_LIBRARY_SHEET]: [],
  } as WorkbookModel;
}

export function parseSheets(workbook: ReturnType<typeof XLSX.read>): WorkbookModel {
  const model = createEmptyWorkbook();
  workbook.SheetNames.forEach((sheetName) => {
    const canonical = normalizeSheetName(sheetName);
    const ws = workbook.Sheets[sheetName];
    if (!ws) return;
    const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(ws, { defval: null });
    (model as any)[canonical] = rows.map((row) =>
      Object.fromEntries(Object.entries(row).map(([key, value]) => [key, normalizeCell(value)])),
    );
  });
  return model;
}

export function parseWorkbook(file: File): Promise<WorkbookModel> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const arrayBuffer = event.target?.result;
        if (!(arrayBuffer instanceof ArrayBuffer)) {
          reject(new Error('Could not read workbook.'));
          return;
        }
        const wb = XLSX.read(arrayBuffer, { type: 'array', cellDates: true });
        resolve(parseSheets(wb));
      } catch (error) {
        reject(error instanceof Error ? error : new Error('Workbook import failed.'));
      }
    };
    reader.onerror = () => reject(new Error('Workbook import failed.'));
    reader.readAsArrayBuffer(file);
  });
}

/** Filter rows that are effectively empty (no `name`, or every cell blank). */
function nonEmptyRows(rows: GridRow[]): GridRow[] {
  return rows.filter((r) => {
    const nameRaw = r['name'];
    const name = typeof nameRaw === 'string' ? nameRaw.trim() : nameRaw;
    if (name !== undefined && name !== null && name !== '') return true;
    // No name — keep only if some other cell has a non-empty value (e.g. snapshots
    // sheet uses `snapshot` column instead of `name`).
    return Object.values(r).some((v) => v !== null && v !== undefined && v !== '');
  });
}

export function buildWorkbook(model: WorkbookModel, dateFormat: DateFormat = 'auto') {
  const workbook = XLSX.utils.book_new();
  SHEETS.forEach((sheet) => {
    const raw = nonEmptyRows((model[sheet] ?? []).map((row) => stripOutputStaticAttributes(sheet, row)));
    if (raw.length === 0) return;   // skip empty sheets entirely; PyPSA will treat them as absent
    const rows = temporalSheetRowsForExport(sheet, raw, dateFormat);
    const ws = XLSX.utils.json_to_sheet(rows);
    XLSX.utils.book_append_sheet(workbook, ws, sheet);
  });

  [...TS_SHEETS, ...Object.keys(model).filter((sheet) => isInputTemporalSheet(sheet) && !TS_SHEETS.includes(sheet))].forEach((sheet) => {
    const rows = (model as any)[sheet] as GridRow[] | undefined;
    if (!rows || rows.length === 0) return;
    const prepared = prepareTemporalRowsForExport(rows, dateFormat);
    const ws = temporalSheetToWorksheet(prepared);
    XLSX.utils.book_append_sheet(workbook, ws, sheet);
  });
  [PATHWAY_CONFIG_SHEET, PATHWAY_PERIODS_SHEET, ROLLING_CONFIG_SHEET, SCENARIO_SHEET, CARBON_LIBRARY_SHEET].forEach((sheet) => {
    const rows = (model as any)[sheet] as GridRow[] | undefined;
    if (!rows || rows.length === 0) return;
    const ws = XLSX.utils.json_to_sheet(rows);
    XLSX.utils.book_append_sheet(workbook, ws, sheet);
  });
  return workbook;
}

export function exportWorkbook(
  model: WorkbookModel,
  filename = 'ragnarok_case.xlsx',
  dateFormat: DateFormat = 'auto',
) {
  XLSX.writeFile(buildWorkbook(model, dateFormat), filename);
}

export function workbookToArrayBuffer(model: WorkbookModel, dateFormat: DateFormat = 'auto'): ArrayBuffer {
  return XLSX.write(buildWorkbook(model, dateFormat), { bookType: 'xlsx', type: 'array' }) as ArrayBuffer;
}

/**
 * Parse a CSV (or TSV) file into GridRow[] for use as a time-series sheet.
 *
 * Expected shape:
 *   Column 0  — snapshot label (ISO string, e.g. "2019-01-01T00:00:00")
 *   Columns 1+ — component names → numeric values
 *
 * SheetJS auto-detects comma vs tab delimiter.  BOM-prefixed files are handled
 * transparently.  All numeric cells are cast to `number`; the label column is
 * kept as `string`.  Unparseable numeric cells become `null`.
 */
export function parseDelimitedTextToGridRows(text: string): GridRow[] {
  const wb = XLSX.read(text, { type: 'string', raw: false });
  const ws = wb.Sheets[wb.SheetNames[0]];
  const raw = XLSX.utils.sheet_to_json<Record<string, unknown>>(ws, { defval: null });

  return raw.map((row) => {
    const entries = Object.entries(row).map(([k, v], i): [string, Primitive] => {
      if (i === 0) {
        // Snapshot label — keep as string
        return [k, v == null ? '' : String(v)];
      }
      // Numeric value column
      const n = typeof v === 'number' ? v : parseFloat(String(v ?? ''));
      return [k, Number.isFinite(n) ? n : null];
    });
    return Object.fromEntries(entries) as GridRow;
  });
}

export async function parseCsvToGridRows(file: File): Promise<GridRow[]> {
  return parseDelimitedTextToGridRows(await file.text());
}

// ─────────────────────────────────────────────────────────────────────────────
//  Project export / import — full input + output round-trip
// ─────────────────────────────────────────────────────────────────────────────
//
//  Export Project writes a PyPSA-native workbook that contains:
//    • Every input static sheet, with each row enriched by the matching solved
//      output static attributes (e.g. `p_nom_opt`) from `results.outputs.static`.
//    • Every input time-series sheet from the model.
//    • Every output time-series sheet from `results.outputs.series`
//      (e.g. `generators-p`, `buses-marginal_price`).
//
//  Import Project reverses this: it splits each component sheet's columns by
//  the schema's input/output classification, dropping the output static
//  columns back into `results.outputs.static[<list>][<comp>][<attr>]` and
//  feeding the input columns into the workbook model. Output time-series
//  sheets (`<list>-<output_attr>`) flow into `results.outputs.series`.

export type ProjectOutputs = NonNullable<RunResults['outputs']>;
export interface ProjectMetadata {
  narrative?: RunResults['narrative'];
  co2Shadow?: RunResults['co2Shadow'];
  pluginAnalytics?: RunResults['pluginAnalytics'];
  /** Per-plugin user config (the form values entered in each installed
   *  plugin's panel). Round-trips through Export Project / Import Project
   *  so a shared workbook reproduces the plugin state, not just the inputs
   *  / outputs. Keyed by plugin id. */
  pluginConfigs?: Record<string, Record<string, unknown>>;
  runMeta?: RunResults['runMeta'];
  pathway?: RunResults['pathway'];
  rolling?: RunResults['rolling'];
  settings?: AppSettings;
  constraints?: CustomConstraint[];
  runState?: ProjectRunState;
  provenance?: ProjectImportProvenance;
}

const EMPTY_OUTPUTS: ProjectOutputs = { static: {}, series: {} };
const EMPTY_METADATA: ProjectMetadata = {};

function isProjectMetadataSheet(sheetName: string): boolean {
  return [
    RESULT_META_SHEET,
    PLUGIN_ANALYTICS_SHEET,
    PLUGIN_CONFIGS_SHEET,
    SETTINGS_SHEET,
    CONSTRAINTS_SHEET,
    RUN_STATE_SHEET,
    RUN_HISTORY_SHEET,
    PROVENANCE_SHEET,
  ].includes(sheetName);
}

/** Schema-driven set of output static attributes per component sheet. */
function outputStaticAttrSet(sheet: string): Set<string> {
  const comp = PYPSA_COMPONENT_BY_SHEET[sheet];
  if (!comp) return new Set();
  return new Set(
    comp.attributes
      .filter((a) => a.status === 'output' && a.storage === 'static')
      .map((a) => a.attribute),
  );
}

/** Schema-driven set of output series attributes per component sheet. */
function outputSeriesAttrSet(sheet: string): Set<string> {
  const comp = PYPSA_COMPONENT_BY_SHEET[sheet];
  if (!comp) return new Set();
  return new Set(
    comp.attributes
      .filter((a) => a.status === 'output' && a.storage !== 'static')
      .map((a) => a.attribute),
  );
}

export function buildProjectWorkbook(
  model: WorkbookModel,
  outputs: ProjectOutputs = EMPTY_OUTPUTS,
  metadata: ProjectMetadata = EMPTY_METADATA,
): XLSX.WorkBook {
  const workbook = XLSX.utils.book_new();
  const dateFormat = metadata.settings?.dateFormat ?? 'auto';

  // ── Static component sheets: input columns + output columns merged ────
  SHEETS.forEach((sheet) => {
    const inputRows = (model[sheet] ?? []).map((r) => stripOutputStaticAttributes(sheet, r));
    const outputStaticForSheet = outputs.static[sheet] ?? {};
    const merged: GridRow[] = inputRows.map((row) => {
      const name = typeof row.name === 'string' ? row.name : String(row.name ?? '');
      const outAttrs = outputStaticForSheet[name];
      return outAttrs ? { ...row, ...outAttrs } : row;
    });
    // Add rows that exist in outputs but not in the input model (rare, e.g.
    // load-shedding generators auto-added by the backend).
    const inputNames = new Set(inputRows.map((r) => String(r.name ?? '')));
    Object.entries(outputStaticForSheet).forEach(([compName, attrs]) => {
      if (!inputNames.has(compName)) {
        merged.push({ name: compName, ...attrs });
      }
    });
    const rows = temporalSheetRowsForExport(sheet, nonEmptyRows(merged), dateFormat);
    if (rows.length === 0) return;
    const ws = XLSX.utils.json_to_sheet(rows);
    XLSX.utils.book_append_sheet(workbook, ws, sheet);
  });

  // ── Input time-series sheets ─────────────────────────────────────────
  const inputTsKeys = [
    ...TS_SHEETS,
    ...Object.keys(model).filter((s) => isInputTemporalSheet(s) && !TS_SHEETS.includes(s)),
  ];
  inputTsKeys.forEach((sheet) => {
    const rows = (model as any)[sheet] as GridRow[] | undefined;
    if (!rows || rows.length === 0) return;
    const prepared = prepareTemporalRowsForExport(rows, dateFormat);
    const ws = temporalSheetToWorksheet(prepared);
    XLSX.utils.book_append_sheet(workbook, ws, sheet);
  });

  // ── Output time-series sheets ────────────────────────────────────────
  Object.entries(outputs.series).forEach(([sheet, rows]) => {
    if (!rows || rows.length === 0) return;
    const prepared = prepareTemporalRowsForExport(rows, dateFormat);
    const ws = temporalSheetToWorksheet(prepared);
    XLSX.utils.book_append_sheet(workbook, ws, sheet);
  });

  [PATHWAY_CONFIG_SHEET, PATHWAY_PERIODS_SHEET, ROLLING_CONFIG_SHEET, SCENARIO_SHEET, CARBON_LIBRARY_SHEET].forEach((sheet) => {
    const rows = (model as any)[sheet] as GridRow[] | undefined;
    if (!rows || rows.length === 0) return;
    const ws = XLSX.utils.json_to_sheet(rows);
    XLSX.utils.book_append_sheet(workbook, ws, sheet);
  });

  const resultMetaEntries: Array<[string, unknown]> = [];
  if (metadata.runMeta) resultMetaEntries.push(['runMeta', metadata.runMeta]);
  if (metadata.pathway) resultMetaEntries.push(['pathway', metadata.pathway]);
  if (metadata.rolling) resultMetaEntries.push(['rolling', metadata.rolling]);
  if (metadata.co2Shadow) resultMetaEntries.push(['co2Shadow', metadata.co2Shadow]);
  if (metadata.narrative) resultMetaEntries.push(['narrative', metadata.narrative]);
  const resultMetaRows: GridRow[] = [];
  resultMetaEntries.forEach(([key, value]) => {
    chunkText(JSON.stringify(value)).forEach((chunk, part) => resultMetaRows.push({ key, part, json: chunk }));
  });
  if (resultMetaRows.length > 0) {
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(resultMetaRows), RESULT_META_SHEET);
  }

  const pluginRows: GridRow[] = [];
  Object.entries(metadata.pluginAnalytics ?? {}).forEach(([moduleId, entry]) => {
    const fields: Array<[string, string]> = [
      ['ui', JSON.stringify(entry.ui ?? {})],
      ['data', JSON.stringify(entry.data ?? {})],
    ];
    fields.forEach(([field, value]) => {
      chunkText(value).forEach((chunk, part) =>
        pluginRows.push({ moduleId, name: entry.name, field, part, value: chunk }),
      );
    });
  });
  if (pluginRows.length > 0) {
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(pluginRows), PLUGIN_ANALYTICS_SHEET);
  }

  // ── Plugin configs ─────────────────────────────────────────────────────
  // Per-plugin user form values. Chunked the same way as PluginAnalytics so
  // a long config payload doesn't hit Excel's 32 767-char cell limit.
  const pluginConfigRows: GridRow[] = [];
  Object.entries(metadata.pluginConfigs ?? {}).forEach(([moduleId, config]) => {
    if (!config || typeof config !== 'object') return;
    chunkText(JSON.stringify(config)).forEach((chunk, part) =>
      pluginConfigRows.push({ moduleId, part, json: chunk }),
    );
  });
  if (pluginConfigRows.length > 0) {
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(pluginConfigRows), PLUGIN_CONFIGS_SHEET);
  }

  if (metadata.settings) {
    const settingsRows: GridRow[] = Object.entries(metadata.settings).map(([key, value]) => ({ key, value }));
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(settingsRows), SETTINGS_SHEET);
  }

  if (metadata.constraints && metadata.constraints.length > 0) {
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(metadata.constraints), CONSTRAINTS_SHEET);
  }

  if (metadata.runState) {
    const runStateRows: GridRow[] = Object.entries(metadata.runState).map(([key, value]) => ({ key, value }));
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(runStateRows), RUN_STATE_SHEET);
  }

  // Run history is intentionally not exported: each entry's full RunResults is
  // large and redundant for re-analysis/re-run. The current run's analysis is
  // rebuilt from the exported `outputs` sheets on import, and a fresh
  // single-entry history is synthesized there.

  if (metadata.provenance) {
    const provenanceRows: GridRow[] = Object.entries(metadata.provenance).map(([key, value]) => ({ key, value }));
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(provenanceRows), PROVENANCE_SHEET);
  }

  return workbook;
}

/** Serialise a full project workbook to an ArrayBuffer (for the File System
 *  Access API, where the caller owns writing to a user-chosen file). */
export function projectWorkbookToArrayBuffer(
  model: WorkbookModel,
  outputs: ProjectOutputs | null | undefined,
  metadata: ProjectMetadata | null | undefined,
): ArrayBuffer {
  return XLSX.write(
    buildProjectWorkbook(model, outputs ?? EMPTY_OUTPUTS, metadata ?? EMPTY_METADATA),
    { bookType: 'xlsx', type: 'array' },
  ) as ArrayBuffer;
}

/**
 * Parse a project workbook back into `{ model, outputs }`. Output static
 * columns inside component sheets are split out into `outputs.static`;
 * `<list>-<output_attr>` sheets are routed to `outputs.series`.
 */
export function parseProjectWorkbook(
  arrayBuffer: ArrayBuffer,
): { model: WorkbookModel; outputs: ProjectOutputs; metadata: ProjectMetadata } {
  const wb = XLSX.read(arrayBuffer, { type: 'array', cellDates: true });
  const model = createEmptyWorkbook();
  const outputs: ProjectOutputs = { static: {}, series: {} };
  const metadata: ProjectMetadata = {};

  wb.SheetNames.forEach((sheetName) => {
    const canonical = normalizeSheetName(sheetName);
    const ws = wb.Sheets[sheetName];
    if (!ws) return;
    const rawRows = XLSX.utils.sheet_to_json<Record<string, unknown>>(ws, { defval: null });

    if (sheetName === RESULT_META_SHEET) {
      const byKey: Record<string, string[]> = {};
      rawRows.forEach((row) => {
        const key = String(row.key ?? '').trim();
        if (!key || typeof row.json !== 'string') return;
        if (!byKey[key]) byKey[key] = [];
        byKey[key][Number(row.part ?? 0)] = row.json;
      });
      Object.entries(byKey).forEach(([key, parts]) => {
        const json = parts.join('');
        if (!json.trim()) return;
        try {
          const parsed = JSON.parse(json);
          if (key === 'runMeta') metadata.runMeta = parsed;
          else if (key === 'pathway') metadata.pathway = parsed;
          else if (key === 'rolling') metadata.rolling = parsed;
          else if (key === 'co2Shadow') metadata.co2Shadow = parsed;
          else if (key === 'narrative') metadata.narrative = parsed;
        } catch {
          // ignore malformed metadata rows
        }
      });
      return;
    }

    if (sheetName === SETTINGS_SHEET) {
      const settings = Object.fromEntries(
        rawRows
          .map((row) => [String(row.key ?? '').trim(), normalizeCell(row.value)] as const)
          .filter(([key]) => key),
      ) as Partial<AppSettings>;
      if (Object.keys(settings).length > 0) metadata.settings = settings as AppSettings;
      return;
    }

    if (sheetName === CONSTRAINTS_SHEET) {
      const constraints: CustomConstraint[] = rawRows.map((row) => ({
        id: String(normalizeCell(row.id) ?? ''),
        enabled: normalizeCell(row.enabled) === true || normalizeCell(row.enabled) === 'true' || normalizeCell(row.enabled) === 1,
        label: String(normalizeCell(row.label) ?? ''),
        metric: String(normalizeCell(row.metric) ?? 'co2_cap') as CustomConstraint['metric'],
        carrier: String(normalizeCell(row.carrier) ?? ''),
        value: Number(normalizeCell(row.value) ?? 0),
        unit: String(normalizeCell(row.unit) ?? ''),
      }));
      if (constraints.length > 0) metadata.constraints = constraints;
      return;
    }

    if (sheetName === RUN_STATE_SHEET) {
      const rawState = Object.fromEntries(
        rawRows
          .map((row) => [String(row.key ?? '').trim(), normalizeCell(row.value)] as const)
          .filter(([key]) => key),
      ) as Record<string, Primitive>;
      if (Object.keys(rawState).length > 0) {
        metadata.runState = {
          snapshotStart: Number(rawState.snapshotStart ?? 0),
          snapshotEnd: Number(rawState.snapshotEnd ?? 0),
          snapshotWeight: Number(rawState.snapshotWeight ?? 1),
          carbonPrice: Number(rawState.carbonPrice ?? 0),
          forceLp: rawState.forceLp === true || rawState.forceLp === 'true' || rawState.forceLp === 1,
          activeScenarioId: typeof rawState.activeScenarioId === 'string' ? rawState.activeScenarioId : null,
        };
      }
      return;
    }

    if (sheetName === PROVENANCE_SHEET) {
      const rawProvenance = Object.fromEntries(
        rawRows
          .map((row) => [String(row.key ?? '').trim(), normalizeCell(row.value)] as const)
          .filter(([key]) => key),
      ) as Record<string, Primitive>;
      if (Object.keys(rawProvenance).length > 0) {
        metadata.provenance = {
          exportedAt: String(rawProvenance.exportedAt ?? ''),
          exportedFilename: String(rawProvenance.exportedFilename ?? ''),
          schemaCommitSha: String(rawProvenance.schemaCommitSha ?? PYPSA_SCHEMA_META.commit_sha ?? ''),
          schemaGeneratedAt: String(rawProvenance.schemaGeneratedAt ?? PYPSA_SCHEMA_META.generated_at ?? ''),
          importedFromFilename: typeof rawProvenance.importedFromFilename === 'string' ? rawProvenance.importedFromFilename : null,
          importedAt: typeof rawProvenance.importedAt === 'string' ? rawProvenance.importedAt : null,
        };
      }
      return;
    }

    if (sheetName === PLUGIN_ANALYTICS_SHEET) {
      // New format: long rows {moduleId, name, field, part, value}. Old format:
      // one row per module {moduleId, name, ui, data}. Support both.
      const isChunked = rawRows.some((r) => 'field' in r);
      const acc: Record<string, { name: string; ui: string[]; data: string[] }> = {};
      rawRows.forEach((row) => {
        const moduleId = String(row.moduleId ?? '').trim();
        if (!moduleId) return;
        if (!acc[moduleId]) acc[moduleId] = { name: String(row.name ?? moduleId), ui: [], data: [] };
        if (isChunked) {
          const part = Number(row.part ?? 0);
          const value = typeof row.value === 'string' ? row.value : '';
          if (String(row.field) === 'ui') acc[moduleId].ui[part] = value;
          else if (String(row.field) === 'data') acc[moduleId].data[part] = value;
        } else {
          acc[moduleId].ui[0] = typeof row.ui === 'string' ? row.ui : '';
          acc[moduleId].data[0] = typeof row.data === 'string' ? row.data : '';
        }
      });
      const pluginAnalytics: NonNullable<ProjectMetadata['pluginAnalytics']> = {};
      Object.entries(acc).forEach(([moduleId, p]) => {
        const uiStr = p.ui.join('');
        const dataStr = p.data.join('');
        try {
          pluginAnalytics[moduleId] = {
            name: p.name,
            ui: uiStr.trim() ? JSON.parse(uiStr) : {},
            data: dataStr.trim() ? JSON.parse(dataStr) : {},
          };
        } catch {
          pluginAnalytics[moduleId] = { name: p.name, ui: {}, data: {} };
        }
      });
      if (Object.keys(pluginAnalytics).length > 0) metadata.pluginAnalytics = pluginAnalytics;
      return;
    }

    if (sheetName === PLUGIN_CONFIGS_SHEET) {
      // Reverse of the writer above: rows are {moduleId, part, json} chunks.
      // Reassemble each moduleId's chunks in part order, JSON.parse the
      // result, and store under metadata.pluginConfigs.
      const acc: Record<string, string[]> = {};
      rawRows.forEach((row) => {
        const moduleId = String(row.moduleId ?? '').trim();
        if (!moduleId) return;
        const part = Number(row.part ?? 0);
        const json = typeof row.json === 'string' ? row.json : '';
        if (!acc[moduleId]) acc[moduleId] = [];
        acc[moduleId][part] = json;
      });
      const pluginConfigs: Record<string, Record<string, unknown>> = {};
      Object.entries(acc).forEach(([moduleId, chunks]) => {
        try {
          const merged = chunks.join('');
          const parsed = merged.trim() ? JSON.parse(merged) : {};
          if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
            pluginConfigs[moduleId] = parsed as Record<string, unknown>;
          }
        } catch {
          /* skip — corrupt chunk, leave that plugin's config to its defaults */
        }
      });
      if (Object.keys(pluginConfigs).length > 0) metadata.pluginConfigs = pluginConfigs;
      return;
    }

    if (isProjectMetadataSheet(sheetName)) return;

    // Output time-series sheet (e.g. generators-p)? Route to outputs.series.
    const dashIndex = canonical.indexOf('-');
    if (dashIndex > 0) {
      const componentSheet = canonical.slice(0, dashIndex);
      const attr = canonical.slice(dashIndex + 1);
      if (outputSeriesAttrSet(componentSheet).has(attr)) {
        outputs.series[canonical] = rawRows.map((row) =>
          Object.fromEntries(
            Object.entries(row).map(([k, v]) => [k, normalizeCell(v)]),
          ),
        ) as GridRow[];
        return;
      }
    }

    // Static component sheet: split input vs output columns.
    const outStaticAttrs = outputStaticAttrSet(canonical);
    const inputRows: GridRow[] = [];
    const sheetOutputs: Record<string, Record<string, Primitive>> = {};

    rawRows.forEach((rawRow) => {
      const inputPart: GridRow = {};
      const outputPart: Record<string, Primitive> = {};
      let name = '';
      Object.entries(rawRow).forEach(([k, v]) => {
        const cell = normalizeCell(v);
        if (k === 'name') {
          inputPart[k] = cell;
          name = typeof cell === 'string' ? cell : String(cell ?? '');
        } else if (outStaticAttrs.has(k)) {
          if (cell !== null && cell !== '') outputPart[k] = cell;
        } else {
          inputPart[k] = cell;
        }
      });
      inputRows.push(inputPart);
      if (name && Object.keys(outputPart).length > 0) {
        sheetOutputs[name] = outputPart;
      }
    });

    (model as any)[canonical] = inputRows;
    if (Object.keys(sheetOutputs).length > 0) {
      outputs.static[canonical] = sheetOutputs;
    }
  });

  return { model, outputs, metadata };
}

export function parseProjectFile(
  file: File,
): Promise<{ model: WorkbookModel; outputs: ProjectOutputs; metadata: ProjectMetadata }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const arrayBuffer = event.target?.result;
        if (!(arrayBuffer instanceof ArrayBuffer)) {
          reject(new Error('Could not read project workbook.'));
          return;
        }
        resolve(parseProjectWorkbook(arrayBuffer));
      } catch (error) {
        reject(error instanceof Error ? error : new Error('Project import failed.'));
      }
    };
    reader.onerror = () => reject(new Error('Project import failed.'));
    reader.readAsArrayBuffer(file);
  });
}
