import * as XLSX from 'xlsx';
import { SHEETS, TS_SHEETS, DEFAULT_SHEET_ROWS } from '../../constants';
import { AnySheetName, GridRow, Primitive, WorkbookModel } from '../../types';

export function normalizeCell(value: unknown): Primitive {
  if (value === undefined || value === null) return null;
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return value;
  return String(value);
}

export function createEmptyWorkbook(): WorkbookModel {
  const base = Object.fromEntries(SHEETS.map((s) => [s, []]));
  const ts = Object.fromEntries(TS_SHEETS.map((s) => [s, []]));
  return { ...base, ...ts } as unknown as WorkbookModel;
}

export function parseSheets(workbook: ReturnType<typeof XLSX.read>): WorkbookModel {
  const model = createEmptyWorkbook();
  const allSheets: AnySheetName[] = [...SHEETS, ...TS_SHEETS];
  // Workbooks exported by some PyPSA tooling use underscore-joined names
  // (e.g. "loads_p_set") rather than the hyphen-joined canonical form
  // ("loads-p_set"). Accept either by falling back to the underscore variant.
  const resolveSheet = (canonical: string): string | undefined => {
    if (workbook.Sheets[canonical]) return canonical;
    const underscore = canonical.replace('-', '_');
    if (underscore !== canonical && workbook.Sheets[underscore]) return underscore;
    return undefined;
  };
  allSheets.forEach((sheet) => {
    const sheetName = resolveSheet(sheet);
    if (!sheetName) return;
    const ws = workbook.Sheets[sheetName];
    const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(ws, { defval: null });
    (model as any)[sheet] = rows.map((row) =>
      Object.fromEntries(Object.entries(row).map(([key, value]) => [key, normalizeCell(value)])),
    );
  });
  return model;
}

export async function loadSampleWorkbook(): Promise<WorkbookModel> {
  const res = await fetch('/sample_model.xlsx');
  if (!res.ok) throw new Error('Could not load sample_model.xlsx');
  const arrayBuffer = await res.arrayBuffer();
  return parseSheets(XLSX.read(arrayBuffer, { type: 'array' }));
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

export function buildWorkbook(model: WorkbookModel) {
  const workbook = XLSX.utils.book_new();
  SHEETS.forEach((sheet) => {
    const rows = model[sheet].length > 0 ? model[sheet] : [DEFAULT_SHEET_ROWS[sheet]];
    const ws = XLSX.utils.json_to_sheet(rows);
    XLSX.utils.book_append_sheet(workbook, ws, sheet);
  });
  TS_SHEETS.forEach((sheet) => {
    const rows = (model as any)[sheet] as GridRow[];
    if (rows && rows.length > 0) {
      const ws = XLSX.utils.json_to_sheet(rows);
      XLSX.utils.book_append_sheet(workbook, ws, sheet);
    }
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
