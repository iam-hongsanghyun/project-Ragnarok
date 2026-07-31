/**
 * Pure ECharts option builders for every migrated chart. React-free so the
 * shapes can be unit-tested directly (options.test.ts); components pass the
 * resolved ChartTheme in and hand the returned option to useEChart.
 *
 * Conventions shared by all builders (the "Ragnarok look", 2026-07 redesign):
 *   - hairline grid lines (--chart-grid) and axis lines (--chart-axis) —
 *     recessive chrome that never competes with data
 *   - near-black tooltip (--chart-tooltip-bg / --chart-tooltip-text), 8px
 *     radius, 12.5px type; every tooltip leads with the (bold) value and
 *     follows with the (secondary) series/point name
 *   - animations on (250ms in, 200ms on update) — this is a dashboard people
 *     interact with, not a print plate
 *   - real interactivity: dataZoom (inside + slider) on every zoomable
 *     time/category axis, a compact top-right toolbox (zoom toggle, restore,
 *     save-as-image) on the chart families that benefit from it, and a
 *     functional scroll legend whenever a chart carries >= 2 series
 *   - numbers formatted with toLocaleString, units in axis names / tooltips
 *   - generic series (no domain colour of their own) are assigned the
 *     validated --series-1..8 palette in order; charts coloured by a domain
 *     dimension (energy carrier, etc.) always keep the colour the caller
 *     already supplied
 */
import type { EChartsCoreOption } from 'echarts/core';
import { ChartMode, MeritOrderEntry, MixItem, TimeSeriesRow, TimeSeriesSeries } from 'lib/types';
import type { FreqCurve } from 'lib/physicalRisk/types';
import { numberValue } from 'lib/utils/helpers';
import type { ChartTheme } from './theme';

const CHAR_PX = 6.6; // approximate glyph width of the 11px tick font

/** Page/panel surface — used behind exported PNGs and dataZoom chrome so
 *  charts stay legible against the app's paper background rather than a
 *  transparent (browser-default-white) one. */
const SURFACE = '#fcfcfb';

/** A soft "lifted" hover shadow — reuses the same ink tone as `--shadow` in
 *  _tokens.css rather than inventing a new hue. */
const HOVER_SHADOW = { shadowBlur: 6, shadowColor: 'rgba(28, 27, 23, 0.18)' };

/**
 * Max over an array WITHOUT spreading into `Math.max`. Spreading a large array
 * (`Math.max(1, ...arr)`) passes every element as a function argument and
 * overflows the call stack at ~10⁵ items — a per-asset time-series chart can
 * have far more points than that (assets × snapshots). Reduce instead.
 */
function maxOf(nums: ArrayLike<number>, seed = 1): number {
  let m = seed;
  for (let i = 0; i < nums.length; i++) {
    const n = nums[i];
    if (n > m) m = n;
  }
  return m;
}

export function fmtNum(v: number | string): string {
  const n = typeof v === 'number' ? v : Number(v);
  if (!Number.isFinite(n)) return '—';
  return Math.round(n).toLocaleString();
}

/** Slug a chart title into a filesystem-safe `saveAsImage` file name. */
function slug(title: string): string {
  return title.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'chart';
}

/** Shared dark tooltip chrome. */
export function darkTooltip(theme: ChartTheme): Record<string, unknown> {
  return {
    backgroundColor: theme.tooltipBg,
    borderWidth: 0,
    confine: true,
    textStyle: { color: theme.tooltipText, fontSize: 12.5, fontFamily: theme.fontSans },
    extraCssText: 'border-radius: 8px; box-shadow: none; padding: 8px 10px;',
  };
}

/** Shared tick-label style. */
export function tickLabel(theme: ChartTheme): Record<string, unknown> {
  return { color: theme.muted, fontSize: 11, fontFamily: theme.fontSans };
}

/** Shared axis-name (title) style — matches the old .chart-axis-title. */
export function axisName(theme: ChartTheme): Record<string, unknown> {
  return { color: theme.muted, fontSize: 11, fontWeight: 600, fontFamily: theme.fontSans };
}

function dashedSplitLine(theme: ChartTheme): Record<string, unknown> {
  return { show: true, lineStyle: { color: theme.grid, type: [4, 6] } };
}

/** Recessive axis line — `--chart-axis`, one step darker than the grid. */
function axisLine(theme: ChartTheme): Record<string, unknown> {
  return { lineStyle: { color: theme.axis } };
}

/** One line of a restyled tooltip: the value leads (bold, tooltip-text
 *  colour), the series/point name follows in a muted secondary tone. `value`
 *  is the already-formatted display string (number + unit baked in). */
