/**
 * FuelCostsPreviewPanel: previews the marginal-cost series and the fuel / VOM / carbon split from the server.
 */
import React from 'react';
import { afterEach, describe, expect, it, jest } from '@jest/globals';
import { previewFuelCosts, type FuelCostsPreview } from 'lib/api/fuelCosts';
import { FuelCostsPreviewPanel } from './FuelCostsPreviewPanel';
import { button, click, mount, type Mounted } from '../../shared/testing/dom';

jest.mock('lib/api/fuelCosts');
const mockPreview = jest.mocked(previewFuelCosts);

let mounted: Mounted | null = null;
afterEach(async () => { await mounted?.unmount(); mounted = null; jest.resetAllMocks(); });

const parts = { fuel: 75, vom: 3, carbon: 42.5, other: 0, total: 120.5 };
const result: FuelCostsPreview = {
  active: true, carbonPriceActive: true, basis: 'marginal_cost = fuel / efficiency + VOM', priceSources: { coal: 'series' },
  notes: ['Fuel costs: marginal cost = fuel price / efficiency + VOM written for 1 unit(s) at run time.'],
  smp: { source: 'buses_t.marginal_price', note: 'output' },
  units: [{
    component: 'Generator', name: 'coal', carrier: 'coal', role: 'generator', fuelCarrier: 'coal', suppliers: [], status: 'applied', reason: '',
    efficiencyMean: 0.4, vom: 3, vomSource: 'name', snapshots: 4, pricedSnapshots: 4, unpricedSnapshots: 0,
    marginalCost: { oldMean: 999, newMean: 78, newMin: 53, newMax: 103, basis: 'per MWh of output' }, basis: 'MWh_el', timeMean: parts,
  }],
};

describe('FuelCostsPreviewPanel', () => {
  it('syncs the model, previews with the run\'s carbon setting and lists the breakdown', async () => {
    mockPreview.mockResolvedValueOnce(result);
    const onSessionSync = jest.fn(async () => {});
    mounted = await mount(<FuelCostsPreviewPanel carbonPrice={50} carbonPriceSchedule={[]} currencySymbol="$" onSessionSync={onSessionSync} />);
    expect(mounted.container.textContent).toContain('RAGNAROK_FuelPrices');
    await click(button(mounted.container, 'Preview fuel costs'));
    expect(onSessionSync).toHaveBeenCalled();
    expect(mockPreview).toHaveBeenCalledWith(50, []);
    const text = mounted.container.textContent ?? '';
    expect(text).toContain('coal');
    expect(text).toContain('75.00');
    expect(text).toContain('120.50');
    expect(text).toContain('999.00');
  });

  it('shows the server error (for example a priced unit without efficiency)', async () => {
    mockPreview.mockRejectedValueOnce(new Error('400: Fuel costs: Generator coal: efficiency is blank'));
    mounted = await mount(<FuelCostsPreviewPanel carbonPrice={0} carbonPriceSchedule={[]} currencySymbol="$" onSessionSync={async () => {}} />);
    await click(button(mounted.container, 'Preview fuel costs'));
    expect(mounted.container.querySelector('[role="alert"]')?.textContent).toContain('efficiency is blank');
  });
});
