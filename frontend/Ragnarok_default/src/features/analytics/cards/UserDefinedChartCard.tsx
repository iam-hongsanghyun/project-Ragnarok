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
} from 'lib/types';
import { clamp, numberValue, stringValue } from 'lib/utils/helpers';
import { aggregateMetricRows, buildDonutFromMetric } from 'lib/results/analytics';
import { EMPTY_METRIC_KEY } from 'lib/constants';
import { exportChartToExcel } from 'lib/export/chart';
import { useToast } from '../../../shared/components/Toast';
import { DonutChart } from './DonutChart';
import { InteractiveTimeSeriesCard } from './InteractiveTimeSeriesCard';
import { TimelineSlider } from '../../../shared/components/DualRangeSlider';
import { useMetricOptions } from '../useMetricOptions';
import { AssetPills } from './AssetPills';
import { SearchableSelect } from '../../../shared/components/SearchableSelect';

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

  // The donut is the SUM over the SELECTED period — it tracks the range slider
  // (safeStart/safeEnd), and buildDonutFromMetric sums the raw per-snapshot
  // values across that range.
  const donutData = hasMetric && active.chartType === 'donut'
    ? buildDonutFromMetric(metric!, safeStart, safeEnd)
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
      const data = donutData;
      // Donut legend = the slices (label + colour), so the exported image is
      // self-describing even though the on-screen legend is HTML outside the SVG.
      promise = exportChartToExcel(
        metric.label,
        ['label', 'value'],
        data.map((d) => ({ label: d.label, value: d.value })),
        chartContainerRef.current,
        undefined,
        { title: metric.label, unit: metric.unit, legend: data.map((d) => ({ label: d.label, color: d.color })) },
      );
    } else {
      const keys    = metric.series.map((s) => s.key);
      const headers = ['timestamp', ...keys];
      const rows    = aggregatedRows.map((r) => {
        const row: Record<string, unknown> = { timestamp: r.timestamp ?? r.label };
        keys.forEach((k) => { row[k] = numberValue(r[k] as any); });
        return row;
      });
      promise = exportChartToExcel(
        metric.label,
        headers,
        rows,
        chartContainerRef.current,
        undefined,
        { title: metric.label, unit: metric.unit, legend: metric.series.map((s) => ({ label: s.label, color: s.color })) },
      );
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
          <SearchableSelect
            value={active.focusType}
            options={(Object.keys(FOCUS_LABELS) as FocusType[])
              .filter((ft) => ft === 'system' || assetNamesFor(ft, model).length > 0)
              .map((ft) => ({ value: ft, label: FOCUS_LABELS[ft] }))}
            onChange={(v) => handleFocusTypeChange(v as FocusType)}
          />
        </label>

        {/* Value */}
        <label className="chart-control">
          <span>Value</span>
          <SearchableSelect
            value={active.metricKey}
            disabled={!results}
            options={[{ value: EMPTY_METRIC_KEY, label: 'Select value' }, ...metricOptions.map((m) => ({ value: m.key, label: m.label }))]}
            onChange={(v) => handleMetricChange(v)}
          />
        </label>

        {/* Group by — only for generator multi/all */}
        {showGroupBy && (
          <label className="chart-control">
            <span>Group by</span>
            <SearchableSelect
              value={active.groupBy}
              options={[
                { value: 'carrier', label: 'Carrier' },
                { value: 'asset', label: 'Asset' },
              ]}
              onChange={(v) => patch({ ...active, groupBy: v as GroupByOption })}
            />
          </label>
        )}

        {/* Temporal resolution — irrelevant for a donut, which always shows the
            fully-aggregated total over the entire period. Hide it there so it
            doesn't look like a control that does nothing. */}
        {active.chartType !== 'donut' && (
          <label className="chart-control">
            <span>Temporal resolution</span>
            <SearchableSelect
              value={active.timeframe}
              options={[
                { value: 'aggregated', label: 'Aggregated' },
                { value: 'yearly', label: 'By year' },
                { value: 'monthly', label: 'By month' },
                { value: 'weekly', label: 'By week' },
                { value: 'daily', label: 'By day' },
                { value: 'hourly', label: 'By hour' },
              ]}
              onChange={(v) => patch({ ...active, timeframe: v as TimeframeOption })}
            />
          </label>
        )}

        {/* Chart type */}
        <label className="chart-control">
          <span>Chart</span>
          <SearchableSelect
            value={active.chartType}
            disabled={!hasMetric}
            options={[
              { value: 'line', label: 'Line' },
              { value: 'area', label: 'Area' },
              { value: 'bar', label: 'Bar' },
              { value: 'donut', label: 'Donut' },
            ]}
            onChange={(v) => patch({ ...active, chartType: v as ChartSectionType })}
          />
        </label>

        {/* Stack */}
        {active.chartType !== 'donut' && (
          <label className="chart-control">
            <span>Stack</span>
            <SearchableSelect
              value={active.stacked ? 'stacked' : 'normal'}
              disabled={!hasMetric}
              options={[
                { value: 'stacked', label: 'Stacked' },
                { value: 'normal', label: 'Normal' },
              ]}
              onChange={(v) => patch({ ...active, stacked: v === 'stacked' })}
            />
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
            <SearchableSelect
              value={(active.showLegend ?? true) ? 'show' : 'hide'}
              options={[{ value: 'show', label: 'Show' }, { value: 'hide', label: 'Hide' }]}
              onChange={(v) => patch({ ...active, showLegend: v === 'show' })}
            />
          </label>
          <label className="chart-control">
            <span>Axis labels</span>
            <SearchableSelect
              value={(active.showAxisLabels ?? true) ? 'show' : 'hide'}
              options={[{ value: 'show', label: 'Show' }, { value: 'hide', label: 'Hide' }]}
              onChange={(v) => patch({ ...active, showAxisLabels: v === 'show' })}
            />
          </label>
          <label className="chart-control">
            <span>X-label angle</span>
            <SearchableSelect
              value={String(active.xLabelAngle ?? 0)}
              options={[
                { value: '0', label: 'Horizontal' },
                { value: '-30', label: '-30°' },
                { value: '-45', label: '-45°' },
                { value: '-90', label: 'Vertical' },
              ]}
              onChange={(v) => patch({ ...active, xLabelAngle: Number(v) })}
            />
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

      {/* Timeline slider — drives the visible window for line/bar charts AND the
          summed range for donuts. */}
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
          <p className="empty-text">{compact ? 'Click the settings button to configure this chart.' : 'Choose component, assets, value and chart type.'}</p>
        </div>
      ) : active.chartType === 'donut' ? (
        <section className="chart-card">
          {!compact && (
            <div className="chart-card-header">
              <div><h3>{metric!.label}</h3><p>total {metric!.unit} over the selected period</p></div>
            </div>
          )}
          {donutData.length > 0
            ? <DonutChart data={donutData} />
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
        />
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
          <button className="ghost-button" style={{ color: 'var(--danger)' }} onClick={onRemove}>Remove</button>
        </div>
      </div>
      {settingsPanel}
      {chartBody}
    </section>
  );
}
