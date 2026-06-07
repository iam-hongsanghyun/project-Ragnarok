import { describe, it, expect } from '@jest/globals';
import {
  Adjustment,
  applyAction,
  applyAdjustments,
  columnsOf,
  matchCount,
  rowMatches,
  uniqueValues,
} from './adjust';
import { WorkbookModel } from 'lib/types';

const model = {
  generators: [
    { name: 'g1', carrier: 'gas', province: '경상남도', p_nom: 100 },
    { name: 'g2', carrier: 'gas', province: '서울', p_nom: 200 },
    { name: 'g3', carrier: 'coal', province: '경상남도', p_nom: 300 },
    { name: 'g4', carrier: 'gas', province: '경상남도' }, // no p_nom
  ],
} as unknown as WorkbookModel;

describe('columnsOf / uniqueValues', () => {
  it('lists the union of columns incl. non-PyPSA ones (province)', () => {
    expect(columnsOf(model.generators)).toEqual(['carrier', 'name', 'p_nom', 'province']);
  });
  it('lists distinct non-blank values of a column', () => {
    expect(uniqueValues(model.generators, 'carrier')).toEqual(['coal', 'gas']);
    expect(uniqueValues(model.generators, 'province')).toEqual(['경상남도', '서울']);
    expect(uniqueValues(model.generators, 'missing')).toEqual([]);
  });
});

describe('rowMatches', () => {
  it('ANDs equality filters; blank filters are no-ops', () => {
    const row = model.generators[0];
    expect(rowMatches(row, [{ column: 'carrier', value: 'gas' }])).toBe(true);
    expect(rowMatches(row, [{ column: 'carrier', value: 'gas' }, { column: 'province', value: '경상남도' }])).toBe(true);
    expect(rowMatches(row, [{ column: 'carrier', value: 'coal' }])).toBe(false);
    expect(rowMatches(row, [{ column: '', value: '' }])).toBe(true);
  });
});

describe('applyAction', () => {
  it('multiply is percent, add is delta, set is absolute', () => {
    expect(applyAction(200, 'multiply', 50)).toBe(100); // 50%
    expect(applyAction(200, 'multiply', 100)).toBe(200); // unchanged
    expect(applyAction(200, 'add', -25)).toBe(175);
    expect(applyAction(200, 'set', 42)).toBe(42);
  });
});

describe('applyAdjustments', () => {
  it('multiplies p_nom for gas in 경상남도 by 50%, leaving others untouched', () => {
    const adj: Adjustment = {
      id: 'a', sheet: 'generators',
      filters: [{ column: 'carrier', value: 'gas' }, { column: 'province', value: '경상남도' }],
      attribute: 'p_nom', action: 'multiply', amount: 50,
    };
    const out = applyAdjustments(model, [adj]);
    const gens = out.sheets.generators;
    expect(gens.find((r) => r.name === 'g1')!.p_nom).toBe(50);  // 100 × 50%
    expect(gens.find((r) => r.name === 'g2')!.p_nom).toBe(200); // 서울 untouched
    expect(gens.find((r) => r.name === 'g3')!.p_nom).toBe(300); // coal untouched
    expect(out.changed).toBe(1);
    expect(out.perAdjustment).toEqual([1]);
    // original model is not mutated
    expect(model.generators.find((r) => r.name === 'g1')!.p_nom).toBe(100);
  });

  it('skips multiply/add on rows whose attribute is not numeric', () => {
    const adj: Adjustment = {
      id: 'a', sheet: 'generators', filters: [{ column: 'carrier', value: 'gas' }],
      attribute: 'p_nom', action: 'add', amount: 10,
    };
    const out = applyAdjustments(model, [adj]);
    // g1 100→110, g2 200→210; g4 (no p_nom) skipped
    expect(out.changed).toBe(2);
    expect(out.sheets.generators.find((r) => r.name === 'g4')!.p_nom).toBeUndefined();
  });

  it('set writes even where the attribute was missing', () => {
    const adj: Adjustment = {
      id: 'a', sheet: 'generators', filters: [{ column: 'name', value: 'g4' }],
      attribute: 'p_nom', action: 'set', amount: 5,
    };
    const out = applyAdjustments(model, [adj]);
    expect(out.sheets.generators.find((r) => r.name === 'g4')!.p_nom).toBe(5);
    expect(out.changed).toBe(1);
  });

  it('stacks: later adjustments see earlier results on the same sheet', () => {
    const adjustments: Adjustment[] = [
      { id: 'a', sheet: 'generators', filters: [{ column: 'carrier', value: 'gas' }], attribute: 'p_nom', action: 'set', amount: 100 },
      { id: 'b', sheet: 'generators', filters: [{ column: 'province', value: '경상남도' }], attribute: 'p_nom', action: 'multiply', amount: 200 },
    ];
    const out = applyAdjustments(model, adjustments);
    const g1 = out.sheets.generators.find((r) => r.name === 'g1')!; // gas+경남: set 100 then ×200% = 200
    expect(g1.p_nom).toBe(200);
  });
});

describe('matchCount', () => {
  it('counts rows matching the filters', () => {
    expect(matchCount(model, 'generators', [{ column: 'carrier', value: 'gas' }])).toBe(3);
    expect(matchCount(model, 'generators', [{ column: 'carrier', value: 'gas' }, { column: 'province', value: '경상남도' }])).toBe(2);
  });
});