function tooltipValueRow(theme: ChartTheme, marker: string | undefined, value: string, name: string): string {
  return `<div style="display:flex;align-items:baseline;gap:6px;white-space:nowrap;">`
    + `<span style="font-weight:600;color:${theme.tooltipText};">${value}</span>`
    + `<span style="opacity:.68;">${marker ?? ''}${name}</span>`
    + `</div>`;
}

/** Muted header row for a multi-series axis tooltip (the hovered X value). */
function tooltipHeader(label: string): string {
  return `<div style="opacity:.6;margin-bottom:4px;">${label}</div>`;
}

interface AxisTooltipParam {
  axisValueLabel?: string;
  name?: string;
  seriesName?: string;
  value: number | string | (number | string)[];
  marker?: string;
}

/** Compact top-right toolbox — dataZoom toggle, restore, save-as-image —
 *  shared by every chart family that benefits from export/zoom. */
function chartToolbox(theme: ChartTheme, title: string): Record<string, unknown> {
  return {
    show: true,
    top: 0,
    right: 4,
    itemSize: 13,
    itemGap: 8,
    iconStyle: { borderColor: theme.muted },
    emphasis: { iconStyle: { borderColor: theme.text } },
    feature: {
      dataZoom: { show: true, title: { zoom: 'Zoom', back: 'Reset zoom' } },
      restore: { show: true, title: 'Restore' },
      saveAsImage: { show: true, name: slug(title), backgroundColor: SURFACE, title: 'Save as image' },
    },
  };
}

/** Inside (wheel/drag) + slider dataZoom pair on one axis, styled to match
 *  the recessive grid/axis chrome tokens. */
function axisDataZoom(theme: ChartTheme, axis: 'x' | 'y'): Record<string, unknown>[] {
  const key = axis === 'x' ? 'xAxisIndex' : 'yAxisIndex';
  const sliderChrome = {
    borderColor: theme.grid,
    backgroundColor: SURFACE,
    fillerColor: theme.grid,
    handleStyle: { color: SURFACE, borderColor: theme.axis },
    moveHandleStyle: { color: theme.axis },
    dataBackground: { lineStyle: { color: theme.axis }, areaStyle: { color: theme.grid } },
    selectedDataBackground: { lineStyle: { color: theme.axis }, areaStyle: { color: theme.grid } },
    textStyle: { color: theme.muted, fontSize: 10, fontFamily: theme.fontSans },
  };
  if (axis === 'x') {
    return [
      { type: 'inside', [key]: 0 },
      { type: 'slider', [key]: 0, height: 16, bottom: 4, ...sliderChrome },
    ];
  }
  return [
    { type: 'inside', [key]: 0 },
    { type: 'slider', [key]: 0, orient: 'vertical', width: 16, right: 4, ...sliderChrome },
  ];
}

/** Functional, togglable scroll legend — only ever used when a chart carries
 *  >= 2 series (single-series charts get no legend). */
function scrollLegend(theme: ChartTheme, pos: { top?: number | string; left?: number | string; right?: number | string; bottom?: number | string }): Record<string, unknown> {
  return {
    type: 'scroll',
    icon: 'roundRect',
    itemWidth: 12,
    itemHeight: 8,
    textStyle: tickLabel(theme),
    pageIconColor: theme.axis,
    pageIconInactiveColor: theme.grid,
    pageTextStyle: { color: theme.muted, fontSize: 10, fontFamily: theme.fontSans },
    ...pos,
  };
}

// ── Time series (line / area / bar, stacked or not) ──────────────────────────

export interface TimeSeriesOptionInput {
  /** Pre-formatted category labels, one per row (ISO date convention). */
  xLabels: string[];
  rows: TimeSeriesRow[];
  series: TimeSeriesSeries[];
  mode: ChartMode;
  stacked: boolean;
  xAxisTitle?: string;
  yAxisTitle?: string;
  showAxisLabels: boolean;
  /** Degrees, 0 / -30 / -45 / -90 as stored in ChartSectionConfig. */
  xLabelAngle: number;
  theme: ChartTheme;
  /** Chart title, used only to name the toolbox's saveAsImage export. */
  title?: string;
  /** Suppress the functional legend even when there are >= 2 series (default
   *  true — shown). Never used to force a legend onto a single series. */
  showLegend?: boolean;
}

