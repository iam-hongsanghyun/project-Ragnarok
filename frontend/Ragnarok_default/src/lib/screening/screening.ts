/**
 * Siting screening — pure data shaping for the Screening step (no React, no I/O).
 *
 * The backend computes every statistic; this module only reorders, colours and
 * packs what it returned into chart options and table rows, and parses the few
 * free-text controls (season mapping, month list). Unit tested in screening.test.ts.
 */
import type { EChartsCoreOption } from 'echarts/core';
import {
  HOVER_SHADOW,
  axisDataZoom,
  axisName,
  chartToolbox,
  dashedSplitLine,
  darkTooltip,
  scrollLegend,
  tickLabel,
  tooltipHeader,
  tooltipValueRow,
} from 'lib/charts/options';
import type { ChartTheme } from 'lib/charts/theme';
import type {
  DistancePair,
  DurationCurve,
  LaggedResponse,
  MetricsResponse,
  OptimiseResponse,
  ProfilesResponse,
  RegionRow,
  ScreeningSite,
  StructureResponse,
  ValidationReport,
} from 'lib/api/screening';

/**
 * What the Screening step analyses: a site, or a region series. The shared fields are all the
 * map, the tables and the portfolio need; a region may have no location (an uploaded series
 * without centroid or polygon), so `lat` / `lon` can be null.
 */
export interface ScreeningUnit {
  name: string;
  technology: string;
  /** Region label of a site; for a region unit the region itself. */
  region: string;
  meanCf?: number;
  capacityMw?: number | null;
  lat: number | null;
  lon: number | null;
}

export function siteToUnit(s: ScreeningSite): ScreeningUnit {
  return { name: s.name, technology: s.technology, region: s.region, meanCf: s.meanCf, capacityMw: s.capacityMw, lat: s.lat, lon: s.lon };
}

export function regionToUnit(r: RegionRow): ScreeningUnit {
  return { name: r.name, technology: r.technology, region: r.region, meanCf: r.meanCf, capacityMw: r.capacityMw, lat: r.lat, lon: r.lon };
}

// ── escaping (tooltips are HTML strings; site names come from the user) ──────

export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function fmt(v: number | null | undefined, digits = 2): string {
  return v === null || v === undefined || !Number.isFinite(v) ? 'n/a' : v.toFixed(digits);
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined || !Number.isFinite(v) ? 'n/a' : `${(v * 100).toFixed(digits)}%`;
}

// ── colours ──────────────────────────────────────────────────────────────────

/** Assign `palette` colours to the distinct values in first-seen order (never cycles past the palette: extras reuse the last). */
export function categoryColors(values: string[], palette: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const v of values) {
    if (!(v in out)) out[v] = palette[Math.min(Object.keys(out).length, palette.length - 1)];
  }
  return out;
}

/**
 * Diverging correlation colour: warm for negative, the brand blue for positive,
 * white-ish near zero. `null` (constant series) is neutral grey.
 */
export function correlationColor(r: number | null): string {
  if (r === null || !Number.isFinite(r)) return 'hsl(40 6% 70%)';
  const t = Math.max(-1, Math.min(1, r));
  const hue = t >= 0 ? 214 : 18;
  const sat = 20 + Math.abs(t) * 65;
  const light = 92 - Math.abs(t) * 48;
  return `hsl(${hue} ${sat}% ${light}%)`;
}

// ── matrix shaping ───────────────────────────────────────────────────────────

/** Reorder a square matrix to `order` (names missing from `sites` are dropped). */
export function reorderMatrix(
  sites: string[],
  matrix: Array<Array<number | null>>,
  order: string[],
): { sites: string[]; matrix: Array<Array<number | null>> } {
  const idx = new Map(sites.map((s, i) => [s, i] as const));
  const keep = order.filter((s) => idx.has(s));
  const rest = sites.filter((s) => !keep.includes(s));
  const names = [...keep, ...rest];
  return {
    sites: names,
    matrix: names.map((a) => names.map((b) => matrix[idx.get(a) as number][idx.get(b) as number])),
  };
}

