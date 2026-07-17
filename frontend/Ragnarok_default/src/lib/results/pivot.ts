/**
 * Generic "pivot from outputs" engine.
 *
 * Builds a chart from ACTUAL component values rather than the hardcoded metric
 * registry: pick a component + attribute (output series, static output, or input
 * numeric), group by one or more input dimensions (carrier, bus, …), filter by
 * component attributes and/or per-snapshot value thresholds, and aggregate.
 *
 * "Generation by carrier" = component `generators`, attribute `p`, group-by
 * `carrier`, aggregate `sum` — derived by grouping each generator's `generators-p`
 * output by its input-model carrier.
 *
 * Output feeds the existing renderers: `{rows, series}` → InteractiveTimeSeriesCard
 * (line/area/bar), `MixItem[]` → DonutChart.
 */
import {
  GridRow,
  MixItem,
  Primitive,
  RunResults,
  TimeSeriesRow,
  TimeSeriesSeries,
  WorkbookModel,
} from 'lib/types';
import { carrierColor, hashColor, numberValue, orderByCarrierRows, stringValue } from 'lib/utils/helpers';
import { getTimeBucket } from 'lib/results/analytics';
import { getAttributeSchema, getComponentSchema, PYPSA_COMPONENTS } from 'lib/constants/pypsa_schema';
import { PivotChartConfig, PivotFilter } from 'lib/dashboard/types';

type Aggregate = PivotChartConfig['aggregate'];
export type PivotValueKind = 'series' | 'static' | 'input';

// Row keys that are the time/identity index, never a component column.
const INDEX_KEYS = new Set(['snapshot', 'name', 'datetime', 'timestep', 'index', 'label', 'period', 'total']);

// ── Enumeration (drives the dropdowns) ──────────────────────────────────────

export interface PivotComponentOpt { value: string; label: string }
export interface PivotAttrOpt { value: string; label: string; kind: PivotValueKind; unit: string }

/** Components that have any output data in this run (static or series). */
export function pivotComponents(results: RunResults | null, model: WorkbookModel): PivotComponentOpt[] {
  const staticLists = new Set(Object.keys(results?.outputs?.static ?? {}));
  const seriesLists = new Set(
    [...Object.keys(results?.outputs?.series ?? {}), ...(results?.outputs?.seriesSheets ?? [])]
      .map((s) => s.split('-')[0]),
  );
  return PYPSA_COMPONENTS
    .filter((c) => {
      const hasModelRows = (model[c.sheet_name]?.length ?? 0) > 0;
      return staticLists.has(c.list_name) || seriesLists.has(c.list_name) || hasModelRows;
    })
    .map((c) => ({ value: c.sheet_name, label: c.label }));
}

/** Whether a value attribute is a series output (→ `<list>-<attr>` sheet),
 *  a static output, or an input numeric. Schema-driven so it works before the
 *  series data has been hydrated. */
export function pivotValueKind(sheet: string, attr: string): PivotValueKind {
  const c = getComponentSchema(sheet);
  if (c?.temporal_attributes.includes(attr) && c.output_attributes.includes(attr)) return 'series';
  if (c?.output_attributes.includes(attr)) return 'static';
  return 'input';
}

/** The `<list>-<attr>` output-series sheet for a config, or null when the value
 *  attribute isn't a series output (static / input need no hydration). */
export function pivotSeriesSheet(sheet: string, attr: string): string | null {
  if (!attr) return null;
  const c = getComponentSchema(sheet);
  return c && pivotValueKind(sheet, attr) === 'series' ? `${c.list_name}-${attr}` : null;
}

function isNumericType(type: string | undefined): boolean {
  return !!type && /float|int|double|number/i.test(type);
}

/** Plottable value attributes for a component: output series + static outputs +
 *  input numerics. Labelled with their unit. */
