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
import { GridRow, Primitive, WorkbookModel } from '../types';
import { SHEETS, TS_SHEETS, PYPSA_COMPONENTS, PYPSA_COMPONENT_BY_SHEET } from 'lib/constants/pypsa_schema';
import { parseCsvText } from './csvText';

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

/** A plain decimal literal that survives `Number()` -> `String()` unchanged in
 *  meaning: no leading zeros (`001`), no stray `+`. Anything else stays text. */
const CANONICAL_NUMBER_RE = /^-?(0|[1-9]\d*)?(\.\d+)?([eE][+-]?\d+)?$/;

function isStringAttribute(sheet: string, column: string): boolean {
  if (column === 'name') return true;
  const attrs = PYPSA_COMPONENT_BY_SHEET[sheet]?.attributes;
  return Boolean(attrs?.some((a) => a.attribute === column && a.type === 'string'));
}

/** Parse one CSV into rows. Cells are literal text; only canonical numerals in a
 *  non-string column become numbers, so `name`/`bus`/`carrier` values such as
 *  `001` are never reformatted to `1`. */
function csvTextToRows(csv: string, sheet: string): GridRow[] {
  const table = parseCsvText(csv);
  if (table.length === 0) return [];
  const header = table[0].map((h, i) => (h.trim() !== '' ? h.trim() : `col${i}`));
  return table.slice(1).map((cells) => {
    const out: GridRow = {};
    header.forEach((key, i) => {
      const val = cells[i] ?? '';
      const trimmed = val.trim();
      if (trimmed === '') {
        out[key] = '';
        return;
      }
      // First column of a time-series sheet is the snapshot axis: integers stay
      // integers, anything else (timestamps) stays the literal text.
      const axis = i === 0 && sheet.includes('-');
      const textColumn = isStringAttribute(sheet, key) || (axis && !/^-?(0|[1-9]\d*)$/.test(trimmed));
      const numeric = CANONICAL_NUMBER_RE.test(trimmed) && trimmed !== '-' && trimmed !== '.' && Number.isFinite(Number(trimmed));
      out[key] = numeric && !textColumn ? Number(trimmed) : val;
    });
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
    baseModel[sheetName] = csvTextToRows(csvText, sheetName);
    importedSheets.push(sheetName);
  }

  return { model: baseModel, unknownFiles, importedSheets };
}
