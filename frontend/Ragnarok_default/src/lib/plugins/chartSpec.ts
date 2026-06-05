import {
  MixItem,
  PluginChartSpec,
  PluginMapEdge,
  PluginMapNode,
  TimeSeriesRow,
  TimeSeriesSeries,
} from 'lib/types';
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
  return (
    kind === 'line' || kind === 'area' || kind === 'bar' || kind === 'donut' || kind === 'map'
  );
}

/** A map node with coordinates coerced to finite numbers. */
export interface MapNodePoint {
  id: string;
  label: string;
  lat: number;
  lon: number;
  value: number;
  color?: string;
}

/** A map edge resolved to its endpoint coordinates. */
export interface MapEdgeLine {
  from: string;
  to: string;
  value: number;
  label: string;
  color?: string;
  positions: [[number, number], [number, number]];
}

const isFiniteNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/** Map nodes → points with finite lat/lon (invalid coordinates dropped). */
export function chartSpecToMapNodes(spec: PluginChartSpec): MapNodePoint[] {
  const nodes = Array.isArray(spec.nodes) ? spec.nodes : [];
  return nodes
    .map((n: PluginMapNode) => ({
      id: String(n.id),
      label: stringValue(n.label ?? n.id),
      lat: numberValue(n.lat),
      lon: numberValue(n.lon),
      value: numberValue(n.value),
      color: n.color ? String(n.color) : undefined,
    }))
    .filter((n) => isFiniteNum(n.lat) && isFiniteNum(n.lon) && !(n.lat === 0 && n.lon === 0));
}

/** Map edges → lines, resolving `from`/`to` to node coordinates (unmatched dropped). */
export function chartSpecToMapEdges(spec: PluginChartSpec, nodes: MapNodePoint[]): MapEdgeLine[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const edges = Array.isArray(spec.edges) ? spec.edges : [];
  const lines: MapEdgeLine[] = [];
  for (const e of edges as PluginMapEdge[]) {
    const a = byId.get(String(e.from));
    const b = byId.get(String(e.to));
    if (!a || !b) continue;
    lines.push({
      from: a.id,
      to: b.id,
      value: numberValue(e.value),
      label: stringValue(e.label ?? `${a.label} → ${b.label}`),
      color: e.color ? String(e.color) : undefined,
      positions: [[a.lat, a.lon], [b.lat, b.lon]],
    });
  }
  return lines;
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