export function pivotValueAttributes(sheet: string): PivotAttrOpt[] {
  const c = getComponentSchema(sheet);
  if (!c) return [];
  const out: PivotAttrOpt[] = [];
  const seen = new Set<string>();
  const add = (attr: string, kind: PivotValueKind) => {
    if (!attr || seen.has(attr)) return;
    seen.add(attr);
    const unit = getAttributeSchema(sheet, attr)?.unit;
    const u = unit && unit !== 'n/a' ? unit : '';
    out.push({ value: attr, label: u ? `${attr} (${u})` : attr, kind, unit: u });
  };
  for (const attr of c.output_attributes) add(attr, pivotValueKind(sheet, attr));
  for (const a of c.attributes) {
    if (a.status === 'input' && a.storage === 'static' && isNumericType(a.type)) add(a.attribute, 'input');
  }
  return out;
}

/** Dimension fields available to group / filter by — the input attributes
 *  actually present on the component's rows (so partial/imported models only
 *  surface real columns). */
export function pivotDimensionFields(sheet: string, model: WorkbookModel): string[] {
  const rows = model[sheet] ?? [];
  const keys = new Set<string>();
  for (const r of rows.slice(0, 200)) for (const k of Object.keys(r)) keys.add(k);
  // Stable, useful order: carrier/bus/type first, then the rest alphabetically.
  const lead = ['carrier', 'bus', 'bus0', 'bus1', 'type'].filter((k) => keys.has(k));
  const rest = Array.from(keys).filter((k) => !lead.includes(k)).sort();
  return [...lead, ...rest];
}

export function pivotUniqueValues(sheet: string, model: WorkbookModel, field: string): string[] {
  const rows = model[sheet] ?? [];
  const vals = new Set<string>();
  for (const r of rows) { const v = stringValue(r[field]); if (v) vals.add(v); }
  return Array.from(vals).sort();
}

export function pivotFieldNumeric(sheet: string, model: WorkbookModel, field: string): boolean {
  const attr = getAttributeSchema(sheet, field);
  if (attr) return isNumericType(attr.type);
  // Custom column: sniff the data.
  const rows = (model[sheet] ?? []).slice(0, 20).map((r) => r[field]).filter((v) => v !== null && v !== undefined && v !== '');
  if (!rows.length) return false;
  return rows.every((v) => Number.isFinite(Number(v)));
}

// ── Aggregation ─────────────────────────────────────────────────────────────

function reduce(values: number[], agg: Aggregate): number {
  if (agg === 'count') return values.length;
  if (!values.length) return 0;
  if (agg === 'sum') return values.reduce((a, b) => a + b, 0);
  if (agg === 'mean') return values.reduce((a, b) => a + b, 0) / values.length;
  if (agg === 'max') return Math.max(...values);
  return Math.min(...values);
}

/** The unit label for an aggregated value. Summing a rate series over time
 *  (or over a window with no time axis, e.g. a donut/category total)
 *  integrates power into energy — `MW` becomes `MWh`. `mean` / `max` / `min` /
 *  `count` stay the instantaneous rate. Only literal `MW` is rewritten (the
 *  one rate unit these pivots expose); every other unit (currency, tCO2e, …)
 *  passes through unchanged. */
function integratedUnit(rawUnit: string, integrates: boolean): string {
  return integrates && rawUnit === 'MW' ? 'MWh' : rawUnit;
}

// ── Filters ─────────────────────────────────────────────────────────────────

function passComponentFilters(dim: GridRow, filters: PivotFilter[]): boolean {
  for (const f of filters) {
    if (f.scope !== 'component' || !f.field) continue;
    if (f.op === 'in') {
      if (f.values && f.values.length && !f.values.includes(stringValue(dim[f.field]))) return false;
    } else if (f.value != null) {
      const v = numberValue(dim[f.field]);
      if (f.op === '>' && !(v > f.value)) return false;
      if (f.op === '>=' && !(v >= f.value)) return false;
      if (f.op === '<' && !(v < f.value)) return false;
      if (f.op === '<=' && !(v <= f.value)) return false;
      if (f.op === '=' && !(v === f.value)) return false;
    }
  }
  return true;
}

/** Per-snapshot value-threshold filters — a failing value is dropped from the
 *  group that snapshot. Categorical (`in`) value-filters are ignored. */
