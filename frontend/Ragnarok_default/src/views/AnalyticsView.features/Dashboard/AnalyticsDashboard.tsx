/**
 * Analytics dashboard — wires PyPSA-specific cards into the generic
 * Dashboard grid plus a toolbar for layout edit / save / load.
 *
 * Card kinds supported:
 *   chart  · map  · notes  · kpi-strip  · duration-curve  ·
 *   merit-order · co2-shadow · emissions-breakdown ·
 *   capacity-expansion · capacity-by-period · carrier-analysis ·
 *   load-analysis · stochastic-scenarios
 *
 * The same component renders both the Analytics and Result sub-tabs;
 * the parent picks the storage key and the default preset.
 */
import React, { useEffect, useRef, useState } from 'react';
import { LatLngBoundsExpression } from 'leaflet';
import {
  AnalyticsFocus,
  ChartSectionConfig,
  GridRow,
  RunResults,
  TimeSeriesRow,
  TimeSeriesSeries,
  WorkbookModel,
} from 'lib/types';
import { EMPTY_METRIC_KEY } from 'lib/constants';
import { useDialog } from '../../../shared/components/Dialog';
import { UserDefinedChartCard } from '../../../features/analytics/cards/UserDefinedChartCard';
import { AnalyticsMapCard } from '../../../features/analytics/AnalyticsMapCard';
import { KpiStripCard } from '../../../features/analytics/cards/KpiStripCard';
import { DurationCurveCard } from '../../../features/analytics/cards/DurationCurveCard';
import { MeritOrderCard } from '../../../features/analytics/cards/MeritOrderCard';
import { Co2ShadowCard } from '../../../features/analytics/cards/Co2ShadowCard';
import { GeneratorEconomicsCard } from '../../../features/analytics/cards/GeneratorEconomicsCard';
import { StatisticsCard } from '../../../features/analytics/cards/StatisticsCard';
import { NearOptimalCard } from '../../../features/analytics/cards/NearOptimalCard';
import { MerchantCard } from '../../../features/analytics/cards/MerchantCard';
import { CompanyBreakdownCard } from '../../../features/analytics/cards/CompanyBreakdownCard';
import { CompanyFinanceCard } from '../../../features/analytics/cards/CompanyFinanceCard';
import { CompanyStatementCard } from '../../../features/analytics/cards/CompanyStatementCard';
import { CompanyComparisonCard } from '../../../features/analytics/cards/CompanyComparisonCard';
import { TransitionRiskCard } from '../../../features/analytics/cards/TransitionRiskCard';
import { AdequacyCard } from '../../../features/analytics/cards/AdequacyCard';
import { RawSheetsCard } from '../../../features/analytics/cards/RawSheetsCard';
import { PriceFormationCard } from '../../../features/analytics/cards/PriceFormationCard';
import { CommitmentCard } from '../../../features/analytics/cards/CommitmentCard';
import { BidStrategyCard } from '../../../features/analytics/cards/BidStrategyCard';
import { OptimalBidCard } from '../../../features/analytics/cards/OptimalBidCard';
import { AssetSwapCard } from '../../../features/analytics/cards/AssetSwapCard';
import { EssCard } from '../../../features/analytics/cards/EssCard';
import { PpaCard } from '../../../features/analytics/cards/PpaCard';
import { PpaExplorerCard } from '../../../features/analytics/cards/PpaExplorerCard';
import { EnergyBalanceCard } from '../../../features/analytics/cards/EnergyBalanceCard';
import { DemandResponseCard } from '../../../features/analytics/cards/DemandResponseCard';
import { PriceElasticCard } from '../../../features/analytics/cards/PriceElasticCard';
import { PowerFlowCard } from '../../../features/analytics/cards/PowerFlowCard';
import { MarketSimulationCard } from '../../../features/analytics/cards/MarketSimulationCard';
import { MarketParticipantsCard } from '../../../features/analytics/cards/MarketParticipantsCard';
import { AuctionBookCard } from '../../../features/analytics/cards/AuctionBookCard';
import { StrategicBiddingCard } from '../../../features/analytics/cards/StrategicBiddingCard';
import { ContingencyCard } from '../../../features/analytics/cards/ContingencyCard';
import { EmissionsBreakdownCard } from '../../../features/analytics/cards/EmissionsBreakdownCard';
import { CapacityExpansionCard } from '../../../features/analytics/cards/CapacityExpansionCard';
import { CapacityByPeriodCard } from '../../../features/analytics/cards/CapacityByPeriodCard';
import { CarrierAnalysisCard } from '../../../features/analytics/cards/CarrierAnalysisCard';
import { LoadAnalysisCard } from '../../../features/analytics/cards/LoadAnalysisCard';
import { StochasticScenariosCard } from '../../../features/analytics/cards/StochasticScenariosCard';
import { numberValue } from 'lib/utils/helpers';
import { Dashboard, newId } from './Dashboard';
import { Card, DashboardLayout, PivotChartConfig } from 'lib/dashboard/types';
import { useDashboardLayout } from './useDashboardLayout';
import { PRESETS } from 'lib/dashboard/presets';
import { effectiveEndIndex, fullRunTimeline, OUTPUT_SHEETS_FOR_FOCUS } from 'lib/api/runs';
import { PivotChartCard } from '../../../features/analytics/cards/PivotChartCard';
import { pivotSeriesSheet } from 'lib/results/pivot';