/** The row of correlations of `focus` against every other site. */
export function focusRow(sites: string[], matrix: Array<Array<number | null>>, focus: string): Record<string, number | null> {
  const i = sites.indexOf(focus);
  const out: Record<string, number | null> = {};
  if (i < 0) return out;
  sites.forEach((s, j) => {
    if (j !== i) out[s] = matrix[i][j];
  });
  return out;
}

/** Heatmap cells `[x, y, r]`; y is reversed so the first site sits on top. */
export function heatmapCells(matrix: Array<Array<number | null>>): Array<[number, number, number | null]> {
  const n = matrix.length;
  const cells: Array<[number, number, number | null]> = [];
  for (let row = 0; row < n; row++) {
    for (let col = 0; col < n; col++) cells.push([col, n - 1 - row, matrix[row][col]]);
  }
  return cells;
}

export type PairKind = string;

/** Label of a pair by technology, order-independent ("solar - wind"). */
export function pairKind(a: Pick<ScreeningUnit, 'technology'> | undefined, b: Pick<ScreeningUnit, 'technology'> | undefined): PairKind {
  const ta = a?.technology ?? 'other';
  const tb = b?.technology ?? 'other';
  return ta <= tb ? `${ta} - ${tb}` : `${tb} - ${ta}`;
}

/** Group distance pairs by technology pair for the scatter's legend. */
export function groupPairs(pairs: DistancePair[], sites: ScreeningUnit[]): Record<PairKind, DistancePair[]> {
  const byName = new Map(sites.map((s) => [s.name, s] as const));
  const out: Record<PairKind, DistancePair[]> = {};
  for (const p of pairs) {
    if (p.r === null) continue;
    (out[pairKind(byName.get(p.a), byName.get(p.b))] ||= []).push(p);
  }
  return out;
}

// ── portfolio weights ────────────────────────────────────────────────────────

export function equalWeights(names: string[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const n of names) out[n] = names.length ? 1 / names.length : 0;
  return out;
}

/** Scale to sum 1; drops non-positive entries. Returns {} when nothing is positive. */
export function normaliseWeights(weights: Record<string, number>): Record<string, number> {
  const pos = Object.entries(weights).filter(([, w]) => Number.isFinite(w) && w > 0);
  const total = pos.reduce((a, [, w]) => a + w, 0);
  if (total <= 0) return {};
  return Object.fromEntries(pos.map(([k, w]) => [k, w / total]));
}

// ── free-text controls ───────────────────────────────────────────────────────

/** "6,7,8" or "6-8, 12" -> sorted unique months 1-12; throws on anything else. */
export function parseMonths(text: string): number[] {
  const out = new Set<number>();
  for (const part of text.split(',').map((p) => p.trim()).filter(Boolean)) {
    const range = /^(\d{1,2})\s*-\s*(\d{1,2})$/.exec(part);
    const [lo, hi] = range ? [Number(range[1]), Number(range[2])] : [Number(part), Number(part)];
    if (!Number.isInteger(lo) || !Number.isInteger(hi) || lo < 1 || hi > 12 || lo > hi) {
      throw new Error(`"${part}" is not a month (1-12) or a range like 6-8.`);
    }
    for (let m = lo; m <= hi; m++) out.add(m);
  }
  return Array.from(out).sort((a, b) => a - b);
}

/**
 * "wet:6-9; dry:12,1,2" -> {"6":"wet",...,"12":"dry"}. A month may belong to one season only.
 * Empty text returns undefined (the backend then uses DJF/MAM/JJA/SON).
 */
export function parseSeasonMap(text: string): Record<string, string> | undefined {
  const trimmed = text.trim();
  if (!trimmed) return undefined;
  const out: Record<string, string> = {};
  for (const block of trimmed.split(';').map((b) => b.trim()).filter(Boolean)) {
    const [label, months] = block.split(':').map((p) => p.trim());
    if (!label || months === undefined) throw new Error(`"${block}" should look like name:months, e.g. wet:6-9.`);
    for (const m of parseMonths(months)) {
      if (String(m) in out) throw new Error(`Month ${m} is in both "${out[String(m)]}" and "${label}".`);
      out[String(m)] = label;
    }
  }
  return out;
}