export function buildTimeSeriesOption(input: TimeSeriesOptionInput): EChartsCoreOption {
  const {
    xLabels, rows, series, mode, stacked,
    xAxisTitle, yAxisTitle, showAxisLabels, xLabelAngle, theme, title, showLegend = true,
  } = input;

  const values = series.map((s) => rows.map((r) => numberValue(r[s.key] as string | number | undefined)));
  const multi = series.length > 1;

  // Budget the y-axis name gap from the widest plausible tick label so the
  // rotated name clears the tick column (containLabel only covers the ticks).
  let maxAbs = 1;
  for (const sv of values) for (const v of sv) { const a = Math.abs(v); if (a > maxAbs) maxAbs = a; }
  const yLabelPx = (fmtNum(maxAbs).length + 1) * CHAR_PX;
  const maxXLabelPx = maxOf(xLabels.map((l) => l.length)) * CHAR_PX;
  const rad = (Math.abs(xLabelAngle) * Math.PI) / 180;

  const echartsSeries = series.map((s, i) => {
    const base = {
      name: s.label,
      data: values[i],
      stack: stacked ? 'total' : undefined,
      // Rounds every segment's value-end corners; on a stacked bar the inner
      // seams get a barely-visible 4px round too — cheaper than tracking
      // which series is topmost per category, and visually negligible.
      itemStyle: { color: s.color, borderRadius: [4, 4, 0, 0] as number[] },
      emphasis: { focus: multi ? ('series' as const) : ('none' as const), itemStyle: HOVER_SHADOW },
    };
    if (mode === 'bar') {
      return { ...base, type: 'bar' as const, barMaxWidth: 40, barGap: '30%' };
    }
    return {
      ...base,
      type: 'line' as const,
      showSymbol: false,
      symbolSize: 8,
      lineStyle: { width: 2, color: s.color },
      areaStyle: mode === 'area' ? { opacity: stacked ? 0.72 : 0.24 } : undefined,
    };
  });

  return {
    animation: true,
    animationDuration: 250,
    animationDurationUpdate: 200,
    grid: {
      left: yAxisTitle ? 22 : 8,
      right: 16,
      top: 36,
      bottom: xAxisTitle ? 46 : 28,
      containLabel: true,
    },
    toolbox: chartToolbox(theme, title ?? xAxisTitle ?? 'time-series'),
    dataZoom: axisDataZoom(theme, 'x'),
    legend: multi && showLegend ? scrollLegend(theme, { top: 0, left: 0, right: 74 }) : undefined,
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'axis',
      axisPointer: mode === 'bar'
        ? { type: 'shadow' }
        : { type: 'line', lineStyle: { color: theme.axis, type: [4, 3] } },
      formatter: (params: AxisTooltipParam[]) => {
        if (!params.length) return '';
        const header = tooltipHeader(String(params[0].axisValueLabel ?? params[0].name ?? ''));
        const rows2 = params.map((p) => tooltipValueRow(
          theme, p.marker,
          `${fmtNum(p.value as number)}${yAxisTitle ? ` ${yAxisTitle}` : ''}`,
          p.seriesName ?? '',
        ));
        return header + rows2.join('');
      },
    },
    xAxis: {
      type: 'category',
      boundaryGap: mode === 'bar',
      data: xLabels,
      name: xAxisTitle,
      nameLocation: 'middle',
      nameGap: (showAxisLabels ? Math.ceil(Math.sin(rad) * maxXLabelPx) + 24 : 14),
      nameTextStyle: axisName(theme),
      axisLine: axisLine(theme),
      axisTick: { show: false },
      axisLabel: {
        ...tickLabel(theme),
        show: showAxisLabels,
        rotate: Math.abs(xLabelAngle),
        hideOverlap: true,
      },
    },
    yAxis: {
      type: 'value',
      name: yAxisTitle,
      nameLocation: 'middle',
      nameGap: yLabelPx + 14,
      nameTextStyle: axisName(theme),
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: dashedSplitLine(theme),
      axisLabel: { ...tickLabel(theme), show: showAxisLabels, formatter: fmtNum },
    },
    series: echartsSeries,
  };
}

// ── Donut ─────────────────────────────────────────────────────────────────────

export interface DonutOptionInput {
  data: MixItem[];
  unit?: string;
  theme: ChartTheme;
}

export function buildDonutOption({ data, unit, theme }: DonutOptionInput): EChartsCoreOption {
  const total = data.reduce((s, d) => s + d.value, 0);
  return {
    animation: true,
    animationDuration: 250,
    animationDurationUpdate: 200,
    title: {
      text: unit ? `Total (${unit})` : 'Total',
      subtext: fmtNum(total),
      left: 'center',
      top: '38%',
      itemGap: 4,
      textStyle: { color: theme.muted, fontSize: 13, fontWeight: 400, fontFamily: theme.fontSans },
      subtextStyle: { color: theme.text, fontSize: 16, fontWeight: 700, fontFamily: theme.fontSans },
    },
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'item',
      formatter: (params: { name: string; value: number; percent: number }) =>
        tooltipValueRow(theme, undefined, `${fmtNum(params.value)}${unit ? ` ${unit}` : ''} (${params.percent.toFixed(1)}%)`, params.name),
    },
    series: [{
      type: 'pie',
      radius: ['54%', '88%'],
      center: ['50%', '50%'],
      label: { show: false },
      itemStyle: { borderColor: SURFACE, borderWidth: 2 },
      emphasis: { scale: true, scaleSize: 4, itemStyle: HOVER_SHADOW },
      data: data.map((d) => ({ name: d.label, value: d.value, itemStyle: { color: d.color } })),
    }],
  };
}