const DEFAULT_LAYOUT: DashboardLayout = { rows: [], cards: [] };

/** Human-readable label for a chart card based on its focus + metric. */
// Bloomberg-style auto-titles: a category prefix (the desk / panel a trader
// would scan for) followed by the specific series. Rendered uppercase by CSS.
const SYSTEM_METRIC_LABEL: Record<string, string> = {
  dispatch:          'Generation · Dispatch by carrier',
  dispatch_by_gen:   'Generation · Dispatch by unit',
  curtailment:       'Generation · Curtailment by carrier',
  load:              'Demand · System load',
  system_price:      'Price · Marginal (SMP)',
  system_emissions:  'Emissions · System CO₂',
  storage_power:     'Storage · Charge / discharge',
  storage_state:     'Storage · State of charge',
  storage_soc_by_carrier: 'Storage · SoC by carrier',
};

const FOCUS_TYPE_LABEL: Record<string, string> = {
  system:         'System',
  generator:      'Generator',
  bus:            'Bus',
  storageUnit:    'Storage unit',
  store:          'Store',
  branch:         'Branch',
  process:        'Process',
  shuntImpedance: 'Shunt impedance',
};

function chartCardTitle(cfg: ChartSectionConfig): string {
  if (cfg.metricKey === EMPTY_METRIC_KEY) return 'Empty chart';
  if (cfg.focusType === 'system') {
    return SYSTEM_METRIC_LABEL[cfg.metricKey] ?? 'System chart';
  }
  const focus = FOCUS_TYPE_LABEL[cfg.focusType] ?? cfg.focusType;
  const scope = cfg.focusKeys.length === 1
    ? cfg.focusKeys[0]
    : cfg.focusKeys.length === 0 ? 'all' : `${cfg.focusKeys.length} selected`;
  return `${focus} · ${scope}`;
}

function defaultChartConfig(): ChartSectionConfig {
  return {
    id: Date.now(),
    focusType: 'system',
    focusKeys: [],
    groupBy: 'carrier',
    busFilter: [],
    carrierFilter: [],
    metricKey: EMPTY_METRIC_KEY,
    chartType: 'line',
    timeframe: 'hourly',
    startIndex: 0,
    endIndex: 0,
    stacked: false,
  };
}

function defaultPivotConfig(): PivotChartConfig {
  return {
    id: Date.now(),
    sheet: 'generators',
    valueAttribute: '',
    groupBy: ['carrier'],
    filters: [],
    aggregate: 'sum',
    chartType: 'area',
    timeframe: 'hourly',
    stacked: true,
    startIndex: 0,
    endIndex: 100000,
  };
}

