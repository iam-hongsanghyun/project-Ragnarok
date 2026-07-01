import { describe, it, expect } from '@jest/globals';
import { deriveRunResults } from './runResults';
import { createEmptyWorkbook } from 'lib/workbook/workbook';
import type { RunResults } from 'lib/types';

// Regression: an imported external result (or any run with no server-derived
// summary) is opened via the LIGHT analytics view, which ships `series: null`
// (the heavy per-component output series are stripped and fetched on demand).
// `deriveRunResults` must tolerate that — derive to empty, never throw
// `Object.values(null)` / `null['lines-p0']`. See History import (H2).
describe('deriveRunResults — light-view (stripped series) safety', () => {
  const model = createEmptyWorkbook();

  it('does not throw when outputs.series is null', () => {
    const outputs = { static: {}, series: null } as unknown as NonNullable<RunResults['outputs']>;
    expect(() => deriveRunResults(model, outputs)).not.toThrow();
  });

  it('does not throw when both series and static are null', () => {
    const outputs = { static: null, series: null } as unknown as NonNullable<RunResults['outputs']>;
    expect(() => deriveRunResults(model, outputs)).not.toThrow();
  });

  it('derives empty dispatch / line-loading from a null series', () => {
    const outputs = { static: {}, series: null } as unknown as NonNullable<RunResults['outputs']>;
    const derived = deriveRunResults(model, outputs);
    // Empty, well-formed structures — the cards render "no data", not a crash.
    expect(Array.isArray(derived.dispatchSeries)).toBe(true);
    expect(derived.dispatchSeries).toHaveLength(0);
    expect(Array.isArray(derived.lineLoading)).toBe(true);
    expect(derived.lineLoading).toHaveLength(0);
  });
});

// Sector coupling (M1): a CCGT modelled as a gas→electricity Link must show its
// electricity output under the CCGT carrier, and the gas fuel-supply generator
// (on the gas bus) must NOT be lumped into the electricity dispatch mix.
describe('deriveRunResults — sector-coupled dispatch mix', () => {
  const model = {
    ...createEmptyWorkbook(),
    buses: [{ name: 'elec', carrier: 'AC' }, { name: 'gas', carrier: 'gas' }],
    carriers: [{ name: 'AC' }, { name: 'gas', co2_emissions: 0.2 }, { name: 'wind' }, { name: 'CCGT' }],
    generators: [
      { name: 'gas_supply', bus: 'gas', carrier: 'gas' },
      { name: 'wind', bus: 'elec', carrier: 'wind' },
    ],
    loads: [{ name: 'd', bus: 'elec', p_set: 100 }],
    links: [{ name: 'ccgt', bus0: 'gas', bus1: 'elec', carrier: 'CCGT', efficiency: 0.5 }],
  } as unknown as Parameters<typeof deriveRunResults>[0];

  const outputs = {
    static: {},
    series: {
      'generators-p': [
        { snapshot: '2030-01-01T00:00:00', gas_supply: 120, wind: 40 },
        { snapshot: '2030-01-01T01:00:00', gas_supply: 120, wind: 40 },
      ],
      'links-p0': [
        { snapshot: '2030-01-01T00:00:00', ccgt: 120 },
        { snapshot: '2030-01-01T01:00:00', ccgt: 120 },
      ],
    },
  } as unknown as NonNullable<RunResults['outputs']>;

  it('attributes CCGT link power to its carrier and excludes the gas supply', () => {
    const d = deriveRunResults(model, outputs);
    const v = d.dispatchSeries[0].values;
    expect(v.CCGT).toBeCloseTo(60); // 120 gas × 0.5 efficiency
    expect(v.wind).toBeCloseTo(40);
    expect(v.gas).toBeUndefined(); // fuel supply is not electricity generation
    const mixLabels = d.carrierMix.map((m) => m.label);
    expect(mixLabels).toEqual(expect.arrayContaining(['CCGT', 'wind']));
    expect(mixLabels).not.toContain('gas');
  });
});