// ── Duration curve ────────────────────────────────────────────────────────────

export interface DurationCurveSeriesInput {
  key: string;
  label: string;
  color: string;
  /** Values in rank order (already sorted descending by the caller) — this
   *  group's OWN curve, independent of every other group's ranking. */
  values: number[];
}

export interface DurationCurveOptionInput {
  series: DurationCurveSeriesInput[];
  title: string;
  unit: string;
  theme: ChartTheme;
  /** Show the per-group legend. Only meaningful with more than one series;
   *  a single curve never shows a legend. */
  showLegend?: boolean;
}

export function buildDurationCurveOption(input: DurationCurveOptionInput): EChartsCoreOption {
  const { series, title, unit, theme, showLegend } = input;
  const multi = series.length > 1;
  const echartsSeries = series.map((s) => {
    const n = Math.max(s.values.length - 1, 1);
    const points = s.values.map((v, i) => [(i / n) * 100, v]);
    return {
      name: s.label,
      type: 'line' as const,
      data: points,
      showSymbol: false,
      symbolSize: 8,
      lineStyle: { width: 2, color: s.color },
      areaStyle: multi ? undefined : { opacity: 0.15, color: s.color },
      emphasis: { focus: multi ? ('series' as const) : ('none' as const), itemStyle: HOVER_SHADOW },
    };
  });
  return {
    animation: true,
    animationDuration: 250,
    animationDurationUpdate: 200,
    title: {
      text: title,
      left: 4,
      top: 2,
      textStyle: axisName(theme),
    },
    toolbox: chartToolbox(theme, title),
    dataZoom: axisDataZoom(theme, 'x'),
    legend: multi && showLegend
      ? scrollLegend(theme, { top: 2, right: 74 })
      : undefined,
    grid: { left: 8, right: 16, top: 34, bottom: 26, containLabel: true },
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: theme.axis, type: [4, 3] } },
      formatter: (params: AxisTooltipParam[]) => {
        if (!params.length) return '';
        const pct = (params[0].value as [number, number])[0];
        const header = tooltipHeader(`Exceedance ${pct.toFixed(1)}%`);
        const rows2 = params.map((p) => tooltipValueRow(
          theme, p.marker, `${fmtNum((p.value as [number, number])[1])} ${unit}`, multi ? (p.seriesName ?? '') : '',
        ));
        return header + rows2.join('');
      },
    },
    xAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { ...tickLabel(theme), formatter: '{value}%' },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: dashedSplitLine(theme),
      axisLabel: { ...tickLabel(theme), formatter: fmtNum },
    },
    series: echartsSeries,
  };
}

// ── Merit order (supply stack) ────────────────────────────────────────────────

export interface MeritOrderOptionInput {
  entries: MeritOrderEntry[];
  /** Peak system load in MW — draws the dashed demand line. */
  systemLoad?: number;
  currencySymbol: string;
  theme: ChartTheme;
}

interface MeritDatum {
  value: [number, number, number];
  name: string;
  carrier: string;
  bus: string;
  itemStyle: { color: string; opacity: number };
}

