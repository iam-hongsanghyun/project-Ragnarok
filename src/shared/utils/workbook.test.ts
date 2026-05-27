import { describe, test, expect } from '@jest/globals';
import * as XLSX from 'xlsx';
import {
  buildProjectWorkbook,
  parseProjectWorkbook,
  normalizeInputDatesToIso,
  createEmptyWorkbook,
  workbookToArrayBuffer,
  parseSheets,
  RUN_HISTORY_SHEET,
  type ProjectOutputs,
  type ProjectMetadata,
} from './workbook';
import { normalizeDateToIso } from './helpers';
import type { AppSettings } from '../../features/settings/useSettings';
import type { CustomConstraint, GridRow, WorkbookModel } from '../types';

/** Serialise a workbook to an ArrayBuffer, as the import path expects. */
function toArrayBuffer(wb: XLSX.WorkBook): ArrayBuffer {
  return XLSX.write(wb, { type: 'array', bookType: 'xlsx' }) as ArrayBuffer;
}

/** Build a small hand-made input model: two buses, two generators, snapshots. */
function makeBaseModel(): WorkbookModel {
  const model = createEmptyWorkbook();
  model.buses = [
    { name: 'bus_north', v_nom: 380, x: 10.1, y: 53.5 },
    { name: 'bus_south', v_nom: 380, x: 11.2, y: 48.2 },
  ];
  model.generators = [
    { name: 'gen_coal', bus: 'bus_north', carrier: 'coal', p_nom: 500, marginal_cost: 40 },
    { name: 'gen_wind', bus: 'bus_south', carrier: 'wind', p_nom: 300, marginal_cost: 0 },
  ];
  model.snapshots = [
    { snapshot: '2024-01-01T00:00:00' },
    { snapshot: '2024-01-01T01:00:00' },
  ];
  return model;
}

