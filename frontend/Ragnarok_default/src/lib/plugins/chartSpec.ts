import { MixItem, PluginChartSpec, TimeSeriesRow, TimeSeriesSeries } from 'lib/types';
import { carrierColor, numberValue, stringValue } from 'lib/utils/helpers';

/**
 * Pure mappers from a plugin-declared `PluginChartSpec` to the props the
 * app's own chart components expect. Kept free of React so they can be
 * unit-tested directly; `PluginChart.tsx` is the thin rendering wrapper.
 */

/** Type-guard: is this `data` value a renderable chart spec? */
export function isPluginChartSpec(value: unknown): value is PluginChartSpec {
  if (!value || typeof value !== 'object') return false;
  const kind = (value as { kind?: unknown }).kind;
  return kind === 'line' || kind === 'area' || kind === 'bar' || kind === 'donut';
}

/** Donut slices → `MixItem[]` (DonutChart input). */
export function chartSpecToDonut(spec: PluginChartSpec): MixItem[] {
  const slices = Array.isArray(spec.slices) ? spec.slices : [];
  return slices.map((slice) => ({
    label: stringValue(slice.label),
    value: numberValue(slice.value),
    color: (slice.color && String(slice.color)) || carrierColor(stringValue(slice.label)),
  }));
}

/** Series definitions → `TimeSeriesSeries[]`, colours filled from the palette. */
export function chartSpecToSeries(spec: PluginChartSpec): TimeSeriesSeries[] {
  const series = Array.isArray(spec.series) ? spec.series : [];
  return series.map((item) => ({
    key: String(item.key),
    label: item.label ? String(item.label) : String(item.key),
    color: (item.color && String(item.color)) || carrierColor(String(item.label ?? item.key)),
  }));
}

/**
 * Rows → `TimeSeriesRow[]`. Each row gets a `label` (from `label`/`x`/index),
 * an optional `timestamp` passed through, and every declared series key
 * coerced to a finite number so the chart never NaNs out.
 */
export function chartSpecToRows(spec: PluginChartSpec, series: TimeSeriesSeries[]): TimeSeriesRow[] {
  const rows = Array.isArray(spec.rows) ? spec.rows : [];
  return rows.map((raw, index) => {
    const row: TimeSeriesRow = { label: stringValue(raw.label ?? raw.x ?? index) };
    if (raw.timestamp !== undefined) row.timestamp = String(raw.timestamp);
    for (const item of series) row[item.key] = numberValue(raw[item.key]);
    return row;
  });
}