// ── validation report ────────────────────────────────────────────────────────

export interface GapRow {
  site: string;
  missingSteps: number;
  runs: number;
  longestRunSteps: number;
  firstFrom: string;
}

/** Gap rows of a report, worst site first. */
export function gapRows(report: ValidationReport | undefined): GapRow[] {
  const by = report?.gaps?.bySite ?? {};
  return Object.entries(by)
    .map(([site, g]) => ({
      site,
      missingSteps: g.missingSteps,
      runs: g.runs,
      longestRunSteps: g.longestRunSteps,
      firstFrom: g.first[0]?.from ?? '',
    }))
    .sort((a, b) => b.missingSteps - a.missingSteps);
}

// ── chart options ────────────────────────────────────────────────────────────

const GRID = { left: 8, right: 16, top: 36, bottom: 30, containLabel: true };
/** Grid that leaves a second row, under the title, for the legend. */
const GRID_LEGEND = { ...GRID, top: 60 };
/** Legend on its own row under the title so long site lists never run into the title or the toolbox. */
function legendRow(theme: ChartTheme): Record<string, unknown> {
  return scrollLegend(theme, { top: 24, left: 4, right: 90 });
}

function baseOption(theme: ChartTheme, title: string): Record<string, unknown> {
  return {
    animation: true,
    animationDuration: 250,
    animationDurationUpdate: 200,
    toolbox: chartToolbox(theme, title),
    title: { text: title, left: 4, top: 2, textStyle: axisName(theme) },
  };
}

/** Correlation heatmap with hover values; the visual map slider filters the r range. */
export function buildHeatmapOption(
  sites: string[],
  matrix: Array<Array<number | null>>,
  theme: ChartTheme,
  title = 'Correlation',
): EChartsCoreOption {
  const n = sites.length;
  const cells = heatmapCells(matrix).map(([x, y, r]) => ({ value: [x, y, r] as [number, number, number | null] }));
  const rows = [...sites].reverse();
  const labelOn = n <= 24;
  return {
    ...baseOption(theme, title),
    grid: { left: 8, right: 64, top: 36, bottom: 8, containLabel: true },
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'item',
      formatter: (p: { value: [number, number, number | null] }) => {
        const [x, y, r] = p.value;
        return (
          tooltipHeader(`${escapeHtml(rows[y] ?? '')} / ${escapeHtml(sites[x] ?? '')}`)
          + tooltipValueRow(theme, undefined, fmt(r, 3), 'correlation')
        );
      },
    },
    xAxis: {
      type: 'category', data: sites, position: 'top', splitArea: { show: false },
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { ...tickLabel(theme), interval: 0, rotate: 45 },
    },
    yAxis: {
      type: 'category', data: rows,
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { ...tickLabel(theme), interval: 0 },
    },
    visualMap: {
      type: 'continuous', min: -1, max: 1, calculable: true, orient: 'vertical', right: 0, top: 36, bottom: 8,
      itemWidth: 12, textStyle: tickLabel(theme),
      // zrender parses comma-form colours only: hsl(h s% l%) renders black, so these are hex.
      inRange: { color: ['#d2501a', '#efeee9', '#1a64d0'] },
      outOfRange: { color: theme.grid },
    },
    series: [{
      type: 'heatmap',
      data: cells,
      label: { show: labelOn, formatter: (p: { value: [number, number, number | null] }) => fmt(p.value[2], 2), fontSize: 10, color: theme.text },
      emphasis: { itemStyle: { ...HOVER_SHADOW, borderColor: theme.text, borderWidth: 1 } },
      itemStyle: { borderColor: '#fcfcfb', borderWidth: 1 },
    }],
  };
}