function passValueFilters(val: number, filters: PivotFilter[]): boolean {
  for (const f of filters) {
    if (f.scope !== 'value' || f.value == null || f.op === 'in') continue;
    if (f.op === '>' && !(val > f.value)) return false;
    if (f.op === '>=' && !(val >= f.value)) return false;
    if (f.op === '<' && !(val < f.value)) return false;
    if (f.op === '<=' && !(val <= f.value)) return false;
    if (f.op === '=' && !(val === f.value)) return false;
  }
  return true;
}

// ── Grouping helpers ────────────────────────────────────────────────────────

function indexByName(rows: GridRow[]): Record<string, GridRow> {
  const out: Record<string, GridRow> = {};
  for (const r of rows) { const n = stringValue(r.name); if (n) out[n] = r; }
  return out;
}

function groupKeyOf(dim: GridRow, name: string, groupBy: string[]): string {
  if (!groupBy.length) return name;
  return groupBy.map((f) => stringValue(dim[f]) || 'Unknown').join(' · ');
}

function colorFor(key: string, groupBy: string[]): string {
  return groupBy.length === 1 && groupBy[0] === 'carrier' ? carrierColor(key) : hashColor(key);
}

function orderKeys(keys: string[], groupBy: string[], model: WorkbookModel): string[] {
  if (groupBy.length === 1 && groupBy[0] === 'carrier') return orderByCarrierRows(model.carriers ?? [], keys);
  return keys;
}

function componentColumns(row: GridRow): string[] {
  return Object.keys(row).filter((k) => !INDEX_KEYS.has(k));
}

// ── Build: time-series (line / area / bar) ──────────────────────────────────

export interface PivotSeriesResult {
  rows: TimeSeriesRow[];
  series: TimeSeriesSeries[];
  unit: string;
  /** True when the value is a series output not yet hydrated (light view). */
  loading: boolean;
}

export function buildPivotSeries(
  config: PivotChartConfig,
  results: RunResults | null,
  model: WorkbookModel,
  snapshotWeight = 1,
): PivotSeriesResult {
  const kind = pivotValueKind(config.sheet, config.valueAttribute);
  const rawUnit = getAttributeSchema(config.sheet, config.valueAttribute)?.unit ?? '';
  const dims = indexByName(model[config.sheet] ?? []);
  const compList = getComponentSchema(config.sheet)?.list_name ?? config.sheet;

  // Static / input attributes have no time axis → a single "Total" row. No
  // integration happens here (there's no snapshot weight to apply), so the
  // unit never changes regardless of `aggregate`.
  if (kind !== 'series') {
    const groups = new Map<string, number[]>();
    const staticVals = results?.outputs?.static?.[compList] ?? {};
    for (const [name, dim] of Object.entries(dims)) {
      if (!passComponentFilters(dim, config.filters)) continue;
      const raw = kind === 'static'
        ? numberValue((staticVals[name] as Record<string, Primitive> | undefined)?.[config.valueAttribute])
        : numberValue(dim[config.valueAttribute]);
      const key = groupKeyOf(dim, name, config.groupBy);
      (groups.get(key) ?? groups.set(key, []).get(key)!).push(raw);
    }
    const keys = orderKeys(Array.from(groups.keys()), config.groupBy, model);
    const row: TimeSeriesRow = { label: 'Total', timestamp: undefined };
    keys.forEach((k) => { row[k] = reduce(groups.get(k) ?? [], config.aggregate); });
    return {
      rows: [row],
      series: keys.map((k) => ({ key: k, label: k, color: colorFor(k, config.groupBy) })),
      unit: rawUnit,
      loading: false,
    };
  }

  const sheetKey = `${compList}-${config.valueAttribute}`;
  const seriesRows = results?.outputs?.series?.[sheetKey];
  if (!seriesRows || !seriesRows.length) {
    return { rows: [], series: [], unit: rawUnit, loading: true };
  }

  const start = Math.max(0, config.startIndex);
  const end = Math.min(config.endIndex, seriesRows.length - 1);
  const window = seriesRows.slice(start, end + 1);

  // Per snapshot: reduce member components into one value per group (across-
  // component reduction uses `aggregate`; weight is applied only at time-bucket
  // sum so instantaneous values aren't double-weighted).
  const perRow: TimeSeriesRow[] = [];
  const allKeys = new Set<string>();
  for (const srow of window) {
    const ts = stringValue(srow.snapshot ?? srow.name ?? srow.datetime);
    const groups = new Map<string, number[]>();
    for (const col of componentColumns(srow)) {
      const dim = dims[col] ?? {};
      if (!passComponentFilters(dim, config.filters)) continue;
      const v = numberValue(srow[col]);
      if (!passValueFilters(v, config.filters)) continue;
      const key = groupKeyOf(dim, col, config.groupBy);
      (groups.get(key) ?? groups.set(key, []).get(key)!).push(v);
    }
    const out: TimeSeriesRow = { label: ts, timestamp: ts };
    groups.forEach((vals, key) => { out[key] = reduce(vals, config.aggregate); allKeys.add(key); });
    perRow.push(out);
  }

  const keys = orderKeys(Array.from(allKeys), config.groupBy, model);
  const series: TimeSeriesSeries[] = keys.map((k) => ({ key: k, label: k, color: colorFor(k, config.groupBy) }));

  // `bucketRows` (via `bucketReduce`) is what actually integrates a `sum`
  // aggregate over the snapshot weight — only when snapshots are bucketed
  // (anything but 'hourly'); an hourly view stays one row per snapshot, so a
  // per-group `sum` there only combines components at the same instant and
  // is still a rate.
  const bucketed = config.timeframe !== 'hourly';
  const rows = bucketed
    ? bucketRows(perRow, keys, config.timeframe, config.aggregate, snapshotWeight)
    : perRow;
  const unit = integratedUnit(rawUnit, bucketed && config.aggregate === 'sum');

  return { rows, series, unit, loading: false };
}

