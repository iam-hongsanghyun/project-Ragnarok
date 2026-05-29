import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  AnalyticsFocus,
  ChartSectionConfig,
  ChartSectionType,
  GroupByOption,
  MetricOption,
  RunResults,
  TimeframeOption,
  WorkbookModel,
} from '../../../shared/types';
import { clamp, numberValue, stringValue } from '../../../shared/utils/helpers';
import { aggregateMetricRows, buildDonutFromMetric } from '../../../shared/utils/analytics';
import { EMPTY_METRIC_KEY } from '../../../constants';
import { exportChartToExcel } from '../../../shared/utils/exportChart';
import { useToast } from '../../../shared/components/Toast';
import { DonutChart } from './DonutChart';
import { InteractiveTimeSeriesCard } from './InteractiveTimeSeriesCard';
import { TimelineSlider } from '../../../shared/components/DualRangeSlider';
import { useMetricOptions } from '../useMetricOptions';
import { AssetPills } from './AssetPills';

const BUS_AGG_METRIC_KEYS = new Set([
  'gen_output_by_bus',
  'gen_available_by_bus',
  'gen_curtailment_by_bus',
  'gen_emissions_by_bus',
]);

// ── Helpers ───────────────────────────────────────────────────────────────────
type FocusType = AnalyticsFocus['type'];

const FOCUS_LABELS: Record<FocusType, string> = {
  system:      'System',
  generator:   'Generator',
  bus:         'Bus',
  storageUnit: 'Storage Unit',
  store:       'Store',
  branch:      'Branch',
  process:     'Process',
  shuntImpedance: 'Shunt impedance',
};

function assetNamesFor(focusType: FocusType, model: WorkbookModel): string[] {
  switch (focusType) {
    case 'generator':   return model.generators.map((r)    => stringValue(r.name)).filter(Boolean);
    case 'bus':         return model.buses.map((r)          => stringValue(r.name)).filter(Boolean);
    case 'storageUnit': return model.storage_units.map((r) => stringValue(r.name)).filter(Boolean);
    case 'store':       return model.stores.map((r)         => stringValue(r.name)).filter(Boolean);
    case 'branch':      return [
      ...model.lines.map((r)        => stringValue(r.name)),
      ...model.links.map((r)        => stringValue(r.name)),
      ...model.transformers.map((r) => stringValue(r.name)),
    ].filter(Boolean);
    case 'process':     return (model.processes || []).map((r) => stringValue(r.name)).filter(Boolean);
    case 'shuntImpedance': return (model.shunt_impedances || []).map((r) => stringValue(r.name)).filter(Boolean);
    default:            return [];
  }
}