/** Pairwise correlation against distance, one legend entry per technology pair; zoomable on both axes. */
export function buildDistanceScatterOption(
  groups: Record<PairKind, DistancePair[]>,
  colors: Record<PairKind, string>,
  theme: ChartTheme,
  title = 'Correlation vs distance',
): EChartsCoreOption {
  const kinds = Object.keys(groups);
  return {
    ...baseOption(theme, title),
    grid: kinds.length > 1 ? GRID_LEGEND : GRID,
    legend: kinds.length > 1 ? legendRow(theme) : undefined,
    dataZoom: [
      { type: 'inside', xAxisIndex: 0 }, { type: 'inside', yAxisIndex: 0 },
    ],
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'item',
      formatter: (p: { data: { value: [number, number]; pair: string }; seriesName: string }) =>
        tooltipHeader(escapeHtml(p.data.pair))
        + tooltipValueRow(theme, undefined, `${Math.round(p.data.value[0]).toLocaleString()} km`, 'distance')
        + tooltipValueRow(theme, undefined, fmt(p.data.value[1], 3), `r (${escapeHtml(p.seriesName)})`),
    },
    xAxis: {
      type: 'value', name: 'Distance (km)', nameLocation: 'middle', nameGap: 24, nameTextStyle: axisName(theme),
      scale: true, axisLine: { show: false }, axisTick: { show: false }, splitLine: dashedSplitLine(theme),
      axisLabel: tickLabel(theme),
    },
    yAxis: {
      type: 'value', name: 'Correlation', nameLocation: 'middle', nameGap: 36, nameTextStyle: axisName(theme),
      min: -1, max: 1, axisLine: { show: false }, axisTick: { show: false }, splitLine: dashedSplitLine(theme),
      axisLabel: tickLabel(theme),
    },
    series: kinds.map((k) => ({
      type: 'scatter', name: k, symbolSize: 9,
      itemStyle: { color: colors[k], opacity: 0.85 },
      emphasis: { scale: 1.4, itemStyle: HOVER_SHADOW },
      data: groups[k].map((p) => ({ value: [p.km, p.r], pair: `${p.a} / ${p.b}` })),
    })),
  };
}

export type ProfileView = 'diurnal' | 'monthly' | 'seasonal' | 'timeseries';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Profile lines per site for the chosen view; legend toggles sites, the time series is zoomable. */
export function buildProfileOption(
  profiles: ProfilesResponse,
  view: ProfileView,
  sites: string[],
  colors: Record<string, string>,
  theme: ChartTheme,
): EChartsCoreOption {
  let labels: string[] = [];
  let series: Record<string, Array<number | null>> = {};
  let title = '';
  if (view === 'diurnal') {
    labels = profiles.diurnal.hours.map((h) => `${String(h).padStart(2, '0')}:00`);
    series = profiles.diurnal.series;
    title = 'Diurnal profile (mean CF by hour of day)';
  } else if (view === 'monthly') {
    labels = profiles.monthly.months.map((m) => MONTH_NAMES[m - 1] ?? String(m));
    series = profiles.monthly.series;
    title = 'Seasonal profile (mean CF by month)';
  } else if (view === 'seasonal') {
    labels = profiles.seasonal.labels;
    series = profiles.seasonal.series;
    title = 'Mean CF by season';
  } else {
    labels = profiles.timeseries?.timestamps ?? [];
    series = profiles.timeseries?.series ?? {};
    title = 'Capacity factor over time (down-sampled mean)';
  }
  const shown = sites.filter((s) => s in series);
  const zoomable = view === 'timeseries';
  return {
    ...baseOption(theme, title),
    grid: { ...(shown.length > 1 ? GRID_LEGEND : GRID), bottom: zoomable ? 44 : 30 },
    legend: shown.length > 1 ? legendRow(theme) : undefined,
    dataZoom: zoomable ? axisDataZoom(theme, 'x') : undefined,
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: theme.axis, type: [4, 3] } },
      formatter: (params: Array<{ axisValueLabel?: string; seriesName?: string; value: number | null; marker?: string }>) => {
        if (!params.length) return '';
        return tooltipHeader(escapeHtml(String(params[0].axisValueLabel ?? '')))
          + params.map((p) => tooltipValueRow(theme, p.marker, fmt(p.value, 3), escapeHtml(p.seriesName ?? ''))).join('');
      },
    },
    xAxis: {
      type: 'category', data: labels, boundaryGap: view !== 'diurnal' && view !== 'timeseries',
      axisLine: { show: false }, axisTick: { show: false }, axisLabel: { ...tickLabel(theme), hideOverlap: true },
    },
    yAxis: {
      type: 'value', name: 'Capacity factor', nameLocation: 'middle', nameGap: 38, nameTextStyle: axisName(theme),
      min: 0, axisLine: { show: false }, axisTick: { show: false }, splitLine: dashedSplitLine(theme), axisLabel: tickLabel(theme),
    },
    series: shown.map((s) => ({
      type: 'line', name: s, data: series[s], showSymbol: view !== 'timeseries', symbolSize: 5, smooth: false,
      lineStyle: { width: view === 'timeseries' ? 1.2 : 2, color: colors[s] }, itemStyle: { color: colors[s] },
      emphasis: { focus: 'series' },
    })),
  };
}

