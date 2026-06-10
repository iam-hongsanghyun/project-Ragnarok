import { MetricOption, RunResults, SeriesPoint, TimeframeOption, TimeSeriesRow } from '../types';
import { numberValue } from 'lib/utils/helpers';

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

export function buildRowsFromGeneratorDetails(
  generators: Record<string, { carrier: string; name: string; outputSeries: Array<{ label: string; timestamp: string; output: number }> }>,
  mode: 'generator' | 'carrier',
): TimeSeriesRow[] {
  const buckets = new Map<string, TimeSeriesRow>();
  Object.values(generators).forEach((generator) => {
    generator.outputSeries.forEach((point) => {
      const key = mode === 'carrier' ? generator.carrier : generator.name;
      const row = buckets.get(point.timestamp) || { label: point.label, timestamp: point.timestamp };
      row[key] = numberValue(row[key] as string | number | undefined) + Math.max(point.output, 0);
      buckets.set(point.timestamp, row);
    });
  });
  return Array.from(buckets.values()).sort((left, right) => String(left.timestamp).localeCompare(String(right.timestamp)));
}

export function buildSystemLoadRows(results: RunResults | null): TimeSeriesRow[] {
  if (!results) return [];
  const dispatchRows = (results.dispatchSeries || []).map((point) => ({
    label: point.label,
    timestamp: point.timestamp,
    load: numberValue((point as unknown as Record<string, unknown>).total as number | string | undefined),
  }));
  const hasPositiveDispatchLoad = dispatchRows.some((row) => numberValue(row.load as string | number | undefined) > 0);
  if (hasPositiveDispatchLoad) return dispatchRows;

  const buckets = new Map<string, TimeSeriesRow>();
  Object.values(results.assetDetails.buses || {}).forEach((bus) => {
    bus.netSeries.forEach((point) => {
      const row = buckets.get(point.timestamp) || { label: point.label, timestamp: point.timestamp, load: 0 };
      row.load = numberValue(row.load as string | number | undefined) + point.load;
      buckets.set(point.timestamp, row);
    });
  });
  return Array.from(buckets.values()).sort((left, right) => String(left.timestamp).localeCompare(String(right.timestamp)));
}

export function aggregateValues(values: number[], reducer: MetricOption['reducer']) {
  if (!values.length) return 0;
  if (reducer === 'sum') return values.reduce((sum, value) => sum + value, 0);
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

export function aggregateMetricRows(metric: MetricOption, startIndex: number, endIndex: number, timeframe: TimeframeOption) {
  const rows = metric.rows.slice(startIndex, endIndex + 1);
  if (!rows.length) return [];
  if (timeframe === 'hourly') return rows;
  if (timeframe === 'aggregated') {
    const aggregated: TimeSeriesRow = { label: 'Total', timestamp: rows[rows.length - 1]?.timestamp };
    metric.series.forEach((item) => {
      aggregated[item.key] = aggregateValues(
        rows.map((row) => numberValue(row[item.key] as string | number | undefined)),
        metric.reducer,
      );
    });
    return [aggregated];
  }
  const buckets = new Map<string, TimeSeriesRow[]>();
  rows.forEach((row) => {
    const bucket = getTimeBucket(row.timestamp, timeframe);
    const current = buckets.get(bucket) || [];
    current.push(row);
    buckets.set(bucket, current);
  });
  return Array.from(buckets.entries()).map(([bucket, bucketRows]) => {
    const aggregated: TimeSeriesRow = { label: bucket, timestamp: bucketRows[bucketRows.length - 1]?.timestamp };
    metric.series.forEach((item) => {
      aggregated[item.key] = aggregateValues(
        bucketRows.map((row) => numberValue(row[item.key] as string | number | undefined)),
        metric.reducer,
      );
    });
    return aggregated;
  });
}

export function buildDonutFromMetric(metric: MetricOption, startIndex: number, endIndex: number) {
  // A donut is the SUM over the selected period — sum the raw per-snapshot
  // values across [startIndex, endIndex], regardless of the metric's reducer
  // (mean/last) or any timeframe bucketing. So sliding the range re-sums exactly
  // the selected snapshots.
  const rows = metric.rows.slice(startIndex, endIndex + 1);
  return metric.series
    .map((item) => ({
      label: item.label,
      value: rows.reduce((sum, row) => sum + Math.abs(numberValue(row[item.key] as string | number | undefined)), 0),
      color: item.color,
    }))
    .filter((item) => item.value > 0)
    .sort((left, right) => right.value - left.value);
}
