import { describe, test, expect } from '@jest/globals';
import type { RunResults } from 'lib/types';
import { dualSheetsIn, dualSheetsOf, parseDualSheet } from './dualViews';

describe('dual views (P30)', () => {
  test('recognises only the four dual output sheets', () => {
    expect(dualSheetsIn(['generators-p', 'generators-mu_ramp_limit_up', 'storage_units-mu_state_of_charge_set', 'generators-mu_upper']))
      .toEqual(['generators-mu_ramp_limit_up', 'storage_units-mu_state_of_charge_set']);
    expect(parseDualSheet('links-mu_p_set')).toEqual({ component: 'links', attribute: 'mu_p_set' });
    expect(parseDualSheet('links-p0')).toBeNull();
  });

  test('dualSheetsOf reads populated series of a full bundle and seriesSheets of a light one', () => {
    const full = { outputs: { static: {}, series: { 'generators-mu_p_set': [{ snapshot: 'a', g: 1 }], 'links-mu_p_set': [], 'generators-p': [{ snapshot: 'a', g: 1 }] } } } as unknown as RunResults;
    expect(dualSheetsOf(full)).toEqual(['generators-mu_p_set']);
    const light = { outputs: { static: {}, series: null, seriesSheets: ['generators-p', 'storage_units-mu_state_of_charge_set'] } } as unknown as RunResults;
    expect(dualSheetsOf(light)).toEqual(['storage_units-mu_state_of_charge_set']);
    expect(dualSheetsOf({} as RunResults)).toEqual([]);
  });
});
