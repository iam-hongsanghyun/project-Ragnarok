import { describe, test, expect } from '@jest/globals';
import * as XLSX from 'xlsx';
import { canonicalizeTemporalRows, excelSerialToIso, parseProjectWorkbook, parseWorkbook, parseDelimitedTextToGridRows } from './workbook';
import { importCsvFolderZip } from './csvFolder';
import { inferDateOrder, normalizeDateToIso } from 'lib/utils/helpers';
import type { GridRow } from 'lib/types';

const serialOf = (y: number, m: number, d: number, h = 0, mi = 0, s = 0) =>
  (Date.UTC(y, m - 1, d, h, mi, s) - Date.UTC(1899, 11, 30)) / 86400000;

function dateSheetBuffer(stamps: Array<[number, number, number, number]>): ArrayBuffer {
  const rows: unknown[][] = [['snapshot', 'v']];
  stamps.forEach(([y, m, d, h], i) => rows.push([serialOf(y, m, d, h), i]));
  const ws = XLSX.utils.aoa_to_sheet(rows);
  for (let r = 2; r <= rows.length; r += 1) {
    ws[`A${r}`].t = 'n';
    ws[`A${r}`].z = 'yyyy-mm-dd hh:mm:ss';
  }
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'loads-p_set');
  return XLSX.write(wb, { type: 'array', bookType: 'xlsx' }) as ArrayBuffer;
}

// DST transition days in Seoul (none), Berlin (2024-03-31, 2024-10-27), New York (2024-03-10, 2024-11-03),
// plus the first stamp of 1900 and of the year (Seoul LMT gave -52 s).
const STAMPS: Array<[number, number, number, number]> = [
  [2024, 1, 1, 0], [2024, 3, 31, 1], [2024, 3, 31, 2], [2024, 3, 31, 3],
  [2024, 10, 27, 1], [2024, 10, 27, 2], [2024, 10, 27, 3],
  [2024, 3, 10, 2], [2024, 11, 3, 1], [2024, 11, 3, 2], [1980, 1, 1, 0],
];
const EXPECTED = STAMPS.map(([y, m, d, h]) => `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}T${String(h).padStart(2, '0')}:00:00`);

describe('Excel dates are wall-clock, zone independent', () => {
  test('serial to ISO uses UTC parts', () => {
    expect(excelSerialToIso(serialOf(2024, 1, 1))).toBe('2024-01-01T00:00:00');
    expect(excelSerialToIso(serialOf(2024, 3, 31, 2, 30, 15))).toBe('2024-03-31T02:30:15');
    expect(excelSerialToIso(0 + 1462 + serialOf(2024, 1, 1) - 1462, false)).toBe('2024-01-01T00:00:00');
  });

  test('project workbook date cells survive any process time zone (no DST duplicate, no -52 s)', () => {
    const { model } = parseProjectWorkbook(dateSheetBuffer(STAMPS));
    const rows = canonicalizeTemporalRows(model['loads-p_set'] as GridRow[], 'auto');
    expect(rows.map((r) => r.snapshot)).toEqual(EXPECTED);
    expect(new Set(rows.map((r) => r.snapshot)).size).toBe(STAMPS.length);
  });

  test('parseWorkbook (File) yields the same stamps', async () => {
    const file = new File([dateSheetBuffer(STAMPS)], 'x.xlsx');
    const model = await parseWorkbook(file);
    const rows = canonicalizeTemporalRows(model['loads-p_set'] as GridRow[], 'auto');
    expect(rows.map((r) => r.snapshot)).toEqual(EXPECTED);
  });

  test('integer snapshot axes stay integers', () => {
    const rows: GridRow[] = [{ snapshot: 0, a: 1 }, { snapshot: 1, a: 2 }, { snapshot: 2, a: 3 }];
    expect(canonicalizeTemporalRows(rows, 'auto').map((r) => r.snapshot)).toEqual([0, 1, 2]);
  });
});

describe('CSV is read as literal text', () => {
  test('time-series CSV keeps timestamps as written and parses values', () => {
    const rows = parseDelimitedTextToGridRows('snapshot,g\n2024-03-31 02:00,0.5\n"2024-03-31 03:00",0.25\n');
    expect(rows).toEqual([{ snapshot: '2024-03-31 02:00', g: 0.5 }, { snapshot: '2024-03-31 03:00', g: 0.25 }]);
  });

  test('CSV folder keeps 001 as a string in name/bus columns', async () => {
    const { zipSync, strToU8 } = await import('fflate');
    const zip = zipSync({
      'p/buses.csv': strToU8('name,v_nom\n001,380\n7,110\n'),
      'p/generators.csv': strToU8('name,bus,p_nom\n007,001,50\n'),
    });
    const { model } = await importCsvFolderZip(zip);
    expect(model.buses.map((b) => b.name)).toEqual(['001', '7']);
    expect(model.buses[0].v_nom).toBe(380);
    expect(model.generators[0]).toMatchObject({ name: '007', bus: '001', p_nom: 50 });
  });
});

describe('date order is decided once per column with validity checks', () => {
  test('a column with a day > 12 is dmy throughout', () => {
    const rows: GridRow[] = [{ snapshot: '01/02/2024' }, { snapshot: '13/02/2024' }, { snapshot: '03/04/2024 05:00' }];
    expect(canonicalizeTemporalRows(rows, 'auto').map((r) => r.snapshot)).toEqual([
      '2024-02-01T00:00:00', '2024-02-13T00:00:00', '2024-04-03T05:00:00',
    ]);
  });
  test('a column with a second component > 12 is mdy throughout', () => {
    expect(inferDateOrder(['01/02/2024', '02/13/2024'], 'auto')).toBe('mdy');
  });
  test('impossible dates are returned unchanged', () => {
    expect(normalizeDateToIso('31/02/2024', 'dmy')).toBe('31/02/2024');
    expect(normalizeDateToIso('2024-13-01', 'auto')).toBe('2024-13-01');
    expect(normalizeDateToIso('01/01/2024 25:00', 'dmy')).toBe('01/01/2024 25:00');
    expect(normalizeDateToIso('29/02/2024', 'dmy')).toBe('2024-02-29');
  });
});