/** Output duration curve of the portfolio (bold) and, toggleable in the legend, each site. */
export function buildDurationOption(
  curves: MetricsResponse['durationCurve'],
  colors: Record<string, string>,
  theme: ChartTheme,
): EChartsCoreOption {
  const mk = (name: string, c: DurationCurve, color: string, width: number) => ({
    type: 'line', name, data: c.x.map((x, i) => [x, c.y[i]]), showSymbol: false,
    lineStyle: { width, color }, itemStyle: { color }, emphasis: { focus: 'series' },
    areaStyle: name === 'Portfolio' ? { opacity: 0.12, color } : undefined,
    z: name === 'Portfolio' ? 5 : 2,
  });
  const siteNames = Object.keys(curves.sites);
  const selected: Record<string, boolean> = { Portfolio: true };
  siteNames.forEach((s) => { selected[s] = false; });
  return {
    ...baseOption(theme, 'Combined output duration curve'),
    grid: { ...GRID_LEGEND, bottom: 44 },
    legend: { ...legendRow(theme), selected },
    dataZoom: axisDataZoom(theme, 'x'),
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: theme.axis, type: [4, 3] } },
      formatter: (params: Array<{ value: [number, number]; seriesName?: string; marker?: string }>) => {
        if (!params.length) return '';
        return tooltipHeader(`Exceeded ${params[0].value[0].toFixed(1)}% of the time`)
          + params.map((p) => tooltipValueRow(theme, p.marker, fmt(p.value[1], 3), escapeHtml(p.seriesName ?? ''))).join('');
      },
    },
    xAxis: {
      type: 'value', min: 0, max: 100, name: 'Share of time exceeded', nameLocation: 'middle', nameGap: 24,
      nameTextStyle: axisName(theme), axisLine: { show: false }, axisTick: { show: false },
      splitLine: { show: false }, axisLabel: { ...tickLabel(theme), formatter: '{value}%' },
    },
    yAxis: {
      type: 'value', min: 0, name: 'Output (CF)', nameLocation: 'middle', nameGap: 36, nameTextStyle: axisName(theme),
      axisLine: { show: false }, axisTick: { show: false }, splitLine: dashedSplitLine(theme), axisLabel: tickLabel(theme),
    },
    series: [
      mk('Portfolio', curves.portfolio, theme.text, 2.4),
      ...siteNames.map((s) => mk(s, curves.sites[s], colors[s] ?? theme.muted, 1.2)),
    ],
  };
}

