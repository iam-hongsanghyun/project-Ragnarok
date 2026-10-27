/**
 * Snapshot-weight handling in chart aggregation.
 *
 * Rows hold per-snapshot MW rates. On a run with gaps between snapshots
 * (snapshotWeight = hours per snapshot), integrating to energy must scale by
 * the weight:
 *
 *   energy = sum_t MW_t * w   [MWh]
 *
 * 'mean' and 'last' reducers are weight-invariant under a uniform per-run
 * weight and must NOT change.
 */
import { describe, test, it, expect } from '@jest/globals';
import type { MetricOption } from 'lib/types';
import { aggregateMetricRows, aggregateValues, buildDonutFromMetric, selectGeneratorEnergy, statisticsForPeriod } from './analytics';

function mwMetric(reducer: MetricOption['reducer']): MetricOption {
  return {
    key: 'm', label: 'M', unit: 'MW', reducer, allowDonut: true,
    series: [{ key: 'wind', label: 'Wind', color: '#0a0' }],
    rows: [
      { label: '0', timestamp: '2025-01-01T00:00:00', wind: 10 },
      { label: '1', timestamp: '2025-01-01T04:00:00', wind: 20 },
      { label: '2', timestamp: '2025-01-01T08:00:00', wind: 30 },
    ],
  };
}

describe('snapshot-weighted aggregation', () => {
  test('sum reducer integrates MW into MWh with a 4 h weight', () => {
    expect(aggregateValues([10, 20, 30], 'sum', 4)).toBe(240);
  });

  test('mean and last reducers ignore the weight', () => {
    expect(aggregateValues([10, 20, 30], 'mean', 4)).toBe(20);
    expect(aggregateValues([10, 20, 30], 'last', 4)).toBe(30);
  });

  test('weight defaults to 1 (hourly runs unchanged)', () => {
    expect(aggregateValues([10, 20, 30], 'sum')).toBe(60);
  });

  test('aggregated timeframe applies the weight to sum metrics', () => {
    const rows = aggregateMetricRows(mwMetric('sum'), 0, 2, 'aggregated', 4);
    expect(rows).toHaveLength(1);
    expect(rows[0].wind).toBe(240);
  });

  test('aggregated timeframe leaves mean metrics unweighted', () => {
    const rows = aggregateMetricRows(mwMetric('mean'), 0, 2, 'aggregated', 4);
    expect(rows[0].wind).toBe(20);
  });

  test('hourly timeframe returns raw MW rows untouched', () => {
    const rows = aggregateMetricRows(mwMetric('mean'), 0, 2, 'hourly', 4);
    expect(rows.map((r) => r.wind)).toEqual([10, 20, 30]);
  });

  test('donut total scales by the weight regardless of reducer', () => {
    const donut = buildDonutFromMetric(mwMetric('mean'), 0, 2, 4);
    expect(donut).toEqual([{ label: 'Wind', value: 240, color: '#0a0' }]);
  });

  test('donut range slicing still sums only the selected snapshots', () => {
    const donut = buildDonutFromMetric(mwMetric('mean'), 1, 2, 4);
    expect(donut[0].value).toBe(200);
  });
});


describe('period-aware backend aggregates', () => {
  const entries = [
    { name: 'g', value: 300 },
    { name: 'g', value: 100, period: 2030 },
    { name: 'g', value: 200, period: 2040 },
  ];
  it('selectGeneratorEnergy never mixes whole-horizon and per-period entries', () => {
    expect(selectGeneratorEnergy(entries, 2040)?.map((e) => e.value)).toEqual([200]);
    expect(selectGeneratorEnergy(entries, null)?.map((e) => e.value)).toEqual([300]);
    expect(selectGeneratorEnergy(entries, 1999)?.map((e) => e.value)).toEqual([300]);
    expect(selectGeneratorEnergy(entries.slice(0, 1), 2030)?.map((e) => e.value)).toEqual([300]);
  });
  it('statisticsForPeriod filters pathway rows and passes single-period through', () => {
    const st = { columns: ['a'], periods: [2030, 2040], rows: [
      { component: 'G', carrier: 'x', period: 2030, values: { a: 1 } },
      { component: 'G', carrier: 'x', period: 2040, values: { a: 2 } },
    ] };
    expect(statisticsForPeriod(st, 2040)?.rows.map((r) => r.values.a)).toEqual([2]);
    const single = { columns: ['a'], rows: [{ component: 'G', carrier: 'x', values: { a: 1 } }] };
    expect(statisticsForPeriod(single, 2040)).toBe(single);
  });
});
