import { describe, test, expect } from '@jest/globals';
import type { RunResults } from 'lib/types';
import { dualSheetsIn, dualSheetsOf, parseDualSheet, summariseDualSheet } from './dualViews';

const rows = [
  { snapshot: '2030-01-01T00:00:00', gas: 0, coal: 0 },
  { snapshot: '2030-01-01T01:00:00', gas: -12.5, coal: 0 },
  { snapshot: '2030-01-01T02:00:00', gas: -30, coal: 0 },
  { snapshot: '2030-01-01T03:00:00', gas: 0, coal: 0 },
  { snapshot: '2030-01-01T04:00:00', gas: 5, coal: 0 },
];

describe('dual views (P30)', () => {
  test('recognises only the four dual output sheets', () => {
    expect(dualSheetsIn(['generators-p', 'generators-mu_ramp_limit_up', 'storage_units-mu_state_of_charge_set', 'generators-mu_upper']))
      .toEqual(['generators-mu_ramp_limit_up', 'storage_units-mu_state_of_charge_set']);
    expect(parseDualSheet('links-mu_p_set')).toEqual({ component: 'links', attribute: 'mu_p_set' });
    expect(parseDualSheet('links-p0')).toBeNull();
  });

  test('summarises binding hours, peak shadow price, and drops slack assets', () => {
    const s = summariseDualSheet('generators-mu_ramp_limit_down', rows, 2);
    expect(s.assetsChecked).toBe(2);
    expect(s.rows).toHaveLength(1);
    const g = s.rows[0];
    expect(g.asset).toBe('gas');
    expect(g.bindingSnapshots).toBe(3);
    expect(g.bindingHours).toBe(6); // 3 snapshots x weight 2
    expect(g.peakShadowPrice).toBe(-30);
    expect(g.peakAt).toBe('2030-01-01T02:00:00');
    expect(g.meanShadowPrice).toBeCloseTo((12.5 + 30 + 5) / 3, 10);
    expect(g.segments).toEqual([
      { on: false, length: 1 }, { on: true, length: 2 }, { on: false, length: 1 }, { on: true, length: 1 },
    ]);
  });

  test('tolerance separates numerical noise from binding', () => {
    expect(summariseDualSheet('generators-mu_p_set', [{ snapshot: 'a', g: 1e-9 }], 1).rows).toEqual([]);
    expect(summariseDualSheet('generators-p', rows, 1).rows).toEqual([]);
  });

  test('dualSheetsOf reads populated series of a full bundle and seriesSheets of a light one', () => {
    const full = { outputs: { static: {}, series: { 'generators-mu_p_set': [{ snapshot: 'a', g: 1 }], 'links-mu_p_set': [], 'generators-p': [{ snapshot: 'a', g: 1 }] } } } as unknown as RunResults;
    expect(dualSheetsOf(full)).toEqual(['generators-mu_p_set']);
    const light = { outputs: { static: {}, series: null, seriesSheets: ['generators-p', 'storage_units-mu_state_of_charge_set'] } } as unknown as RunResults;
    expect(dualSheetsOf(light)).toEqual(['storage_units-mu_state_of_charge_set']);
    expect(dualSheetsOf({} as RunResults)).toEqual([]);
  });
});
