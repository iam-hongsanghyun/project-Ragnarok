/**
 * Shape tests for the pure ECharts option builders. These guard the
 * data→option mapping (series values, stacking, axis titles, totals) — the
 * rendering itself belongs to ECharts.
 */
import { describe, test, expect } from '@jest/globals';
import {
  buildDonutOption,
  buildDurationCurveOption,
  buildExpansionOption,
  buildMeritOrderOption,
  buildTimeSeriesOption,
  fmtNum,
} from './options';
import { FALLBACK_CHART_THEME } from './theme';

const theme = FALLBACK_CHART_THEME;

const rows = [
  { label: '00:00', a: 10, b: 5 },
  { label: '01:00', a: 20, b: 0 },
  { label: '02:00', a: 30, b: 15 },
];
const series = [
  { key: 'a', label: 'Alpha', color: '#111111' },
  { key: 'b', label: 'Beta', color: '#222222' },
];

describe('fmtNum', () => {
  test('rounds and localises', () => {
    expect(fmtNum(88609.4)).toBe((88609).toLocaleString());
  });
  test('dashes non-finite input', () => {
    expect(fmtNum('not-a-number')).toBe('—');
  });
});

describe('buildTimeSeriesOption', () => {
  test('maps rows into one data array per series', () => {
    const opt = buildTimeSeriesOption({
      xLabels: rows.map((r) => r.label), rows, series,
      mode: 'line', stacked: false,
      showAxisLabels: true, xLabelAngle: 0, theme,
    }) as { series: Array<{ name: string; data: number[]; type: string; stack?: string }> };
    expect(opt.series).toHaveLength(2);
    expect(opt.series[0].name).toBe('Alpha');
    expect(opt.series[0].data).toEqual([10, 20, 30]);
    expect(opt.series[1].data).toEqual([5, 0, 15]);
    expect(opt.series[0].type).toBe('line');
    expect(opt.series[0].stack).toBeUndefined();
  });

  test('stacked area sets stack + areaStyle; bar mode sets bar type', () => {
    const area = buildTimeSeriesOption({
      xLabels: rows.map((r) => r.label), rows, series,
      mode: 'area', stacked: true,
      showAxisLabels: true, xLabelAngle: 0, theme,
    }) as { series: Array<{ stack?: string; areaStyle?: object; type: string }> };
    expect(area.series[0].stack).toBe('total');
    expect(area.series[0].areaStyle).toBeDefined();

    const bar = buildTimeSeriesOption({
      xLabels: rows.map((r) => r.label), rows, series,
      mode: 'bar', stacked: false,
      showAxisLabels: true, xLabelAngle: 0, theme,
    }) as { series: Array<{ type: string }> };
    expect(bar.series[0].type).toBe('bar');
  });

  test('axis titles land as axis names and labels can be hidden', () => {
    const opt = buildTimeSeriesOption({
      xLabels: rows.map((r) => r.label), rows, series,
      mode: 'line', stacked: false,
      xAxisTitle: 'Time', yAxisTitle: 'MW',
      showAxisLabels: false, xLabelAngle: -45, theme,
    }) as { xAxis: { name?: string; axisLabel: { show: boolean; rotate: number } }; yAxis: { name?: string } };
    expect(opt.xAxis.name).toBe('Time');
    expect(opt.yAxis.name).toBe('MW');
    expect(opt.xAxis.axisLabel.show).toBe(false);
    expect(opt.xAxis.axisLabel.rotate).toBe(45);
  });
});

describe('buildDonutOption', () => {
  test('totals the slices into the centre subtext with unit', () => {
    const opt = buildDonutOption({
      data: [
        { label: 'wind', value: 60, color: '#1' },
        { label: 'solar', value: 40, color: '#2' },
      ],
      unit: 'MW', theme,
    }) as { title: { text: string; subtext: string }; series: Array<{ data: Array<{ name: string; value: number }> }> };
    expect(opt.title.text).toBe('Total (MW)');
    expect(opt.title.subtext).toBe((100).toLocaleString());
    expect(opt.series[0].data.map((d) => d.name)).toEqual(['wind', 'solar']);
  });
});

describe('buildDurationCurveOption', () => {
  test('spreads ranks over 0–100% exceedance', () => {
    const opt = buildDurationCurveOption({
      data: [30, 20, 10], title: 'Load (MW)', unit: 'MW', color: '#f97316', theme,
    }) as { series: Array<{ data: Array<[number, number]> }> };
    expect(opt.series[0].data).toEqual([[0, 30], [50, 20], [100, 10]]);
  });
});

describe('buildMeritOrderOption', () => {
  const entries = [
    { name: 'g1', carrier: 'coal', bus: 'b1', marginal_cost: 30, p_nom: 100, cumulative_mw: 0, color: '#1' },
    { name: 'g2', carrier: 'gas', bus: 'b1', marginal_cost: 60, p_nom: 50, cumulative_mw: 100, color: '#2' },
  ];

  test('x axis spans total capacity; data keeps block geometry', () => {
    const opt = buildMeritOrderOption({ entries, systemLoad: 120, currencySymbol: '$', theme }) as {
      xAxis: { max: number };
      series: Array<{ data: Array<{ value: [number, number, number] }>; markLine: { data: Array<{ xAxis: number }> } }>;
    };
    expect(opt.xAxis.max).toBe(150);
    expect(opt.series[0].data[1].value).toEqual([100, 50, 60]);
    expect(opt.series[0].markLine.data[0].xAxis).toBe(120);
  });

  test('demand line clamps to total capacity and is omitted without load', () => {
    const clamped = buildMeritOrderOption({ entries, systemLoad: 9999, currencySymbol: '$', theme }) as {
      series: Array<{ markLine: { data: Array<{ xAxis: number }> } }>;
    };
    expect(clamped.series[0].markLine.data[0].xAxis).toBe(150);
    const none = buildMeritOrderOption({ entries, currencySymbol: '$', theme }) as {
      series: Array<{ markLine?: unknown }>;
    };
    expect(none.series[0].markLine).toBeUndefined();
  });
});

describe('buildExpansionOption', () => {
  test('two series over the same category axis, first row on top', () => {
    const opt = buildExpansionOption(
      [
        { name: 'wind-1', installed: 100, optimised: 250, color: '#1' },
        { name: 'gas-1', installed: 50, optimised: 50, color: '#2' },
      ],
      theme,
    ) as {
      yAxis: { data: string[]; inverse: boolean };
      series: Array<{ name: string; data: unknown[] }>;
    };
    expect(opt.yAxis.data).toEqual(['wind-1', 'gas-1']);
    expect(opt.yAxis.inverse).toBe(true);
    expect(opt.series.map((s) => s.name)).toEqual(['Installed', 'Optimised']);
    expect(opt.series[0].data).toEqual([100, 50]);
  });
});