/** Attribute display label for series naming (falls back to the raw name). */
function attrLabel(sheet: string, attr: string): string {
  return getAttributeSchema(sheet, attr)?.attribute ?? attr;
}

/**
 * Multi-attribute time series: build one pass per value attribute and merge into
 * a single chart. Each attribute's group series are namespaced (`attr::key`) so
 * the same group across different attributes stays a distinct series; rows are
 * merged by timestamp. Falls back to the single-attribute builder for one (or
 * zero) attributes — existing behaviour unchanged.
 */
export function buildPivotSeriesMulti(
  config: PivotChartConfig,
  attrs: string[],
  results: RunResults | null,
  model: WorkbookModel,
  snapshotWeight = 1,
): PivotSeriesResult {
  const list = (attrs && attrs.length ? attrs : [config.valueAttribute]).filter(Boolean);
  if (list.length <= 1) {
    return buildPivotSeries({ ...config, valueAttribute: list[0] ?? config.valueAttribute }, results, model, snapshotWeight);
  }
  const rowByKey = new Map<string, TimeSeriesRow>();
  const order: string[] = [];
  const series: TimeSeriesSeries[] = [];
  let unit = '';
  let unitSet = false;
  let loading = false;
  for (const attr of list) {
    const pass = buildPivotSeries({ ...config, valueAttribute: attr }, results, model, snapshotWeight);
    loading = loading || pass.loading;
    if (!unitSet) { unit = pass.unit; unitSet = true; } else if (unit !== pass.unit) unit = '';
    const al = attrLabel(config.sheet, attr);
    for (const s of pass.series) {
      series.push({ key: `${attr}::${s.key}`, label: `${al} · ${s.label}`, color: s.color });
    }
    for (const r of pass.rows) {
      const rk = String(r.timestamp ?? r.label);
      let merged = rowByKey.get(rk);
      if (!merged) { merged = { label: r.label, timestamp: r.timestamp }; rowByKey.set(rk, merged); order.push(rk); }
      for (const s of pass.series) if (s.key in r) merged[`${attr}::${s.key}`] = r[s.key];
    }
  }
  return { rows: order.map((k) => rowByKey.get(k)!), series, unit, loading };
}

/**
 * Multi-attribute category chart (grouped / horizontal bar): each attribute
 * becomes one series across the shared category labels, with its sub-group
 * series collapsed to a single total per category. Falls back to the
 * single-attribute builder for one (or zero) attributes.
 */
