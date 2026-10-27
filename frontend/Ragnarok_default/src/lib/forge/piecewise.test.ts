import { afterAll, beforeAll, describe, expect, test } from '@jest/globals';
import schemaFixture from 'lib/constants/__fixtures__/pypsa_schema.fixture.json';
import { applyConfigBundle } from 'lib/constants/pypsa_schema';
import { exportModelAsCsvFolderBytes, importCsvFolderZip } from 'lib/workbook/csvFolder';
import { buildProjectWorkbook, buildWorkbook, createEmptyWorkbook, parseProjectWorkbook, parseSheets } from 'lib/workbook/workbook';
import {
  Breakpoint,
  baseAttribute,
  checkCurve,
  costAt,
  curveFromRows,
  curveShape,
  defaultCurve,
  longToNativeTable,
  nativeTableToLong,
  parsePiecewiseSheetName,
  piecewiseSheetName,
  portAttributes,
  priceAt,
  replaceCurve,
  replaceCurves,
  rowsFromCurve,
} from './piecewise';
import { piecewiseCapableSheets, piecewiseSpecFor, xAttributeOfSheet } from './piecewiseSchema';

// The checked-in schema fixture predates PyPSA 1.3: add the curve table the backend now publishes
// (backend/pypsa/network/piecewise.py::piecewise_catalog) so the schema-aware helpers are exercised.
const CATALOG: Record<string, Array<[string, string, 'cost' | 'efficiency', boolean, boolean]>> = {
  generators: [['marginal_cost', 'p_pu', 'cost', false, false], ['capital_cost', 'p_nom', 'cost', false, true], ['efficiency', 'p_pu', 'efficiency', false, false]],
  links: [['marginal_cost', 'p_pu', 'cost', false, false], ['capital_cost', 'p_nom', 'cost', false, true], ['efficiency', 'p_pu', 'efficiency', true, false]],
  processes: [['marginal_cost', 'p_pu', 'cost', false, false], ['rate', 'p_pu', 'efficiency', true, false]],
  stores: [['marginal_cost', 'p_pu', 'cost', false, false], ['capital_cost', 'e_nom', 'cost', false, true]],
};

beforeAll(() => {
  const schema = JSON.parse(JSON.stringify(schemaFixture));
  Object.entries(CATALOG).forEach(([sheet, rows]) => {
    if (!schema.components[sheet]) return;
    schema.components[sheet].piecewise_attributes = rows.map(([attribute, x, kind, ported, allow]) => ({
      attribute, x, kind, ported, allow_extendable: allow, output: kind === 'cost' ? `${attribute}_piecewise_opt` : null,
      sheet: piecewiseSheetName(sheet, attribute),
    }));
  });
  applyConfigBundle(schema, { fields: [] });
});

afterAll(() => {
  applyConfigBundle(schemaFixture as unknown as Parameters<typeof applyConfigBundle>[0], { fields: [] });
});

const CONVEX: Breakpoint[] = [{ x: 0, y: 0 }, { x: 0.5, y: 10 }, { x: 1, y: 40 }];
const NONCONVEX: Breakpoint[] = [{ x: 0, y: 0 }, { x: 0.5, y: 40 }, { x: 1, y: 10 }];

describe('sheet naming', () => {
  test('round-trips <list>-<attr>-pw and rejects look-alikes', () => {
    expect(piecewiseSheetName('generators', 'marginal_cost')).toBe('generators-marginal_cost-pw');
    expect(parsePiecewiseSheetName('storage_units-capital_cost-pw')).toEqual({ listSheet: 'storage_units', attribute: 'capital_cost' });
    expect(parsePiecewiseSheetName('links-efficiency2-pw')).toEqual({ listSheet: 'links', attribute: 'efficiency2' });
    expect(parsePiecewiseSheetName('generators-p_max_pu')).toBeNull();
    expect(parsePiecewiseSheetName('-pw')).toBeNull();
    expect(baseAttribute('efficiency2')).toBe('efficiency');
    expect(baseAttribute('rate0')).toBe('rate');
    expect(baseAttribute('p_nom')).toBe('p_nom');
  });

  test('every sheet name PyPSA can produce fits Excel\'s 31 characters', () => {
    Object.entries(CATALOG).forEach(([sheet, rows]) => rows.forEach(([attr]) => expect(piecewiseSheetName(sheet, attr).length).toBeLessThanOrEqual(31)));
  });
});

