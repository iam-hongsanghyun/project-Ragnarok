import { MetricOption, RunResults, SeriesPoint, StatisticsResult, TimeframeOption, TimeSeriesRow } from '../types';
import { numberValue } from 'lib/utils/helpers';

/** `RunResults.assetDetails` with no assets - what a result carries until the server's
 *  per-asset details (`GET /api/runs/{name}/assets`) are loaded. */
export function emptyAssetDetails(): RunResults['assetDetails'] {
  return {
    generators: {}, buses: {}, storageUnits: {}, stores: {}, branches: {}, processes: {}, shuntImpedances: {},
  };
}

export function normalizeSeriesPoint(point: SeriesPoint): TimeSeriesRow {
  const fallbackValues = Object.fromEntries(
    Object.entries(point as unknown as Record<string, unknown>).filter(
      ([key, value]) => !['label', 'timestamp', 'total', 'values', 'period'].includes(key) && typeof value === 'number',
    ),
  ) as Record<string, number>;
  return {
    label: point.label,
    timestamp: point.timestamp,
    period: point.period ?? undefined,
    total: point.total || 0,
    ...fallbackValues,
    ...(point.values || {}),
  };
}

/** Keep rows of the selected investment period. Rows with no numeric `period`
 *  (single-period runs, aggregates that predate period-aware output) are kept. */
export function filterRowsByPeriod<T extends object>(
  rows: T[], period: number | null | undefined,
): T[] {
  if (period === null || period === undefined) return rows;
  return rows.filter((row) => {
    const raw = (row as { period?: unknown }).period;
    if (raw === undefined || raw === null || raw === '') return true;
    const n = Number(raw);
    return !Number.isFinite(n) || n === period;
  });
}

type GeneratorEnergyEntry = NonNullable<RunResults['generatorEnergy']>[number];

/**
 * Pick ONE family of `generatorEnergy` entries. Pathway backends append
 * per-(generator, period) entries next to the whole-horizon ones, so mixing
 * them double counts: with period entries present use only the selected
 * period's; otherwise (single-period runs, older bundles, no matching period)
 * use only the period-less whole-horizon entries.
 */
export function selectGeneratorEnergy(
  entries: GeneratorEnergyEntry[] | undefined, period: number | null | undefined,
): GeneratorEnergyEntry[] | undefined {
  if (!entries) return entries;
  const hasPeriod = (e: GeneratorEnergyEntry) => e.period !== undefined && e.period !== null;
  const perPeriod = entries.filter((e) => hasPeriod(e) && Number(e.period) === period);
  if (period !== null && period !== undefined && perPeriod.length > 0) return perPeriod;
  return entries.filter((e) => !hasPeriod(e));
}

/** Statistics table for the selected period (pathway rows carry `period`;
 *  single-period tables pass through unchanged). */
export function statisticsForPeriod(
  stats: StatisticsResult | undefined, period: number | null | undefined,
): StatisticsResult | undefined {
  if (!stats || period === null || period === undefined) return stats;
  if (!stats.rows.some((r) => r.period !== undefined && r.period !== null)) return stats;
  return { ...stats, rows: stats.rows.filter((r) => r.period === undefined || r.period === null || Number(r.period) === period) };
}

/** Hours the snapshots stand for: one number for a uniform run, or PyPSA's own `snapshot_weightings` per snapshot
 *  (`runMeta.snapshotWeights`; a sampled run's snapshots represent different numbers of hours). */
export type SnapshotWeights = number | readonly number[];

/** The run's snapshot hours: PyPSA's per-snapshot weightings when the payload carries them, else the uniform number. */
export function runSnapshotWeights(
  results: { runMeta?: { snapshotWeights?: number[] | null; snapshotWeight?: number } } | null | undefined,
): SnapshotWeights {
  const perSnapshot = results?.runMeta?.snapshotWeights;
  return perSnapshot && perSnapshot.length ? perSnapshot : (results?.runMeta?.snapshotWeight ?? 1);
}

/** Hours of snapshot `index` of `count` rows. A per-snapshot array that does not line up with the rows (a period
 *  view, a window of a different length) falls back to its mean, never to a wrong row's weight. */
export function weightAt(weights: SnapshotWeights, index: number, count: number): number {
  if (typeof weights === 'number') return weights;
  if (weights.length === count) return weights[index] ?? 1;
  return weights.length ? weights.reduce((a, b) => a + b, 0) / weights.length : 1;
}

/** Reduce per-snapshot values over a time bucket.
 *
 * `weights` (hours per snapshot) integrate rates into amounts for the 'sum' reducer: a 4-hourly run summing
 * MW snapshots must scale by 4 to get MWh, and a sampled run by each snapshot's own hours (`weightAt`).
 * `values` are the rows' values in row order and `offset` is the index of the first of them among
 * `count` rows. 'mean' and 'last' are weight-invariant and stay untouched. */
