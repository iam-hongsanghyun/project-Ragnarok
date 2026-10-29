/** pathwayPeriodsOf: the results run picker. */
import { describe, expect, it } from '@jest/globals';
import { pathwayPeriodsOf } from './pathway';

describe('pathwayPeriodsOf (the P2X results period picker)', () => {
  it('offers periods only for a pathway run, sorted and de-duplicated', () => {
    expect(pathwayPeriodsOf({ name: 'a', isPathway: true, pathwayPeriods: [2040, 2030, 2040] })).toEqual({ isPathway: true, periods: [2030, 2040] });
  });
  it('a single-period run has no period choice', () => {
    expect(pathwayPeriodsOf({ name: 'a', isPathway: false, pathwayPeriods: [] })).toEqual({ isPathway: false, periods: [] });
    expect(pathwayPeriodsOf(undefined)).toEqual({ isPathway: false, periods: [] });
  });
  it('reads the older pathway block when the flag is absent (runs stored before it existed)', () => {
    expect(pathwayPeriodsOf({ name: 'a', pathway: { enabled: true, periods: [2030, { period: 2035 }] } })).toEqual({ isPathway: true, periods: [2030, 2035] });
    expect(pathwayPeriodsOf({ name: 'a', pathway: { enabled: false, periods: [2030] } })).toEqual({ isPathway: false, periods: [] });
  });
});
