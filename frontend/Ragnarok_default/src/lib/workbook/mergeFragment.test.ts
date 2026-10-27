import { describe, it, expect } from '@jest/globals';
import { mergeWorkbookFragment } from './mergeFragment';
import type { WorkbookModel } from '../types';
import type { WorkbookFragment } from '../api/databases';

const prov = (database_id: string) => ({
  database_id,
  country_iso: 'XXX',
  country_name: 'X',
  filters_json: '{}',
  convert_options_json: '{}',
  fetch_timestamp: '2026-01-01T00:00:00+00:00',
  row_counts_json: '{}',
});

describe('mergeWorkbookFragment carriers (RI2)', () => {
  const model = {
    carriers: [{ name: 'gas', co2_emissions: 0.2, color: '' }],
    generators: [
      { name: 'ccgt', carrier: 'gas', efficiency: 0.5, marginal_cost: 3 },
      { name: 'ocgt', carrier: 'gas', marginal_cost: 1 },
      { name: 'wind1', carrier: 'wind', marginal_cost: 0 },
    ],
  } as unknown as WorkbookModel;

  it('fuel-price fragment overwrites carrier attrs and sets generator marginal_cost = thermal / efficiency', () => {
    const fragment = {
      sheets: { carriers: [{ name: 'gas', fuel_cost_thermal: 34.1214, raw_price: 10, co2_emissions: 0.9 }] },
      provenance: prov('fuel_prices'),
    } as unknown as WorkbookFragment;
    const out = mergeWorkbookFragment(model, fragment);
    const gas = (out.carriers as Array<Record<string, unknown>>).find((c) => c.name === 'gas')!;
    expect(gas.fuel_cost_thermal).toBe(34.1214);
    expect(gas.co2_emissions).toBe(0.9); // fuel-price importer overwrites
    expect(out.carriers).toHaveLength(1);
    const g = out.generators as Array<Record<string, unknown>>;
    expect(g[0].marginal_cost).toBeCloseTo(68.2428, 4); // 34.1214 / 0.5
    expect(g[1].marginal_cost).toBeCloseTo(34.1214, 4); // efficiency blank -> 1
    expect(g[2].marginal_cost).toBe(0); // other carrier untouched
  });

  it('other importers fill empty carrier cells only; existing non-empty values win', () => {
    const fragment = {
      sheets: { carriers: [{ name: 'gas', co2_emissions: 0.9, color: '#f00' }, { name: 'wind' }] },
      provenance: prov('ember_history'),
    } as unknown as WorkbookFragment;
    const out = mergeWorkbookFragment(model, fragment);
    const carriers = out.carriers as Array<Record<string, unknown>>;
    const gas = carriers.find((c) => c.name === 'gas')!;
    expect(gas.co2_emissions).toBe(0.2);
    expect(gas.color).toBe('#f00');
    expect(carriers.map((c) => c.name)).toEqual(['gas', 'wind']);
    expect((out.generators as Array<Record<string, unknown>>)[0].marginal_cost).toBe(3);
  });
});
