import * as XLSX from 'xlsx';
import { SHEETS, TS_SHEETS } from '../../constants';
import {
  isInputTemporalSheet,
  normalizeSheetName,
  stripOutputStaticAttributes,
  PYPSA_COMPONENT_BY_SHEET,
} from '../../constants/pypsa_schema';
import { GridRow, Primitive, RunResults, WorkbookModel } from '../types';
import { PATHWAY_CONFIG_SHEET, PATHWAY_PERIODS_SHEET } from './pathway';
import { ROLLING_CONFIG_SHEET } from './rolling';

export const RESULT_META_SHEET = 'RAGNAROK_ResultMeta';
export const PLUGIN_ANALYTICS_SHEET = 'RAGNAROK_PluginAnalytics';

export function normalizeCell(value: unknown): Primitive {
  if (value === undefined || value === null) return null;
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return value;
  return String(value);
}

export function createEmptyWorkbook(): WorkbookModel {
  const base = Object.fromEntries(SHEETS.map((s) => [s, []]));
  const ts = Object.fromEntries(TS_SHEETS.map((s) => [s, []]));
  return {
    ...base,
    ...ts,
    [PATHWAY_CONFIG_SHEET]: [],
    [PATHWAY_PERIODS_SHEET]: [],
    [ROLLING_CONFIG_SHEET]: [],
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
        const wb = XLSX.read(arrayBuffer, { type: 'array' });
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

export function buildWorkbook(model: WorkbookModel) {
  const workbook = XLSX.utils.book_new();
  SHEETS.forEach((sheet) => {
    const rows = nonEmptyRows((model[sheet] ?? []).map((row) => stripOutputStaticAttributes(sheet, row)));
    if (rows.length === 0) return;   // skip empty sheets entirely; PyPSA will treat them as absent
    const ws = XLSX.utils.json_to_sheet(rows);
    XLSX.utils.book_append_sheet(workbook, ws, sheet);
  });

  [...TS_SHEETS, ...Object.keys(model).filter((sheet) => isInputTemporalSheet(sheet) && !TS_SHEETS.includes(sheet))].forEach((sheet) => {
    const rows = (model as any)[sheet] as GridRow[] | undefined;
    if (!rows || rows.length === 0) return;
    const ws = XLSX.utils.json_to_sheet(rows);
    XLSX.utils.book_append_sheet(workbook, ws, sheet);
  });
  [PATHWAY_CONFIG_SHEET, PATHWAY_PERIODS_SHEET, ROLLING_CONFIG_SHEET].forEach((sheet) => {
    const rows = (model as any)[sheet] as GridRow[] | undefined;
    if (!rows || rows.length === 0) return;
    const ws = XLSX.utils.json_to_sheet(rows);
    XLSX.utils.book_append_sheet(workbook, ws, sheet);
  });
  return workbook;
}

export function exportWorkbook(model: WorkbookModel, filename = 'ragnarok_case.xlsx') {
  XLSX.writeFile(buildWorkbook(model), filename);
}

export function workbookToArrayBuffer(model: WorkbookModel): ArrayBuffer {
  return XLSX.write(buildWorkbook(model), { bookType: 'xlsx', type: 'array' }) as ArrayBuffer;
}

/**
 * Parse a CSV (or TSV) file into GridRow[] for use as a time-series sheet.
 *
 * Expected shape:
 *   Column 0  — snapshot label (string, e.g. "2019-01-01 00:00")
 *   Columns 1+ — component names → numeric values
 *
 * SheetJS auto-detects comma vs tab delimiter.  BOM-prefixed files are handled
 * transparently.  All numeric cells are cast to `number`; the label column is
 * kept as `string`.  Unparseable numeric cells become `null`.
 */
export async function parseCsvToGridRows(file: File): Promise<GridRow[]> {
  const text = await file.text();
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
  runMeta?: RunResults['runMeta'];
  pathway?: RunResults['pathway'];
  rolling?: RunResults['rolling'];
}

const EMPTY_OUTPUTS: ProjectOutputs = { static: {}, series: {} };
const EMPTY_METADATA: ProjectMetadata = {};

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
    const rows = nonEmptyRows(merged);
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
    const ws = XLSX.utils.json_to_sheet(rows);
    XLSX.utils.book_append_sheet(workbook, ws, sheet);
  });

  // ── Output time-series sheets ────────────────────────────────────────
  Object.entries(outputs.series).forEach(([sheet, rows]) => {
    if (!rows || rows.length === 0) return;
    const ws = XLSX.utils.json_to_sheet(rows);
    XLSX.utils.book_append_sheet(workbook, ws, sheet);
  });

  [PATHWAY_CONFIG_SHEET, PATHWAY_PERIODS_SHEET, ROLLING_CONFIG_SHEET].forEach((sheet) => {
    const rows = (model as any)[sheet] as GridRow[] | undefined;
    if (!rows || rows.length === 0) return;
    const ws = XLSX.utils.json_to_sheet(rows);
    XLSX.utils.book_append_sheet(workbook, ws, sheet);
  });

  const resultMetaRows: GridRow[] = [];
  if (metadata.runMeta) resultMetaRows.push({ key: 'runMeta', json: JSON.stringify(metadata.runMeta) });
  if (metadata.pathway) resultMetaRows.push({ key: 'pathway', json: JSON.stringify(metadata.pathway) });
  if (metadata.rolling) resultMetaRows.push({ key: 'rolling', json: JSON.stringify(metadata.rolling) });
  if (metadata.co2Shadow) resultMetaRows.push({ key: 'co2Shadow', json: JSON.stringify(metadata.co2Shadow) });
  if (metadata.narrative) resultMetaRows.push({ key: 'narrative', json: JSON.stringify(metadata.narrative) });
  if (resultMetaRows.length > 0) {
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(resultMetaRows), RESULT_META_SHEET);
  }

  const pluginRows = Object.entries(metadata.pluginAnalytics ?? {}).map(([moduleId, entry]) => ({
    moduleId,
    name: entry.name,
    ui: JSON.stringify(entry.ui ?? {}),
    data: JSON.stringify(entry.data ?? {}),
  }));
  if (pluginRows.length > 0) {
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(pluginRows), PLUGIN_ANALYTICS_SHEET);
  }

  return workbook;
}

