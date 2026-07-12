import { describe, it, expect } from '@jest/globals';
import { buildRequest, filterReady, QueryFilterState } from './queryEdit';

const filter = (p: Partial<QueryFilterState>): QueryFilterState => ({
  id: 'f', via: '', column: '', op: 'any', values: [], text: '', ...p,
});

describe('buildRequest', () => {
  const base = {
    target: 'generators',
    attribute: 'p_nom',
    temporal: false,
    unit: 'mw' as const,
    scope: 'each' as const,
    split: 'proportional' as const,
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

  it('carries unit/scope/split on a temporal add only', () => {
    const req = buildRequest({
      ...base, temporal: true, filters: [], op: 'add', amount: '100',
      unit: 'mwh', scope: 'total', split: 'equal',
    });
    expect(req.edit).toEqual({ op: 'add', amount: 100, unit: 'mwh', scope: 'total', split: 'equal' });
    // A static add stays a plain amount.
    const stat = buildRequest({ ...base, filters: [], op: 'add', amount: '100', unit: 'mwh', scope: 'total', split: 'equal' });
    expect(stat.edit).toEqual({ op: 'add', amount: 100 });
  });

  it('builds a derive edit from coefficient/source/constant', () => {
    const req = buildRequest({ ...base, filters: [], op: 'derive', amount: '0' });
    expect(req.edit).toEqual({ op: 'derive', source_attr: 'p_nom', coefficient: 3, constant: 0 });
  });

  it('builds the buses join from a via-bus filter', () => {
    const req = buildRequest({
      ...base,
      op: 'multiply', amount: '80',
      filters: [filter({ via: 'bus', column: 'province', values: ['Seoul'] })],
    });
    expect(req.filters).toEqual([
      { column: 'province', op: 'eq', value: 'Seoul', join: { component: 'buses', ref_column: 'bus' } },
    ]);
  });

  it('maps a multi-value "is any of" to an in filter (union)', () => {
    const req = buildRequest({
      ...base, op: 'set', amount: '0',
      filters: [filter({ column: 'carrier', values: ['gas', 'oil', 'coal'] })],
    });
    expect(req.filters[0]).toEqual({ column: 'carrier', op: 'in', values: ['gas', 'oil', 'coal'] });
  });

  it('maps "is none of" to one ANDed ne per value', () => {
    const req = buildRequest({
      ...base, op: 'set', amount: '0',
      filters: [filter({ column: 'carrier', op: 'none', values: ['gas', 'oil'] })],
    });
    expect(req.filters).toEqual([
      { column: 'carrier', op: 'ne', value: 'gas' },
      { column: 'carrier', op: 'ne', value: 'oil' },
    ]);
  });

  it('passes text ops through with their typed value', () => {
    const req = buildRequest({
      ...base, op: 'set', amount: '0',
      filters: [filter({ column: 'p_nom', op: 'gt', text: ' 50 ' })],
    });
    expect(req.filters[0]).toEqual({ column: 'p_nom', op: 'gt', value: '50' });
  });

  it('drops incomplete filters', () => {
    const req = buildRequest({
      ...base, op: 'set', amount: '0',
      filters: [filter({ column: '', values: ['x'] }), filter({ column: 'carrier', values: ['gas'] })],
    });
    expect(req.filters).toHaveLength(1);
  });
});

describe('filterReady', () => {
  it('requires a column and at least one value', () => {
    expect(filterReady(filter({ column: '', values: ['x'] }))).toBe(false);
    expect(filterReady(filter({ column: 'carrier', values: [] }))).toBe(false);
    expect(filterReady(filter({ column: 'carrier', values: ['gas', 'oil'] }))).toBe(true);
  });

  it('requires typed text for contains / numeric ops', () => {
    expect(filterReady(filter({ column: 'carrier', op: 'contains', text: '' }))).toBe(false);
    expect(filterReady(filter({ column: 'p_nom', op: 'gt', text: '50' }))).toBe(true);
  });
});
