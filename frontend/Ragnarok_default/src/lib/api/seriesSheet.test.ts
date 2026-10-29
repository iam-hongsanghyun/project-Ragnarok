import { describe, expect, test } from '@jest/globals';
import { isSeriesSheet, MODULE_SERIES_SHEETS } from './session';

describe('isSeriesSheet', () => {
  test('PyPSA <component>-<attribute> sheets are series; snapshots and -pw tables are not', () => {
    expect(isSeriesSheet('generators-p_max_pu')).toBe(true);
    expect(isSeriesSheet('snapshots')).toBe(false);
    expect(isSeriesSheet('generators-marginal_cost-pw')).toBe(false);
    expect(isSeriesSheet('generators')).toBe(false);
  });

  test('a registered module sheet is a series although its name has no dash', () => {
    expect(MODULE_SERIES_SHEETS.has('RAGNAROK_CarrierOutputCap')).toBe(true);
    expect(isSeriesSheet('RAGNAROK_CarrierOutputCap')).toBe(true);
    expect(isSeriesSheet('RAGNAROK_CustomDSL')).toBe(false);
  });
});
