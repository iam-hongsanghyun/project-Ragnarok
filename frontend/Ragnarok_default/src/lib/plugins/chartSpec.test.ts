import { describe, it, expect } from '@jest/globals';
import {
  chartSpecToDonut,
  chartSpecToRows,
  chartSpecToSeries,
  isPluginChartSpec,
} from './chartSpec';
import { PluginChartSpec } from 'lib/types';

describe('isPluginChartSpec', () => {
  it('accepts the four supported kinds', () => {
    for (const kind of ['line', 'area', 'bar', 'donut'] as const) {
      expect(isPluginChartSpec({ kind })).toBe(true);
    }
  });

  it('rejects non-objects and unknown kinds', () => {
    expect(isPluginChartSpec(null)).toBe(false);
    expect(isPluginChartSpec('line')).toBe(false);
    expect(isPluginChartSpec({})).toBe(false);
    expect(isPluginChartSpec({ kind: 'pie' })).toBe(false);
  });
});

describe('chartSpecToDonut', () => {
  it('maps slices to MixItems and coerces values', () => {
    const spec: PluginChartSpec = {
      kind: 'donut',
      slices: [
        { label: 'Solar', value: 10, color: '#abc' },
        { label: 'Wind', value: '20' as unknown as number },
      ],
    };
    const out = chartSpecToDonut(spec);
    expect(out).toHaveLength(2);
    expect(out[0]).toEqual({ label: 'Solar', value: 10, color: '#abc' });
    expect(out[1].label).toBe('Wind');
    expect(out[1].value).toBe(20); // coerced from string
    expect(out[1].color).toMatch(/^#|^hsl/); // palette fallback
  });

  it('returns [] when slices are missing', () => {
    expect(chartSpecToDonut({ kind: 'donut' })).toEqual([]);
  });
});

describe('chartSpecToSeries', () => {
  it('fills label and colour defaults', () => {
    const spec: PluginChartSpec = {
      kind: 'line',
      series: [{ key: 'a' }, { key: 'b', label: 'Bee', color: '#123' }],
    };
    const out = chartSpecToSeries(spec);
    expect(out[0]).toMatchObject({ key: 'a', label: 'a' });
    expect(out[0].color).toMatch(/^#|^hsl/);
    expect(out[1]).toMatchObject({ key: 'b', label: 'Bee', color: '#123' });
  });
});

describe('chartSpecToRows', () => {
  it('derives label, passes timestamp, and coerces series values to numbers', () => {
    const spec: PluginChartSpec = {
      kind: 'bar',
      series: [{ key: 'a' }, { key: 'b' }],
      rows: [
        { label: 'Q1', a: 1, b: 2 },
        { x: 'Q2', a: '3' as unknown as number },
        { timestamp: '2030-01-01T00:00:00', a: 5, b: 6 },
      ],
    };
    const series = chartSpecToSeries(spec);
    const out = chartSpecToRows(spec, series);

    expect(out[0]).toEqual({ label: 'Q1', a: 1, b: 2 });
    expect(out[1].label).toBe('Q2'); // from `x`
    expect(out[1].a).toBe(3); // coerced
    expect(out[1].b).toBe(0); // missing → 0, never NaN
    expect(out[2].timestamp).toBe('2030-01-01T00:00:00');
  });

  it('falls back to row index for the label', () => {
    const spec: PluginChartSpec = { kind: 'line', series: [{ key: 'a' }], rows: [{ a: 1 }] };
    const out = chartSpecToRows(spec, chartSpecToSeries(spec));
    expect(out[0].label).toBe('0');
  });
});