export function buildMeritOrderOption(input: MeritOrderOptionInput): EChartsCoreOption {
  const { entries, systemLoad, currencySymbol, theme } = input;
  const totalMW = entries.reduce((s, e) => s + e.p_nom, 0);
  const demandX = systemLoad != null ? Math.min(systemLoad, totalMW) : null;

  const data: MeritDatum[] = entries.map((e) => ({
    value: [e.cumulative_mw, e.p_nom, e.marginal_cost],
    name: e.name,
    carrier: e.carrier,
    bus: e.bus,
    itemStyle: { color: e.color, opacity: 0.78 },
  }));

  return {
    animation: true,
    animationDuration: 250,
    animationDurationUpdate: 200,
    grid: { left: 26, right: 16, top: 16, bottom: 30, containLabel: true },
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'item',
      formatter: (params: { data: MeritDatum }) => {
        const d = params.data;
        return tooltipValueRow(theme, undefined, `${currencySymbol}${fmtNum(d.value[2])}/MWh`, d.name)
          + `<div style="opacity:.66;margin-top:2px;">${d.carrier} · ${d.bus} · ${fmtNum(d.value[1])} MW</div>`;
      },
    },
    xAxis: {
      type: 'value',
      min: 0,
      max: totalMW,
      name: 'Cumulative capacity (MW)',
      nameLocation: 'middle',
      nameGap: 26,
      nameTextStyle: axisName(theme),
      axisLine: axisLine(theme),
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { ...tickLabel(theme), formatter: fmtNum },
    },
    yAxis: {
      type: 'value',
      name: `Marginal cost (${currencySymbol}/MWh)`,
      nameLocation: 'middle',
      // Clear the widest tick label (e.g. "500,000" ≈ 7ch) so the rotated
      // name never overlaps the tick column.
      nameGap: (fmtNum(maxOf(entries.map((e) => e.marginal_cost))).length + 1) * CHAR_PX + 10,
      nameTextStyle: axisName(theme),
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: dashedSplitLine(theme),
      axisLabel: { ...tickLabel(theme), formatter: fmtNum },
    },
    series: [{
      type: 'custom',
      clip: true,
      // Each generator: a block from cumulative_mw to cumulative_mw + p_nom,
      // 0 up to marginal_cost — the classic supply stack.
      renderItem: (
        params: { dataIndex: number },
        api: {
          value: (i: number) => number;
          coord: (xy: [number, number]) => [number, number];
        },
      ) => {
        const topLeft = api.coord([api.value(0), api.value(2)]);
        const bottomRight = api.coord([api.value(0) + api.value(1), 0]);
        const entry = entries[params.dataIndex];
        return {
          type: 'rect',
          shape: {
            x: topLeft[0],
            y: topLeft[1],
            width: Math.max(bottomRight[0] - topLeft[0], 1),
            height: Math.max(bottomRight[1] - topLeft[1], 2),
          },
          // Literal style: api.style() is deprecated in ECharts 5.
          style: { fill: entry?.color ?? theme.muted, opacity: 0.78 },
          emphasis: { style: { opacity: 1, stroke: theme.text, lineWidth: 1 } },
        };
      },
      encode: { x: 0, y: 2 },
      data,
      markLine: demandX == null ? undefined : {
        symbol: 'none',
        animation: false,
        lineStyle: { color: theme.danger, width: 2, type: [6, 3] },
        label: {
          formatter: 'Peak load',
          position: 'insideEndTop',
          color: theme.danger,
          fontSize: 10,
          fontWeight: 600,
          fontFamily: theme.fontSans,
        },
        data: [{ xAxis: demandX }],
      },
    }],
  };
}

// ── Capacity expansion (horizontal installed-vs-optimised bars) ──────────────

export interface ExpansionRow {
  name: string;
  installed: number;
  optimised: number;
  color: string;
}

/** Rows beyond this get a vertical dataZoom (inside + slider) on the category
 *  axis — a handful of assets read fine without one. */
const MANY_EXPANSION_ROWS = 12;

export function buildExpansionOption(rows: ExpansionRow[], theme: ChartTheme, title?: string): EChartsCoreOption {
  const manyRows = rows.length > MANY_EXPANSION_ROWS;
  return {
    animation: true,
    animationDuration: 250,
    animationDurationUpdate: 200,
    grid: { left: 4, right: manyRows ? 80 : 60, top: 28, bottom: 24, containLabel: true },
    toolbox: chartToolbox(theme, title ?? 'capacity-expansion'),
    dataZoom: manyRows ? axisDataZoom(theme, 'y') : undefined,
    legend: scrollLegend(theme, { bottom: 0, left: 0 }),
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: AxisTooltipParam[]) => {
        if (!params.length) return '';
        const header = tooltipHeader(String(params[0].name ?? ''));
        const rows2 = params.map((p) => tooltipValueRow(theme, p.marker, `${fmtNum(p.value as number)} MW`, p.seriesName ?? ''));
        return header + rows2.join('');
      },
    },
    xAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: dashedSplitLine(theme),
      axisLabel: { ...tickLabel(theme), formatter: fmtNum },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: rows.map((r) => r.name),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { ...tickLabel(theme), width: 130, overflow: 'truncate' as const },
    },
    series: [
      {
        name: 'Installed',
        type: 'bar',
        barWidth: 8,
        itemStyle: { color: theme.borderStrong, borderRadius: [0, 4, 4, 0] },
        emphasis: { itemStyle: HOVER_SHADOW },
        data: rows.map((r) => r.installed),
      },
      {
        name: 'Optimised',
        type: 'bar',
        barWidth: 10,
        barGap: '10%',
        label: {
          show: true,
          position: 'right',
          formatter: (p: { value: number }) => `${fmtNum(p.value)} MW`,
          color: theme.text,
          fontSize: 10,
          fontWeight: 700,
          fontFamily: theme.fontSans,
        },
        emphasis: { itemStyle: HOVER_SHADOW },
        data: rows.map((r) => ({ value: r.optimised, itemStyle: { color: r.color, opacity: 0.85, borderRadius: [0, 4, 4, 0] } })),
      },
    ],
  };
}

