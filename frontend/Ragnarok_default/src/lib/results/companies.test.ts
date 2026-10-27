import { describe, test, expect } from '@jest/globals';
import { joinCompanies } from './companies';
import type { CompanyBreakdownResult, CompanyFinanceResult, CompanyStatementResult } from 'lib/types';

const breakdown = {
  currency: '$',
  companies: [
    { company: 'A', capacityMW: 100, energyMWh: 10, revenue: 500, emissionsTonnes: 5 },
    { company: 'B', capacityMW: 300, energyMWh: 20, revenue: 200, emissionsTonnes: 50 },
  ],
} as unknown as CompanyBreakdownResult;
const finance = {
  currency: '$',
  companies: [{ company: 'A', npv: 10, irr: 0.1, paybackYears: 4 }],
} as unknown as CompanyFinanceResult;
const statement = {
  currency: '$',
  companies: [{ company: 'B', netMargin: 77 }],
} as unknown as CompanyStatementResult;

describe('joinCompanies', () => {
  test('joins the three blocks by name and sorts by the first available metric, missing last', () => {
    const out = joinCompanies(breakdown, finance, statement);
    expect(out.metrics.map((m) => m.key)).toEqual(['npv', 'netMargin', 'irr', 'revenue', 'capacityMW', 'emissionsTonnes']);
    expect(out.sortedBy).toBe('npv');
    expect(out.items.map((r) => r.company)).toEqual(['A', 'B']); // B has no npv -> last
    expect(out.items[1].netMargin).toBe(77);
    expect(out.currency).toBe('$');
  });
  test('lower-is-better metrics sort ascending; unknown sort key falls back', () => {
    expect(joinCompanies(breakdown, undefined, undefined, 'emissionsTonnes').items.map((r) => r.company)).toEqual(['A', 'B']);
    expect(joinCompanies(breakdown, undefined, undefined, 'capacityMW').items.map((r) => r.company)).toEqual(['B', 'A']);
    expect(joinCompanies(breakdown, undefined, undefined, 'bogus').sortedBy).toBe('revenue');
  });
});