/** Efficient frontier (mean CF vs std) with each site and the chosen portfolio marked. */
export function buildFrontierOption(
  opt: OptimiseResponse,
  perSite: Array<{ site: string; meanCf: number; std: number }>,
  colors: Record<string, string>,
  theme: ChartTheme,
): EChartsCoreOption {
  return {
    ...baseOption(theme, 'Risk / return (std of CF vs mean CF)'),
    grid: GRID_LEGEND,
    legend: legendRow(theme),
    dataZoom: [{ type: 'inside', xAxisIndex: 0 }, { type: 'inside', yAxisIndex: 0 }],
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'item',
      formatter: (p: { seriesName: string; data: { value: [number, number]; name?: string } }) =>
        tooltipHeader(escapeHtml(p.data.name ?? p.seriesName))
        + tooltipValueRow(theme, undefined, fmt(p.data.value[1], 3), 'mean CF')
        + tooltipValueRow(theme, undefined, fmt(p.data.value[0], 3), 'std'),
    },
    xAxis: {
      type: 'value', name: 'Std of CF', nameLocation: 'middle', nameGap: 24, nameTextStyle: axisName(theme), scale: true,
      axisLine: { show: false }, axisTick: { show: false }, splitLine: dashedSplitLine(theme), axisLabel: tickLabel(theme),
    },
    yAxis: {
      type: 'value', name: 'Mean CF', nameLocation: 'middle', nameGap: 36, nameTextStyle: axisName(theme), scale: true,
      axisLine: { show: false }, axisTick: { show: false }, splitLine: dashedSplitLine(theme), axisLabel: tickLabel(theme),
    },
    series: [
      {
        type: 'line', name: 'Efficient frontier', showSymbol: true, symbolSize: 5, lineStyle: { width: 1.5, color: theme.axis },
        itemStyle: { color: theme.axis }, data: opt.frontier.map((p) => ({ value: [p.std, p.meanCf] })),
      },
      {
        type: 'scatter', name: 'Sites', symbolSize: 9,
        data: perSite.map((s) => ({ value: [s.std, s.meanCf], name: s.site, itemStyle: { color: colors[s.site] } })),
        emphasis: { scale: 1.4, itemStyle: HOVER_SHADOW },
      },
      {
        type: 'scatter', name: 'Optimised portfolio', symbol: 'diamond', symbolSize: 14, itemStyle: { color: theme.danger },
        data: [{ value: [opt.std, opt.meanCf], name: 'Optimised portfolio' }],
      },
    ],
  };
}

/** Lagged cross-correlation of one site against the others, one line per other site. */
export function buildLaggedOption(
  lagged: LaggedResponse,
  colors: Record<string, string>,
  theme: ChartTheme,
): EChartsCoreOption {
  const others = Object.keys(lagged.series);
  return {
    ...baseOption(theme, `Lagged correlation from ${lagged.site}`),
    grid: { ...(others.length > 1 ? GRID_LEGEND : GRID), bottom: 44 },
    legend: others.length > 1 ? legendRow(theme) : undefined,
    dataZoom: axisDataZoom(theme, 'x'),
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: theme.axis, type: [4, 3] } },
      formatter: (params: Array<{ axisValueLabel?: string; seriesName?: string; value: [number, number | null]; marker?: string }>) => {
        if (!params.length) return '';
        return tooltipHeader(`Lag ${params[0].axisValueLabel ?? ''} h`)
          + params.map((p) => tooltipValueRow(theme, p.marker, fmt(p.value[1], 3), escapeHtml(p.seriesName ?? ''))).join('');
      },
    },
    xAxis: {
      type: 'value', min: lagged.lagsHours[0], max: lagged.lagsHours[lagged.lagsHours.length - 1],
      name: 'Lag (hours; positive = other site follows)', nameLocation: 'middle', nameGap: 24, nameTextStyle: axisName(theme),
      axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: tickLabel(theme),
    },
    yAxis: {
      type: 'value', min: -1, max: 1, name: 'Correlation', nameLocation: 'middle', nameGap: 36, nameTextStyle: axisName(theme),
      axisLine: { show: false }, axisTick: { show: false }, splitLine: dashedSplitLine(theme), axisLabel: tickLabel(theme),
    },
    series: others.map((o) => ({
      type: 'line', name: o, showSymbol: false, lineStyle: { width: 1.6, color: colors[o] }, itemStyle: { color: colors[o] },
      data: lagged.lagsHours.map((h, i) => [h, lagged.series[o][i]]), emphasis: { focus: 'series' },
    })),
  };
}

