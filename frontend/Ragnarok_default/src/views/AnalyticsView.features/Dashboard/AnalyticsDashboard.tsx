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
import { numberValue } from 'lib/utils/helpers';
import { Dashboard, newId } from './Dashboard';
import { Card, DashboardLayout } from 'lib/dashboard/types';
import { useDashboardLayout } from './useDashboardLayout';
import { PRESETS } from 'lib/dashboard/presets';
import { DEFAULT_CHART_WINDOW_HOURS, OUTPUT_SHEETS_FOR_FOCUS } from 'lib/api/runs';

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

function newChartCard(): Card { return { id: newId('chart'), kind: 'chart', config: defaultChartConfig() }; }
function newMapCard(): Card   { return { id: newId('map'),   kind: 'map' }; }
function newNotesCard(): Card { return { id: newId('notes'), kind: 'notes' }; }

/** Kinds offered from an empty placeholder cell's "+" menu. */
const ADDABLE_CARDS = [
  { kind: 'chart', label: 'Chart' },
  { kind: 'map',   label: 'Map' },
  { kind: 'notes', label: 'Run notes' },
];

function createCard(kind: string): Card {
  switch (kind) {
    case 'map':   return newMapCard();
    case 'notes': return newNotesCard();
    default:      return newChartCard();
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
  /** Report, per output-series sheet, the MAX temporal window (hours; null =
   *  whole run) the current layout's per-asset charts ask for, so the parent
   *  hydrates only those sheets at the length needed. Each chart sets its own
   *  window in its gear. Empty when the layout is system-only. */
  onNeedSeries?: (windows: Record<string, number | null>) => void;
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

  // Tell the parent, per output-series sheet, the MAX temporal window the
  // layout's per-asset charts ask for (each chart sets its own in its gear), so
  // it hydrates only those sheets at the length needed. Runs on layout change
  // (chart added / window changed / preset loaded), not every render. A
  // system-only layout reports {} → no fetch → the common result view is instant.
  useEffect(() => {
    if (!onNeedSeries) return;
    const windows: Record<string, number | null> = {};
    for (const card of layout.cards) {
      if (card.kind !== 'chart' || card.config.focusType === 'system') continue;
      const hours = card.config.windowHours === undefined
        ? DEFAULT_CHART_WINDOW_HOURS
        : card.config.windowHours;
      for (const sheet of OUTPUT_SHEETS_FOR_FOCUS[card.config.focusType] ?? []) {
        if (!(sheet in windows)) windows[sheet] = hours;
        else {
          const cur = windows[sheet];
          // null (full run) wins; otherwise keep the longer window.
          windows[sheet] = cur == null || hours == null ? null : Math.max(cur, hours);
        }
      }
    }
    onNeedSeries(windows);
  }, [layout, onNeedSeries]);
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
          window.alert('That file is not a valid dashboard layout.');
        }
      } catch {
        window.alert('Could not read that file as JSON.');
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