export function exportProjectWorkbook(
  model: WorkbookModel,
  outputs: ProjectOutputs | null | undefined,
  metadata: ProjectMetadata | null | undefined,
  filename = 'ragnarok_project.xlsx',
): void {
  XLSX.writeFile(buildProjectWorkbook(model, outputs ?? EMPTY_OUTPUTS, metadata ?? EMPTY_METADATA), filename);
}

/**
 * Parse a project workbook back into `{ model, outputs }`. Output static
 * columns inside component sheets are split out into `outputs.static`;
 * `<list>-<output_attr>` sheets are routed to `outputs.series`.
 */
export function parseProjectWorkbook(
  arrayBuffer: ArrayBuffer,
): { model: WorkbookModel; outputs: ProjectOutputs; metadata: ProjectMetadata } {
  const wb = XLSX.read(arrayBuffer, { type: 'array' });
  const model = createEmptyWorkbook();
  const outputs: ProjectOutputs = { static: {}, series: {} };
  const metadata: ProjectMetadata = {};

  wb.SheetNames.forEach((sheetName) => {
    const canonical = normalizeSheetName(sheetName);
    const ws = wb.Sheets[sheetName];
    if (!ws) return;
    const rawRows = XLSX.utils.sheet_to_json<Record<string, unknown>>(ws, { defval: null });

    if (sheetName === RESULT_META_SHEET) {
      rawRows.forEach((row) => {
        const key = String(row.key ?? '').trim();
        const json = row.json;
        if (!key || typeof json !== 'string' || !json.trim()) return;
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

    if (sheetName === PLUGIN_ANALYTICS_SHEET) {
      const pluginAnalytics: NonNullable<ProjectMetadata['pluginAnalytics']> = {};
      rawRows.forEach((row) => {
        const moduleId = String(row.moduleId ?? '').trim();
        if (!moduleId) return;
        try {
          pluginAnalytics[moduleId] = {
            name: String(row.name ?? moduleId),
            ui: typeof row.ui === 'string' && row.ui.trim() ? JSON.parse(row.ui) : {},
            data: typeof row.data === 'string' && row.data.trim() ? JSON.parse(row.data) : {},
          };
        } catch {
          pluginAnalytics[moduleId] = {
            name: String(row.name ?? moduleId),
            ui: {},
            data: {},
          };
        }
      });
      if (Object.keys(pluginAnalytics).length > 0) metadata.pluginAnalytics = pluginAnalytics;
      return;
    }

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
