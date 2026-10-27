import { describe, test, expect } from '@jest/globals';
import { kpisFromResults } from './kpis';
import type { RunResults, WorkbookModel } from 'lib/types';

const model = { carriers: [{ name: 'wind', co2_emissions: 0 }, { name: 'gas', co2_emissions: 0.2 }], storage_units: [] } as unknown as WorkbookModel;
const results = {
  summary: [
    { label: 'Peak demand', value: '8,760 MW' },
    { label: 'System emissions', value: '1 ktCO2e' },
  ],
  carrierMix: [{ label: 'wind', value: 600, color: '#000' }, { label: 'gas', value: 400, color: '#000' }],
  systemPriceSeries: [{ value: 10 }, { value: 30 }],
  costBreakdown: [{ label: 'Fuel cost', value: 1000.4 }, { label: 'Carbon cost', value: 200 }],
  runMeta: { snapshotCount: 2, snapshotWeight: 1 },
  assetDetails: { buses: {} },
} as unknown as RunResults;

describe('kpisFromResults (local fallback)', () => {
  test('matches the server definitions: summary peak, energy/hours load factor, cost from breakdown', () => {
    const k = kpisFromResults(results, model, '$');
    expect(k.dispatchMwh).toBe(1000);
    expect(k.avgPrice).toBe(20);
    expect([k.minPrice, k.maxPrice]).toEqual([10, 30]);
    expect(k.peakLoadMw).toBe(8760);
    expect(k.loadFactor).toBeCloseTo(500 / 8760, 12); // 1000 MWh / 2 h over the peak
    expect(k.renewableSharePct).toBeCloseTo(60, 10);
    expect(k.totalCost).toBe('$1,200');
    expect(k.emissions).toBe('1 ktCO2e');
  });
  // Re-baselined: with runMeta.averageSystemPrice the KPI is the load-weighted run average
  // (n.statistics.prices(weighting="load")), not the unweighted series mean (20); the mean is
  // only the fallback for runs stored before that field existed (tested above).
  test('avg price is the load-weighted runMeta.averageSystemPrice when present', () => {
    const r = { ...results, runMeta: { ...results.runMeta, averageSystemPrice: 24.5 } } as unknown as RunResults;
    expect(kpisFromResults(r, model, '$').avgPrice).toBe(24.5);
  });
  test('missing pieces are null, not zero', () => {
    const k = kpisFromResults({ ...results, summary: [], systemPriceSeries: [], costBreakdown: [] } as unknown as RunResults, model);
    expect([k.totalCost, k.peakLoadMw, k.minPrice, k.emissions]).toEqual([null, null, null, null]);
    expect(k.avgPrice).toBe(0);
  });
});