describe('curve shape — mirrors backend curve_shape', () => {
  test('cost curves: convex iff segment prices do not fall', () => {
    expect(curveShape('cost', CONVEX)).toBe('convex');
    expect(curveShape('cost', NONCONVEX)).toBe('nonconvex');
    expect(curveShape('cost', [{ x: 0, y: 0 }, { x: 0.5, y: 20 }, { x: 1, y: 20 }])).toBe('linear');
    // order of entry is irrelevant
    expect(curveShape('cost', [...CONVEX].reverse())).toBe('convex');
  });
  test('efficiency curves: only a straight output line is LP-expressible', () => {
    expect(curveShape('efficiency', [{ x: 0, y: 0 }, { x: 0.5, y: 0.4 }, { x: 1, y: 0.4 }])).toBe('linear');
    expect(curveShape('efficiency', [{ x: 0, y: 0 }, { x: 0.5, y: 0.3 }, { x: 1, y: 0.45 }])).toBe('nonconvex');
    // generator efficiency is inverted (primary energy x / y); constant efficiency stays linear
    expect(curveShape('efficiency', [{ x: 0, y: 0 }, { x: 1, y: 0.5 }], true)).toBe('linear');
  });
});

describe('checkCurve — the conditions the backend refuses', () => {
  const opts = { perUnit: true, kind: 'cost' as const };
  test('a valid convex curve has no errors and an LP hint', () => {
    const c = checkCurve(CONVEX, opts);
    expect(c.errors).toEqual([]);
    expect(c.shape).toBe('convex');
    expect(c.isMip).toBe(false);
    expect(c.warnings.join(' ')).toMatch(/LP/);
  });
  test('non-convex is allowed but flagged as a MIP', () => {
    const c = checkCurve(NONCONVEX, opts);
    expect(c.errors).toEqual([]);
    expect(c.isMip).toBe(true);
    expect(c.warnings.join(' ')).toMatch(/MIP/);
  });
  test('x must be strictly increasing, start at 0 and (per-unit) end at 1', () => {
    expect(checkCurve([{ x: 0, y: 0 }, { x: 0, y: 5 }, { x: 1, y: 9 }], opts).errors.join(' ')).toMatch(/strictly increasing/);
    expect(checkCurve([{ x: 0.2, y: 0 }, { x: 1, y: 9 }], opts).errors.join(' ')).toMatch(/start at x = 0/);
    expect(checkCurve([{ x: 0, y: 0 }, { x: 0.8, y: 9 }], opts).errors.join(' ')).toMatch(/end at x = 1/);
    // an absolute-x capital_cost curve does not have to end at 1
    expect(checkCurve([{ x: 0, y: 0 }, { x: 50, y: 9 }], { perUnit: false, kind: 'cost' }).errors).toEqual([]);
  });
  test('needs two numeric points', () => {
    expect(checkCurve([{ x: 0, y: 0 }], opts).errors.join(' ')).toMatch(/at least 2/);
    expect(checkCurve([{ x: 0, y: 0 }, { x: Number.NaN, y: 1 }], opts).errors.join(' ')).toMatch(/numeric/);
  });
  test('per-unit curve on an extendable row is an error; capital curve is not', () => {
    expect(checkCurve(CONVEX, { ...opts, anyExtendable: true }).errors.join(' ')).toMatch(/fixed capacity/);
    expect(checkCurve([{ x: 0, y: 0 }, { x: 50, y: 9 }], { perUnit: false, kind: 'cost', anyExtendable: true }).errors).toEqual([]);
  });
  test('efficiency curves cannot mix signs; a non-zero y at x=0 is only advice', () => {
    const eff = { perUnit: true, kind: 'efficiency' as const };
    expect(checkCurve([{ x: 0, y: -0.1 }, { x: 1, y: 0.5 }], eff).errors.join(' ')).toMatch(/mix positive and negative/);
    const c = checkCurve([{ x: 0, y: 3 }, { x: 1, y: 5 }], opts);
    expect(c.errors).toEqual([]);
    expect(c.warnings.join(' ')).toMatch(/y at x = 0 is ignored/);
  });
});

