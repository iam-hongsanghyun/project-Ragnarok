import { describe, it, expect } from '@jest/globals';
// applyAdjustments / revertAdjustments now live in backend/app/forge_helpers.py;
// their parity tests are in backend/tests/test_forge_build_helpers.py.
import {
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

describe('matchCount', () => {
  it('counts rows matching the filters', () => {
    expect(matchCount(model, 'generators', [{ column: 'carrier', value: 'gas' }])).toBe(3);
    expect(matchCount(model, 'generators', [{ column: 'carrier', value: 'gas' }, { column: 'province', value: '경상남도' }])).toBe(2);
  });
});
