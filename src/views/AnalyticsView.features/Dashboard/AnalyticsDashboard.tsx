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
import React, { useState } from 'react';
import { LatLngBoundsExpression } from 'leaflet';
import {
  AnalyticsFocus,
  ChartSectionConfig,
  GridRow,
  RunResults,
  TimeSeriesRow,
  TimeSeriesSeries,
  WorkbookModel,
} from '../../../shared/types';
import { EMPTY_METRIC_KEY } from '../../../constants';
import { UserDefinedChartCard } from '../../../features/analytics/cards/UserDefinedChartCard';
import { AnalyticsMapCard } from '../../../features/analytics/AnalyticsMapCard';
import { KpiStripCard } from '../../../features/analytics/cards/KpiStripCard';
import { DurationCurveCard } from '../../../features/analytics/cards/DurationCurveCard';
import { MeritOrderCard } from '../../../features/analytics/cards/MeritOrderCard';
import { Co2ShadowCard } from '../../../features/analytics/cards/Co2ShadowCard';
import { EmissionsBreakdownCard } from '../../../features/analytics/cards/EmissionsBreakdownCard';
import { CapacityExpansionCard } from '../../../features/analytics/cards/CapacityExpansionCard';
import { CapacityByPeriodCard } from '../../../features/analytics/cards/CapacityByPeriodCard';
import { CarrierAnalysisCard } from '../../../features/analytics/cards/CarrierAnalysisCard';
import { LoadAnalysisCard } from '../../../features/analytics/cards/LoadAnalysisCard';
import { StochasticScenariosCard } from '../../../features/analytics/cards/StochasticScenariosCard';
import { numberValue } from '../../../shared/utils/helpers';
import { Dashboard, addCard, newId } from './Dashboard';
import { Card, ChartCard, DashboardLayout } from './types';
import { useDashboardLayout } from './useDashboardLayout';
import { PRESETS } from './presets';

const DEFAULT_LAYOUT: DashboardLayout = { rows: [], cards: [] };