// ── Category bar (horizontal / grouped / stacked) ───────────────────────────
// A generic categorical bar over `labels` with one or more `series`. Drives the
// pivot's grouped-bar and horizontal-bar types (stackable). When a single
// series carries `barColors`, each bar is coloured individually (value-by-carrier).

export interface CategorySeriesInput {
  labels: string[];
  series: { key: string; label: string; color: string; values: number[] }[];
  stacked: boolean;
  /** Per-label colours for a single-series category chart (else use series colour). */
  barColors?: string[];
  unit?: string;
  xAxisTitle?: string;
  yAxisTitle?: string;
  showAxisLabels: boolean;
  xLabelAngle?: number;
  theme: ChartTheme;
  /** Chart title, used only to name the toolbox's saveAsImage export
   *  (grouped-bar only — see `buildGroupedBarOption`). */
  title?: string;
  /** Emit the interactive (series-toggling) legend when multi-series. Set
   *  false where the host already supplies one — e.g. a shared legend across
   *  small multiples — so the card does not render two. Default true. */
  showLegend?: boolean;
}

function categoryBarSeries(input: CategorySeriesInput, orientation: 'vertical' | 'horizontal') {
  const single = input.series.length === 1 && input.barColors;
  const radius = orientation === 'vertical' ? [4, 4, 0, 0] : [0, 4, 4, 0];
  return input.series.map((s) => ({
    name: s.label,
    type: 'bar' as const,
    stack: input.stacked ? 'total' : undefined,
    barMaxWidth: 36,
    barGap: '30%',
    itemStyle: single ? { borderRadius: radius } : { color: s.color, borderRadius: radius },
    data: single
      ? s.values.map((v, i) => ({ value: v, itemStyle: { color: input.barColors![i] ?? s.color, borderRadius: radius } }))
      : s.values,
    emphasis: {
      focus: input.series.length > 1 ? ('series' as const) : ('none' as const),
      itemStyle: HOVER_SHADOW,
    },
  }));
}

/** Item-trigger tooltip for the category-bar family: the hovered mark IS the
 *  hit target (a bar, not "everything at this X"), value leading. */
function categoryBarTooltip(theme: ChartTheme, unit: string | undefined, multi: boolean) {
  return {
    ...darkTooltip(theme),
    trigger: 'item' as const,
    formatter: (p: { name?: string; seriesName?: string; value: number; marker?: string }) => {
      const label = multi && p.seriesName ? `${p.name ?? ''} · ${p.seriesName}` : (p.name ?? p.seriesName ?? '');
      return tooltipValueRow(theme, p.marker, `${fmtNum(p.value)}${unit ? ` ${unit}` : ''}`, label);
    },
  };
}

export function buildHorizontalBarOption(input: CategorySeriesInput): EChartsCoreOption {
  const { labels, theme, showAxisLabels, showLegend = true } = input;
  const multi = input.series.length > 1;
  const withLegend = multi && showLegend;
  return {
    animation: true,
    animationDuration: 250,
    animationDurationUpdate: 200,
    grid: { left: 4, right: 16, top: withLegend ? 28 : 8, bottom: 4, containLabel: true },
    legend: withLegend ? scrollLegend(theme, { top: 0, left: 0 }) : undefined,
    tooltip: categoryBarTooltip(theme, input.unit, multi),
    xAxis: {
      type: 'value',
      name: input.xAxisTitle,
      nameLocation: 'middle',
      nameGap: 24,
      nameTextStyle: axisName(theme),
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: dashedSplitLine(theme),
      axisLabel: { show: showAxisLabels, ...tickLabel(theme), formatter: fmtNum },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: labels,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { show: showAxisLabels, ...tickLabel(theme), width: 130, overflow: 'truncate' as const },
    },
    series: categoryBarSeries(input, 'horizontal'),
  };
}