/** "N1:2, N2:1" -> {N1: 2, N2: 1}; weights are non-negative numbers (they are normalised per region by the backend). */
export function parseSiteWeights(text: string): Record<string, number> | undefined {
  const trimmed = text.trim();
  if (!trimmed) return undefined;
  const out: Record<string, number> = {};
  for (const part of trimmed.split(',').map((p) => p.trim()).filter(Boolean)) {
    const at = part.lastIndexOf(':');
    const site = at > 0 ? part.slice(0, at).trim() : '';
    const w = Number(part.slice(at + 1));
    if (!site || at < 0 || !Number.isFinite(w) || w < 0) {
      throw new Error(`"${part}" should look like site:weight with a weight of at least 0, e.g. N1:2.`);
    }
    out[site] = w;
  }
  return out;
}

/** Box plot of the pairwise site correlations within each region and across each region pair. */
export function buildWithinBetweenOption(
  st: StructureResponse,
  theme: ChartTheme,
  title = 'Pairwise site correlation, within vs between regions',
): EChartsCoreOption {
  type Item = { name: string; kind: 'within' | 'between'; n: number; box: [number, number, number, number, number]; mean: number; aggregateR: number | null };
  const items: Item[] = [];
  const full = (v: number | null): v is number => v !== null && Number.isFinite(v);
  for (const w of st.within) {
    if (w.n > 0 && full(w.min) && full(w.q1) && full(w.median) && full(w.q3) && full(w.max) && full(w.mean)) {
      items.push({ name: `within ${w.region}`, kind: 'within', n: w.n, box: [w.min, w.q1, w.median, w.q3, w.max], mean: w.mean, aggregateR: null });
    }
  }
  for (const b of st.between) {
    if (b.n > 0 && full(b.min) && full(b.q1) && full(b.median) && full(b.q3) && full(b.max) && full(b.mean)) {
      items.push({ name: `${b.a} / ${b.b}`, kind: 'between', n: b.n, box: [b.min, b.q1, b.median, b.q3, b.max], mean: b.mean, aggregateR: b.aggregateR });
    }
  }
  const color = (kind: Item['kind']) => (kind === 'within' ? theme.seriesPalette[0] : theme.seriesPalette[1]);
  const names = items.map((i) => i.name);
  return {
    ...baseOption(theme, title),
    grid: { ...GRID_LEGEND, bottom: 44 },
    legend: { ...legendRow(theme), data: ['Pair distribution', 'Mean', 'Aggregated regions'] },
    dataZoom: [{ type: 'inside', yAxisIndex: 0 }],
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'item',
      formatter: (p: { dataIndex: number }) => {
        const it = items[p.dataIndex];
        if (!it) return '';
        return tooltipHeader(escapeHtml(it.name))
          + tooltipValueRow(theme, undefined, String(it.n), 'site pairs')
          + tooltipValueRow(theme, undefined, fmt(it.mean, 3), 'mean r')
          + tooltipValueRow(theme, undefined, fmt(it.box[2], 3), 'median r')
          + tooltipValueRow(theme, undefined, `${fmt(it.box[1], 2)} to ${fmt(it.box[3], 2)}`, 'quartiles')
          + tooltipValueRow(theme, undefined, `${fmt(it.box[0], 2)} to ${fmt(it.box[4], 2)}`, 'range')
          + (it.aggregateR !== null ? tooltipValueRow(theme, undefined, fmt(it.aggregateR, 3), 'aggregated regions') : '');
      },
    },
    xAxis: {
      type: 'category', data: names, boundaryGap: true,
      axisLine: { show: false }, axisTick: { show: false }, axisLabel: { ...tickLabel(theme), interval: 0, rotate: names.length > 6 ? 30 : 0 },
    },
    yAxis: {
      type: 'value', min: -1, max: 1, name: 'Correlation', nameLocation: 'middle', nameGap: 36, nameTextStyle: axisName(theme),
      axisLine: { show: false }, axisTick: { show: false }, splitLine: dashedSplitLine(theme), axisLabel: tickLabel(theme),
    },
    series: [
      {
        type: 'boxplot', name: 'Pair distribution',
        data: items.map((i) => ({ value: i.box, itemStyle: { color: color(i.kind), borderColor: theme.text, opacity: 0.8 } })),
      },
      {
        type: 'scatter', name: 'Mean', symbolSize: 8, itemStyle: { color: theme.text },
        data: items.map((i, k) => [k, i.mean]),
      },
      {
        type: 'scatter', name: 'Aggregated regions', symbol: 'diamond', symbolSize: 11, itemStyle: { color: theme.danger },
        data: items.map((i, k) => [k, i.aggregateR]),
      },
    ],
  };
}