function newPivotCard(): Card { return { id: newId('pivot'), kind: 'pivot', config: defaultPivotConfig() }; }
function newChartCard(): Card { return { id: newId('chart'), kind: 'chart', config: defaultChartConfig() }; }
function newMapCard(): Card   { return { id: newId('map'),   kind: 'map' }; }
function newNotesCard(): Card { return { id: newId('notes'), kind: 'notes' }; }

/** Kinds offered from an empty placeholder cell's "+" menu. The Pivot chart is
 *  the primary chart builder; the legacy metric chart stays available. */
const ADDABLE_CARDS = [
  { kind: 'pivot', label: 'Pivot chart' },
  { kind: 'chart', label: 'Metric chart' },
  { kind: 'map',   label: 'Map' },
  { kind: 'notes', label: 'Run notes' },
];

function createCard(kind: string): Card {
  switch (kind) {
    case 'chart': return newChartCard();
    case 'map':   return newMapCard();
    case 'notes': return newNotesCard();
    default:      return newPivotCard();
  }
}

interface Props {
  results: RunResults;
  model: WorkbookModel;
  bounds: LatLngBoundsExpression | null;
  busIndex: Record<string, GridRow>;
  /** System-aggregated time series — passed in from the parent because
   *  App.tsx already computes them once. Saves recomputing here. */
  dispatchRows?: TimeSeriesRow[];
  dispatchSeries?: TimeSeriesSeries[];
  systemLoadRows?: TimeSeriesRow[];
  systemPriceRows?: TimeSeriesRow[];
  storageRows?: TimeSeriesRow[];
  currencySymbol: string;
  analyticsFocus: AnalyticsFocus;
  onFocusChange: (focus: AnalyticsFocus) => void;
  /** localStorage key for this dashboard instance. */
  /** `null` disables layout persistence (always rebuild from initialLayout). */
  storageKey?: string | null;
  /** Initial layout if nothing is stored yet. */
  initialLayout?: DashboardLayout;
  /** Show the Presets ▾ picker. Off for the curated Result tab. */
  showPresets?: boolean;
  /** Report, per output-series sheet, the MAX number of snapshots the current
   *  layout's per-asset charts need loaded (each chart's slider right edge), so
   *  the parent hydrates only those sheets at the length needed. Empty {} when
   *  the layout is system-only. */
  onNeedSeries?: (windows: Record<string, number>) => void;
}

