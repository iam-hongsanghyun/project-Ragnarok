/**
 * CompositesCard: one row per composite from the plant results payload; starts by tier with their cost, BESS cycles, H2 share and
 * avoided CO2, LCOH; a run without composites says so.
 */
import React from 'react';
import { afterEach, describe, expect, it, jest } from '@jest/globals';
import { fetchPlantResults, type PlantResults } from 'lib/api/plants';
import { CompositesCard } from './CompositesCard';
import { mount, settle, type Mounted } from '../../../shared/testing/dom';

jest.mock('lib/api/plants');
const mockResults = jest.mocked(fetchPlantResults);

const base = { operatingCost: 0, fixedCost: 0, fuelCost: 0, warnings: [] as string[] };
const payload: PlantResults = {
  currency: 'EUR', windowYears: 0.0192, totals: {},
  plants: [
    { ...base, plantId: 'cofire', type: 'cofiring_network', label: 'cofire', capacityMwEl: 200, generationMwh: 9000, capacityFactor: 0.62, totalCost: 1234,
      starts: 4, startCosts: { starts: { hot: 2, warm: 1, cold: 1 }, startCost: 12000, nativeStartUpCost: 8000, tierIncrement: 4000, basis: '' },
      cofiring: { hoursOn: 10, maxHourlyEnergyShare: 0.2, minHourlyEnergyShare: 0.1 },
      fuel: { gasMwhTh: 1, h2MwhTh: 1, totalMwhTh: 2, h2EnergyShare: 0.114, h2VolShare: 0.3 }, emissions: { actualT: 1, gasOnlyBaselineT: 2, avoidedT: 1234, avoidedShare: 0.11 } },
    { ...base, plantId: 'ccgt', type: 'ccgt', label: 'ccgt', capacityMwEl: 200, generationMwh: 5000, capacityFactor: 0.5, totalCost: 7,
      fuel: { gasMwhTh: 9, h2MwhTh: 0, totalMwhTh: 9, h2EnergyShare: 0, h2VolShare: 0 }, emissions: { actualT: 1, gasOnlyBaselineT: 1, avoidedT: 0, avoidedShare: 0 } },
    { ...base, plantId: 'bess', type: 'bess', label: 'bess', capacityMwEl: 50, generationMwh: 100, capacityFactor: 0.1, totalCost: 10, storage: { chargeMwh: 1, dischargeMwh: 1, energyCapacityMwh: 200, equivalentCycles: 1.5 } },
    { ...base, plantId: 'p2x', type: 'p2x', label: 'p2x', totalCost: 5, p2x: { lcohPerKg: 4.34, h2Tonnes: 151, electrolyserCapacityFactor: 0.94, products: { NH3: { costPerTonne: 990, producedTonnes: 10 } } } },
  ],
};

let mounted: Mounted | null = null;
afterEach(async () => { await mounted?.unmount(); mounted = null; jest.resetAllMocks(); });

describe('CompositesCard', () => {
  it('summarises each composite', async () => {
    mockResults.mockResolvedValue(payload);
    mounted = await mount(<CompositesCard runName="r" />);
    await settle();
    const rows = Array.from(mounted.container.querySelectorAll('tbody tr')).map((r) => Array.from(r.children).map((c) => c.textContent));
    expect(rows[0].slice(0, 6)).toEqual(['cofire', 'cofiring_network', '200', '9,000', '62 %', 'hot 2, warm 1, cold 1; cost 12,000']);
    expect(rows[0][7]).toContain('H2 11.4 % of fuel; avoided 1,234 tCO2');
    expect(rows[1][7]).toBe('—');                                  // plain CCGT: no blend, no avoided CO2
    expect(rows[2][6]).toBe('1.5');
    expect(rows[3][8]).toBe('LCOH 4.34 per kg H2; NH3 990 per t');
    expect(mockResults).toHaveBeenCalledWith('r', undefined, null);
  });

  it('says so with no run and with no composites', async () => {
    mounted = await mount(<CompositesCard />);
    expect(mounted.container.textContent).toContain('read from a stored run');
    await mounted.unmount();
    mockResults.mockRejectedValue(new Error("This run's model has no plants (no `plant` column)."));
    mounted = await mount(<CompositesCard runName="r" />);
    await settle();
    expect(mounted.container.textContent).toContain('no composite assets');
  });
});