describe('workbook project round-trip', () => {
  test('input static sheets round-trip: rows, columns and values survive', () => {
    const model = makeBaseModel();
    const wb = buildProjectWorkbook(model);
    const { model: parsed } = parseProjectWorkbook(toArrayBuffer(wb));

    expect(parsed.buses).toHaveLength(2);
    expect(parsed.generators).toHaveLength(2);

    const coal = parsed.generators.find((r) => r.name === 'gen_coal');
    expect(coal).toBeDefined();
    expect(coal?.bus).toBe('bus_north');
    expect(coal?.carrier).toBe('coal');
    expect(coal?.p_nom).toBe(500);
    expect(coal?.marginal_cost).toBe(40);

    const north = parsed.buses.find((r) => r.name === 'bus_north');
    expect(north?.v_nom).toBe(380);
    expect(north?.x).toBe(10.1);
    expect(north?.y).toBe(53.5);
  });

  test('output static + series round-trip without merging destructively into inputs', () => {
    const model = makeBaseModel();
    const outputs: ProjectOutputs = {
      static: {
        generators: {
          gen_coal: { p_nom_opt: 480 },
          gen_wind: { p_nom_opt: 310 },
        },
      },
      series: {
        // PyPSA-standard single `snapshot` index column (matches input sheets).
        'generators-p': [
          { snapshot: '2024-01-01T00:00:00', gen_coal: 200, gen_wind: 120 },
          { snapshot: '2024-01-01T01:00:00', gen_coal: 180, gen_wind: 140 },
        ],
      },
    };

    const wb = buildProjectWorkbook(model, outputs);
    const { model: parsed, outputs: parsedOut } = parseProjectWorkbook(toArrayBuffer(wb));

    // Output static attrs are split back into outputs.static, not left on inputs.
    expect(parsedOut.static.generators?.gen_coal?.p_nom_opt).toBe(480);
    expect(parsedOut.static.generators?.gen_wind?.p_nom_opt).toBe(310);

    const coal = parsed.generators.find((r) => r.name === 'gen_coal');
    expect(coal?.p_nom).toBe(500);          // input survives
    expect('p_nom_opt' in (coal ?? {})).toBe(false);   // output not merged into input row

    // Output series sheet routed into outputs.series.
    const series = parsedOut.series['generators-p'];
    expect(series).toBeDefined();
    expect(series).toHaveLength(2);
    expect(series?.[0]?.gen_coal).toBe(200);
    expect(series?.[1]?.gen_wind).toBe(140);
    // Single PyPSA-standard `snapshot` index column survives the round-trip
    // (no redundant `name`/`timestamp` duplicate columns).
    expect(series?.[0]?.snapshot).toBe('2024-01-01T00:00:00');
    expect('timestamp' in (series?.[0] ?? {})).toBe(false);
  });

  test('settings round-trip preserves field types', () => {
    const settings: AppSettings = {
      dateFormat: 'dmy',
      solverThreads: 4,
      solverType: 'ipm',
      currencyCode: 'EUR',
      currencySymbol: '€',
      enableLoadShedding: true,
      loadSheddingCost: 9000,
      discountRate: 0.07,
    };
    const metadata: ProjectMetadata = { settings };

    const wb = buildProjectWorkbook(makeBaseModel(), undefined, metadata);
    const { metadata: parsedMeta } = parseProjectWorkbook(toArrayBuffer(wb));

    const parsed = parsedMeta.settings;
    expect(parsed).toBeDefined();
    expect(parsed?.dateFormat).toBe('dmy');
    expect(parsed?.solverType).toBe('ipm');
    expect(parsed?.currencyCode).toBe('EUR');
    expect(parsed?.currencySymbol).toBe('€');

    // Numbers must stay numbers, not strings.
    expect(typeof parsed?.solverThreads).toBe('number');
    expect(parsed?.solverThreads).toBe(4);
    expect(typeof parsed?.loadSheddingCost).toBe('number');
    expect(parsed?.loadSheddingCost).toBe(9000);
    expect(typeof parsed?.discountRate).toBe('number');
    expect(parsed?.discountRate).toBe(0.07);

    // Booleans must stay booleans, not the string "true".
    expect(typeof parsed?.enableLoadShedding).toBe('boolean');
    expect(parsed?.enableLoadShedding).toBe(true);
  });

  test('constraints round-trip', () => {
    const constraints: CustomConstraint[] = [
      { id: 'c1', enabled: true, label: 'CO2 cap', metric: 'co2_cap', carrier: '', value: 1000, unit: 'tCO2' },
      { id: 'c2', enabled: false, label: 'Wind floor', metric: 'carrier_min_gen', carrier: 'wind', value: 50, unit: 'MWh' },
    ];
    const metadata: ProjectMetadata = { constraints };

    const wb = buildProjectWorkbook(makeBaseModel(), undefined, metadata);
    const { metadata: parsedMeta } = parseProjectWorkbook(toArrayBuffer(wb));

    expect(parsedMeta.constraints).toHaveLength(2);
    const c1 = parsedMeta.constraints?.find((c) => c.id === 'c1');
    expect(c1?.enabled).toBe(true);
    expect(c1?.metric).toBe('co2_cap');
    expect(c1?.value).toBe(1000);
    expect(typeof c1?.value).toBe('number');

    const c2 = parsedMeta.constraints?.find((c) => c.id === 'c2');
    expect(c2?.enabled).toBe(false);
    expect(typeof c2?.enabled).toBe('boolean');
    expect(c2?.carrier).toBe('wind');
  });

  test('large-payload chunking reassembles correctly across multiple cells', () => {
    // A >40k-char JSON string must be split across rows (MAX_CELL_CHARS ~30000).
    const bigTable = Array.from({ length: 4000 }, (_, i) => ({
      asset: `unit_${i}`,
      value: i * 1.5,
      note: 'lorem-ipsum-padding',
    }));
    const metadata: ProjectMetadata = {
      pluginAnalytics: {
        'mod.big': {
          name: 'Big Module',
          ui: { value: { label: 'Value', format: 'number' } },
          data: { table: bigTable, marker: 'sentinel-end' },
        },
      },
    };

    // Sanity: the serialised data is genuinely larger than a single cell.
    const dataJson = JSON.stringify(metadata.pluginAnalytics!['mod.big'].data);
    expect(dataJson.length).toBeGreaterThan(40000);

    const wb = buildProjectWorkbook(makeBaseModel(), undefined, metadata);

    // Confirm chunking actually produced multiple rows for the data field.
    const sheet = wb.Sheets['RAGNAROK_PluginAnalytics'];
    const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet, { defval: null });
    const dataParts = rows.filter((r) => r.field === 'data');
    expect(dataParts.length).toBeGreaterThan(1);

    const { metadata: parsedMeta } = parseProjectWorkbook(toArrayBuffer(wb));
    const entry = parsedMeta.pluginAnalytics?.['mod.big'];
    expect(entry).toBeDefined();
    expect(entry?.name).toBe('Big Module');
    const data = entry?.data as { table: typeof bigTable; marker: string };
    expect(data.marker).toBe('sentinel-end');
    expect(data.table).toHaveLength(4000);
    expect(data.table[0]).toEqual({ asset: 'unit_0', value: 0, note: 'lorem-ipsum-padding' });
    expect(data.table[3999]).toEqual({ asset: 'unit_3999', value: 3999 * 1.5, note: 'lorem-ipsum-padding' });
  });

  test('run history is NOT exported', () => {
    const wb = buildProjectWorkbook(makeBaseModel(), undefined, {});
    expect(wb.SheetNames).not.toContain(RUN_HISTORY_SHEET);

    const { metadata } = parseProjectWorkbook(toArrayBuffer(wb));
    expect(metadata.runHistory).toBeUndefined();
  });
});

