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

// RF3: client-derived costs must agree with the backend split.
describe('deriveRunResults — cost breakdown matches the backend', () => {
  type Model = Parameters<typeof deriveRunResults>[0];
  const model = {
    ...createEmptyWorkbook(),
    buses: [{ name: 'b1', carrier: 'AC' }],
    carriers: [{ name: 'AC' }, { name: 'gas', co2_emissions: 0.2 }],
    generators: [
      { name: 'g1', bus: 'b1', carrier: 'gas', p_nom: 100, marginal_cost: 50 },
      { name: 'gx', bus: 'b1', carrier: 'gas', p_nom: 100, marginal_cost: 10, p_nom_extendable: true, capital_cost: 8760 },
    ],
    loads: [{ name: 'l1', bus: 'b1', p_set: 50 }],
  } as unknown as Model;
  const outputs = {
    static: { generators: { gx: { p_nom_opt: 20 } } },
    series: {
      'generators-p': [
        { snapshot: '2030-01-01T00:00:00', g1: 10, gx: 0 },
        { snapshot: '2030-01-01T01:00:00', g1: 10, gx: 0 },
      ],
    },
  } as unknown as NonNullable<RunResults['outputs']>;
  const cost = (r: RunResults, label: string) => r.costBreakdown.find((c) => c.label.startsWith(label))?.value;

  it('fuel is E x marginal_cost (no carbon subtracted), carbon is E x ef x price', () => {
    const r = deriveRunResults(model, outputs, { carbonPrice: 30 });
    expect(cost(r, 'Fuel')).toBe(20 * 50);
    expect(cost(r, 'Carbon')).toBe(20 * 0.2 * 30);
  });

  it('resolves a carbon schedule per calendar year, superseding the scalar', () => {
    const r = deriveRunResults(model, outputs, {
      carbonPrice: 999,
      carbonPriceSchedule: [{ year: 2025, price: 10 }, { year: 2030, price: 60 }],
    });
    expect(cost(r, 'Carbon')).toBe(20 * 0.2 * 60);
  });

  it('pro-rates capex to the modelled window and uses p_nom_opt for capacity', () => {
    const r = deriveRunResults(model, outputs, { snapshotWeight: 1 });
    // annuity at 5 % / 20 y x p_nom_opt 20 MW, scaled by 2 h / 8760 h
    const annual = r.expansionResults![0].capex_annual;
    expect(cost(r, 'Capital cost')).toBe(Math.round(annual * (2 / 8760)));
    expect(r.summary.find((s) => s.label === 'Generator capacity')?.value).toBe('120 MW');
  });

  it('scopes demand to electricity buses in a sector-coupled model', () => {
    const coupled = {
      ...model,
      buses: [{ name: 'b1', carrier: 'AC' }, { name: 'h', carrier: 'heat' }],
      loads: [{ name: 'l1', bus: 'b1', p_set: 50 }, { name: 'lh', bus: 'h', p_set: 500 }],
    } as unknown as Model;
    const r = deriveRunResults(coupled, outputs);
    expect(r.summary.find((s) => s.label === 'Peak demand')?.value).toBe('50 MW');
  });
});

// RF4: pathway input profiles are keyed by period|snapshot.
describe('deriveRunResults — pathway input lookups', () => {
  const model = {
    ...createEmptyWorkbook(),
    buses: [{ name: 'b1' }],
    carriers: [{ name: 'gas', co2_emissions: 0.2 }],
    generators: [{ name: 'g1', bus: 'b1', carrier: 'gas', p_nom: 100, marginal_cost: 50 }],
    loads: [{ name: 'l1', bus: 'b1', p_set: 0 }],
    'loads-p_set': [
      { period: 2030, snapshot: '2030-01-01T00:00:00', l1: 50 },
      { period: 2040, snapshot: '2030-01-01T00:00:00', l1: 80 },
    ],
  } as unknown as Parameters<typeof deriveRunResults>[0];
  const outputs = {
    static: {},
    series: {
      'generators-p': [
        { period: 2030, snapshot: '2030-01-01T00:00:00.000000', g1: 50 },
        { period: 2040, snapshot: '2030-01-01T00:00:00.000000', g1: 80 },
      ],
    },
  } as unknown as NonNullable<RunResults['outputs']>;
  const pathway = { enabled: true, periods: [2030, 2040], selectedPeriod: 2030, snapshotMappingMode: 'explicit_period_column' as const, summaries: [] };

  it('each period reads its own load (and tolerates fractional-second stamps)', () => {
    const a = deriveRunResults(model, outputs, { pathway, selectedPeriod: 2030 });
    const b = deriveRunResults(model, outputs, { pathway, selectedPeriod: 2040 });
    expect(a.dispatchSeries[0].total).toBe(50);
    expect(b.dispatchSeries[0].total).toBe(80);
    expect(a.pathway?.summaries.map((s) => s.peakLoad)).toEqual([50, 80]);
  });

  it('fallback period summaries exclude load shedding from dispatch', () => {
    const withShed = {
      ...model,
      generators: [...(model.generators ?? []), { name: 'load_shedding_b1', bus: 'b1', carrier: 'gas', p_nom: 1e6 }],
    } as unknown as Parameters<typeof deriveRunResults>[0];
    const o = {
      static: {},
      series: { 'generators-p': [
        { period: 2030, snapshot: '2030-01-01T00:00:00', g1: 50, load_shedding_b1: 7 },
      ] },
    } as unknown as NonNullable<RunResults['outputs']>;
    const r = deriveRunResults(withShed, o, { pathway: { ...pathway, periods: [2030] } });
    expect(r.pathway?.summaries[0].totalDispatch).toBe(50);
  });
});

// Backend parity: system storage series splits charge/discharge per unit and
// includes Stores (state = SoC + e).
describe('deriveRunResults — storage series', () => {
  it('does not net units against each other and counts Stores', () => {
    const model = {
      ...createEmptyWorkbook(),
      buses: [{ name: 'b1' }],
      storage_units: [{ name: 's1', bus: 'b1' }, { name: 's2', bus: 'b1' }],
      stores: [{ name: 'st', bus: 'b1' }],
    } as unknown as Parameters<typeof deriveRunResults>[0];
    const outputs = { static: {}, series: {
      'storage_units-p': [{ snapshot: '2030-01-01T00:00:00', s1: 10, s2: -4 }],
      'storage_units-state_of_charge': [{ snapshot: '2030-01-01T00:00:00', s1: 5, s2: 6 }],
      'stores-p': [{ snapshot: '2030-01-01T00:00:00', st: -2 }],
      'stores-e': [{ snapshot: '2030-01-01T00:00:00', st: 7 }],
    } } as unknown as NonNullable<RunResults['outputs']>;
    const p = deriveRunResults(model, outputs).storageSeries[0];
    expect(p.discharge).toBe(10);
    expect(p.charge).toBe(6);
    expect(p.state).toBe(18);
  });
});