export function buildPivotCategoryMulti(
  config: PivotChartConfig,
  attrs: string[],
  results: RunResults | null,
  model: WorkbookModel,
  snapshotWeight = 1,
): PivotCategoryResult {
  const list = (attrs && attrs.length ? attrs : [config.valueAttribute]).filter(Boolean);
  if (list.length <= 1) {
    return buildPivotCategory({ ...config, valueAttribute: list[0] ?? config.valueAttribute }, results, model, snapshotWeight);
  }
  const passes = list.map((attr) => ({ attr, r: buildPivotCategory({ ...config, valueAttribute: attr }, results, model, snapshotWeight) }));
  const loading = passes.some((p) => p.r.loading);
  const labels: string[] = [];
  for (const { r } of passes) for (const l of r.labels) if (!labels.includes(l)) labels.push(l);
  let unit = passes[0]?.r.unit ?? '';
  if (passes.some((p) => p.r.unit !== unit)) unit = '';
  const series = passes.map(({ attr, r }) => {
    const perLabel = new Map<string, number>();
    r.labels.forEach((l, i) => {
      perLabel.set(l, r.series.reduce((sum, ser) => sum + (ser.values[i] ?? 0), 0));
    });
    return { key: attr, label: attrLabel(config.sheet, attr), color: hashColor(attr), values: labels.map((l) => perLabel.get(l) ?? 0) };
  });
  return { labels, series, unit, loading };
}

function bucketRows(
  perRow: TimeSeriesRow[],
  keys: string[],
  timeframe: PivotChartConfig['timeframe'],
  agg: Aggregate,
  weight: number,
): TimeSeriesRow[] {
  if (timeframe === 'aggregated') {
    const row: TimeSeriesRow = { label: 'Total', timestamp: perRow[perRow.length - 1]?.timestamp };
    keys.forEach((k) => { row[k] = bucketReduce(perRow.map((r) => numberValue(r[k])), agg, weight); });
    return [row];
  }
  const buckets = new Map<string, TimeSeriesRow[]>();
  for (const r of perRow) {
    const b = getTimeBucket(r.timestamp, timeframe);
    (buckets.get(b) ?? buckets.set(b, []).get(b)!).push(r);
  }
  return Array.from(buckets.entries()).map(([b, rs]) => {
    const row: TimeSeriesRow = { label: b, timestamp: rs[rs.length - 1]?.timestamp };
    keys.forEach((k) => { row[k] = bucketReduce(rs.map((r) => numberValue(r[k])), agg, weight); });
    return row;
  });
}

/** Time-bucket reduce: `sum` integrates over the snapshot weight (MW→MWh); the
 *  others are weight-invariant. */
function bucketReduce(values: number[], agg: Aggregate, weight: number): number {
  if (agg === 'sum') return values.reduce((a, b) => a + b, 0) * weight;
  return reduce(values, agg);
}

// ── Build: donut / static mix ───────────────────────────────────────────────

export interface PivotMixResult { data: MixItem[]; unit: string; loading: boolean }

