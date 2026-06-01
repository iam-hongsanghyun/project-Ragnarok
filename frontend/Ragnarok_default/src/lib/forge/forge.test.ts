import { describe, test, expect } from '@jest/globals';
import { applyRounding, numericColumns } from './transforms';
import { buildTargets, haversineKm, sheetSnappable, snapSheet } from './snap';
import { nonEmptySheets, roundFindings, snapFindings } from './validate';
import type { GridRow, WorkbookModel } from 'lib/types';

describe('forge/transforms', () => {
  const rows: GridRow[] = [
    { name: 'a', p: 1.234, q: '5.678', s: 'abc' },
    { name: 'b', p: 2.0 },
  ];

  test('numericColumns: only all-numeric, non-name columns', () => {
    expect(numericColumns(rows)).toEqual(['p', 'q']);
  });

  test('round respects decimals and converts numeric strings', () => {
    const { rows: out, changed } = applyRounding(rows, ['p', 'q', 's'], 'round', 1);
    expect(out[0].p).toBe(1.2);
    expect(out[0].q).toBe(5.7);
    expect(out[0].s).toBe('abc'); // non-numeric untouched
    expect(out[1].p).toBe(2); // already whole → unchanged
    expect(changed).toBe(2);
    expect(out[1]).toBe(rows[1]); // unchanged row keeps identity
  });

  test('ceil and floor', () => {
    expect(applyRounding(rows, ['p'], 'ceil', 0).rows[0].p).toBe(2);
    expect(applyRounding(rows, ['p'], 'floor', 0).rows[0].p).toBe(1);
  });
});

describe('forge/snap', () => {
  test('haversine ~111 km per degree of longitude at the equator', () => {
    expect(haversineKm(0, 0, 0, 1)).toBeCloseTo(111.19, 0);
  });

  const buses: GridRow[] = [
    { name: 'A', x: 0, y: 0 },
    { name: 'B', x: 1, y: 0 },
  ];
  const targets = buildTargets(buses);

  test('buildTargets reads x=lon, y=lat from named rows', () => {
    expect(targets.map((t) => t.name)).toEqual(['A', 'B']);
    expect(targets[1]).toMatchObject({ lat: 0, lon: 1 });
  });

  test('snap assigns nearest within buffer and reports those outside', () => {
    const overlay: GridRow[] = [
      { name: 'g1', x: 0.1, y: 0, bus: '' }, // ~11 km from A
      { name: 'g2', x: 0.9, y: 0, bus: '' }, // ~11 km from B
      { name: 'far', x: 5, y: 0, bus: '' }, // ~445 km from B
      { name: 'nogeo', bus: '' }, // no coordinates
    ];
    const r = snapSheet(overlay, targets, 50);
    expect(r.rows[0].bus).toBe('A');
    expect(r.rows[1].bus).toBe('B');
    expect(r.rows[2].bus).toBe(''); // beyond buffer → unchanged
    expect(r.assigned).toBe(2);
    expect(r.outside).toHaveLength(1);
    expect(r.outside[0]).toMatchObject({ name: 'far', nearest: 'B', field: 'bus' });
    expect(r.noCoords).toBe(1);
    expect(r.anchors).toEqual(['bus']);
  });

  test('snap drives bus0 / bus1 from branch endpoint anchors', () => {
    const lines: GridRow[] = [{ name: 'L', x0: 0, y0: 0, x1: 1, y1: 0, bus0: '', bus1: '' }];
    const r = snapSheet(lines, targets, 50);
    expect(r.rows[0].bus0).toBe('A');
    expect(r.rows[0].bus1).toBe('B');
    expect(r.assigned).toBe(2);
    expect(r.anchors.sort()).toEqual(['bus0', 'bus1']);
  });

  test('sheetSnappable detects any coordinate anchor', () => {
    expect(sheetSnappable([{ name: 'g', x: 1, y: 2 }])).toBe(true);
    expect(sheetSnappable([{ name: 'g', bus: 'A' }])).toBe(false);
  });
});

describe('forge/validate', () => {
  test('nonEmptySheets lists only sheets that hold rows', () => {
    const model = {
      buses: [{ name: 'A' }],
      generators: [],
      snapshots: [{ snapshot: 't' }],
    } as unknown as WorkbookModel;
    expect(nonEmptySheets(model).sort()).toEqual(['buses', 'snapshots']);
  });

  test('roundFindings reports values not at the chosen precision', () => {
    const model = {
      generators: [{ name: 'g', p_nom: 1.234, capital_cost: 5 }],
    } as unknown as WorkbookModel;
    const f = roundFindings(model, 1, 1e7, 1e-6);
    expect(f).toHaveLength(1); // p_nom needs rounding; capital_cost already integral
    expect(f[0]).toMatchObject({ sheet: 'generators' });
    expect(f[0].message).toContain('p_nom');
  });

  test('roundFindings flags magnitude outliers', () => {
    const model = { generators: [{ name: 'g', capital_cost: 20000000 }] } as unknown as WorkbookModel;
    const f = roundFindings(model, 2, 1e7, 1e-6);
    expect(f).toHaveLength(1);
    expect(f[0].message).toContain('very large');
  });

  test('snapFindings reports coordinate rows with missing / unknown bus', () => {
    const model = {
      buses: [{ name: 'A', x: 0, y: 0 }],
      generators: [
        { name: 'g1', x: 0.1, y: 0, bus: '' }, // missing bus
        { name: 'g2', x: 0.2, y: 0, bus: 'ZZZ' }, // unknown bus
        { name: 'g3', x: 0.3, y: 0, bus: 'A' }, // already connected
      ],
    } as unknown as WorkbookModel;
    const f = snapFindings(model);
    expect(f).toHaveLength(1);
    expect(f[0].sheet).toBe('generators');
    expect(f[0].message).toContain('1 with coordinates & no bus');
    expect(f[0].message).toContain('1 referencing an unknown bus');
  });
});