// ── Main component ────────────────────────────────────────────────────────────
export function UserDefinedChartCard({
  section,
  results,
  model,
  onChange,
  onClean,
  onRemove,
  currencySymbol = '$',
  compact = false,
  title,
  onTitleChange,
}: {
  section: ChartSectionConfig;
  results: RunResults | null;
  model: WorkbookModel;
  onChange: (next: ChartSectionConfig) => void;
  onClean: () => void;
  onRemove: () => void;
  currencySymbol?: string;
  /** Compact mode: hide all controls; render only the chart with a gear
   *  button overlay. Opening the gear pops the full settings panel. */
  compact?: boolean;
  /** Card-level title override (set via the modal's Title input). */
  title?: string;
  onTitleChange?: (next: string) => void;
}) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const { showToast } = useToast();
  const [settingsOpen, setSettingsOpen] = useState(false);

  // While the settings modal is open (compact mode) edits are staged in a
  // local draft and only committed to the parent on "Apply" — "Cancel"/Esc
  // discards them. `active` is the config the modal + preview read from.
  const [draft, setDraft] = useState<ChartSectionConfig | null>(null);
  const [draftTitle, setDraftTitle] = useState<string>('');
  const staging = compact && settingsOpen && draft != null;
  const active = staging ? (draft as ChartSectionConfig) : section;
  const activeTitle = staging ? draftTitle : (title ?? '');

  const openSettings = () => {
    setDraft(section);
    setDraftTitle(title ?? '');
    setSettingsOpen(true);
  };
  const cancelSettings = () => { setSettingsOpen(false); setDraft(null); };
  const applySettings = () => {
    if (draft) onChange(draft);
    if (onTitleChange && draftTitle !== (title ?? '')) onTitleChange(draftTitle);
    setSettingsOpen(false);
    setDraft(null);
  };

  /** Stage (compact modal) or apply live (full inline mode) a config patch. */
  const patch = (next: ChartSectionConfig) => {
    if (staging) setDraft(next);
    else onChange(next);
  };

  // Esc cancels the settings modal (discards the draft).
  useEffect(() => {
    if (!settingsOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') cancelSettings(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [settingsOpen]);

  const assetNames = assetNamesFor(active.focusType, model);

  // Bus + carrier filter source lists (used by the secondary pill rows below)
  const busNames = model.buses.map((r) => stringValue(r.name)).filter(Boolean);
  const carrierNames = Array.from(
    new Set(model.generators.map((r) => stringValue(r.carrier)).filter(Boolean)),
  );

  // Per-card metric options from the card's own focus/keys/groupBy/filters
  const metricOptions: MetricOption[] = useMetricOptions(
    results,
    model,
    active.focusType,
    active.focusKeys,
    active.groupBy,
    currencySymbol,
    active.busFilter ?? [],
    active.carrierFilter ?? [],
  );

  const metric     = metricOptions.find((m) => m.key === active.metricKey);
  const hasMetric  = Boolean(metric);
  const metricRows = metric?.rows || [];

  const safeStart = hasMetric
    ? clamp(Math.min(active.startIndex, active.endIndex), 0, Math.max(metricRows.length - 1, 0))
    : 0;
  const safeEnd = hasMetric
    ? clamp(Math.max(active.endIndex, safeStart), safeStart, Math.max(metricRows.length - 1, 0))
    : 0;
  const aggregatedRows = hasMetric
    ? aggregateMetricRows(metric!, safeStart, safeEnd, active.timeframe)
    : [];

  // Show Group by when:
  //   - Generator focus with multi/all selection, OR
  //   - Bus focus with one of the generator-aggregated metrics picked
  const isMultiOrAll  = active.focusType !== 'system' && active.focusKeys.length !== 1;
  const showGroupBy   =
    (isMultiOrAll && active.focusType === 'generator') ||
    (active.focusType === 'bus' && BUS_AGG_METRIC_KEYS.has(active.metricKey));

  // Filter rows visibility
  const showBusFilter     = ['generator', 'storageUnit', 'store'].includes(active.focusType) && busNames.length > 0;
  const showCarrierFilter = active.focusType === 'generator' && carrierNames.length > 0;

  // ── Handlers ──────────────────────────────────────────────────────────────

  const resetMetric = (extra: Partial<ChartSectionConfig> = {}) =>
    patch({ ...active, metricKey: EMPTY_METRIC_KEY, startIndex: 0, endIndex: 0, ...extra });

  const handleFocusTypeChange = (newType: FocusType) => {
    const names = assetNamesFor(newType, model);
    resetMetric({
      focusType: newType,
      focusKeys: newType === 'system' ? [] : [],  // start with "All" for non-system too
      groupBy: 'carrier',
      busFilter: [],
      carrierFilter: [],
    });
    void names; // suppress lint
  };

  const handleMetricChange = (newKey: string) => {
    const m   = metricOptions.find((x) => x.key === newKey);
    const len = m?.rows.length || 1;
    patch({ ...active, metricKey: newKey, startIndex: 0, endIndex: Math.max(len - 1, 0) });
  };

  const handleExport = () => {
    if (!metric) return;
    let promise: Promise<void>;
    if (active.chartType === 'donut') {
      const data = buildDonutFromMetric(metric, safeStart, safeEnd);
      promise = exportChartToExcel(
        metric.label,
        ['label', 'value'],
        data.map((d) => ({ label: d.label, value: d.value })),
        chartContainerRef.current,
      );
    } else {
      const keys    = metric.series.map((s) => s.key);
      const headers = ['timestamp', ...keys];
      const rows    = aggregatedRows.map((r) => {
        const row: Record<string, unknown> = { timestamp: r.timestamp ?? r.label };
        keys.forEach((k) => { row[k] = numberValue(r[k] as any); });
        return row;
      });
      promise = exportChartToExcel(metric.label, headers, rows, chartContainerRef.current);
    }
    promise
      .then(() => showToast(`Exported ${metric.label}`, 'success'))
      .catch(()  => showToast('Export failed', 'error'));
  };

  // ── Settings panel (extracted so both compact and full modes can render it) ──
  const settingsPanel = (
    <>
      {/* controls row */}
      <div className="chart-builder-controls">

        {/* Component */}
        <label className="chart-control">
          <span>Component</span>
          <select
            value={active.focusType}
            onChange={(e) => handleFocusTypeChange(e.target.value as FocusType)}
          >
            {(Object.keys(FOCUS_LABELS) as FocusType[]).map((ft) => (
              <option key={ft} value={ft} disabled={ft !== 'system' && assetNamesFor(ft, model).length === 0}>
                {FOCUS_LABELS[ft]}
              </option>
            ))}
          </select>
        </label>

        {/* Value */}
        <label className="chart-control">
          <span>Value</span>
          <select
            value={active.metricKey}
            onChange={(e) => handleMetricChange(e.target.value)}
            disabled={!results}
          >
            <option value={EMPTY_METRIC_KEY}>Select value</option>
            {metricOptions.map((m) => (
              <option key={m.key} value={m.key}>{m.label}</option>
            ))}
          </select>
        </label>

        {/* Group by — only for generator multi/all */}
        {showGroupBy && (
          <label className="chart-control">
            <span>Group by</span>
            <select
              value={active.groupBy}
              onChange={(e) =>
                patch({ ...active, groupBy: e.target.value as GroupByOption })
              }
            >
              <option value="carrier">Carrier</option>
              <option value="asset">Asset</option>
            </select>
          </label>
        )}

        {/* Temporal resolution */}
        <label className="chart-control">
          <span>Temporal resolution</span>
          <select
            value={active.timeframe}
            onChange={(e) => patch({ ...active, timeframe: e.target.value as TimeframeOption })}
          >
            <option value="aggregated">Aggregated</option>
            <option value="yearly">By year</option>
            <option value="monthly">By month</option>
            <option value="weekly">By week</option>
            <option value="daily">By day</option>
            <option value="hourly">By hour</option>
          </select>
        </label>

        {/* Chart type */}
        <label className="chart-control">
          <span>Chart</span>
          <select
            value={active.chartType}
            onChange={(e) => patch({ ...active, chartType: e.target.value as ChartSectionType })}
            disabled={!hasMetric}
          >
            <option value="line">Line</option>
            <option value="area">Area</option>
            <option value="bar">Bar</option>
            <option value="donut">Donut</option>
          </select>
        </label>

        {/* Stack */}
        {active.chartType !== 'donut' && (
          <label className="chart-control">
            <span>Stack</span>
            <select
              value={active.stacked ? 'stacked' : 'normal'}
              onChange={(e) => patch({ ...active, stacked: e.target.value === 'stacked' })}
              disabled={!hasMetric}
            >
              <option value="stacked">Stacked</option>
              <option value="normal">Normal</option>
            </select>
          </label>
        )}
      </div>

      {/* Appearance — axis titles, legend, tick labels (time-series only) */}
      {active.chartType !== 'donut' && (
        <div className="chart-builder-controls">
          <label className="chart-control">
            <span>X-axis title</span>
            <input
              type="text"
              value={active.xAxisTitle ?? ''}
              placeholder="none"
              onChange={(e) => patch({ ...active, xAxisTitle: e.target.value })}
            />
          </label>
          <label className="chart-control">
            <span>Y-axis title</span>
            <input
              type="text"
              value={active.yAxisTitle ?? ''}
              placeholder="none"
              onChange={(e) => patch({ ...active, yAxisTitle: e.target.value })}
            />
          </label>
          <label className="chart-control">
            <span>Legend</span>
            <select
              value={(active.showLegend ?? true) ? 'show' : 'hide'}
              onChange={(e) => patch({ ...active, showLegend: e.target.value === 'show' })}
            >
              <option value="show">Show</option>
              <option value="hide">Hide</option>
            </select>
          </label>
          <label className="chart-control">
            <span>Axis labels</span>
            <select
              value={(active.showAxisLabels ?? true) ? 'show' : 'hide'}
              onChange={(e) => patch({ ...active, showAxisLabels: e.target.value === 'show' })}
            >
              <option value="show">Show</option>
              <option value="hide">Hide</option>
            </select>
          </label>
          <label className="chart-control">
            <span>X-label angle</span>
            <select
              value={String(active.xLabelAngle ?? 0)}
              onChange={(e) => patch({ ...active, xLabelAngle: Number(e.target.value) })}
            >
              <option value="0">Horizontal</option>
              <option value="-30">-30°</option>
              <option value="-45">-45°</option>
              <option value="-90">Vertical</option>
            </select>
          </label>
        </div>
      )}

      {/* Asset pill multi-select (hidden for system) */}
      {active.focusType !== 'system' && assetNames.length > 0 && (
        <div className="chart-control-row">
          <span className="chart-control-label">Assets</span>
          <AssetPills
            names={assetNames}
            selected={active.focusKeys}
            onChange={(keys) => patch({ ...active, focusKeys: keys })}
          />
        </div>
      )}

      {/* Secondary filter: bus (generator / storage unit / store) */}
      {showBusFilter && (
        <div className="chart-control-row">
          <span className="chart-control-label">Filter by bus</span>
          <AssetPills
            names={busNames}
            selected={active.busFilter ?? []}
            onChange={(keys) => patch({ ...active, busFilter: keys })}
          />
        </div>
      )}

      {/* Secondary filter: carrier (generator only) */}
      {showCarrierFilter && (
        <div className="chart-control-row">
          <span className="chart-control-label">Filter by carrier</span>
          <AssetPills
            names={carrierNames}
            selected={active.carrierFilter ?? []}
            onChange={(keys) => patch({ ...active, carrierFilter: keys })}
          />
        </div>
      )}

      {/* Timeline slider */}
      {hasMetric && (
        <TimelineSlider
          data={metric!.rows}
          startIndex={safeStart}
          endIndex={safeEnd}
          onChange={(lo, hi) => patch({ ...active, startIndex: lo, endIndex: hi })}
        />
      )}

    </>
  );

  const chartBody = (
    <div ref={chartContainerRef} className="chart-body">
      {!hasMetric ? (
        <div className="chart-empty-state">
          <p className="empty-text">{compact ? 'Click ⚙ to configure this chart.' : 'Choose component, assets, value and chart type.'}</p>
        </div>
      ) : active.chartType === 'donut' ? (
        <section className="chart-card">
          {!compact && (
            <div className="chart-card-header">
              <div><h3>{metric!.label}</h3><p>average {metric!.unit} over window</p></div>
            </div>
          )}
          {buildDonutFromMetric(metric!, safeStart, safeEnd).length > 0
            ? <DonutChart data={buildDonutFromMetric(metric!, safeStart, safeEnd)} />
            : <p className="empty-text">No data for current selection.</p>
          }
        </section>
      ) : (
        <InteractiveTimeSeriesCard
          title={compact ? '' : metric!.label}
          description={compact ? '' : `${active.timeframe} · ${metric!.unit}`}
          data={aggregatedRows}
          series={metric!.series}
          mode={active.chartType}
          stacked={active.stacked}
          xAxisTitle={active.xAxisTitle}
          yAxisTitle={active.yAxisTitle}
          showLegend={active.showLegend ?? true}
          showAxisLabels={active.showAxisLabels ?? true}
          xLabelAngle={active.xLabelAngle ?? 0}
        />
      )}
    </div>
  );

  // ── Compact render (Bloomberg dashboard cell) ────────────────────────────
  if (compact) {
    return (
      <div className={`chart-builder-compact${settingsOpen ? ' is-settings-open' : ''}`}>
        <button
          type="button"
          className="chart-builder-gear"
          onClick={openSettings}
          aria-label="Chart settings"
          title="Chart settings"
        >
          ⚙
        </button>
        {chartBody}
        {settingsOpen && createPortal(
          <div
            className="chart-modal-backdrop"
            onClick={cancelSettings}
            role="dialog"
            aria-modal="true"
          >
            <div className="chart-modal" onClick={(e) => e.stopPropagation()}>
              <div className="chart-modal-head">
                <div>
                  <strong>{hasMetric ? metric!.label : 'Configure chart'}</strong>
                  {hasMetric && <p className="chart-modal-sub">{metric!.unit}</p>}
                </div>
                <div className="chart-modal-actions">
                  {hasMetric && <button className="tb-btn" onClick={handleExport}>Export</button>}
                  <button className="tb-btn" onClick={onClean}>Clean</button>
                  <button className="tb-btn" onClick={cancelSettings}>Cancel</button>
                  <button className="tb-btn tb-btn--active" onClick={applySettings}>Apply</button>
                  <button
                    className="chart-modal-close"
                    onClick={cancelSettings}
                    aria-label="Close settings"
                    title="Cancel (Esc)"
                  >
                    ×
                  </button>
                </div>
              </div>
              <div className="chart-modal-body">
                {onTitleChange && (
                  <div className="chart-modal-meta-row">
                    <label className="chart-control">
                      <span>Card title</span>
                      <input
                        type="text"
                        value={activeTitle}
                        placeholder="auto"
                        onChange={(e) => setDraftTitle(e.target.value)}
                      />
                    </label>
                  </div>
                )}
                {settingsPanel}
              </div>
            </div>
          </div>,
          document.body,
        )}
      </div>
    );
  }

  // ── Full render (legacy / non-dashboard context) ─────────────────────────
  return (
    <section className="chart-card chart-builder-card">
      {/* header row */}
      <div className="chart-card-header chart-card-controls">
        <div>
          <h3>{hasMetric ? metric!.label : 'Empty chart'}</h3>
          <p>{hasMetric ? metric!.unit : 'Select a component and value to render a chart.'}</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {hasMetric && (
            <button className="ghost-button chart-export-btn" onClick={handleExport}>Export</button>
          )}
          <button className="ghost-button" onClick={onClean}>Clean</button>
          <button className="ghost-button" style={{ color: '#dc2626' }} onClick={onRemove}>Remove</button>
        </div>
      </div>
      {settingsPanel}
      {chartBody}
    </section>
  );
}
