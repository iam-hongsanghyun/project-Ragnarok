/**
 * Built-in preset layouts for the Analytics dashboard.
 *
 * Each preset gives a different analytical angle on the same run.
 * Loading one replaces the current layout (autosaved). The user can
 * then resize, rearrange, or save under a new name.
 *
 * All cards use `system` focus so the metric keys are stable across
 * any run. The known system-focus metric keys (see useMetricOptions):
 *   dispatch · dispatch_by_gen · load · system_price ·
 *   system_emissions · storage_power · storage_state
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

/** Build a chart card from a short spec. */
function chartCard(spec: CellSpec): { card: Card; flex: number } {
  const cardId = id('chart');
  return {
    card: {
      id: cardId,
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

/** Shape a list of (card, flex) pairs into a Row. */
function row(height: number, items: Array<{ card: Card; flex: number }>): {
  row: { id: string; height: number; cells: Array<{ id: string; flex: number; cardId: string }> };
  cards: Card[];
} {
  return {
    row: {
      id: id('row'),
      height,
      cells: items.map((it) => ({ id: id('cell'), flex: it.flex, cardId: it.card.id })),
    },
    cards: items.map((it) => it.card),
  };
}

/** Stitch rows into a layout, flattening their cards. */
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
  // ── 1. Quick situational awareness ──────────────────────────────────────
  {
    key: 'overview',
    label: 'System overview',
    description: 'Top-line situational awareness: stacked dispatch, then load + price side-by-side, then run notes.',
    build: () => layout([
      row(320, [chartCard({ metric: 'dispatch',      chart: 'area', stacked: true })]),
      row(240, [
        chartCard({ metric: 'load' }),
        chartCard({ metric: 'system_price' }),
      ]),
      row(160, [notesCard()]),
    ]),
  },

  // ── 2. Detailed dispatch viewing ────────────────────────────────────────
  {
    key: 'dispatch-deep-dive',
    label: 'Dispatch deep-dive',
    description: 'Three ways to slice generation: stacked area by carrier, stacked area by generator, and a donut of total energy. Load reference below.',
    build: () => layout([
      row(280, [
        chartCard({ metric: 'dispatch',        chart: 'area', stacked: true }),
        chartCard({ metric: 'dispatch_by_gen', chart: 'area', stacked: true }),
        chartCard({ metric: 'dispatch',        chart: 'donut' }),
      ]),
      row(200, [chartCard({ metric: 'load' })]),
    ]),
  },

  // ── 3. Storage cycle inspection ─────────────────────────────────────────
  {
    key: 'storage-focus',
    label: 'Storage operations',
    description: 'Dispatch on top, then storage state-of-charge and charge/discharge power side-by-side.',
    build: () => layout([
      row(280, [chartCard({ metric: 'dispatch', chart: 'area', stacked: true })]),
      row(240, [
        chartCard({ metric: 'storage_state' }),
        chartCard({ metric: 'storage_power' }),
      ]),
    ]),
  },

  // ── 4. Market & economics ───────────────────────────────────────────────
  {
    key: 'market-economics',
    label: 'Market & economics',
    description: 'Price front-and-centre, then load + dispatch composition + emissions side-by-side. For traders and economists.',
    build: () => layout([
      row(240, [chartCard({ metric: 'system_price', chart: 'line' })]),
      row(260, [
        chartCard({ metric: 'load' }),
        chartCard({ metric: 'dispatch',         chart: 'donut' }),
        chartCard({ metric: 'system_emissions', chart: 'line' }),
      ]),
      row(160, [notesCard()]),
    ]),
  },

  // ── 5. Carrier mix and curtailment ──────────────────────────────────────
  {
    key: 'carrier-mix',
    label: 'Carrier mix',
    description: 'Large stacked dispatch view, then carrier-share donut + daily generator dispatch.',
    build: () => layout([
      row(340, [chartCard({ metric: 'dispatch', chart: 'area', stacked: true })]),
      row(220, [
        chartCard({ metric: 'dispatch',        chart: 'donut' }),
        chartCard({ metric: 'dispatch_by_gen', chart: 'bar', stacked: true, timeframe: 'daily' }),
      ]),
      row(160, [notesCard()]),
    ]),
  },

  // ── 6. Emissions trajectory ─────────────────────────────────────────────
  {
    key: 'emissions',
    label: 'Emissions trajectory',
    description: 'System emissions over time + daily emissions bars side-by-side, with dispatch context below.',
    build: () => layout([
      row(260, [
        chartCard({ metric: 'system_emissions', chart: 'line' }),
        chartCard({ metric: 'system_emissions', chart: 'bar', timeframe: 'daily' }),
      ]),
      row(240, [chartCard({ metric: 'dispatch', chart: 'area', stacked: true })]),
      row(160, [notesCard()]),
    ]),
  },

  // ── 7. Daily summary ────────────────────────────────────────────────────
  {
    key: 'daily-summary',
    label: 'Daily summary',
    description: 'Everything aggregated to daily resolution: easier to read multi-week runs.',
    build: () => layout([
      row(240, [
        chartCard({ metric: 'dispatch',         chart: 'bar', stacked: true, timeframe: 'daily' }),
        chartCard({ metric: 'load',             chart: 'bar',               timeframe: 'daily' }),
      ]),
      row(240, [
        chartCard({ metric: 'system_price',     chart: 'line',              timeframe: 'daily' }),
        chartCard({ metric: 'system_emissions', chart: 'bar',               timeframe: 'daily' }),
      ]),
      row(160, [notesCard()]),
    ]),
  },

  // ── 8. Trader-style 3×3 tile board ──────────────────────────────────────
  {
    key: 'trader-board',
    label: 'Trader board (3×3)',
    description: 'Nine small tiles: load, price, emissions, two dispatch views, donut, storage SoC, storage power, notes. Bloomberg-terminal density.',
    build: () => layout([
      row(180, [
        chartCard({ metric: 'load' }),
        chartCard({ metric: 'system_price' }),
        chartCard({ metric: 'system_emissions' }),
      ]),
      row(180, [
        chartCard({ metric: 'dispatch',        chart: 'line', stacked: true }),
        chartCard({ metric: 'dispatch_by_gen', chart: 'line', stacked: true }),
        chartCard({ metric: 'dispatch',        chart: 'donut' }),
      ]),
      row(180, [
        chartCard({ metric: 'storage_state' }),
        chartCard({ metric: 'storage_power' }),
        notesCard(),
      ]),
    ]),
  },

  // ── 9. Minimal blank starting point ─────────────────────────────────────
  {
    key: 'minimal',
    label: 'Blank minimal',
    description: 'One empty chart card. Build the rest yourself.',
    build: () => layout([
      row(320, [chartCard({ metric: EMPTY_METRIC_KEY })]),
    ]),
  },
];
