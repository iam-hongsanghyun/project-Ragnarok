import { describe, it, expect } from '@jest/globals';
import { generatorCarriers, unresolvedCarrierConstraints } from './custom';
import { CustomConstraint, WorkbookModel } from '../types';

/**
 * A carrier constraint binds only when its carrier matches a GENERATOR's
 * carrier — the solver resolves `generators.carrier`, not the carriers sheet.
 * Regression: the picker used to be fed from the carriers sheet, so a model
 * whose sheet lists "AC" (a network carrier no generator uses) produced
 * constraints the solve silently dropped.
 */
const model = {
  carriers: [{ name: 'AC' }, { name: 'gas' }, { name: 'solar' }, { name: 'coal' }],
  generators: [
    { name: 'g1', carrier: 'gas' },
    { name: 'g2', carrier: 'solar' },
    { name: 'g3', carrier: 'solar' },
    { name: 'g4', carrier: '' },
  ],
} as unknown as WorkbookModel;

const constraint = (over: Partial<CustomConstraint>): CustomConstraint => ({
  id: 'c', enabled: true, label: 'l', metric: 'carrier_max_cf',
  carrier: 'gas', value: 50, unit: '%', ...over,
} as CustomConstraint);

describe('generatorCarriers', () => {
  it('returns only carriers a generator actually uses, sorted and deduped', () => {
    // "AC" and "coal" are on the carriers sheet but no generator carries them.
    expect(generatorCarriers(model)).toEqual(['gas', 'solar']);
  });

  it('ignores blank carriers and a missing generators sheet', () => {
    expect(generatorCarriers({ generators: [] } as unknown as WorkbookModel)).toEqual([]);
    expect(generatorCarriers({} as unknown as WorkbookModel)).toEqual([]);
  });
});

describe('unresolvedCarrierConstraints', () => {
  const carriers = generatorCarriers(model);

  it('accepts a carrier that a generator uses', () => {
    expect(unresolvedCarrierConstraints([constraint({ carrier: 'gas' })], carriers)).toEqual([]);
  });

  it('flags a carrier no generator uses (the silent-skip case)', () => {
    const bad = constraint({ carrier: 'coal' });
    expect(unresolvedCarrierConstraints([bad], carriers)).toEqual([bad]);
  });

  it('flags the sheet-only "AC" carrier the picker used to default to', () => {
    expect(unresolvedCarrierConstraints([constraint({ carrier: 'AC' })], carriers)).toHaveLength(1);
  });

  it('is case-sensitive, matching the backend comparison', () => {
    expect(unresolvedCarrierConstraints([constraint({ carrier: 'Gas' })], carriers)).toHaveLength(1);
  });

  it('flags a blank carrier on a metric that needs one', () => {
    expect(unresolvedCarrierConstraints([constraint({ carrier: '' })], carriers)).toHaveLength(1);
  });

  it('ignores disabled rows and metrics that need no carrier', () => {
    expect(unresolvedCarrierConstraints([constraint({ carrier: 'coal', enabled: false })], carriers)).toEqual([]);
    // co2_cap carries no carrier at all — never flagged.
    expect(unresolvedCarrierConstraints([constraint({ metric: 'co2_cap', carrier: '' })], carriers)).toEqual([]);
  });
});
