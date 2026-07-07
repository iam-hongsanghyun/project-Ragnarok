import { describe, it, expect } from '@jest/globals';
import { buildRequest, filterReady, QueryFilterState } from './queryEdit';

const filter = (p: Partial<QueryFilterState>): QueryFilterState => ({
  id: 'f', join: false, joinComponent: '', refColumn: 'bus', column: '', op: 'eq', value: '', ...p,
});

describe('buildRequest', () => {
  const base = {
    target: 'generators',
    attribute: 'p_nom',
    temporal: false,
    derive: { source_attr: 'p_nom', coefficient: 3, constant: 0 },
  };

  it('converts a multiply percent to a factor at the wire boundary', () => {
    const req = buildRequest({ ...base, filters: [], op: 'multiply', amount: '80' });
    expect(req.edit).toEqual({ op: 'multiply', amount: 0.8 });
  });

  it('passes set/add amounts through unchanged', () => {
    expect(buildRequest({ ...base, filters: [], op: 'add', amount: '5' }).edit).toEqual({ op: 'add', amount: 5 });
    expect(buildRequest({ ...base, filters: [], op: 'set', amount: '12' }).edit).toEqual({ op: 'set', amount: 12 });
  });

  it('builds a derive edit from coefficient/source/constant', () => {
    const req = buildRequest({ ...base, filters: [], op: 'derive', amount: '0' });
    expect(req.edit).toEqual({ op: 'derive', source_attr: 'p_nom', coefficient: 3, constant: 0 });
  });

  it('serializes a join filter with ref column', () => {
    const req = buildRequest({
      ...base,
      op: 'multiply', amount: '80',
      filters: [filter({ join: true, joinComponent: 'buses', refColumn: 'bus', column: 'province', op: 'eq', value: 'Seoul' })],
    });
    expect(req.filters).toEqual([
      { column: 'province', op: 'eq', value: 'Seoul', join: { component: 'buses', ref_column: 'bus' } },
    ]);
  });

  it('splits an "in" value into a values array', () => {
    const req = buildRequest({
      ...base, op: 'set', amount: '0',
      filters: [filter({ column: 'carrier', op: 'in', value: 'gas, oil , coal' })],
    });
    expect(req.filters[0]).toEqual({ column: 'carrier', op: 'in', values: ['gas', 'oil', 'coal'] });
  });

  it('drops incomplete filters', () => {
    const req = buildRequest({
      ...base, op: 'set', amount: '0',
      filters: [filter({ column: '', value: 'x' }), filter({ column: 'carrier', op: 'eq', value: 'gas' })],
    });
    expect(req.filters).toHaveLength(1);
  });
});

describe('filterReady', () => {
  it('requires a column and a value', () => {
    expect(filterReady(filter({ column: '', value: 'x' }))).toBe(false);
    expect(filterReady(filter({ column: 'carrier', value: '' }))).toBe(false);
    expect(filterReady(filter({ column: 'carrier', value: 'gas' }))).toBe(true);
  });

  it('requires join component + ref column when joining', () => {
    expect(filterReady(filter({ join: true, joinComponent: '', column: 'province', value: 'Seoul' }))).toBe(false);
    expect(filterReady(filter({ join: true, joinComponent: 'buses', refColumn: 'bus', column: 'province', value: 'Seoul' }))).toBe(true);
  });
});