export function buildPivotMix(
  config: PivotChartConfig,
  results: RunResults | null,
  model: WorkbookModel,
  snapshotWeight = 1,
): PivotMixResult {
  const kind = pivotValueKind(config.sheet, config.valueAttribute);
  const rawUnit = getAttributeSchema(config.sheet, config.valueAttribute)?.unit ?? '';
  const unit = integratedUnit(rawUnit, kind === 'series' && config.aggregate === 'sum');
  const dims = indexByName(model[config.sheet] ?? []);
  const compList = getComponentSchema(config.sheet)?.list_name ?? config.sheet;
  const groups = new Map<string, number[]>();

  if (kind === 'series') {
    const sheetKey = `${compList}-${config.valueAttribute}`;
    const seriesRows = results?.outputs?.series?.[sheetKey];
    if (!seriesRows || !seriesRows.length) return { data: [], unit, loading: true };
    const start = Math.max(0, config.startIndex);
    const end = Math.min(config.endIndex, seriesRows.length - 1);
    for (const srow of seriesRows.slice(start, end + 1)) {
      for (const col of componentColumns(srow)) {
        const dim = dims[col] ?? {};
        if (!passComponentFilters(dim, config.filters)) continue;
        const v = numberValue(srow[col]);
        if (!passValueFilters(v, config.filters)) continue;
        const key = groupKeyOf(dim, col, config.groupBy);
        (groups.get(key) ?? groups.set(key, []).get(key)!).push(v);
      }
    }
  } else {
    const staticVals = results?.outputs?.static?.[compList] ?? {};
    for (const [name, dim] of Object.entries(dims)) {
      if (!passComponentFilters(dim, config.filters)) continue;
      const raw = kind === 'static'
        ? numberValue((staticVals[name] as Record<string, Primitive> | undefined)?.[config.valueAttribute])
        : numberValue(dim[config.valueAttribute]);
      const key = groupKeyOf(dim, name, config.groupBy);
      (groups.get(key) ?? groups.set(key, []).get(key)!).push(raw);
    }
  }

  // A series donut integrates a rate over the period (sum × weight = energy);
  // static/input keep the chosen aggregate.
  const total = (vals: number[]) =>
    kind === 'series' && config.aggregate === 'sum' ? vals.reduce((a, b) => a + b, 0) * snapshotWeight : reduce(vals, config.aggregate);

  const data: MixItem[] = Array.from(groups.entries())
    .map(([label, vals]) => ({ label, value: total(vals), color: colorFor(label, config.groupBy) }))
    .filter((d) => Math.abs(d.value) > 0)
    .sort((a, b) => b.value - a.value);
  return { data, unit, loading: false };
}

/** Reduce a group's pooled values to one number: series + `sum` integrates over
 *  the snapshot weight (energy); everything else uses the chosen aggregate. */
function totalOf(vals: number[], kind: PivotValueKind, agg: Aggregate, weight: number): number {
  return kind === 'series' && agg === 'sum' ? vals.reduce((a, b) => a + b, 0) * weight : reduce(vals, agg);
}

// ── Build: category bar (grouped / horizontal / stacked over categories) ─────

export interface PivotCategorySeries { key: string; label: string; color: string; values: number[] }
export interface PivotCategoryResult {
  labels: string[];
  series: PivotCategorySeries[];
  /** Per-label colours for the single-series case (value-by-carrier bars). */
  barColors?: string[];
  unit: string;
  loading: boolean;
}

