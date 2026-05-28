/**
 * Built-in preset layouts for the Analytics dashboard.
 *
 * Loading a preset replaces the active layout (autosaved). The user
 * can then resize, rearrange, or save under a new name.
 *
 * Each preset is hand-shaped around the aspect rule the dashboard
 * enforces for `autoHeight` rows:
 *     1 cell → height = 0.5 × containerWidth   (wide hero chart)
 *     N ≥ 2 → height =       containerWidth / N   (square cells)
 * So:
 *   single-cell rows  → big time-series charts
 *   2-cell rows       → side-by-side comparisons in square panels
 *   3-cell rows       → KPI-density tile strips
 *
 * All cards use `system` focus so the metric keys are stable across
 * any run. Known system-focus metric keys (see useMetricOptions):
 *
 *   Line / area / bar friendly:
 *     dispatch · dispatch_by_gen · load · system_price ·
 *     system_emissions · storage_state
 *   Donut friendly (allowDonut === true):
 *     dispatch · dispatch_by_gen · storage_power
 */
import { ChartSectionConfig, ChartSectionType, TimeframeOption } from '../../../shared/types';
import { EMPTY_METRIC_KEY } from '../../../constants';
import { Card, DashboardLayout } from './types';

let _id = 0;
const id = (p: string) => `${p}-${Date.now().toString(36)}-${(_id++).toString(36)}`;

function chartConfig(patch: Partial<ChartSectionConfig>): ChartSectionConfig {
  return {
    id: Date.now() + Math.random(),
    focusType: 'system',
    focusKeys: [],
    groupBy: 'carrier',
    busFilter: [],
    carrierFilter: [],
    metricKey: EMPTY_METRIC_KEY,
    chartType: 'line',
    timeframe: 'hourly',
    startIndex: 0,
    endIndex: 100000,  // clamped to actual data length by UDC
    stacked: false,
    ...patch,
  };
}

interface CellSpec {
  metric: string;
  chart?: ChartSectionType;
  stacked?: boolean;
  timeframe?: TimeframeOption;
  flex?: number;
}

function chartCard(spec: CellSpec): { card: Card; flex: number } {
  return {
    card: {
      id: id('chart'),
      kind: 'chart',
      config: chartConfig({
        metricKey: spec.metric,
        chartType: spec.chart ?? 'line',
        stacked: spec.stacked ?? false,
        timeframe: spec.timeframe ?? 'hourly',
      }),
    },
    flex: spec.flex ?? 1,
  };
}

function notesCard(): { card: Card; flex: number } {
  return { card: { id: id('notes'), kind: 'notes' }, flex: 1 };
}

function row(items: Array<{ card: Card; flex: number }>): {
  row: { id: string; height: number; autoHeight: boolean; cells: Array<{ id: string; flex: number; cardId: string }> };
  cards: Card[];
} {
  return {
    row: {
      id: id('row'),
      height: 280,
      autoHeight: true,
      cells: items.map((it) => ({ id: id('cell'), flex: it.flex, cardId: it.card.id })),
    },
    cards: items.map((it) => it.card),
  };
}

function layout(rows: Array<ReturnType<typeof row>>): DashboardLayout {
  return {
    rows: rows.map((r) => r.row),
    cards: rows.flatMap((r) => r.cards),
  };
}

export interface Preset {
  key: string;
  label: string;
  description: string;
  build: () => DashboardLayout;
}