describe('cost maths', () => {
  test('price and total cost follow the segment convention', () => {
    expect(priceAt(CONVEX, 0.25)).toBe(10);
    expect(priceAt(CONVEX, 0.75)).toBe(40);
    // C(0.75) = 10*0.5 + 40*0.25
    expect(costAt(CONVEX, 0.75)).toBeCloseTo(15, 12);
    expect(costAt(CONVEX, 1)).toBeCloseTo(25, 12);
    expect(costAt(CONVEX, 0)).toBe(0);
    // the same numbers as the backend parity test: g at 50 MW on a 100 MW unit costs 10 * 50
    expect(costAt(CONVEX, 0.5) * 100).toBeCloseTo(500, 9);
  });
  test('default curves pass their own validation', () => {
    const gen = piecewiseSpecFor('generators', 'marginal_cost')!;
    expect(checkCurve(defaultCurve(gen), { perUnit: true, kind: 'cost' }).errors).toEqual([]);
    const eff = piecewiseSpecFor('generators', 'efficiency')!;
    expect(checkCurve(defaultCurve(eff), { perUnit: true, kind: 'efficiency' }).errors).toEqual([]);
    const cap = piecewiseSpecFor('generators', 'capital_cost')!;
    expect(checkCurve(defaultCurve(cap, 100), { perUnit: false, kind: 'cost' }).errors).toEqual([]);
  });
});

describe('long rows', () => {
  test('rowsFromCurve / curveFromRows round-trip and sort by x', () => {
    const rows = rowsFromCurve('g1', 'p_pu', 'marginal_cost', [...CONVEX].reverse());
    expect(rows).toEqual([
      { name: 'g1', breakpoint: 0, p_pu: 0, marginal_cost: 0 },
      { name: 'g1', breakpoint: 1, p_pu: 0.5, marginal_cost: 10 },
      { name: 'g1', breakpoint: 2, p_pu: 1, marginal_cost: 40 },
    ]);
    expect(curveFromRows(rows, 'g1', 'p_pu', 'marginal_cost')).toEqual(CONVEX);
    expect(curveFromRows(rows, 'other', 'p_pu', 'marginal_cost')).toEqual([]);
  });
  test('replaceCurve touches only the named component; pts=[] clears it', () => {
    const base = [...rowsFromCurve('a', 'p_pu', 'marginal_cost', CONVEX), ...rowsFromCurve('b', 'p_pu', 'marginal_cost', NONCONVEX)];
    const next = replaceCurve(base, 'a', 'p_pu', 'marginal_cost', NONCONVEX);
    expect(curveFromRows(next, 'a', 'p_pu', 'marginal_cost')).toEqual(NONCONVEX);
    expect(curveFromRows(next, 'b', 'p_pu', 'marginal_cost')).toEqual(NONCONVEX);
    const cleared = replaceCurve(next, 'a', 'p_pu', 'marginal_cost', []);
    expect(cleared.every((r) => r.name === 'b')).toBe(true);
    const many = replaceCurves(base, ['a', 'c'], 'p_pu', 'marginal_cost', CONVEX);
    expect(curveFromRows(many, 'c', 'p_pu', 'marginal_cost')).toEqual(CONVEX);
    expect(curveFromRows(many, 'b', 'p_pu', 'marginal_cost')).toEqual(NONCONVEX);
  });
});

describe('schema-aware lookups', () => {
  test('specs come from the bundle; ported attributes resolve to their base spec', () => {
    expect(piecewiseSpecFor('generators', 'marginal_cost')?.x).toBe('p_pu');
    expect(piecewiseSpecFor('links', 'efficiency2')?.attribute).toBe('efficiency');
    expect(piecewiseSpecFor('processes', 'rate1')?.attribute).toBe('rate');
    expect(piecewiseSpecFor('buses', 'marginal_cost')).toBeNull();
    expect(xAttributeOfSheet('stores-capital_cost-pw')).toBe('e_nom');
    expect(xAttributeOfSheet('generators-p_max_pu')).toBeNull();
    expect(piecewiseCapableSheets()).toEqual(expect.arrayContaining(['generators', 'links', 'processes', 'stores']));
  });
  test('port attributes follow the bus columns in use', () => {
    const link = piecewiseSpecFor('links', 'efficiency')!;
    expect(portAttributes(link, [{ name: 'l', bus0: 'a', bus1: 'b' }])).toEqual(['efficiency']);
    expect(portAttributes(link, [{ name: 'l', bus0: 'a', bus1: 'b', bus2: 'c', bus3: '' }])).toEqual(['efficiency', 'efficiency2']);
    const proc = piecewiseSpecFor('processes', 'rate')!;
    expect(portAttributes(proc, [{ name: 'p', bus0: 'a', bus1: 'b', bus2: 'c' }])).toEqual(['rate0', 'rate1', 'rate2']);
  });
});

