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
import { describe, test, expect } from '@jest/globals';
import type { MetricOption } from 'lib/types';
import { aggregateMetricRows, aggregateValues, buildDonutFromMetric } from './analytics';

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
