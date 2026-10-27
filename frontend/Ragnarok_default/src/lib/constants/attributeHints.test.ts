import { describe, test, expect } from '@jest/globals';
import { decorateHeader, getAttributeHint } from './attributeHints';

describe('attribute hints (P46)', () => {
  test('maintenance fields are grouped for generators, links and processes only', () => {
    for (const sheet of ['generators', 'links', 'processes']) {
      expect(getAttributeHint(sheet, 'maintainable')?.group).toBe('Maintenance');
    }
    expect(getAttributeHint('loads', 'maintainable')).toBeNull();
    expect(getAttributeHint('generators', 'maintenance_duration')?.unit).toBe('h');
  });

  test('phase shifter bounds carry the degrees unit', () => {
    expect(getAttributeHint('transformers', 'phase_shift_min')?.unit).toBe('deg');
    expect(getAttributeHint('transformers', 'phase_shift_max')?.group).toBe('Phase shifter');
    expect(getAttributeHint('lines', 'phase_shift_min')).toBeNull();
  });

  test('v_ang_min is deprecated, v_ang_max is not', () => {
    expect(getAttributeHint('lines', 'v_ang_min')?.deprecated).toBe(true);
    expect(getAttributeHint('transformers', 'v_ang_max')?.deprecated).toBeUndefined();
    expect(decorateHeader('lines', 'v_ang_min', 'degrees', false)).toBe('v_ang_min (deg) [deprecated]');
    expect(decorateHeader('lines', 'v_ang_max', 'degrees', false)).toBe('v_ang_max (deg)');
  });

  test('start-up/shut-down cost say they can be a time series', () => {
    expect(getAttributeHint('generators', 'start_up_cost')?.note).toMatch(/time series/);
    expect(getAttributeHint('processes', 'shut_down_cost')?.note).toMatch(/generators|processes-shut_down_cost/);
  });

  test('unknown attributes fall back to schema unit', () => {
    expect(getAttributeHint('generators', 'p_nom')).toBeNull();
    expect(decorateHeader('generators', 'p_nom', 'MW', true)).toBe('p_nom (MW) *');
  });
});
