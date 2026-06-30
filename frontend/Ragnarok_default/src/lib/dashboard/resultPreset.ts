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
import { RunResults, ChartSectionConfig } from 'lib/types';
import { EMPTY_METRIC_KEY } from 'lib/constants';
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
  // Network-analysis runs (power flow / N-1 contingency) carry no optimise data
  // (dispatch / cost / price), so the standard charts would be empty. Give them
  // a focused layout: KPIs + the study card + the map.
  if (results.powerFlow || results.contingency) {
    const studyCard: Card = results.powerFlow
      ? { id: id('pf'), kind: 'power-flow' }
      : { id: id('ctg'), kind: 'contingency' };
    const naRows = [
      row({ height: 90, autoHeight: false, cards: [{ card: { id: id('kpi'), kind: 'kpi-strip' } }] }),
      row({ cards: [{ card: studyCard }] }),
      row({ cards: [{ card: { id: id('map'), kind: 'map' } }] }),
      row({ cards: [{ card: { id: id('notes'), kind: 'notes' } }] }),
    ];
    return { rows: naRows.map((r) => r.row), cards: naRows.flatMap((r) => r.cards) };
  }

  // Check storageUnits in assetDetails (live run) OR any non-zero value in the
  // pre-computed storageSeries (analytics-bundle view where series = null and
  // assetDetails is empty).
  const hasStorage =
    (results.assetDetails && Object.values(results.assetDetails.storageUnits || {}).length > 0) ||
    (results.storageSeries?.some((p) => p.charge > 0 || p.discharge > 0 || p.state > 0) ?? false);
  const hasPathway   = !!results.pathway?.enabled;
  const hasExpansion = !!(results.expansionResults && results.expansionResults.length > 0);
  const hasStoch     = !!results.stochastic?.enabled;
  const hasEmissionsBd = !!(results.emissionsBreakdown && (
    results.emissionsBreakdown.byCarrier.length > 0 || results.emissionsBreakdown.byGenerator.length > 0
  ));
  const hasEconomics = !!(results.generatorEconomics && (
    results.generatorEconomics.generators.length > 0 || results.generatorEconomics.storage.length > 0
  ));

  const rows: Array<ReturnType<typeof row>> = [];

  // 1. KPI strip — fixed pixel height, full width
  const kpi: Card = { id: id('kpi'), kind: 'kpi-strip' };
  rows.push(row({ height: 90, autoHeight: false, cards: [{ card: kpi }] }));

  // 2. Headline: generation dispatch by carrier — full-width time series
  rows.push(row({
    cards: [
      { card: makeChart({ metricKey: 'dispatch', chartType: 'area', stacked: true }) },
    ],
  }));

  // 3. Demand + price + storage SoC by carrier, side by side. The SoC chart
  //    drops out automatically when the run has no storage.
  rows.push(row({
    cards: [
      { card: makeChart({ metricKey: 'load' }) },
      { card: makeChart({ metricKey: 'system_price' }) },
      ...(hasStorage ? [{ card: makeChart({ metricKey: 'storage_soc_by_carrier' }) }] : []),
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

  // 5. Merit order + curtailment-by-carrier line chart. The curtailment chart
  // takes the slot the CO₂-shadow card used to occupy; the carrier-analysis
  // table below is now full-width. (The co2-shadow card kind still exists and
  // can be added manually — only the default layout drops it.)
  const merit:  Card = { id: id('merit'),    kind: 'merit-order' };
  const curt = makeChart({ metricKey: 'curtailment', chartType: 'line' });
  rows.push(row({ cards: [{ card: merit }, { card: curt }] }));

  // 6. Emissions breakdown (conditional)
  if (hasEmissionsBd) {
    const eb: Card = { id: id('em-bd'), kind: 'emissions-breakdown' };
    rows.push(row({ cards: [{ card: eb }] }));
  }

  // (Storage SoC lives in the demand · price · SoC row above.)

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

  // 9b. Asset economics — revenue / margin / capex recovery (F0, conditional)
  if (hasEconomics) {
    const econ: Card = { id: id('econ'), kind: 'generator-economics' };
    rows.push(row({ cards: [{ card: econ }] }));
  }

  // 10. Carrier analysis — full-width performance table.
  const ca: Card = { id: id('ca'), kind: 'carrier-analysis' };
  rows.push(row({ cards: [{ card: ca }] }));

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