export function AnalyticsDashboard({
  results, model, bounds, busIndex,
  systemLoadRows = [],
  systemPriceRows = [],
  currencySymbol,
  analyticsFocus, onFocusChange,
  storageKey,
  initialLayout = DEFAULT_LAYOUT,
  showPresets = true,
  onNeedSeries,
}: Props) {
  const { layout, setLayout, editing, setEditing, resetToDefault } =
    useDashboardLayout(initialLayout, storageKey);
  const { alert: alertDialog } = useDialog();

  // Tell the parent, per output-series sheet, the MAX snapshot count the
  // layout's per-asset charts need loaded (each chart's slider right edge), so
  // it hydrates only those sheets at that length. Runs on layout change (chart
  // added / slider moved / preset loaded), not every render. A system-only
  // layout reports {} → no fetch → the common result view is instant.
  useEffect(() => {
    if (!onNeedSeries) return;
    const totalSnaps = fullRunTimeline(results).length;
    const weight = results.runMeta?.snapshotWeight ?? 1;
    const windows: Record<string, number> = {};
    for (const card of layout.cards) {
      if (card.kind === 'chart' && card.config.focusType !== 'system') {
        const end = effectiveEndIndex(card.config.focusType, card.config.endIndex, totalSnaps, weight);
        const snaps = end + 1;
        for (const sheet of OUTPUT_SHEETS_FOR_FOCUS[card.config.focusType] ?? []) {
          windows[sheet] = Math.max(windows[sheet] ?? 0, snaps);
        }
      } else if (card.kind === 'pivot') {
        // A pivot whose value is an output series needs that one sheet hydrated,
        // up to the chart's window right-edge. Static / input values need none.
        const sheet = pivotSeriesSheet(card.config.sheet, card.config.valueAttribute);
        if (!sheet) continue;
        const end = effectiveEndIndex('generator', card.config.endIndex, totalSnaps, weight);
        windows[sheet] = Math.max(windows[sheet] ?? 0, end + 1);
      }
    }
    onNeedSeries(windows);
  }, [layout, onNeedSeries, results]);
  const [openMenu, setOpenMenu] = useState<'presets' | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const presetsMenuRef = useRef<HTMLDivElement | null>(null);

  // Close the Presets menu when clicking anywhere outside it.
  useEffect(() => {
    if (openMenu !== 'presets') return;
    const onDown = (e: MouseEvent) => {
      if (presetsMenuRef.current && !presetsMenuRef.current.contains(e.target as Node)) {
        setOpenMenu(null);
      }
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [openMenu]);

  // Track which preset is currently in play so Reset re-imports *that*
  // preset rather than the hardcoded default. null = the initial layout.
  const [currentPresetKey, setCurrentPresetKey] = useState<string | null>(null);

  // Edit-mode staging: snapshot the layout when the user starts editing so
  // Cancel can revert every drag/resize/add. Apply just keeps the changes.
  const [editSnapshot, setEditSnapshot] = useState<DashboardLayout | null>(null);

  const startEditing = () => { setEditSnapshot(layout); setEditing(true); };
  const applyEditing = () => { setEditSnapshot(null); setEditing(false); setOpenMenu(null); };
  const cancelEditing = () => {
    if (editSnapshot) setLayout(editSnapshot);
    setEditSnapshot(null);
    setEditing(false);
    setOpenMenu(null);
  };

  const updateCard = (cardId: string, patch: Partial<Card>) =>
    setLayout({
      ...layout,
      cards: layout.cards.map((c) => (c.id === cardId ? ({ ...c, ...patch } as Card) : c)),
    });

  const updateChartConfig = (cardId: string, next: ChartSectionConfig) =>
    setLayout({
      ...layout,
      cards: layout.cards.map((c) =>
        c.id === cardId && c.kind === 'chart' ? { ...c, config: next } : c,
      ),
    });

  const updatePivotConfig = (cardId: string, next: PivotChartConfig) =>
    setLayout({
      ...layout,
      cards: layout.cards.map((c) =>
        c.id === cardId && c.kind === 'pivot' ? { ...c, config: next } : c,
      ),
    });

  // Save the current layout as a downloadable .json file the user can keep
  // on disk and re-import later (or share). The active layout still
  // autosaves to localStorage; this is the portable, explicit export.
  const handleExport = () => {
    const json = JSON.stringify(layout, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ragnarok-dashboard-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setOpenMenu(null);
  };

  const handleImportFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // reset so the same file can be re-imported
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result)) as DashboardLayout;
        if (parsed && Array.isArray(parsed.rows) && Array.isArray(parsed.cards)) {
          setLayout(parsed);
        } else {
          void alertDialog('That file is not a valid dashboard layout.', { title: 'Import failed' });
        }
      } catch {
        void alertDialog('Could not read that file as JSON.', { title: 'Import failed' });
      }
    };
    reader.readAsText(file);
  };

  const handleLoadPreset = (key: string) => {
    const preset = PRESETS.find((p) => p.key === key);
    if (preset) { setLayout(preset.build()); setCurrentPresetKey(key); }
    setOpenMenu(null);
  };

  // Reset re-imports the currently selected preset (a fresh copy, discarding
  // edits). If no preset has been picked, fall back to the initial layout.
  const handleReset = () => {
    const preset = currentPresetKey ? PRESETS.find((p) => p.key === currentPresetKey) : null;
    if (preset) setLayout(preset.build());
    else resetToDefault();
    setOpenMenu(null);
  };

  // Sorted load / price for duration curves and merit-order systemLoad.
  const sortedLoad = systemLoadRows
    .map((r) => numberValue(r['load'] as number | string | undefined))
    .filter((v: number) => v > 0)
    .sort((a: number, b: number) => b - a);
  const sortedPrice = systemPriceRows
    .map((r) => numberValue(r['price'] as number | string | undefined))
    .sort((a: number, b: number) => b - a);

  const renderCard = (card: Card): React.ReactNode => {
    try {
      switch (card.kind) {
        case 'chart':
          return (
            <UserDefinedChartCard
              compact
              section={card.config}
              results={results}
              model={model}
              currencySymbol={currencySymbol}
              onChange={(next) => updateChartConfig(card.id, next)}
              onClean={() => updateChartConfig(card.id, defaultChartConfig())}
              onRemove={() => { /* dashboard cell × handles removal */ }}
              title={card.title}
              onTitleChange={(next) => updateCard(card.id, { title: next.trim() || undefined })}
            />
          );
        case 'pivot':
          return (
            <PivotChartCard
              compact
              config={card.config}
              results={results}
              model={model}
              onChange={(next) => updatePivotConfig(card.id, next)}
              onClean={() => updatePivotConfig(card.id, defaultPivotConfig())}
              title={card.title}
              onTitleChange={(next) => updateCard(card.id, { title: next.trim() || undefined })}
            />
          );
        case 'map':
          return (
            <AnalyticsMapCard
              results={results}
              model={model}
              bounds={bounds}
              busIndex={busIndex}
              analyticsFocus={analyticsFocus}
              onFocusChange={onFocusChange}
              currencySymbol={currencySymbol}
            />
          );
        case 'notes':
          return (
            <ul className="dashboard-notes">
              {results.narrative.length === 0 && <li className="dashboard-notes-empty">No notes from this run.</li>}
              {results.narrative.map((item, i) => <li key={`${i}-${item}`}>{item}</li>)}
            </ul>
          );
        case 'kpi-strip':
          return <KpiStripCard results={results} model={model} currencySymbol={currencySymbol} />;
        case 'duration-curve':
          return (
            <DurationCurveCard
              title={card.source === 'price' ? `Marginal price (${currencySymbol}/MWh)` : 'Load (MW)'}
              data={card.source === 'price' ? sortedPrice : sortedLoad}
              unit={card.source === 'price' ? `${currencySymbol}/MWh` : 'MW'}
              color={card.source === 'price' ? 'var(--text)' : 'var(--warm)'}
            />
          );
        case 'merit-order':
          return (
            <MeritOrderCard
              entries={results.meritOrder ?? []}
              systemLoad={sortedLoad.length > 0 ? sortedLoad[0] : undefined}
              currencySymbol={currencySymbol}
            />
          );
        case 'co2-shadow':
          return (
            <Co2ShadowCard
              currencySymbol={currencySymbol}
              shadow={results.co2Shadow ?? {
                found: false,
                constraint_name: null,
                shadow_price: 0,
                explicit_price: 0,
                cap_ktco2: null,
                status: 'none',
                note: 'No CO₂ shadow price for this run.',
              }}
            />
          );
        case 'generator-economics':
          return results.generatorEconomics
            ? <GeneratorEconomicsCard data={results.generatorEconomics} currencySymbol={currencySymbol} />
            : <p className="dashboard-cell-missing">No asset economics available for this run.</p>;
        case 'statistics':
          return results.statistics
            ? <StatisticsCard data={results.statistics} />
            : <p className="dashboard-cell-missing">No statistics available for this run.</p>;
        case 'near-optimal':
          return results.nearOptimal
            ? <NearOptimalCard data={results.nearOptimal} />
            : <p className="dashboard-cell-missing">This run did not include MGA near-optimal exploration.</p>;
        case 'merchant':
          return results.merchant
            ? <MerchantCard data={results.merchant} />
            : <p className="dashboard-cell-missing">This run did not include merchant (price-taker) analysis.</p>;
        case 'company-breakdown':
          return results.companies
            ? <CompanyBreakdownCard data={results.companies} />
            : <p className="dashboard-cell-missing">No owner-tagged assets in this run.</p>;
        case 'company-finance':
          return results.companyFinance
            ? <CompanyFinanceCard data={results.companyFinance} />
            : <p className="dashboard-cell-missing">No company finance for this run (needs owner tags and an LP run).</p>;
        case 'company-statement':
          return results.companyStatement
            ? <CompanyStatementCard data={results.companyStatement} />
            : <p className="dashboard-cell-missing">No company P&amp;L for this run (needs owner tags and an LP run).</p>;
        case 'company-comparison':
          return (results.companies || results.companyFinance || results.companyStatement)
            ? <CompanyComparisonCard breakdown={results.companies} finance={results.companyFinance} statement={results.companyStatement} />
            : <p className="dashboard-cell-missing">No owner-tagged companies to compare.</p>;
        case 'transition-risk':
          return results.companyStatement
            ? <TransitionRiskCard data={results.companyStatement} />
            : <p className="dashboard-cell-missing">No company P&amp;L for this run (needs owner tags and an LP run).</p>;
        case 'adequacy':
          return results.adequacy
            ? <AdequacyCard data={results.adequacy} />
            : <p className="dashboard-cell-missing">No adequacy study (needs renewable generators with time-varying availability).</p>;
        case 'raw-sheets':
          return results.rawSheets && Object.keys(results.rawSheets).length > 0
            ? <RawSheetsCard data={results.rawSheets} />
            : <p className="dashboard-cell-missing">No unrecognised sheets in this import.</p>;
        case 'price-formation':
          return results.priceFormation
            ? <PriceFormationCard data={results.priceFormation} />
            : <p className="dashboard-cell-missing">No price-formation data for this run (needs an LP run with prices).</p>;
        case 'commitment':
          return results.commitment
            ? <CommitmentCard data={results.commitment} />
            : <p className="dashboard-cell-missing">No committable units in this run.</p>;
        case 'bid-strategy':
          return results.bidStrategy
            ? <BidStrategyCard data={results.bidStrategy} />
            : <p className="dashboard-cell-missing">This run did not include bid-strategy simulation.</p>;
        case 'optimal-bid':
          return results.optimalBid
            ? <OptimalBidCard data={results.optimalBid} />
            : <p className="dashboard-cell-missing">This run did not include optimal-bid search.</p>;
        case 'asset-swap':
          return results.assetSwap
            ? <AssetSwapCard data={results.assetSwap} />
            : <p className="dashboard-cell-missing">This run did not include an asset-swap what-if.</p>;
        case 'ess-business-case':
          return results.essBusinessCase
            ? <EssCard data={results.essBusinessCase} />
            : <p className="dashboard-cell-missing">This run did not include an ESS business case.</p>;
        case 'ppa':
          return results.ppa
            ? <PpaCard data={results.ppa} />
            : <p className="dashboard-cell-missing">This run did not include a PPA valuation.</p>;
        case 'ppa-explorer':
          return results.ppaExplorer
            ? <PpaExplorerCard data={results.ppaExplorer} />
            : <p className="dashboard-cell-missing">This run did not include a PPA shape comparison.</p>;
        case 'energy-balance':
          return results.energyBalance
            ? <EnergyBalanceCard data={results.energyBalance} />
            : <p className="dashboard-cell-missing">This run is single-carrier — no sector-coupling balance.</p>;
        case 'demand-response':
          return results.demandResponse
            ? <DemandResponseCard data={results.demandResponse} />
            : <p className="dashboard-cell-missing">This run did not include demand response.</p>;
        case 'price-elastic':
          return results.priceElastic
            ? <PriceElasticCard data={results.priceElastic} />
            : <p className="dashboard-cell-missing">This run did not include price-elastic demand.</p>;
        case 'power-flow':
          return results.powerFlow
            ? <PowerFlowCard data={results.powerFlow} />
            : <p className="dashboard-cell-missing">This run was not a power-flow study.</p>;
        case 'market-simulation':
          return results.marketSimulation
            ? <MarketSimulationCard data={results.marketSimulation} />
            : <p className="dashboard-cell-missing">This run was not a market simulation.</p>;
        case 'market-participants':
          return results.marketSimulation
            ? <MarketParticipantsCard data={results.marketSimulation} />
            : <p className="dashboard-cell-missing">This run was not a market simulation.</p>;
        case 'auction-book':
          return results.marketSimulation
            ? <AuctionBookCard data={results.marketSimulation} />
            : <p className="dashboard-cell-missing">This run was not a market simulation.</p>;
        case 'strategic-bidding':
          return results.strategicBidding
            ? <StrategicBiddingCard data={results.strategicBidding} />
            : <p className="dashboard-cell-missing">No strategic-bidding analysis in this run.</p>;
        case 'contingency':
          return results.contingency
            ? <ContingencyCard data={results.contingency} />
            : <p className="dashboard-cell-missing">This run was not an N-1 contingency analysis.</p>;
        case 'emissions-breakdown':
          return results.emissionsBreakdown
            ? <EmissionsBreakdownCard data={results.emissionsBreakdown} />
            : <p className="dashboard-cell-missing">No emissions breakdown available.</p>;
        case 'capacity-expansion':
          return results.expansionResults && results.expansionResults.length > 0
            ? <CapacityExpansionCard assets={results.expansionResults} currencySymbol={currencySymbol} />
            : <p className="dashboard-cell-missing">No capacity expansion in this run.</p>;
        case 'capacity-by-period':
          return results.pathway?.enabled
            ? <CapacityByPeriodCard model={model} results={results} />
            : <p className="dashboard-cell-missing">Pathway not enabled.</p>;
        case 'carrier-analysis':
          return <CarrierAnalysisCard results={results} currencySymbol={currencySymbol} model={model} />;
        case 'load-analysis':
          return <LoadAnalysisCard results={results} currencySymbol={currencySymbol} />;
        case 'stochastic-scenarios':
          return results.stochastic?.enabled
            ? <StochasticScenariosCard stochastic={results.stochastic} currencySymbol={currencySymbol} />
            : <p className="dashboard-cell-missing">Stochastic mode not enabled.</p>;
      }
    } catch (err) {
      return <p className="dashboard-cell-missing">Card failed to render.</p>;
    }
    return null;
  };

  const cardTitle = (card: Card): string => {
    if (card.title) return card.title;
    if (card.kind === 'pivot') {
      const cfg = card.config;
      if (!cfg.valueAttribute) return 'Empty chart';
      const grp = cfg.groupBy.length ? ` by ${cfg.groupBy.join(' + ')}` : '';
      const tf = cfg.chartType !== 'donut' && cfg.timeframe && cfg.timeframe !== 'hourly' ? ` · ${cfg.timeframe}` : '';
      return `${cfg.sheet} · ${cfg.valueAttribute}${grp}${tf}`;
    }
    if (card.kind === 'chart') {
      const label = chartCardTitle(card.config);
      const tf = card.config.timeframe;
      // Donuts always show the full-period total, so the timeframe is irrelevant
      // (and misleading) in the title — omit it there.
      const tfSuffix = card.config.chartType === 'donut'
        ? ''
        : (tf && tf !== 'hourly' ? ` · ${tf}` : '');
      return `${label}${tfSuffix}`;
    }
    switch (card.kind) {
      case 'map': return 'Network map';
      case 'notes': return 'Run notes';
      case 'kpi-strip': return 'KPIs';
      case 'duration-curve': return card.source === 'price' ? 'Price duration curve' : 'Load duration curve';
      case 'merit-order': return 'Merit order (supply stack)';
      case 'co2-shadow': return 'CO₂ shadow price';
      case 'generator-economics': return 'Asset economics (revenue & recovery)';
      case 'statistics': return 'PyPSA statistics (per-carrier metrics)';
      case 'near-optimal': return 'Near-optimal capacity corridor (MGA)';
      case 'merchant': return 'Merchant economics (price-taker)';
      case 'company-breakdown': return 'Company breakdown (per-owner KPIs)';
      case 'company-finance': return 'Company finance (NPV / IRR / payback)';
      case 'company-statement': return 'Company P&L (per-owner annual statement)';
      case 'company-comparison': return 'Company comparison (rank owners side by side)';
      case 'transition-risk': return 'Transition risk (carbon-price margin erosion)';
      case 'adequacy': return 'Resource adequacy (LOLE / EENS)';
      case 'raw-sheets': return 'Imported raw sheets (unrecognised)';
      case 'price-formation': return 'Price formation (why the price is what it is)';
      case 'commitment': return 'Unit commitment (starts & on/off)';
      case 'bid-strategy': return 'Bid strategy (markup vs price-taker)';
      case 'optimal-bid': return 'Optimal bid (profit-maximising markup)';
      case 'asset-swap': return 'Asset swap (repowering what-if)';
      case 'ess-business-case': return 'ESS business case (size sweep)';
      case 'ppa': return 'PPA contract (CfD settlement)';
      case 'ppa-explorer': return 'PPA opportunity explorer (shape ranking)';
      case 'energy-balance': return 'Energy balance (by carrier)';
      case 'demand-response': return 'Demand response (shiftable load)';
      case 'price-elastic': return 'Price-elastic demand';
      case 'power-flow': return 'Power flow (convergence & voltages)';
      case 'market-simulation': return 'Market simulation (prices & unit economics)';
      case 'market-participants': return 'Auction participants (per-owner profit)';
      case 'auction-book': return 'Auction book (bid stack & clearing)';
      case 'strategic-bidding': return 'Strategic bidding (market power best response)';
      case 'contingency': return 'N-1 contingency (security)';
      case 'emissions-breakdown': return 'Emissions by generator / carrier';
      case 'capacity-expansion': return 'Capacity expansion';
      case 'capacity-by-period': return 'Capacity by period';
      case 'carrier-analysis': return 'Carrier performance';
      case 'load-analysis': return 'Load analysis';
      case 'stochastic-scenarios': return 'Stochastic scenarios';
    }
    return 'Card';
  };

  // Rename text input on the chart settings modal is rendered by
  // UserDefinedChartCard. The card object is passed through so a small
  // adapter handles the title field. Same for map's rename affordance —
  // simpler: a tiny inline rename overlay activated on cell title click.

  return (
    <div className="analytics-dashboard">
      <div className="dashboard-toolbar">
        {editing ? (
          <>
            <button className="tb-btn tb-btn--active" onClick={applyEditing}>Apply</button>
            <button className="tb-btn tb-btn--muted" onClick={cancelEditing}>Cancel</button>
          </>
        ) : (
          <button className="tb-btn" onClick={startEditing}>Edit layout</button>
        )}

        {showPresets && (
          <>
            <div className="dashboard-toolbar-sep" />
            <div className="dashboard-toolbar-menu" ref={presetsMenuRef}>
              <button className="tb-btn" onClick={() => setOpenMenu(openMenu === 'presets' ? null : 'presets')}>
                Presets ▾
              </button>
              {openMenu === 'presets' && (
                <div className="dashboard-toolbar-pop dashboard-toolbar-pop--wide">
                  {PRESETS.map((p) => (
                    <button
                      key={p.key}
                      className="dashboard-preset-row"
                      onClick={() => handleLoadPreset(p.key)}
                      title={p.description}
                    >
                      <span className="dashboard-preset-label">{p.label}</span>
                      <span className="dashboard-preset-desc">{p.description}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </>
        )}

        {editing && (
          <>
            <button className="tb-btn" onClick={handleExport} title="Download this layout as a .json file">
              Save layout…
            </button>
            <button className="tb-btn" onClick={() => fileInputRef.current?.click()} title="Import a layout from a .json file">
              Import…
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="application/json,.json"
              style={{ display: 'none' }}
              onChange={handleImportFile}
            />
            <div className="dashboard-toolbar-sep" />
            <button className="tb-btn tb-btn--muted" onClick={handleReset} title="Re-import the current preset (discards edits)">
              Reset
            </button>
          </>
        )}
      </div>

      <Dashboard
        layout={layout}
        onLayoutChange={setLayout}
        editing={editing}
        renderCard={renderCard}
        cardTitle={cardTitle}
        onCardRename={(cardId, title) => updateCard(cardId, { title })}
        addableCards={ADDABLE_CARDS}
        createCard={createCard}
      />
    </div>
  );
}
