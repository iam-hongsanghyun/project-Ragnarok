import { describe, test, expect } from '@jest/globals';
import { globalConstraintHints, growthLimitHint, type ConstraintHintContext } from './globalConstraintHints';

const ctx: ConstraintHintContext = {
  carriers: ['gas', 'wind'],
  carrierAttributes: ['name', 'co2_emissions'],
  investmentPeriods: [],
  pathwayEnabled: false,
};

describe('globalConstraintHints (P27)', () => {
  test('investment_period on a single-period primary_energy row is an error', () => {
    const h = globalConstraintHints({ name: 'cap', type: 'primary_energy', sense: '<=', investment_period: 2030 }, ctx);
    expect(h.some((x) => x.severity === 'error' && /investment_period/.test(x.message))).toBe(true);
  });
  test('investment_period outside the configured periods warns in pathway mode', () => {
    const h = globalConstraintHints(
      { name: 'cap', type: 'operational_limit', sense: '<=', investment_period: 2040 },
      { ...ctx, pathwayEnabled: true, investmentPeriods: [2030, 2050] },
    );
    expect(h.map((x) => x.severity)).toEqual(['warning']);
  });
  test('tech_capacity_expansion_limit needs a carrier', () => {
    expect(globalConstraintHints({ type: 'tech_capacity_expansion_limit', sense: '<=' }, ctx)[0].severity).toBe('error');
    expect(globalConstraintHints({ type: 'tech_capacity_expansion_limit', sense: '<=', carrier_attribute: 'coal' }, ctx)[0].severity).toBe('warning');
    expect(globalConstraintHints({ type: 'tech_capacity_expansion_limit', sense: '<=', carrier_attribute: 'gas' }, ctx)).toEqual([]);
  });
  test('primary_energy attribute must be a carriers column; unknown type is an error', () => {
    expect(globalConstraintHints({ type: 'primary_energy', sense: '<=', carrier_attribute: 'nope' }, ctx)).toHaveLength(1);
    expect(globalConstraintHints({ type: 'primary_energy', sense: '<=', carrier_attribute: 'co2_emissions' }, ctx)).toEqual([]);
    expect(globalConstraintHints({ type: 'bogus', sense: '<=' }, ctx)[0].severity).toBe('error');
  });
});

describe('growthLimitHint (P27)', () => {
  test('mirrors check_growth_limits', () => {
    expect(growthLimitHint('max_growth', '', false)).toBeNull();
    expect(growthLimitHint('max_growth', Infinity, false)).toBeNull();
    expect(growthLimitHint('max_relative_growth', 0, false)).toBeNull();
    expect(growthLimitHint('max_growth', -1, true)?.severity).toBe('error');
    expect(growthLimitHint('max_growth', 100, false)?.severity).toBe('warning');
    expect(growthLimitHint('max_growth', 100, true)).toBeNull();
  });
});