describe('input date normalization', () => {
  test('normalizeInputDatesToIso converts dmy snapshots and temporal sheets to ISO', () => {
    const model = createEmptyWorkbook();
    model.snapshots = [
      { snapshot: '01-08-2024 00:00' },   // ambiguous: dmy => 2024-08-01
      { snapshot: '15-12-2024 06:30' },
    ];
    model['loads-p_set'] = [
      { snapshot: '01-08-2024 00:00', load_a: 100 },
      { snapshot: '15-12-2024 06:30', load_a: 120 },
    ];

    normalizeInputDatesToIso(model, 'dmy');

    expect(model.snapshots[0].snapshot).toBe('2024-08-01T00:00:00');
    expect(model.snapshots[1].snapshot).toBe('2024-12-15T06:30:00');
    // dmy must NOT be misread as mdy (would give 2024-01-08).
    expect(model.snapshots[0].snapshot).not.toBe('2024-01-08T00:00:00');

    const ts = model['loads-p_set'] as GridRow[];
    expect(ts[0].snapshot).toBe('2024-08-01T00:00:00');
    expect(ts[0].load_a).toBe(100);   // numeric data untouched
    expect(ts[1].snapshot).toBe('2024-12-15T06:30:00');
  });

  test('normalizeDateToIso handles dmy / mdy / ymd / auto', () => {
    expect(normalizeDateToIso('01-08-2024', 'dmy')).toBe('2024-08-01');
    expect(normalizeDateToIso('01-08-2024', 'mdy')).toBe('2024-01-08');
    expect(normalizeDateToIso('2024-08-01', 'ymd')).toBe('2024-08-01');

    // auto: 4-digit leading => ymd.
    expect(normalizeDateToIso('2024/08/01', 'auto')).toBe('2024-08-01');
    // auto: first part > 12 => must be a day => dmy.
    expect(normalizeDateToIso('13-08-2024', 'auto')).toBe('2024-08-13');
    // auto: ambiguous, both <= 12 => mdy fallback.
    expect(normalizeDateToIso('08-01-2024', 'auto')).toBe('2024-08-01');

    // Non-date strings pass through unchanged.
    expect(normalizeDateToIso('not-a-date', 'dmy')).toBe('not-a-date');
  });
});

describe('export temporal sheet formatting', () => {
  test('snapshot column is first and dates are ISO on export', () => {
    const model = createEmptyWorkbook();
    model.snapshots = [{ snapshot: '2024-01-01 00:00' }, { snapshot: '2024-01-01 01:00' }];
    model['loads-p_set'] = [
      { load_a: 100, snapshot: '2024-01-01 00:00' },
      { load_a: 120, snapshot: '2024-01-01 01:00' },
    ];

    const wb = buildProjectWorkbook(model);
    const snapHeader = XLSX.utils.sheet_to_json<string[]>(wb.Sheets.snapshots!, { header: 1 })[0];
    expect(snapHeader[0]).toBe('snapshot');

    const loadHeader = XLSX.utils.sheet_to_json<string[]>(wb.Sheets['loads-p_set']!, { header: 1 })[0];
    expect(loadHeader[0]).toBe('snapshot');

    const loadRows = XLSX.utils.sheet_to_json<Record<string, string>>(wb.Sheets['loads-p_set']!);
    expect(loadRows[0].snapshot).toBe('2024-01-01T00:00:00');
    expect(loadRows[0].snapshot).not.toContain(' ');
  });

  test('output series sheets use ISO snapshot in the first column on export', () => {
    const outputs: ProjectOutputs = {
      static: {},
      series: {
        'generators-p': [
          { gen_coal: 200, snapshot: '2024-01-01 00:00' },
        ],
      },
    };
    const wb = buildProjectWorkbook(makeBaseModel(), outputs);
    const header = XLSX.utils.sheet_to_json<string[]>(wb.Sheets['generators-p']!, { header: 1 })[0];
    expect(header[0]).toBe('snapshot');
    const rows = XLSX.utils.sheet_to_json<Record<string, string>>(wb.Sheets['generators-p']!);
    expect(rows[0].snapshot).toBe('2024-01-01T00:00:00');
  });
});

describe('input-only workbook round-trip', () => {
  test('workbookToArrayBuffer + parseSheets preserves static sheets', () => {
    const model = makeBaseModel();
    const buf = workbookToArrayBuffer(model);
    const parsed = parseSheets(XLSX.read(buf, { type: 'array' }));
    expect(parsed.buses).toHaveLength(2);
    expect(parsed.generators.find((r) => r.name === 'gen_wind')?.p_nom).toBe(300);
  });
});