export function buildGroupedBarOption(input: CategorySeriesInput): EChartsCoreOption {
  const { labels, theme, showAxisLabels, title, showLegend = true } = input;
  const multi = input.series.length > 1;
  const withLegend = multi && showLegend;
  const maxLabel = maxOf(labels.map((l) => l.length)) * CHAR_PX;
  return {
    animation: true,
    animationDuration: 250,
    animationDurationUpdate: 200,
    grid: { left: 8, right: 12, top: withLegend ? 34 : 26, bottom: 4, containLabel: true },
    toolbox: chartToolbox(theme, title ?? input.xAxisTitle ?? 'grouped-bar'),
    legend: withLegend ? scrollLegend(theme, { top: 0, left: 0, right: 74 }) : undefined,
    tooltip: categoryBarTooltip(theme, input.unit, multi),
    xAxis: {
      type: 'category',
      boundaryGap: true,
      data: labels,
      name: input.xAxisTitle,
      nameLocation: 'middle',
      nameGap: maxLabel > 40 ? 52 : 26,
      nameTextStyle: axisName(theme),
      axisLine: axisLine(theme),
      axisTick: { show: false },
      axisLabel: { show: showAxisLabels, ...tickLabel(theme), rotate: input.xLabelAngle ? Math.abs(input.xLabelAngle) : 0, hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      name: input.yAxisTitle,
      nameTextStyle: axisName(theme),
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: dashedSplitLine(theme),
      axisLabel: { show: showAxisLabels, ...tickLabel(theme), formatter: fmtNum },
    },
    series: categoryBarSeries(input, 'vertical'),
  };
}

// ── Scatter (value X vs value Y per component) ───────────────────────────────

export interface ScatterOptionInput {
  points: { x: number; y: number; label: string; color: string }[];
  xName: string;
  yName: string;
  showAxisLabels: boolean;
  theme: ChartTheme;
  /** Chart title, used only to name the toolbox's saveAsImage export. */
  title?: string;
}

export function buildScatterOption(input: ScatterOptionInput): EChartsCoreOption {
  const { points, xName, yName, showAxisLabels, theme, title } = input;
  return {
    animation: true,
    animationDuration: 250,
    animationDurationUpdate: 200,
    grid: { left: 16, right: 20, top: 34, bottom: 22, containLabel: true },
    toolbox: chartToolbox(theme, title ?? `${xName}-vs-${yName}`),
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'item',
      formatter: (p: { data: { value: [number, number]; name: string } }) =>
        `<div style="font-weight:600;color:${theme.tooltipText};margin-bottom:2px;">${p.data.name}</div>`
        + tooltipValueRow(theme, undefined, fmtNum(p.data.value[0]), xName)
        + tooltipValueRow(theme, undefined, fmtNum(p.data.value[1]), yName),
    },
    xAxis: {
      type: 'value',
      scale: true,
      name: xName,
      nameLocation: 'middle',
      nameGap: 26,
      nameTextStyle: axisName(theme),
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: dashedSplitLine(theme),
      axisLabel: { show: showAxisLabels, ...tickLabel(theme), formatter: fmtNum },
    },
    yAxis: {
      type: 'value',
      scale: true,
      name: yName,
      nameLocation: 'middle',
      nameGap: 48,
      nameTextStyle: axisName(theme),
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: dashedSplitLine(theme),
      axisLabel: { show: showAxisLabels, ...tickLabel(theme), formatter: fmtNum },
    },
    series: [{
      type: 'scatter',
      symbolSize: 10,
      emphasis: { scale: 1.4, itemStyle: HOVER_SHADOW },
      data: points.map((p) => ({ value: [p.x, p.y], name: p.label, itemStyle: { color: p.color } })),
    }],
  };
}

// ── Physical-risk charts (ported from hand-rolled SVG) ───────────────────────

export interface FreqCurveOptionInput {
  curve: FreqCurve;
  currencySymbol: string;
  theme: ChartTheme;
}

/** Return-period (exceedance) loss curve — a true log-x axis (matches the
 *  original hand-rolled SVG's log10 mapping), single series. */
export function buildFreqCurveOption({ curve, currencySymbol, theme }: FreqCurveOptionInput): EChartsCoreOption {
  const { returnPeriods, losses } = curve;
  const color = theme.seriesPalette[0];
  const data = returnPeriods.map((rp, i) => [rp, losses[i]]);
  const money = (v: number) => `${currencySymbol}${fmtNum(v)}`;
  return {
    animation: true,
    animationDuration: 250,
    animationDurationUpdate: 200,
    grid: { left: 12, right: 20, top: 34, bottom: 30, containLabel: true },
    toolbox: chartToolbox(theme, 'return-period-losses'),
    dataZoom: axisDataZoom(theme, 'x'),
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: theme.axis, type: [4, 3] } },
      formatter: (params: AxisTooltipParam[]) => {
        if (!params.length) return '';
        const [rp, loss] = params[0].value as [number, number];
        return tooltipHeader(`${rp}-year return period`) + tooltipValueRow(theme, undefined, money(loss), 'Loss');
      },
    },
    xAxis: {
      type: 'log',
      logBase: 10,
      min: Math.min(...returnPeriods),
      max: Math.max(...returnPeriods),
      name: 'Return period (years)',
      nameLocation: 'middle',
      nameGap: 26,
      nameTextStyle: axisName(theme),
      axisLine: axisLine(theme),
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { ...tickLabel(theme), formatter: (v: number) => fmtNum(v) },
    },
    yAxis: {
      type: 'value',
      name: `Loss (${currencySymbol})`,
      nameLocation: 'middle',
      nameGap: (money(maxOf(losses)).length + 1) * CHAR_PX,
      nameTextStyle: axisName(theme),
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: dashedSplitLine(theme),
      axisLabel: { ...tickLabel(theme), formatter: (v: number) => money(v) },
    },
    series: [{
      type: 'line',
      data,
      showSymbol: false,
      symbolSize: 8,
      lineStyle: { width: 2, color },
      itemStyle: { color },
      areaStyle: { opacity: 0.12, color },
      emphasis: { focus: 'none', itemStyle: HOVER_SHADOW },
    }],
  };
}

