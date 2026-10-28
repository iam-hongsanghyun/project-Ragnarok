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
import { aggregateMetricRows, aggregateValues, buildDonutFromMetric, runSnapshotWeights, selectGeneratorEnergy, statisticsForPeriod, weightAt } from './analytics';

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


describe('per-snapshot weights (a sampled run)', () => {
  // The three rows stand for 1 h, 2 h and 5 h (PyPSA snapshot_weightings), not one uniform number.
  const weights = [1, 2, 5];

  test('sum integrates each snapshot with its own hours', () => {
    expect(aggregateValues([10, 20, 30], 'sum', weights)).toBe(10 * 1 + 20 * 2 + 30 * 5);
    expect(aggregateValues([20, 30], 'sum', weights, 1, 3)).toBe(20 * 2 + 30 * 5);   // a window starting at row 1
  });

  test('donut and aggregated rows use the same per-row hours', () => {
    expect(buildDonutFromMetric(mwMetric('mean'), 0, 2, weights)[0].value).toBe(200);
    expect(buildDonutFromMetric(mwMetric('mean'), 1, 2, weights)[0].value).toBe(190);
    expect(aggregateMetricRows(mwMetric('sum'), 0, 2, 'aggregated', weights)[0].wind).toBe(200);
    expect(aggregateMetricRows(mwMetric('sum'), 0, 2, 'daily', weights)[0].wind).toBe(200);
  });

  test('weights that do not line up with the rows fall back to their mean, never a wrong row', () => {
    expect(weightAt([1, 2, 5], 0, 4)).toBeCloseTo(8 / 3);
    expect(weightAt(4, 7, 100)).toBe(4);
  });

  test('the run carries PyPSA weights, else the uniform one', () => {
    expect(runSnapshotWeights({ runMeta: { snapshotWeights: [1, 2], snapshotWeight: 9 } })).toEqual([1, 2]);
    expect(runSnapshotWeights({ runMeta: { snapshotWeights: null, snapshotWeight: 4 } })).toBe(4);
    expect(runSnapshotWeights(null)).toBe(1);
  });
});
