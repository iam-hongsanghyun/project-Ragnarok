/**
 * Pure ECharts option builders for the P2X results (React-free, unit-tested in charts.test.ts):
 * the cost waterfall, electrolyser dispatch against the designated RES, and the H2 store state of charge.
 * They reuse the shared chart chrome of `lib/charts/options.ts` so the P2X charts match the rest of the app.
 */
import type { EChartsCoreOption } from 'echarts/core';
import { axisDataZoom, axisName, chartToolbox, darkTooltip, tickLabel } from 'lib/charts/options';
import type { ChartTheme } from 'lib/charts/theme';
import type { WaterfallStep } from 'lib/api/p2x';

const fmt = (v: number, digits = 2): string =>
  Number.isFinite(v) ? v.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—';

export interface WaterfallBar { label: string; base: number; value: number; total: boolean }

/** Waterfall geometry: each step floats on the running total; the last bar is the total from zero. */
export function waterfallBars(steps: WaterfallStep[], totalLabel: string): WaterfallBar[] {
  const bars: WaterfallBar[] = [];
  let running = 0;
  for (const s of steps) {
    const lo = Math.min(running, running + s.value);
    bars.push({ label: s.label, base: lo, value: Math.abs(s.value), total: false });
    running += s.value;
  }
  bars.push({ label: totalLabel, base: 0, value: running, total: true });
  return bars;
}

export function buildWaterfallOption(input: { steps: WaterfallStep[]; unit: string; theme: ChartTheme }): EChartsCoreOption {
  const { steps, unit, theme } = input;
  const bars = waterfallBars(steps, 'Total');
  return {
    animation: true,
    grid: { left: 36, right: 16, top: 24, bottom: 8, containLabel: true },
    tooltip: {
      ...darkTooltip(theme), trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (params: Array<{ dataIndex: number }>) => {
        const i = params[0]?.dataIndex ?? 0;
        const b = bars[i];
        return `<b>${fmt(b.total ? b.value : steps[i].value, 3)} ${unit}</b><br/>${b.label}`
          + (b.total ? '' : `<br/>cumulative ${fmt(steps[i].cumulative, 3)}`);
      },
    },
    xAxis: { type: 'category', data: bars.map((b) => b.label), axisLabel: { ...tickLabel(theme), interval: 0, rotate: 25, width: 96, overflow: 'truncate' }, axisTick: { show: false } },
    yAxis: { type: 'value', name: unit, nameTextStyle: axisName(theme), axisLabel: tickLabel(theme), splitLine: { lineStyle: { color: theme.grid } } },
    series: [
      { type: 'bar', stack: 'w', silent: true, itemStyle: { color: 'transparent' }, data: bars.map((b) => b.base) },
      {
        type: 'bar', stack: 'w', barMaxWidth: 34,
        data: bars.map((b) => ({ value: b.value, itemStyle: { color: b.total ? theme.seriesPalette[0] : theme.seriesPalette[1], borderRadius: [3, 3, 0, 0] } })),
        label: { show: true, position: 'top', color: theme.text, fontSize: 11, fontFamily: theme.fontSans, formatter: (p: { value: number }) => fmt(p.value, 2) },
      },
    ],
  };
}

export interface DispatchInput {
  snapshots: string[]; electrolyserMw: number[]; designatedMw: number[]; gridMw: number[]; theme: ChartTheme;
  /** Cap the MW axis just above the electrolyser peak, so a designated fleet far larger than the electrolyser does not flatten it. */
  fitToElectrolyser?: boolean;
}

/** Electrolyser electricity against the designated RES output; the grid-supplied part is shaded. */
export function buildDispatchOption({ snapshots, electrolyserMw, designatedMw, gridMw, theme, fitToElectrolyser }: DispatchInput): EChartsCoreOption {
  const p = theme.seriesPalette;
  const peak = electrolyserMw.reduce((m, v) => (v > m ? v : m), 0);
  return {
    animation: false,
    grid: { left: 8, right: 16, top: 36, bottom: 56, containLabel: true },
    legend: { top: 0, type: 'scroll', textStyle: { color: theme.muted, fontSize: 11, fontFamily: theme.fontSans } },
    toolbox: chartToolbox(theme, 'p2x-electrolyser-dispatch'),
    tooltip: { ...darkTooltip(theme), trigger: 'axis' },
    xAxis: { type: 'category', data: snapshots, boundaryGap: false, axisLabel: { ...tickLabel(theme), hideOverlap: true }, axisTick: { show: false } },
    yAxis: {
      type: 'value', name: 'MW', nameTextStyle: axisName(theme), axisLabel: tickLabel(theme), splitLine: { lineStyle: { color: theme.grid } },
      ...(fitToElectrolyser && peak > 0 ? { max: Math.ceil(peak * 1.15) } : {}),
    },
    dataZoom: axisDataZoom(theme, 'x'),
    series: [
      { name: 'Designated RES output', type: 'line', showSymbol: false, areaStyle: { opacity: 0.18 }, lineStyle: { width: 1.5 }, itemStyle: { color: p[2] }, data: designatedMw },
      { name: 'Electrolyser electricity', type: 'line', showSymbol: false, lineStyle: { width: 2 }, itemStyle: { color: p[0] }, data: electrolyserMw },
      { name: 'Grid-supplied (unmatched)', type: 'line', showSymbol: false, areaStyle: { opacity: 0.35 }, lineStyle: { width: 0 }, itemStyle: { color: p[1] }, data: gridMw },
    ],
  };
}

export function buildSocOption(input: { snapshots: string[]; socTonnes: number[]; theme: ChartTheme }): EChartsCoreOption {
  const { snapshots, socTonnes, theme } = input;
  return {
    animation: false,
    grid: { left: 8, right: 16, top: 24, bottom: 56, containLabel: true },
    toolbox: chartToolbox(theme, 'p2x-h2-soc'),
    tooltip: { ...darkTooltip(theme), trigger: 'axis' },
    xAxis: { type: 'category', data: snapshots, boundaryGap: false, axisLabel: { ...tickLabel(theme), hideOverlap: true }, axisTick: { show: false } },
    yAxis: { type: 'value', name: 't H2', nameTextStyle: axisName(theme), axisLabel: tickLabel(theme), splitLine: { lineStyle: { color: theme.grid } } },
    dataZoom: axisDataZoom(theme, 'x'),
    series: [{ name: 'H2 store state of charge', type: 'line', showSymbol: false, areaStyle: { opacity: 0.2 }, lineStyle: { width: 1.5 }, itemStyle: { color: theme.seriesPalette[2] }, data: socTonnes }],
  };
}