export interface RiskBarDatum {
  name: string;
  value: number;
}

export interface RiskBarOptionInput {
  data: RiskBarDatum[];
  formatValue: (v: number) => string;
  theme: ChartTheme;
}

/** Horizontal "name -> value" breakdown bar — single generic series, so it
 *  gets the item-trigger + hover-emphasis treatment (matches donut/scatter). */
export function buildRiskBarOption({ data, formatValue, theme }: RiskBarOptionInput): EChartsCoreOption {
  const color = theme.seriesPalette[0];
  return {
    animation: true,
    animationDuration: 250,
    animationDurationUpdate: 200,
    grid: { left: 4, right: 56, top: 8, bottom: 8, containLabel: true },
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'item',
      formatter: (p: { name: string; value: number }) => tooltipValueRow(theme, undefined, formatValue(p.value), p.name),
    },
    xAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { show: false },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: data.map((d) => d.name),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { ...tickLabel(theme), width: 130, overflow: 'truncate' as const },
    },
    series: [{
      type: 'bar',
      barMaxWidth: 16,
      barCategoryGap: '38%',
      showBackground: true,
      backgroundStyle: { color: theme.grid },
      itemStyle: { color, borderRadius: [0, 4, 4, 0] },
      emphasis: { itemStyle: HOVER_SHADOW },
      label: {
        show: true,
        position: 'right',
        formatter: (p: { value: number }) => formatValue(p.value),
        color: theme.text,
        fontSize: 11,
        fontFamily: theme.fontSans,
      },
      data: data.map((d) => d.value),
    }],
  };
}

export interface TransitionCostOptionInput {
  years: number[];
  values: number[];
  formatValue: (v: number) => string;
  theme: ChartTheme;
}

/** Annual carbon-cost trajectory (year -> cost) — single generic line series. */
export function buildTransitionCostOption({ years, values, formatValue, theme }: TransitionCostOptionInput): EChartsCoreOption {
  const color = theme.seriesPalette[0];
  const data = years.map((y, i) => [y, values[i]]);
  return {
    animation: true,
    animationDuration: 250,
    animationDurationUpdate: 200,
    grid: { left: 12, right: 20, top: 34, bottom: 30, containLabel: true },
    toolbox: chartToolbox(theme, 'carbon-cost-trajectory'),
    dataZoom: axisDataZoom(theme, 'x'),
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: theme.axis, type: [4, 3] } },
      formatter: (params: AxisTooltipParam[]) => {
        if (!params.length) return '';
        const [yr, v] = params[0].value as [number, number];
        return tooltipHeader(`Year ${yr}`) + tooltipValueRow(theme, undefined, formatValue(v), 'Carbon cost');
      },
    },
    xAxis: {
      type: 'value',
      min: years.length ? Math.min(...years) : undefined,
      max: years.length ? Math.max(...years) : undefined,
      name: 'Year',
      nameLocation: 'middle',
      nameGap: 26,
      nameTextStyle: axisName(theme),
      axisLine: axisLine(theme),
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { ...tickLabel(theme), formatter: (v: number) => String(Math.round(v)) },
    },
    yAxis: {
      type: 'value',
      name: 'Annual carbon cost',
      nameLocation: 'middle',
      nameGap: 48,
      nameTextStyle: axisName(theme),
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: dashedSplitLine(theme),
      axisLabel: { ...tickLabel(theme), formatter: (v: number) => formatValue(v) },
    },
    series: [{
      type: 'line',
      data,
      showSymbol: false,
      symbolSize: 8,
      lineStyle: { width: 2, color },
      itemStyle: { color },
      areaStyle: { opacity: 0.12, color },
      emphasis: { focus: 'none', itemStyle: HOVER_SHADOW },
    }],
  };
}
