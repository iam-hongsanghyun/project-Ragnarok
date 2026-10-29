/**
 * CarbonPreviewPanel: lists the model's stored carbon schedules and previews a price per generator from the server.
 */
import React from 'react';
import { afterEach, describe, expect, it, jest } from '@jest/globals';
import { getServerCarbonSchedules, previewCarbonPrice } from 'lib/api/policyModules';
import { CarbonPreviewPanel } from './CarbonPreviewPanel';
import { button, click, mount, setValue, type Mounted } from '../../shared/testing/dom';

jest.mock('lib/api/policyModules');
const mockSchedules = jest.mocked(getServerCarbonSchedules);
const mockPreview = jest.mocked(previewCarbonPrice);

let mounted: Mounted | null = null;
afterEach(async () => { await mounted?.unmount(); mounted = null; jest.resetAllMocks(); });

const stored = [{ id: 'ets', name: 'ETS pathway', schedule: [{ year: 2030, price: 80 }, { year: 2040, price: 150 }] }];
const result = {
  active: true, priceMin: 80, priceMax: 150, basis: 'objective += price x co2_emissions / efficiency x output',
  generators: [{ generator: 'gas', carrier: 'gas', co2PerMWhFuel: 0.2, adderMean: 41.5, adderMax: 75 }],
};

describe('CarbonPreviewPanel', () => {
  it('previews the run setting by default', async () => {
    mockSchedules.mockResolvedValue(stored);
    mockPreview.mockResolvedValueOnce(result);
    const onSessionSync = jest.fn(async () => {});
    mounted = await mount(<CarbonPreviewPanel carbonPrice={50} carbonPriceSchedule={[]} currencySymbol="$" onSessionSync={onSessionSync} />);
    await click(button(mounted.container, 'Preview effect'));
    expect(onSessionSync).toHaveBeenCalled();
    expect(mockPreview).toHaveBeenCalledWith(50, []);
    expect(mounted.container.textContent).toContain('Price ranges $80.00 to $150.00 per tCO2');
    expect(mounted.container.textContent).toContain('41.50');
  });

  it('lists a stored schedule and previews that schedule instead of the run setting', async () => {
    mockSchedules.mockResolvedValue(stored);
    mockPreview.mockResolvedValueOnce(result);
    mounted = await mount(<CarbonPreviewPanel carbonPrice={50} carbonPriceSchedule={[]} currencySymbol="$" onSessionSync={async () => {}} />);
    const select = mounted.container.querySelector('select') as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual(['Run setting: scalar $50/tCO2', 'ETS pathway']);
    await setValue(select, 'ets');
    expect(mounted.container.textContent).toContain('2030 $80/tCO2, 2040 $150/tCO2');
    await click(button(mounted.container, 'Preview effect'));
    expect(mockPreview).toHaveBeenCalledWith(50, stored[0].schedule);
  });

  it('shows the server error and an empty library notice', async () => {
    mockSchedules.mockResolvedValue([]);
    mockPreview.mockRejectedValueOnce(new Error('400: No model loaded'));
    mounted = await mount(<CarbonPreviewPanel carbonPrice={0} carbonPriceSchedule={[]} currencySymbol="$" onSessionSync={async () => {}} />);
    expect(mounted.container.textContent).toContain('stores no carbon schedules');
    await click(button(mounted.container, 'Preview effect'));
    expect(mounted.container.querySelector('[role="alert"]')?.textContent).toBe('400: No model loaded');
  });

  it('blames missing emission factors only when a price is active', async () => {
    mockSchedules.mockResolvedValue([]);
    mockPreview.mockResolvedValueOnce({ ...result, active: false, priceMin: 0, priceMax: 0, generators: [] });
    mounted = await mount(<CarbonPreviewPanel carbonPrice={0} carbonPriceSchedule={[]} currencySymbol="$" onSessionSync={async () => {}} />);
    await click(button(mounted.container, 'Preview effect'));
    expect(mounted.container.textContent).toContain('No carbon price is active');
    expect(mounted.container.textContent).not.toContain('No generator has a co2_emissions factor');
  });
});