describe('PyPSA-native wide layout', () => {
  test('long -> native table -> long is lossless, including ragged curves', () => {
    const rows = [...rowsFromCurve('g', 'p_pu', 'marginal_cost', CONVEX), ...rowsFromCurve('h', 'p_pu', 'marginal_cost', [{ x: 0, y: 0 }, { x: 1, y: 7 }])];
    const table = longToNativeTable(rows, 'p_pu', 'marginal_cost');
    expect(table[0]).toEqual(['name', 'g', 'g', 'h', 'h']);
    expect(table[1]).toEqual(['attribute', 'p_pu', 'marginal_cost', 'p_pu', 'marginal_cost']);
    expect(table[2]).toEqual(['breakpoint', '', '', '', '']);
    expect(table[3]).toEqual(['0', '0', '0', '0', '0']);
    expect(table[5]).toEqual(['2', '1', '40', '', '']);
    const back = nativeTableToLong(table, 'p_pu', 'marginal_cost');
    expect(curveFromRows(back, 'g', 'p_pu', 'marginal_cost')).toEqual(CONVEX);
    expect(curveFromRows(back, 'h', 'p_pu', 'marginal_cost')).toEqual([{ x: 0, y: 0 }, { x: 1, y: 7 }]);
  });
  test('reads exactly what PyPSA writes (generators-marginal_cost-pw.csv)', () => {
    const native = [['name', 'g', 'g'], ['attribute', 'p_pu', 'marginal_cost'], ['breakpoint', '', ''], ['0', '0.0', '0.0'], ['1', '0.5', '10.0'], ['2', '1.0', '40.0']];
    expect(curveFromRows(nativeTableToLong(native, 'p_pu', 'marginal_cost'), 'g', 'p_pu', 'marginal_cost')).toEqual(CONVEX);
  });
});

describe('workbook I/O keeps the curves (P40)', () => {
  const SHEET = 'generators-marginal_cost-pw';
  const model = () => {
    const m = createEmptyWorkbook();
    m.generators = [{ name: 'g', bus: 'b', p_nom: 100 }];
    (m as Record<string, unknown>)[SHEET] = rowsFromCurve('g', 'p_pu', 'marginal_cost', NONCONVEX);
    return m;
  };

  test('CSV folder zip: native wide file out, same curve back in', async () => {
    const bytes = exportModelAsCsvFolderBytes(model(), 'case');
    const { unzipSync, strFromU8 } = await import('fflate');
    const files = unzipSync(bytes);
    const csv = strFromU8(files[`case/${SHEET}.csv`]);
    expect(csv.split('\n')[0]).toBe('name,g,g'); // PyPSA's own header, not our long layout
    const { model: imported, unknownFiles, importedSheets } = await importCsvFolderZip(bytes);
    expect(unknownFiles).toEqual([]);
    expect(importedSheets).toContain(SHEET);
    expect(curveFromRows((imported as Record<string, any>)[SHEET], 'g', 'p_pu', 'marginal_cost')).toEqual(NONCONVEX);
  });

  test('CSV folder zip also reads a long-form -pw file', async () => {
    const { zipSync, strToU8 } = await import('fflate');
    const zip = zipSync({ [`x/${SHEET}.csv`]: strToU8('name,breakpoint,p_pu,marginal_cost\ng,0,0,0\ng,1,1,9\n') });
    const { model: imported } = await importCsvFolderZip(zip);
    expect(curveFromRows((imported as Record<string, any>)[SHEET], 'g', 'p_pu', 'marginal_cost')).toEqual([{ x: 0, y: 0 }, { x: 1, y: 9 }]);
  });

  test('xlsx workbook (inputs only) round-trips the long sheet', () => {
    const wb = buildWorkbook(model());
    expect(wb.SheetNames).toContain(SHEET);
    const back = parseSheets(wb);
    expect(curveFromRows((back as Record<string, any>)[SHEET], 'g', 'p_pu', 'marginal_cost')).toEqual(NONCONVEX);
  });

  test('project workbook (inputs + outputs) round-trips the long sheet', () => {
    const wb = buildProjectWorkbook(model());
    expect(wb.SheetNames).toContain(SHEET);
    const XLSX = require('xlsx');
    const buf = XLSX.write(wb, { bookType: 'xlsx', type: 'array' }) as ArrayBuffer;
    const { model: back } = parseProjectWorkbook(buf);
    expect(curveFromRows((back as Record<string, any>)[SHEET], 'g', 'p_pu', 'marginal_cost')).toEqual(NONCONVEX);
  });
});