/** Human-readable label for a chart card based on its focus + metric. */
const SYSTEM_METRIC_LABEL: Record<string, string> = {
  dispatch:          'Dispatch by carrier',
  dispatch_by_gen:   'Dispatch by generator',
  load:              'Total load',
  system_price:      'Marginal price',
  system_emissions:  'Emissions',
  storage_power:     'Storage power',
  storage_state:     'State of charge',
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

function newChartCard(): Card { return { id: newId('chart'), kind: 'chart', config: defaultChartConfig() }; }
function newMapCard(): Card   { return { id: newId('map'),   kind: 'map' }; }
function newNotesCard(): Card { return { id: newId('notes'), kind: 'notes' }; }

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
  storageKey?: string;
  /** Initial layout if nothing is stored yet. */
  initialLayout?: DashboardLayout;
  /** Show the Presets ▾ picker. Off for the curated Result tab. */
  showPresets?: boolean;
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
}: Props) {
  const { layout, setLayout, editing, setEditing, savedLayouts, saveAs, load, remove, resetToDefault } =
    useDashboardLayout(initialLayout, storageKey);
  const [openMenu, setOpenMenu] = useState<'add' | 'layouts' | 'presets' | null>(null);

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

  /** Click on a map asset → rewrite focus on every chart card flagged
   *  followFocus. Cards without the flag (the default for manually
   *  added cards) stay put. */
  const handleMapFocusChange = (focus: AnalyticsFocus) => {
    onFocusChange(focus);
    if (focus.type === 'system') return; // system means "no focus"; leave cards alone
    setLayout({
      ...layout,
      cards: layout.cards.map((c) => {
        if (c.kind !== 'chart') return c;
        const cc = c as ChartCard;
        if (!cc.followFocus) return c;
        return {
          ...cc,
          config: {
            ...cc.config,
            focusType: focus.type,
            focusKeys: [focus.key],
          },
        };
      }),
    });
  };

  const handleAdd = (kind: 'chart' | 'map' | 'notes') => {
    const card = kind === 'chart' ? newChartCard() : kind === 'map' ? newMapCard() : newNotesCard();
    const targetRow = layout.rows[layout.rows.length - 1]?.id ?? null;
    setLayout(addCard(layout, targetRow, card));
    setOpenMenu(null);
  };

  const handleSave = () => {
    const name = window.prompt('Save layout as:', `layout-${savedLayouts.length + 1}`);
    if (name) saveAs(name);
    setOpenMenu(null);
  };

  const handleLoad = (name: string) => { load(name); setOpenMenu(null); };
  const handleDelete = (name: string) => { if (window.confirm(`Delete saved layout "${name}"?`)) remove(name); };
  const handleLoadPreset = (key: string) => {
    const preset = PRESETS.find((p) => p.key === key);
    if (preset) setLayout(preset.build());
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
              followFocus={card.followFocus}
              onFollowFocusChange={(next) => updateCard(card.id, { followFocus: next })}
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
              onFocusChange={handleMapFocusChange}
              currencySymbol={currencySymbol}
            />
          );
        case 'notes':
          return (
            <ul className="dashboard-notes">
              {results.narrative.length === 0 && <li className="dashboard-notes-empty">No notes from this run.</li>}
              {results.narrative.map((item) => <li key={item}>{item}</li>)}
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
              color={card.source === 'price' ? '#111827' : '#f97316'}
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
          return <CarrierAnalysisCard results={results} currencySymbol={currencySymbol} />;
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
    if (card.kind === 'chart') {
      const label = chartCardTitle(card.config);
      const tf = card.config.timeframe;
      const tfSuffix = tf && tf !== 'hourly' ? ` · ${tf}` : '';
      return `${label}${tfSuffix}`;
    }
    switch (card.kind) {
      case 'map': return 'Network map';
      case 'notes': return 'Run notes';
      case 'kpi-strip': return 'KPIs';
      case 'duration-curve': return card.source === 'price' ? 'Price duration curve' : 'Load duration curve';
      case 'merit-order': return 'Merit order (supply stack)';
      case 'co2-shadow': return 'CO₂ shadow price';
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
        <button
          className={`tb-btn${editing ? ' tb-btn--active' : ''}`}
          onClick={() => setEditing(!editing)}
        >
          {editing ? 'Done editing' : 'Edit layout'}
        </button>

        {showPresets && (
          <>
            <div className="dashboard-toolbar-sep" />
            <div className="dashboard-toolbar-menu">
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
            <div className="dashboard-toolbar-menu">
              <button className="tb-btn" onClick={() => setOpenMenu(openMenu === 'add' ? null : 'add')}>
                + Add card
              </button>
              {openMenu === 'add' && (
                <div className="dashboard-toolbar-pop">
                  <button className="tb-btn" onClick={() => handleAdd('chart')}>Chart</button>
                  <button className="tb-btn" onClick={() => handleAdd('map')}>Map</button>
                  <button className="tb-btn" onClick={() => handleAdd('notes')}>Run notes</button>
                </div>
              )}
            </div>
            <div className="dashboard-toolbar-sep" />
            <button className="tb-btn" onClick={handleSave}>Save layout…</button>
            <div className="dashboard-toolbar-menu">
              <button
                className="tb-btn"
                onClick={() => setOpenMenu(openMenu === 'layouts' ? null : 'layouts')}
                disabled={savedLayouts.length === 0}
              >
                Load…
              </button>
              {openMenu === 'layouts' && savedLayouts.length > 0 && (
                <div className="dashboard-toolbar-pop">
                  {savedLayouts.map((s) => (
                    <div key={s.name} className="dashboard-saved-row">
                      <button className="tb-btn" onClick={() => handleLoad(s.name)} title={`Saved ${new Date(s.updatedAt).toLocaleString()}`}>
                        {s.name}
                      </button>
                      <button className="tb-btn tb-btn--muted" onClick={() => handleDelete(s.name)} title="Delete">
                        ×
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="dashboard-toolbar-sep" />
            <button className="tb-btn tb-btn--muted" onClick={resetToDefault} title="Reset to empty layout">
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
      />
    </div>
  );
}
