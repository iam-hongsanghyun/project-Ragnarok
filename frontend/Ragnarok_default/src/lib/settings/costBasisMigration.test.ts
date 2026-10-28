import { describe, it, expect } from '@jest/globals';
import { formatCostBasisMigration } from './costBasisMigration';
import { needsCostBasisMigration, stampSchema, createEmptyWorkbook, parseSheets } from 'lib/workbook/workbook';
import * as XLSX from 'xlsx';

const report = {
  fromVersion: 1, toVersion: 2, discountRate: 0.05, discountRateSource: 'the run / app setting',
  changedRows: [
    { sheet: 'generators', name: 'wind_1', extendable: true, capital_cost_was: 1200000, overnight_cost: 1200000, discount_rate: 0.05, lifetime: 25, lifetimeDefaulted: false },
    { sheet: 'generators', name: 'gas', extendable: true, capital_cost_was: 60000, overnight_cost: 60000, discount_rate: 0.05, lifetime: 20, lifetimeDefaulted: true },
    { sheet: 'generators', name: 'old', extendable: false, capital_cost_was: 5, overnight_cost: 5, discount_rate: 0.05, lifetime: null, lifetimeDefaulted: false },
  ],
  review: [{ sheet: 'links', name: 'l1', reason: 'has a piecewise capital_cost curve' }],
  notes: ['note'],
};

describe('formatCostBasisMigration', () => {
  it('lists the rows, the rate and the review items', () => {
    const text = formatCostBasisMigration(report);
    expect(text).toContain('3 row(s)');
    expect(text).toContain('5.00 %');
    expect(text).toContain('generators / wind_1: overnight_cost 1,200,000, lifetime 25 y');
    expect(text).toContain('20 y (was unset)');
    expect(text).toContain('fixed asset');
    expect(text).toContain('links / l1: has a piecewise capital_cost curve');
  });
});

describe('needsCostBasisMigration', () => {
  it('is false for a stamped workbook and for a plain PyPSA workbook', () => {
    expect(needsCostBasisMigration(createEmptyWorkbook())).toBe(false);
    const pypsa = { generators: [{ name: 'g', capital_cost: 5 }] } as never;
    expect(needsCostBasisMigration(pypsa)).toBe(false);
  });
  it('is true for an unstamped Ragnarok workbook (has RAGNAROK_* sheets)', () => {
    const old = { generators: [{ name: 'g', capital_cost: 5 }], RAGNAROK_Scenarios: [{ name: 'a' }] } as never;
    expect(needsCostBasisMigration(old)).toBe(true);
    expect(needsCostBasisMigration(stampSchema(old))).toBe(false);
  });
  it('a parsed file does not inherit the empty workbook stamp', () => {
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet([{ name: 'g', capital_cost: 5 }]), 'generators');
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet([{ name: 's' }]), 'RAGNAROK_Scenarios');
    expect(needsCostBasisMigration(parseSheets(wb))).toBe(true);
  });
});