export const PRESETS: Preset[] = [
  // ── 1. Glance ───────────────────────────────────────────────────────────
  {
    key: 'glance',
    label: 'At a glance',
    description: 'Three small donuts up top showing the energy / generator / storage mix; one big hero dispatch chart; then load and price side-by-side.',
    build: () => layout([
      row([
        chartCard({ metric: 'dispatch',        chart: 'donut' }),
        chartCard({ metric: 'dispatch_by_gen', chart: 'donut' }),
        chartCard({ metric: 'storage_power',   chart: 'donut' }),
      ]),
      row([chartCard({ metric: 'dispatch', chart: 'area', stacked: true })]),
      row([
        chartCard({ metric: 'load' }),
        chartCard({ metric: 'system_price' }),
      ]),
    ]),
  },

  // ── 2. Operations log (hero stack) ─────────────────────────────────────
  {
    key: 'ops-log',
    label: 'Operations log',
    description: 'Four full-width time series stacked vertically: dispatch · load · price · emissions. The hourly story of the system.',
    build: () => layout([
      row([chartCard({ metric: 'dispatch',         chart: 'area', stacked: true })]),
      row([chartCard({ metric: 'load',             chart: 'line' })]),
      row([chartCard({ metric: 'system_price',     chart: 'line' })]),
      row([chartCard({ metric: 'system_emissions', chart: 'line' })]),
    ]),
  },

  // ── 3. Daily digest ────────────────────────────────────────────────────
  {
    key: 'daily-digest',
    label: 'Daily digest',
    description: 'Daily-aggregated bars (dispatch · load · price · emissions) in a 2×2 grid, then the underlying hourly dispatch below.',
    build: () => layout([
      row([
        chartCard({ metric: 'dispatch',         chart: 'bar',  stacked: true, timeframe: 'daily' }),
        chartCard({ metric: 'load',             chart: 'bar',                 timeframe: 'daily' }),
      ]),
      row([
        chartCard({ metric: 'system_price',     chart: 'line',                timeframe: 'daily' }),
        chartCard({ metric: 'system_emissions', chart: 'bar',                 timeframe: 'daily' }),
      ]),
      row([chartCard({ metric: 'dispatch', chart: 'area', stacked: true })]),
    ]),
  },

  // ── 4. Supply mix ──────────────────────────────────────────────────────
  {
    key: 'supply-mix',
    label: 'Supply mix',
    description: 'Where the energy is coming from: stacked by carrier, then stacked by individual generator, then donuts of each.',
    build: () => layout([
      row([chartCard({ metric: 'dispatch',        chart: 'area', stacked: true })]),
      row([chartCard({ metric: 'dispatch_by_gen', chart: 'area', stacked: true })]),
      row([
        chartCard({ metric: 'dispatch',        chart: 'donut' }),
        chartCard({ metric: 'dispatch_by_gen', chart: 'donut' }),
        notesCard(),
      ]),
    ]),
  },

  // ── 5. Market & price ──────────────────────────────────────────────────
  {
    key: 'market',
    label: 'Market & price',
    description: 'Price front-and-centre with a daily summary, then the load and energy-mix context that drives it.',
    build: () => layout([
      row([chartCard({ metric: 'system_price', chart: 'line' })]),
      row([
        chartCard({ metric: 'system_price', chart: 'bar',   timeframe: 'daily' }),
        chartCard({ metric: 'load',         chart: 'line' }),
        chartCard({ metric: 'dispatch',     chart: 'donut' }),
      ]),
      row([chartCard({ metric: 'dispatch_by_gen', chart: 'area', stacked: true })]),
    ]),
  },

  // ── 6. Storage cycle ───────────────────────────────────────────────────
  {
    key: 'storage',
    label: 'Storage cycle',
    description: 'State of charge over the run, then charge/discharge power, then the dispatch and load it interacts with.',
    build: () => layout([
      row([chartCard({ metric: 'storage_state' })]),
      row([chartCard({ metric: 'storage_power', chart: 'area' })]),
      row([
        chartCard({ metric: 'dispatch', chart: 'area', stacked: true }),
        chartCard({ metric: 'load' }),
      ]),
    ]),
  },

  // ── 7. Emissions tracker ───────────────────────────────────────────────
  {
    key: 'emissions',
    label: 'Emissions tracker',
    description: 'Hourly emissions on top, then a daily bar comparison and the dispatch mix that produced them.',
    build: () => layout([
      row([chartCard({ metric: 'system_emissions', chart: 'line' })]),
      row([
        chartCard({ metric: 'system_emissions', chart: 'bar',   timeframe: 'daily' }),
        chartCard({ metric: 'dispatch',         chart: 'donut' }),
      ]),
      row([chartCard({ metric: 'dispatch', chart: 'area', stacked: true })]),
    ]),
  },

  // ── 8. Trader board (3×3 density) ──────────────────────────────────────
  {
    key: 'trader',
    label: 'Trader board (3×3)',
    description: 'Nine compact tiles in a Bloomberg-terminal grid: load · price · emissions; two dispatch views and energy donut; two storage views and run notes.',
    build: () => layout([
      row([
        chartCard({ metric: 'load' }),
        chartCard({ metric: 'system_price' }),
        chartCard({ metric: 'system_emissions' }),
      ]),
      row([
        chartCard({ metric: 'dispatch',        chart: 'line', stacked: true }),
        chartCard({ metric: 'dispatch_by_gen', chart: 'line', stacked: true }),
        chartCard({ metric: 'dispatch',        chart: 'donut' }),
      ]),
      row([
        chartCard({ metric: 'storage_state' }),
        chartCard({ metric: 'storage_power' }),
        notesCard(),
      ]),
    ]),
  },

  // ── 9. Notes-led briefing ──────────────────────────────────────────────
  {
    key: 'briefing',
    label: 'Briefing',
    description: 'Run-notes commentary at the top, then a hero dispatch chart, then load and price beneath. Good for screenshots / hand-offs.',
    build: () => layout([
      row([notesCard()]),
      row([chartCard({ metric: 'dispatch', chart: 'area', stacked: true })]),
      row([
        chartCard({ metric: 'load' }),
        chartCard({ metric: 'system_price' }),
      ]),
    ]),
  },

  // ── 10. Blank ──────────────────────────────────────────────────────────
  {
    key: 'blank',
    label: 'Blank',
    description: 'One empty chart card. Open its settings to choose what to plot.',
    build: () => layout([
      row([chartCard({ metric: EMPTY_METRIC_KEY })]),
    ]),
  },
];