/** "north:0.5, south:0.6" -> {north: 0.5, south: 0.6}; each cap is a total-weight share in (0, 1]. */
export function parseRegionCaps(text: string): Record<string, number> | undefined {
  const trimmed = text.trim();
  if (!trimmed) return undefined;
  const out: Record<string, number> = {};
  for (const part of trimmed.split(',').map((p) => p.trim()).filter(Boolean)) {
    const [region, value] = part.split(':').map((p) => p.trim());
    const cap = Number(value);
    if (!region || value === undefined || !Number.isFinite(cap) || cap <= 0 || cap > 1) {
      throw new Error(`"${part}" should look like region:share with a share in (0, 1], e.g. north:0.5.`);
    }
    out[region] = cap;
  }
  return out;
}

// ── hand-off to the Siting tab ───────────────────────────────────────────────

/** A screened site carried into the Siting tab (only sites that have a location). */
export interface SitingHandoffSite {
  name: string;
  technology: string;
  lat: number;
  lon: number;
  capacityMw: number | null;
}

/**
 * What "Open in Siting" carries: the selected sites, the candidate region that encloses them and the technologies they
 * use. Siting scans a grid of candidates over a region, so the region is the sites' envelope grown by `HANDOFF_MARGIN_DEG`
 * on every side (a single site, or sites on one parallel, still enclose an area); the sites themselves are shown on the
 * Siting map as the screened shortlist.
 */
export interface SitingHandoff {
  sites: SitingHandoffSite[];
  /** `[minLon, minLat, maxLon, maxLat]` (WGS84), the envelope plus the margin. */
  bbox: [number, number, number, number];
  /** The solar / wind technologies present (the scan models only these two). */
  technologies: Array<'solar' | 'wind'>;
  /** Selected units left behind because they have no coordinates (a region series, an uploaded site without lat / lon). */
  withoutLocation: string[];
}

/** Margin added around the sites' envelope, in degrees (about 28 km of latitude). */
export const HANDOFF_MARGIN_DEG = 0.25;

/** The Siting hand-off of `units`; `null` when none of them has a location. */
export function buildSitingHandoff(units: ScreeningUnit[]): SitingHandoff | null {
  const sites: SitingHandoffSite[] = [];
  const withoutLocation: string[] = [];
  for (const u of units) {
    if (u.lat === null || u.lon === null || !Number.isFinite(u.lat) || !Number.isFinite(u.lon)) {
      withoutLocation.push(u.name);
    } else {
      sites.push({ name: u.name, technology: u.technology, lat: u.lat, lon: u.lon, capacityMw: u.capacityMw ?? null });
    }
  }
  if (sites.length === 0) return null;
  const lats = sites.map((s) => s.lat);
  const lons = sites.map((s) => s.lon);
  const technologies = (['solar', 'wind'] as const).filter((t) => sites.some((s) => s.technology === t));
  return {
    sites,
    bbox: [
      Math.min(...lons) - HANDOFF_MARGIN_DEG, Math.min(...lats) - HANDOFF_MARGIN_DEG,
      Math.max(...lons) + HANDOFF_MARGIN_DEG, Math.max(...lats) + HANDOFF_MARGIN_DEG,
    ],
    technologies: [...technologies],
    withoutLocation,
  };
}