export function buildPivotCategory(
  config: PivotChartConfig,
  results: RunResults | null,
  model: WorkbookModel,
  snapshotWeight = 1,
): PivotCategoryResult {
  const kind = pivotValueKind(config.sheet, config.valueAttribute);
  const rawUnit = getAttributeSchema(config.sheet, config.valueAttribute)?.unit ?? '';
  const unit = integratedUnit(rawUnit, kind === 'series' && config.aggregate === 'sum');
  const dims = indexByName(model[config.sheet] ?? []);
  const compList = getComponentSchema(config.sheet)?.list_name ?? config.sheet;

  const catField = config.groupBy[0] ?? null;       // first dim → category axis
  const serFields = config.groupBy.slice(1);          // remaining dims → stack/cluster series
  const SINGLE = '__v';
  const byCat = new Map<string, Map<string, number[]>>();
  const push = (cat: string, ser: string, v: number) => {
    let m = byCat.get(cat); if (!m) { m = new Map(); byCat.set(cat, m); }
    (m.get(ser) ?? m.set(ser, []).get(ser)!).push(v);
  };

  if (kind === 'series') {
    const seriesRows = results?.outputs?.series?.[`${compList}-${config.valueAttribute}`];
    if (!seriesRows || !seriesRows.length) return { labels: [], series: [], unit, loading: true };
    const start = Math.max(0, config.startIndex);
    const end = Math.min(config.endIndex, seriesRows.length - 1);
    for (const srow of seriesRows.slice(start, end + 1)) {
      for (const col of componentColumns(srow)) {
        const dim = dims[col] ?? {};
        if (!passComponentFilters(dim, config.filters)) continue;
        const v = numberValue(srow[col]);
        if (!passValueFilters(v, config.filters)) continue;
        const cat = catField ? (stringValue(dim[catField]) || 'Unknown') : col;
        const ser = serFields.length ? serFields.map((f) => stringValue(dim[f]) || 'Unknown').join(' · ') : SINGLE;
        push(cat, ser, v);
      }
    }
  } else {
    const staticVals = results?.outputs?.static?.[compList] ?? {};
    for (const [name, dim] of Object.entries(dims)) {
      if (!passComponentFilters(dim, config.filters)) continue;
      const raw = kind === 'static'
        ? numberValue((staticVals[name] as Record<string, Primitive> | undefined)?.[config.valueAttribute])
        : numberValue(dim[config.valueAttribute]);
      const cat = catField ? (stringValue(dim[catField]) || 'Unknown') : name;
      const ser = serFields.length ? serFields.map((f) => stringValue(dim[f]) || 'Unknown').join(' · ') : SINGLE;
      push(cat, ser, raw);
    }
  }

  const cellTotal = (vals: number[] | undefined) => (vals ? totalOf(vals, kind, config.aggregate, snapshotWeight) : 0);
  let labels = orderKeys(Array.from(byCat.keys()), catField ? [catField] : [], model);
  const serKeys: string[] = [];
  Array.from(byCat.values()).forEach((m) => Array.from(m.keys()).forEach((k) => { if (!serKeys.includes(k)) serKeys.push(k); }));

  if (serKeys.length === 1 && serKeys[0] === SINGLE) {
    // value-by-category: a single series, one colour per bar.
    labels = labels.filter((l) => Math.abs(cellTotal(byCat.get(l)?.get(SINGLE))) > 0);
    return {
      labels,
      series: [{ key: SINGLE, label: unit || config.valueAttribute, color: '#0f766e', values: labels.map((l) => cellTotal(byCat.get(l)?.get(SINGLE))) }],
      barColors: labels.map((l) => colorFor(l, catField ? [catField] : [])),
      unit,
      loading: false,
    };
  }

  const orderedSer = orderKeys(serKeys, serFields, model);
  return {
    labels,
    series: orderedSer.map((k) => ({ key: k, label: k, color: colorFor(k, serFields), values: labels.map((l) => cellTotal(byCat.get(l)?.get(k))) })),
    unit,
    loading: false,
  };
}

// ── Build: scatter (value X vs value Y, one point per component / group) ─────

export interface PivotScatterResult {
  points: { x: number; y: number; label: string; color: string }[];
  xUnit: string;
  yUnit: string;
  loading: boolean;
}

/** One reduced value per component for an attribute (series reduced over the
 *  window, static/input read directly). `loading` when a needed series sheet
 *  isn't hydrated. */
function perComponentValues(
  sheet: string, attr: string, config: PivotChartConfig,
  results: RunResults | null, model: WorkbookModel, weight: number,
): { values: Record<string, number>; loading: boolean } {
  const kind = pivotValueKind(sheet, attr);
  const compList = getComponentSchema(sheet)?.list_name ?? sheet;
  const dims = indexByName(model[sheet] ?? []);
  const out: Record<string, number> = {};
  if (kind === 'series') {
    const seriesRows = results?.outputs?.series?.[`${compList}-${attr}`];
    if (!seriesRows || !seriesRows.length) return { values: out, loading: true };
    const start = Math.max(0, config.startIndex);
    const end = Math.min(config.endIndex, seriesRows.length - 1);
    const cols = new Map<string, number[]>();
    for (const srow of seriesRows.slice(start, end + 1)) {
      for (const col of componentColumns(srow)) (cols.get(col) ?? cols.set(col, []).get(col)!).push(numberValue(srow[col]));
    }
    cols.forEach((vals, col) => { out[col] = bucketReduce(vals, config.aggregate, weight); });
  } else {
    const staticVals = results?.outputs?.static?.[compList] ?? {};
    for (const [name, dim] of Object.entries(dims)) {
      out[name] = kind === 'static'
        ? numberValue((staticVals[name] as Record<string, Primitive> | undefined)?.[attr])
        : numberValue(dim[attr]);
    }
  }
  return { values: out, loading: false };
}

