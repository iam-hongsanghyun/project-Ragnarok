/**
 * Pure ECharts option builders for every migrated chart. React-free so the
 * shapes can be unit-tested directly (options.test.ts); components pass the
 * resolved ChartTheme in and hand the returned option to useEChart.
 *
 * Conventions shared by all builders (the "Ragnarok look"):
 *   - dashed slate grid lines, 11px muted sans tick labels, no axis ticks
 *   - dark slate tooltip (matches the old hand-rolled rgba(15,23,42,.88))
 *   - square corners, no animations (dense dashboard; resize stays snappy)
 *   - numbers formatted with toLocaleString, units in axis names / tooltips
 */
import type { EChartsCoreOption } from 'echarts/core';
import { ChartMode, MeritOrderEntry, MixItem, TimeSeriesRow, TimeSeriesSeries } from 'lib/types';
import { numberValue } from 'lib/utils/helpers';
import type { ChartTheme } from './theme';

const CHAR_PX = 6.6; // approximate glyph width of the 11px tick font

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

/** Shared dark tooltip chrome. */
export function darkTooltip(theme: ChartTheme): Record<string, unknown> {
  return {
    backgroundColor: theme.tooltipBg,
    borderWidth: 0,
    confine: true,
    textStyle: { color: '#ffffff', fontSize: 11, fontFamily: theme.fontSans },
    extraCssText: 'border-radius: 4px; box-shadow: none;',
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
  return { show: true, lineStyle: { color: theme.gridLine, type: [4, 6] } };
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
}

export function buildTimeSeriesOption(input: TimeSeriesOptionInput): EChartsCoreOption {
  const {
    xLabels, rows, series, mode, stacked,
    xAxisTitle, yAxisTitle, showAxisLabels, xLabelAngle, theme,
  } = input;

  const values = series.map((s) => rows.map((r) => numberValue(r[s.key] as string | number | undefined)));

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
      itemStyle: { color: s.color },
      emphasis: { focus: series.length > 1 ? ('series' as const) : ('none' as const) },
    };
    if (mode === 'bar') {
      return { ...base, type: 'bar' as const, barMaxWidth: 40 };
    }
    return {
      ...base,
      type: 'line' as const,
      showSymbol: false,
      lineStyle: { width: mode === 'area' ? 1.8 : 2.2, color: s.color },
      areaStyle: mode === 'area' ? { opacity: stacked ? 0.72 : 0.24 } : undefined,
    };
  });

  return {
    animation: false,
    grid: {
      left: yAxisTitle ? 22 : 8,
      right: 16,
      top: 24,
      bottom: xAxisTitle ? 24 : 6,
      containLabel: true,
    },
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'axis',
      axisPointer: mode === 'bar'
        ? { type: 'shadow' }
        : { type: 'line', lineStyle: { color: 'rgba(15, 23, 42, 0.28)', type: [4, 3] } },
      valueFormatter: fmtNum,
    },
    xAxis: {
      type: 'category',
      boundaryGap: mode === 'bar',
      data: xLabels,
      name: xAxisTitle,
      nameLocation: 'middle',
      nameGap: (showAxisLabels ? Math.ceil(Math.sin(rad) * maxXLabelPx) + 24 : 14),
      nameTextStyle: axisName(theme),
      axisLine: { lineStyle: { color: theme.border } },
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
        `${params.name}: <b>${fmtNum(params.value)}${unit ? ` ${unit}` : ''}</b> (${params.percent.toFixed(1)}%)`,
    },
    series: [{
      type: 'pie',
      radius: ['54%', '88%'],
      center: ['50%', '50%'],
      label: { show: false },
      itemStyle: { borderColor: '#ffffff', borderWidth: 2 },
      emphasis: { scale: true, scaleSize: 4 },
      data: data.map((d) => ({ name: d.label, value: d.value, itemStyle: { color: d.color } })),
    }],
  };
}

// ── Duration curve ────────────────────────────────────────────────────────────

export interface DurationCurveOptionInput {
  /** Values in rank order (already sorted descending by the caller). */
  data: number[];
  title: string;
  unit: string;
  color: string;
  theme: ChartTheme;
}

export function buildDurationCurveOption(input: DurationCurveOptionInput): EChartsCoreOption {
  const { data, title, unit, color, theme } = input;
  const n = Math.max(data.length - 1, 1);
  const points = data.map((v, i) => [(i / n) * 100, v]);
  return {
    animation: false,
    title: {
      text: title,
      left: 4,
      top: 2,
      textStyle: axisName(theme),
    },
    grid: { left: 8, right: 16, top: 30, bottom: 4, containLabel: true },
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: 'rgba(15, 23, 42, 0.28)', type: [4, 3] } },
      formatter: (params: Array<{ data: [number, number] }>) => {
        const [pct, v] = params[0].data;
        return `Exceedance ${pct.toFixed(1)}%<br/><b>${fmtNum(v)} ${unit}</b>`;
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
    series: [{
      type: 'line',
      data: points,
      showSymbol: false,
      lineStyle: { width: 2, color },
      areaStyle: { opacity: 0.15, color },
    }],
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
    animation: false,
    grid: { left: 26, right: 16, top: 16, bottom: 30, containLabel: true },
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'item',
      formatter: (params: { data: MeritDatum }) => {
        const d = params.data;
        return [
          `<b>${d.name}</b>`,
          `${d.carrier} · ${d.bus}`,
          `Cost: <b>${currencySymbol}${d.value[2].toLocaleString()}/MWh</b>`,
          `Capacity: <b>${fmtNum(d.value[1])} MW</b>`,
        ].join('<br/>');
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
      axisLine: { lineStyle: { color: theme.borderStrong } },
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
      splitLine: { show: true, lineStyle: { color: 'rgba(15, 23, 42, 0.07)' } },
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
          style: { fill: entry?.color ?? '#94a3b8', opacity: 0.78 },
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

export function buildExpansionOption(rows: ExpansionRow[], theme: ChartTheme): EChartsCoreOption {
  return {
    animation: false,
    grid: { left: 4, right: 60, top: 4, bottom: 24, containLabel: true },
    legend: {
      bottom: 0,
      left: 0,
      icon: 'rect',
      itemWidth: 12,
      itemHeight: 8,
      textStyle: { ...tickLabel(theme), fontSize: 10 },
    },
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (v: number | string) => `${fmtNum(v)} MW`,
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
        itemStyle: { color: theme.borderStrong },
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
        data: rows.map((r) => ({ value: r.optimised, itemStyle: { color: r.color, opacity: 0.85 } })),
      },
    ],
  };
}