export function aggregateValues(
  values: number[], reducer: MetricOption['reducer'], weights: SnapshotWeights = 1, offset = 0, count = values.length,
) {
  if (!values.length) return 0;
  if (reducer === 'sum') return values.reduce((sum, value, i) => sum + value * weightAt(weights, offset + i, count), 0);
  if (reducer === 'last') return values[values.length - 1];
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

export function getTimeBucket(timestamp: string | undefined, timeframe: TimeframeOption) {
  if (!timestamp || timeframe === 'hourly') return timestamp || '';
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;
  if (timeframe === 'aggregated') return 'aggregated';
  if (timeframe === 'yearly') return `${date.getFullYear()}`;
  if (timeframe === 'monthly') return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
  if (timeframe === 'daily') return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  const start = new Date(date);
  const day = (date.getDay() + 6) % 7;
  start.setDate(date.getDate() - day);
  start.setHours(0, 0, 0, 0);
  return `${start.getFullYear()}-W${String(start.getMonth() + 1).padStart(2, '0')}-${String(start.getDate()).padStart(2, '0')}`;
}

/** Effective time span for choosing x-label granularity.
 *
 * `last − first` over-counts for sampled-blocks runs: 4 blocks of 168 hourly
 * rows span a whole year on the calendar but hold only 672 dense points, so
 * span-based labels would jump to month level. Using the MEDIAN consecutive
 * delta × row count is immune to the few huge block-gap deltas, while for
 * contiguous data median × n ≈ true span, preserving existing behaviour. */
export function effectiveSpanMs(rows: Array<{ timestamp?: string }>): number {
  const times = rows
    .map((r) => (r.timestamp ? new Date(r.timestamp).getTime() : NaN))
    .filter((t) => Number.isFinite(t));
  if (times.length < 2) return 0;
  const rawSpan = times[times.length - 1] - times[0];
  if (times.length < 3) return rawSpan;
  const deltas = [];
  for (let i = 1; i < times.length; i++) deltas.push(times[i] - times[i - 1]);
  deltas.sort((a, b) => a - b);
  const median = deltas[Math.floor(deltas.length / 2)];
  return median > 0 ? median * times.length : rawSpan;
}

export function aggregateMetricRows(metric: MetricOption, startIndex: number, endIndex: number, timeframe: TimeframeOption, snapshotWeight: SnapshotWeights = 1) {
  const count = metric.rows.length;
  const rows = metric.rows.slice(startIndex, endIndex + 1);
  if (!rows.length) return [];
  if (timeframe === 'hourly') return rows;
  if (timeframe === 'aggregated') {
    const aggregated: TimeSeriesRow = { label: 'Total', timestamp: rows[rows.length - 1]?.timestamp };
    metric.series.forEach((item) => {
      aggregated[item.key] = aggregateValues(
        rows.map((row) => numberValue(row[item.key] as string | number | undefined)),
        metric.reducer,
        snapshotWeight,
        startIndex,
        count,
      );
    });
    return [aggregated];
  }
  const buckets = new Map<string, TimeSeriesRow[]>();
  const rowIndex = new Map<TimeSeriesRow, number>();
  rows.forEach((row, i) => {
    rowIndex.set(row, startIndex + i);
    const bucket = getTimeBucket(row.timestamp, timeframe);
    const current = buckets.get(bucket) || [];
    current.push(row);
    buckets.set(bucket, current);
  });
  return Array.from(buckets.entries()).map(([bucket, bucketRows]) => {
    const aggregated: TimeSeriesRow = { label: bucket, timestamp: bucketRows[bucketRows.length - 1]?.timestamp };
    metric.series.forEach((item) => {
      // A sum weights each row by its own hours, so the bucket carries its rows' absolute indices.
      aggregated[item.key] = metric.reducer === 'sum'
        ? bucketRows.reduce(
            (sum, row) => sum + numberValue(row[item.key] as string | number | undefined) * weightAt(snapshotWeight, rowIndex.get(row) ?? 0, count),
            0,
          )
        : aggregateValues(
            bucketRows.map((row) => numberValue(row[item.key] as string | number | undefined)),
            metric.reducer,
            snapshotWeight,
          );
    });
    return aggregated;
  });
}

export function buildDonutFromMetric(metric: MetricOption, startIndex: number, endIndex: number, snapshotWeight: SnapshotWeights = 1) {
  // A donut is the SUM over the selected period — sum the raw per-snapshot
  // values across [startIndex, endIndex], regardless of the metric's reducer
  // (mean/last) or any timeframe bucketing. So sliding the range re-sums exactly
  // the selected snapshots. `snapshotWeight` (hours per snapshot) integrates
  // MW-rate rows into MWh totals on runs with gaps between snapshots; a per-snapshot array weights each row
  // by its own hours (a sampled run).
  const count = metric.rows.length;
  const rows = metric.rows.slice(startIndex, endIndex + 1);
  return metric.series
    .map((item) => ({
      label: item.label,
      value: rows.reduce(
        (sum, row, i) => sum + Math.abs(numberValue(row[item.key] as string | number | undefined)) * weightAt(snapshotWeight, startIndex + i, count),
        0,
      ),
      color: item.color,
    }))
    .filter((item) => item.value > 0)
    .sort((left, right) => right.value - left.value);
}