export function buildPivotScatter(
  config: PivotChartConfig,
  results: RunResults | null,
  model: WorkbookModel,
  snapshotWeight = 1,
): PivotScatterResult {
  const xUnit = getAttributeSchema(config.sheet, config.valueAttribute)?.unit ?? '';
  const yAttr = config.scatterYAttribute;
  const yUnit = yAttr ? getAttributeSchema(config.sheet, yAttr)?.unit ?? '' : '';
  if (!yAttr) return { points: [], xUnit, yUnit, loading: false };

  const xRes = perComponentValues(config.sheet, config.valueAttribute, config, results, model, snapshotWeight);
  const yRes = perComponentValues(config.sheet, yAttr, config, results, model, snapshotWeight);
  if (xRes.loading || yRes.loading) return { points: [], xUnit, yUnit, loading: true };

  const dims = indexByName(model[config.sheet] ?? []);
  const grouped = config.groupBy.length > 0;
  const acc = new Map<string, { x: number; y: number; dim: GridRow }>();
  for (const [name, dim] of Object.entries(dims)) {
    if (!passComponentFilters(dim, config.filters)) continue;
    if (!(name in xRes.values) || !(name in yRes.values)) continue;
    const key = grouped ? groupKeyOf(dim, name, config.groupBy) : name;
    const cur = acc.get(key) ?? { x: 0, y: 0, dim };
    cur.x += xRes.values[name];
    cur.y += yRes.values[name];
    acc.set(key, cur);
  }
  const points = Array.from(acc.entries()).map(([label, p]) => ({ x: p.x, y: p.y, label, color: colorFor(label, config.groupBy) }));
  return { points, xUnit, yUnit, loading: false };
}

// ── Build: duration curve (series values ranked descending, PER GROUP) ───────

export interface PivotDurationSeries { key: string; label: string; color: string; values: number[] }
export interface PivotDurationResult { series: PivotDurationSeries[]; unit: string; loading: boolean }

/** One duration curve per group (carrier, bus, …) — each group's own
 *  per-snapshot values sorted descending independently, not pooled into a
 *  single ranking across groups (that would mix e.g. wind and solar hours
 *  into one meaningless curve). */
export function buildPivotDurationCurve(
  config: PivotChartConfig,
  results: RunResults | null,
  model: WorkbookModel,
  snapshotWeight = 1,
): PivotDurationResult {
  const res = buildPivotSeries({ ...config, timeframe: 'hourly' }, results, model, snapshotWeight);
  if (res.loading) return { series: [], unit: res.unit, loading: true };
  const series: PivotDurationSeries[] = res.series.map((s) => ({
    key: s.key,
    label: s.label,
    color: s.color,
    values: res.rows.map((row) => numberValue(row[s.key])).sort((a, b) => b - a),
  }));
  return { series, unit: res.unit, loading: false };
}

// ── Build: daily profile (mean by hour-of-day) ───────────────────────────────

function extractHour(ts: string | undefined): number | null {
  if (!ts) return null;
  const m = ts.match(/(\d{1,2}):(\d{2})/);
  return m ? parseInt(m[1], 10) : null;
}

export function buildPivotDailyProfile(
  config: PivotChartConfig,
  results: RunResults | null,
  model: WorkbookModel,
  snapshotWeight = 1,
): PivotSeriesResult {
  const res = buildPivotSeries({ ...config, timeframe: 'hourly' }, results, model, snapshotWeight);
  if (res.loading) return res;
  const sums: Record<string, number[]> = {};
  const counts: Record<string, number[]> = {};
  for (const s of res.series) { sums[s.key] = new Array(24).fill(0); counts[s.key] = new Array(24).fill(0); }
  for (const row of res.rows) {
    const h = extractHour(row.timestamp);
    if (h === null || h < 0 || h > 23) continue;
    for (const s of res.series) { sums[s.key][h] += numberValue(row[s.key]); counts[s.key][h] += 1; }
  }
  const rows: TimeSeriesRow[] = Array.from({ length: 24 }, (_, h) => {
    const row: TimeSeriesRow = { label: `${h}:00`, timestamp: undefined };
    for (const s of res.series) row[s.key] = counts[s.key][h] ? sums[s.key][h] / counts[s.key][h] : 0;
    return row;
  });
  return { rows, series: res.series, unit: res.unit, loading: false };
}
