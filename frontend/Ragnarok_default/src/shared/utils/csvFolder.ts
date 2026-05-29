/**
 * PyPSA-native CSV folder import/export.
 *
 * PyPSA stores a network as a directory of CSV files — one per component
 * class plus per-attribute time-series files (e.g. `generators.csv`,
 * `generators-p_max_pu.csv`). Ragnarok bundles the same set into a single
 * `.zip` for cross-browser portability:
 *
 *   network.csv            (top-level Network attrs)
 *   snapshots.csv          (snapshot index)
 *   <list_name>.csv        (static component sheet, e.g. generators.csv)
 *   <list_name>-<attr>.csv (time-varying attribute, e.g. generators-p_max_pu.csv)
 *
 * Round-trips via `pypsa.Network.import_from_csv_folder(...)` /
 * `export_to_csv_folder(...)`, so users can hand the artefact off to any
 * Python-based PyPSA tool.
 */
import { unzipSync, zipSync, strToU8, strFromU8 } from 'fflate';
import * as XLSX from 'xlsx';
import { GridRow, Primitive, WorkbookModel } from '../types';
import { SHEETS, TS_SHEETS, PYPSA_COMPONENTS } from '../../constants/pypsa_schema';

const ALL_KNOWN_NAMES = new Set<string>([
  ...SHEETS,
  ...TS_SHEETS,
  ...PYPSA_COMPONENTS.flatMap((c) => c.input_temporal_attributes.map((attr) => `${c.list_name}-${attr}`)),
]);

// ── CSV serialisation ────────────────────────────────────────────────────────

function escapeCell(value: Primitive): string {
  if (value === null || value === undefined) return '';
  const s = String(value);
  if (s.includes(',') || s.includes('"') || s.includes('\n') || s.includes('\r')) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

function rowsToCsv(rows: GridRow[]): string {
  if (!rows.length) return '';
  // Union of all keys, preserving first-seen order.
  const cols: string[] = [];
  const seen = new Set<string>();
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (!seen.has(key)) {
        seen.add(key);
        cols.push(key);
      }
    }
  }
  const header = cols.map(escapeCell).join(',');
  const lines = rows.map((row) =>
    cols.map((c) => escapeCell(row[c] as Primitive)).join(','),
  );
  return `${header}\n${lines.join('\n')}\n`;
}

// ── Export: model → zip ──────────────────────────────────────────────────────

/** Pack the model into a deflated zip and return the raw bytes. The
 *  browser caller wraps the bytes in a Blob for download. */
export function exportModelAsCsvFolderBytes(model: WorkbookModel, archiveName: string): Uint8Array {
  const files: Record<string, Uint8Array> = {};
  for (const [sheetName, rows] of Object.entries(model)) {
    if (!Array.isArray(rows) || rows.length === 0) continue;
    if (!ALL_KNOWN_NAMES.has(sheetName)) continue; // skip Ragnarok-only metadata sheets
    const csv = rowsToCsv(rows as GridRow[]);
    if (!csv.trim()) continue;
    files[`${archiveName}/${sheetName}.csv`] = strToU8(csv);
  }
  return zipSync(files, { level: 6 });
}

export function exportModelAsCsvFolderZip(model: WorkbookModel, archiveName: string): Blob {
  return new Blob([exportModelAsCsvFolderBytes(model, archiveName)], { type: 'application/zip' });
}

// ── Import: zip → model ──────────────────────────────────────────────────────

function csvTextToRows(csv: string): GridRow[] {
  const wb = XLSX.read(csv, { type: 'string', raw: false });
  if (!wb.SheetNames.length) return [];
  const ws = wb.Sheets[wb.SheetNames[0]];
  const raw = XLSX.utils.sheet_to_json<Record<string, unknown>>(ws, { defval: null });
  return raw.map((row) => {
    const out: GridRow = {};
    for (const [key, val] of Object.entries(row)) {
      if (val === null || val === undefined || val === '') {
        out[key] = '';
        continue;
      }
      // Try numeric coercion for non-string-like values
      const asNum = typeof val === 'number' ? val : Number(val);
      out[key] = Number.isFinite(asNum) && String(val).trim() !== '' && /^-?\d/.test(String(val))
        ? asNum
        : String(val);
    }
    return out;
  });
}

export interface CsvFolderImportResult {
  model: WorkbookModel;
  unknownFiles: string[];
  importedSheets: string[];
}

export async function importCsvFolderZip(file: File | Blob | ArrayBuffer | Uint8Array): Promise<CsvFolderImportResult> {
  let buffer: Uint8Array;
  if (file instanceof Uint8Array) {
    buffer = file;
  } else if (file instanceof ArrayBuffer) {
    buffer = new Uint8Array(file);
  } else if (typeof (file as Blob).arrayBuffer === 'function') {
    buffer = new Uint8Array(await (file as Blob).arrayBuffer());
  } else {
    // jsdom Blob fallback — read via FileReader.
    buffer = await new Promise<Uint8Array>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
      reader.onerror = () => reject(reader.error);
      reader.readAsArrayBuffer(file as Blob);
    });
  }
  const entries = unzipSync(buffer);

  const baseModel: WorkbookModel = Object.fromEntries(
    [...SHEETS, ...TS_SHEETS].map((s) => [s, []]),
  ) as WorkbookModel;

  const unknownFiles: string[] = [];
  const importedSheets: string[] = [];

  for (const [path, data] of Object.entries(entries)) {
    if (!path.toLowerCase().endsWith('.csv')) continue;
    const filename = path.split('/').pop()!;
    const sheetName = filename.replace(/\.csv$/i, '');
    if (!ALL_KNOWN_NAMES.has(sheetName)) {
      unknownFiles.push(path);
      continue;
    }
    const csvText = strFromU8(data);
    baseModel[sheetName] = csvTextToRows(csvText);
    importedSheets.push(sheetName);
  }

  return { model: baseModel, unknownFiles, importedSheets };
}
