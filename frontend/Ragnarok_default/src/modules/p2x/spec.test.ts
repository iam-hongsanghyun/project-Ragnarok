/** P2X designer form <-> backend spec mapping (pure). */
import { describe, expect, it } from '@jest/globals';
import { activeTechnologies, defaultForm, formToSpec, nextChainId, parseProfile, pathwayPeriodsOf } from './spec';

describe('formToSpec', () => {
  it('defaults to an H2 chain with a flat 1000 t/yr offtake and an extendable AEC electrolyser', () => {
    const spec = formToSpec(defaultForm(0.07, 'grid'));
    expect(spec.products).toEqual(['H2']);
    expect(spec.discountRate).toBe(0.07);
    expect(spec.anchorBus).toBe('grid');
    expect(spec.h2Bus).toBeNull();
    expect(spec.electrolyser).toMatchObject({ tech: 'aec', extendable: true, pNomMax: null, applyAvailability: true });
    expect(spec.offtake).toEqual({ H2: { mode: 'flat', tonnesPerYear: 1000 } });
  });

  it('adds only the ticked derivatives, their offtake and the numeric parameter overrides', () => {
    const f = defaultForm(0.05);
    f.products.NH3 = true;
    f.products.eFuel = true;
    f.offtake.NH3 = { mode: 'flat', tonnesPerYear: '5000', mw: '', profileText: '' };
    f.offtake.eFuel = { mode: 'profile', tonnesPerYear: '', mw: '12', profileText: '1, 2\n3' };
    f.params = { 'electrolyser_aec.capex': '600', 'haber_bosch.fom': '', 'asu.capex': 'abc' };
    f.designated = ['wind'];
    const spec = formToSpec(f);
    expect(spec.products).toEqual(['H2', 'NH3', 'eFuel']);
    expect(Object.keys(spec.offtake)).toEqual(['H2', 'NH3', 'eFuel']);
    expect(spec.offtake.NH3).toEqual({ mode: 'flat', tonnesPerYear: 5000 });
    expect(spec.offtake.eFuel).toEqual({ mode: 'profile', mw: 12, profile: [1, 2, 3] });
    expect(spec.params).toEqual({ 'electrolyser_aec.capex': 600 });      // blank and non-numeric overrides are dropped
    expect(spec.designatedGenerators).toEqual(['wind']);
  });

  it('keeps a fixed electrolyser size and treats an empty max as unbounded', () => {
    const f = defaultForm(0.05);
    f.electrolyser = { ...f.electrolyser, extendable: false, pNom: '30', pNomMax: '', buildYear: '2030' };
    const spec = formToSpec(f);
    expect(spec.electrolyser).toMatchObject({ extendable: false, pNom: 30, pNomMax: null, buildYear: 2030 });
  });
});

describe('profile parsing and ids', () => {
  it('reads newline, comma, semicolon and space separated numbers and drops the rest', () => {
    expect(parseProfile('1,2;3\n4 5\n\nx 6')).toEqual([1, 2, 3, 4, 5, 6]);
    expect(parseProfile('')).toEqual([]);
  });

  it('picks the next unused chain id', () => {
    expect(nextChainId('p2x', [])).toBe('p2x');
    expect(nextChainId('p2x', ['p2x'])).toBe('p2x_2');
    expect(nextChainId('p2x', ['p2x', 'p2x_2'])).toBe('p2x_3');
  });
});

describe('activeTechnologies', () => {
  it('follows the products, storage and CO2 source', () => {
    const f = defaultForm(0.05);
    expect(activeTechnologies(f)).toEqual(['electrolyser_aec', 'water', 'h2_storage_tank']);
    f.products.NH3 = true;
    f.products.MeOH = true;
    f.storage = { ...f.storage, compressor: true };
    f.co2Source = 'point';
    expect(activeTechnologies(f)).toEqual(expect.arrayContaining(['h2_compressor', 'h2_storage_tank_bare', 'haber_bosch', 'asu', 'nh3_storage', 'methanolisation', 'meoh_storage', 'co2_point']));
    expect(activeTechnologies(f)).not.toContain('co2_dac');
    f.storage = { ...f.storage, type: 'cavern', compressor: false };
    expect(activeTechnologies(f)).toContain('h2_storage_cavern');
  });
});

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
