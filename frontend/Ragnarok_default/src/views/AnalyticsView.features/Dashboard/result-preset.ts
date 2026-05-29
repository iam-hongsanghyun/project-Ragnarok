/**
 * Result sub-tab default preset — a curated dashboard built from the
 * card kinds the engine supports, conditional on what data exists in
 * the run results.
 *
 * Built lazily from `results` so each run gets a layout that omits
 * rows whose data is empty (no storage, no pathway, no stochastic,
 * etc.). Once the user saves a custom layout, this builder is no
 * longer consulted — the stored layout wins.
 */
import { RunResults, ChartSectionConfig } from '../../../shared/types';
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
    endIndex: 100000,
    stacked: false,
    ...patch,
  };
}

interface RowInput {
  height?: number;
  autoHeight?: boolean;
  cards: Array<{ card: Card; flex?: number }>;
}

function row(input: RowInput) {
  return {
    row: {
      id: id('row'),
      height: input.height ?? 280,
      autoHeight: input.autoHeight ?? true,
      cells: input.cards.map((c) => ({ id: id('cell'), flex: c.flex ?? 1, cardId: c.card.id })),
    },
    cards: input.cards.map((c) => c.card),
  };
}

function makeChart(patch: Partial<ChartSectionConfig>): Card {
  return { id: id('chart'), kind: 'chart', config: chartConfig(patch) };
}

export function buildResultPreset(results: RunResults): DashboardLayout {
  const hasStorage =
    results.assetDetails &&
    Object.values(results.assetDetails.storageUnits || {}).length > 0;
  const hasPathway   = !!results.pathway?.enabled;
  const hasExpansion = !!(results.expansionResults && results.expansionResults.length > 0);
  const hasStoch     = !!results.stochastic?.enabled;
  const hasEmissionsBd = !!(results.emissionsBreakdown && (
    results.emissionsBreakdown.byCarrier.length > 0 || results.emissionsBreakdown.byGenerator.length > 0
  ));

  const rows: Array<ReturnType<typeof row>> = [];

  // 1. KPI strip — fixed pixel height, full width
  const kpi: Card = { id: id('kpi'), kind: 'kpi-strip' };
  rows.push(row({ height: 90, autoHeight: false, cards: [{ card: kpi }] }));

  // 2. Headline charts: dispatch + load + price
  rows.push(row({
    cards: [
      { card: makeChart({ metricKey: 'dispatch',     chartType: 'area', stacked: true }) },
      { card: makeChart({ metricKey: 'load' }) },
      { card: makeChart({ metricKey: 'system_price' }) },
    ],
  }));

  // 3. Energy mix donut + cost donut (donuts via chart card)
  rows.push(row({
    cards: [
      { card: makeChart({ metricKey: 'dispatch', chartType: 'donut' }) },
      { card: makeChart({ metricKey: 'dispatch_by_gen', chartType: 'donut' }) },
    ],
  }));

  // 4. Duration curves
  const loadDur:  Card = { id: id('dur-load'),  kind: 'duration-curve', source: 'load' };
  const priceDur: Card = { id: id('dur-price'), kind: 'duration-curve', source: 'price' };
  rows.push(row({ cards: [{ card: loadDur }, { card: priceDur }] }));

  // 5. Merit order + CO₂ shadow
  const merit:  Card = { id: id('merit'),    kind: 'merit-order' };
  const shadow: Card = { id: id('co2'),      kind: 'co2-shadow' };
  rows.push(row({ cards: [{ card: merit }, { card: shadow }] }));

  // 6. Emissions breakdown (conditional)
  if (hasEmissionsBd) {
    const eb: Card = { id: id('em-bd'), kind: 'emissions-breakdown' };
    rows.push(row({ cards: [{ card: eb }] }));
  }

  // 7. Storage SoC (conditional)
  if (hasStorage) {
    rows.push(row({
      cards: [{ card: makeChart({ metricKey: 'storage_state' }) }],
    }));
  }

  // 8. Capacity by period (conditional on pathway)
  if (hasPathway) {
    const cbp: Card = { id: id('cbp'), kind: 'capacity-by-period' };
    rows.push(row({ cards: [{ card: cbp }] }));
  }

  // 9. Capacity expansion (conditional)
  if (hasExpansion) {
    const ce: Card = { id: id('ce'), kind: 'capacity-expansion' };
    rows.push(row({ cards: [{ card: ce }] }));
  }

  // 10. Carrier analysis + Load analysis
  const ca: Card = { id: id('ca'), kind: 'carrier-analysis' };
  const la: Card = { id: id('la'), kind: 'load-analysis' };
  rows.push(row({ cards: [{ card: ca }, { card: la }] }));

  // 11. Stochastic scenarios (conditional)
  if (hasStoch) {
    const ss: Card = { id: id('ss'), kind: 'stochastic-scenarios' };
    rows.push(row({ cards: [{ card: ss }] }));
  }

  // 12. Notes
  const notes: Card = { id: id('notes'), kind: 'notes' };
  rows.push(row({ cards: [{ card: notes }] }));

  return {
    rows: rows.map((r) => r.row),
    cards: rows.flatMap((r) => r.cards),
  };
}
