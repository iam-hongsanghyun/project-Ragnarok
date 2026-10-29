/**
 * PathwayOverviewCard: one row per period plus the whole run, every figure from the KPI endpoint (period and whole horizon).
 */
import React from 'react';
import { afterEach, describe, expect, it, jest } from '@jest/globals';
import type { RunResults } from 'lib/types';
import { fetchRunKpis, type RunKpis } from 'lib/api/resultsDerived';
import { PathwayOverviewCard } from './PathwayOverviewCard';
import { mount, settle, type Mounted } from '../../../shared/testing/dom';

jest.mock('lib/api/resultsDerived');
const mockKpis = jest.mocked(fetchRunKpis);

const kpi = (cost: string, dispatch: number): RunKpis => ({
  totalCost: cost, dispatchMwh: dispatch, avgPrice: 55.5, minPrice: 0, maxPrice: 100, peakLoadMw: 400, loadFactor: 0.6,
  renewableSharePct: 40, emissions: '1,190 ktCO2e', snapshotCount: 24, snapshotWeightHours: 1, currencySymbol: '$',
});
const results = { pathway: { summaries: [
  { period: 2030, yearsWeight: 10, installedCapacityMw: 1000, storageCapacityMw: null },
  { period: 2040, yearsWeight: 10, installedCapacityMw: 1500, storageCapacityMw: 200 },
] } } as unknown as RunResults;

let mounted: Mounted | null = null;
afterEach(async () => { await mounted?.unmount(); mounted = null; jest.resetAllMocks(); });

describe('PathwayOverviewCard', () => {
  it('shows a row per period and the whole run from the server KPIs', async () => {
    mockKpis.mockImplementation(async (_run, _cur, period) => ({ run: 'r', period: period ?? null, kpis: period === 2030 ? kpi('$100', 1000) : period === 2040 ? kpi('$200', 2000) : kpi('$300', 3000) }));
    mounted = await mount(<PathwayOverviewCard results={results} runName="r" />);
    await settle();
    const rows = Array.from(mounted.container.querySelectorAll('tbody tr')).map((r) => Array.from(r.children).map((c) => c.textContent));
    expect(rows).toHaveLength(3);
    expect(rows[0].slice(0, 5)).toEqual(['2030', '10', '1,000 MW', '—', '1,000 MWh']);
    expect(rows[1][3]).toBe('200 MW');
    expect(rows[2][0]).toBe('Whole run');
    expect(rows[2][1]).toBe('20');                                  // the horizon: the periods' years added up
    expect(rows[2][5]).toBe('$300');
    expect(mockKpis).toHaveBeenCalledWith('r', '$', 2030);
  });

  it('explains itself without a stored run, without periods, and on error', async () => {
    mounted = await mount(<PathwayOverviewCard results={results} />);
    expect(mounted.container.textContent).toContain('read from a stored run');
    await mounted.unmount();
    mounted = await mount(<PathwayOverviewCard results={{} as RunResults} runName="r" />);
    expect(mounted.container.textContent).toContain('no pathway periods');
    await mounted.unmount();
    mockKpis.mockRejectedValue(new Error('boom'));
    mounted = await mount(<PathwayOverviewCard results={results} runName="r" />);
    await settle();
    expect(mounted.container.querySelector('[role="alert"]')?.textContent).toContain('boom');
  });
});
