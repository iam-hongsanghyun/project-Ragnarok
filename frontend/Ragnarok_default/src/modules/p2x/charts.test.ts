/** P2X chart builders: waterfall geometry and option shape (pure). */
import { describe, expect, it } from '@jest/globals';
import { FALLBACK_CHART_THEME } from 'lib/charts/theme';
import { buildDispatchOption, buildSocOption, buildWaterfallOption, waterfallBars } from './charts';

const steps = [
  { label: 'Electricity', value: 2, cumulative: 2 },
  { label: 'Capex', value: 1.5, cumulative: 3.5 },
  { label: 'Rebate', value: -0.5, cumulative: 3 },
];

describe('waterfallBars', () => {
  it('floats each step on the running total and ends with the total from zero', () => {
    const bars = waterfallBars(steps, 'Total');
    expect(bars.map((b) => [b.base, b.value, b.total])).toEqual([[0, 2, false], [2, 1.5, false], [3, 0.5, false], [0, 3, true]]);
  });
});

describe('option builders', () => {
  it('waterfall: an invisible base series stacked under the visible bars', () => {
    const o = buildWaterfallOption({ steps, unit: 'EUR/kg H2', theme: FALLBACK_CHART_THEME }) as { series: Array<{ data: unknown[] }>; xAxis: { data: string[] } };
    expect(o.xAxis.data).toEqual(['Electricity', 'Capex', 'Rebate', 'Total']);
    expect(o.series).toHaveLength(2);
    expect(o.series[0].data).toEqual([0, 2, 3, 0]);
  });

  it('dispatch: three series, zoomable, with the data passed through', () => {
    const o = buildDispatchOption({ snapshots: ['a', 'b'], electrolyserMw: [1, 2], designatedMw: [3, 4], gridMw: [0, 0], theme: FALLBACK_CHART_THEME }) as {
      series: Array<{ name: string; data: number[] }>; dataZoom: unknown[];
    };
    expect(o.series.map((s) => s.name)).toEqual(['Designated RES output', 'Electrolyser electricity', 'Grid-supplied (unmatched)']);
    expect(o.series[1].data).toEqual([1, 2]);
    expect(o.dataZoom.length).toBeGreaterThan(0);
  });

  it('dispatch: fitToElectrolyser caps the MW axis just above the electrolyser peak', () => {
    const base = { snapshots: ['a', 'b'], electrolyserMw: [10, 20], designatedMw: [500, 600], gridMw: [0, 0], theme: FALLBACK_CHART_THEME };
    const fit = buildDispatchOption({ ...base, fitToElectrolyser: true }) as { yAxis: { max?: number } };
    const free = buildDispatchOption(base) as { yAxis: { max?: number } };
    expect(fit.yAxis.max).toBe(23);
    expect(free.yAxis.max).toBeUndefined();
  });

  it('soc: one series in tonnes', () => {
    const o = buildSocOption({ snapshots: ['a'], socTonnes: [5], theme: FALLBACK_CHART_THEME }) as { series: Array<{ data: number[] }> };
    expect(o.series[0].data).toEqual([5]);
  });
});
