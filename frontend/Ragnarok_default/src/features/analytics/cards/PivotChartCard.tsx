import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ChartMode, RunResults, TimeframeOption, WorkbookModel } from 'lib/types';
import { PivotChartConfig, PivotChartType, PivotFilter, PivotFilterOp } from 'lib/dashboard/types';
import { clamp, numberValue } from 'lib/utils/helpers';
import { effectiveEndIndex, fullRunTimeline } from 'lib/api/runs';
import { exportChartToExcel } from 'lib/export/chart';
import { useToast } from '../../../shared/components/Toast';
import { DonutChart } from './DonutChart';
import { InteractiveTimeSeriesCard } from './InteractiveTimeSeriesCard';
import { DurationCurveCard } from './DurationCurveCard';
import { CategoryBarCard } from './CategoryBarCard';
import { ScatterPlotCard } from './ScatterPlotCard';
import { TimelineSlider } from '../../../shared/components/DualRangeSlider';
import { SearchableSelect } from '../../../shared/components/SearchableSelect';
import { SearchableMultiSelect } from '../../../shared/components/SearchableMultiSelect';
import {
  buildPivotCategory,
  buildPivotDailyProfile,
  buildPivotDurationCurve,
  buildPivotMix,
  buildPivotScatter,
  buildPivotSeries,
  pivotComponents,
  pivotDimensionFields,
  pivotFieldNumeric,
  pivotUniqueValues,
  pivotValueAttributes,
  pivotValueKind,
} from 'lib/results/pivot';

const AGG_OPTIONS = [
  { value: 'sum', label: 'Sum' },
  { value: 'mean', label: 'Mean' },
  { value: 'max', label: 'Max' },
  { value: 'min', label: 'Min' },
  { value: 'count', label: 'Count' },
];
const NUMERIC_OPS: PivotFilterOp[] = ['>', '>=', '<', '<=', '='];
// Chart types that need a time axis (offered only for series value attributes).
const SERIES_ONLY: PivotChartType[] = ['line', 'area', 'duration', 'daily-profile'];
// Chart types that carry a stack control.
const STACKABLE: PivotChartType[] = ['bar', 'area', 'grouped-bar', 'hbar', 'daily-profile'];

export function PivotChartCard({
  config,
  results,
  model,
  onChange,
  onClean,
  compact = false,
  title,
  onTitleChange,
}: {
  config: PivotChartConfig;
  results: RunResults | null;
  model: WorkbookModel;
  onChange: (next: PivotChartConfig) => void;
  onClean: () => void;
  compact?: boolean;
  title?: string;
  onTitleChange?: (next: string) => void;
}) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [draft, setDraft] = useState<PivotChartConfig | null>(null);
  const [draftTitle, setDraftTitle] = useState('');
  const staging = compact && settingsOpen && draft != null;
  const active = staging ? (draft as PivotChartConfig) : config;
  const activeTitle = staging ? draftTitle : (title ?? '');

  const openSettings = () => { setDraft(config); setDraftTitle(title ?? ''); setSettingsOpen(true); };
  const cancelSettings = () => { setSettingsOpen(false); setDraft(null); };
  const applySettings = () => {
    if (draft) onChange(draft);
    if (onTitleChange && draftTitle !== (title ?? '')) onTitleChange(draftTitle);
    setSettingsOpen(false); setDraft(null);
  };
  const patch = (next: PivotChartConfig) => { if (staging) setDraft(next); else onChange(next); };

  useEffect(() => {
    if (!settingsOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') cancelSettings(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [settingsOpen]);

  const { showToast } = useToast();
  const chartContainerRef = useRef<HTMLDivElement>(null);

  // ── Enumerations ──────────────────────────────────────────────────────────
  const components = pivotComponents(results, model);
  const valueAttrs = pivotValueAttributes(active.sheet);
  const dimFields = pivotDimensionFields(active.sheet, model);
  const hasValue = !!active.valueAttribute;
  const kind = hasValue ? pivotValueKind(active.sheet, active.valueAttribute) : null;
  const isSeries = kind === 'series';
  const unit = valueAttrs.find((a) => a.value === active.valueAttribute)?.unit ?? '';

  // ── Window (series only) ──────────────────────────────────────────────────
  const snapshotWeight = results?.runMeta?.snapshotWeight ?? 1;
  const fullTimeline = fullRunTimeline(results);
  const totalSnaps = fullTimeline.length;
  const effEnd = effectiveEndIndex('generator', active.endIndex, totalSnaps, snapshotWeight);
  const effStart = clamp(active.startIndex, 0, effEnd);
  const buildCfg: PivotChartConfig = { ...active, startIndex: effStart, endIndex: effEnd };

  // ── Handlers ──────────────────────────────────────────────────────────────
  const handleSheet = (sheet: string) =>
    patch({ ...active, sheet, valueAttribute: '', groupBy: [], filters: [], startIndex: 0, endIndex: 100000 });
  const handleValue = (valueAttribute: string) => {
    const k = pivotValueKind(active.sheet, valueAttribute);
    // Static / input have no time axis — fall back series-only types to bar.
    const chartType = k === 'series' || !SERIES_ONLY.includes(active.chartType) ? active.chartType : 'bar';
    patch({ ...active, valueAttribute, chartType, startIndex: 0, endIndex: 100000 });
  };
  const updateFilter = (i: number, next: PivotFilter) =>
    patch({ ...active, filters: active.filters.map((f, idx) => (idx === i ? next : f)) });
  const addFilter = () =>
    patch({ ...active, filters: [...active.filters, { scope: 'component', field: dimFields[0] ?? '', op: 'in', values: [] }] });
  const removeFilter = (i: number) => patch({ ...active, filters: active.filters.filter((_, idx) => idx !== i) });

  // Export the pivot's data + chart image to an Excel workbook (same as the
  // metric chart's Export).
  const handleExport = () => {
    if (!hasValue) return;
    const label = `${active.sheet} · ${active.valueAttribute}`;
    let promise: Promise<void>;
    if (active.chartType === 'donut') {
      const { data } = buildPivotMix(buildCfg, results, model, snapshotWeight);
      const donutUnit = unit === 'MW' ? 'MWh' : unit;
      promise = exportChartToExcel(
        label, ['label', 'value'], data.map((d) => ({ label: d.label, value: d.value })),
        chartContainerRef.current, undefined,
        { title: label, unit: donutUnit, legend: data.map((d) => ({ label: d.label, color: d.color })) },
      );
    } else if (active.chartType === 'scatter') {
      const { points } = buildPivotScatter(buildCfg, results, model, snapshotWeight);
      promise = exportChartToExcel(
        label, ['label', active.valueAttribute, active.scatterYAttribute ?? 'y'],
        points.map((p) => ({ label: p.label, [active.valueAttribute]: p.x, [active.scatterYAttribute ?? 'y']: p.y })),
        chartContainerRef.current, undefined, { title: label, unit },
      );
    } else if (active.chartType === 'hbar' || active.chartType === 'grouped-bar') {
      const { labels, series } = buildPivotCategory(buildCfg, results, model, snapshotWeight);
      const keys = series.map((s) => s.key);
      const exportRows = labels.map((lbl, i) => {
        const o: Record<string, unknown> = { category: lbl };
        keys.forEach((k, j) => { o[series[j].label] = series.find((s) => s.key === k)?.values[i] ?? 0; });
        return o;
      });
      promise = exportChartToExcel(
        label, ['category', ...series.map((s) => s.label)], exportRows, chartContainerRef.current, undefined,
        { title: label, unit, legend: series.map((s) => ({ label: s.label, color: s.color })) },
      );
    } else if (active.chartType === 'duration') {
      const { values } = buildPivotDurationCurve(buildCfg, results, model, snapshotWeight);
      promise = exportChartToExcel(
        label, ['rank', 'value'], values.map((v, i) => ({ rank: i + 1, value: v })),
        chartContainerRef.current, undefined, { title: label, unit },
      );
    } else {
      const { rows, series } = active.chartType === 'daily-profile'
        ? buildPivotDailyProfile(buildCfg, results, model, snapshotWeight)
        : buildPivotSeries(buildCfg, results, model, snapshotWeight);
      const keys = series.map((s) => s.key);
      const exportRows = rows.map((r) => {
        const o: Record<string, unknown> = { timestamp: r.timestamp ?? r.label };
        keys.forEach((k) => { o[k] = numberValue(r[k] as string | number | undefined); });
        return o;
      });
      promise = exportChartToExcel(
        label, ['timestamp', ...keys], exportRows, chartContainerRef.current, undefined,
        { title: label, unit, legend: series.map((s) => ({ label: s.label, color: s.color })) },
      );
    }
    promise.then(() => showToast(`Exported ${label}`, 'success')).catch(() => showToast('Export failed', 'error'));
  };

  // ── Chart body ────────────────────────────────────────────────────────────
  // Universal types work for any value; line/area/duration/daily-profile need a
  // time axis (series only).
  const chartTypeOptions = [
    ...(isSeries ? [{ value: 'line', label: 'Line' }, { value: 'area', label: 'Area' }] : []),
    { value: 'bar', label: 'Bar' },
    { value: 'grouped-bar', label: 'Grouped bar' },
    { value: 'hbar', label: 'Horizontal bar' },
    { value: 'donut', label: 'Donut' },
    { value: 'scatter', label: 'Scatter' },
    ...(isSeries ? [{ value: 'duration', label: 'Duration curve' }, { value: 'daily-profile', label: 'Daily profile' }] : []),
  ];

  const loadingBody = <div className="chart-empty-state"><p className="empty-text">Loading series…</p></div>;
  const emptyBody = (msg: string) => <div className="chart-empty-state"><p className="empty-text">{msg}</p></div>;

  const chartBody = (() => {
    if (!hasValue) {
      return emptyBody(compact ? 'Click the settings button to configure this chart.' : 'Pick a component and attribute.');
    }
    const ct = active.chartType;
    if (ct === 'donut') {
      const { data, loading } = buildPivotMix(buildCfg, results, model, snapshotWeight);
      if (loading) return loadingBody;
      return data.length ? <DonutChart data={data} unit={unit === 'MW' ? 'MWh' : unit} /> : emptyBody('No data for current selection.');
    }
    if (ct === 'scatter') {
      const sc = buildPivotScatter(buildCfg, results, model, snapshotWeight);
      if (sc.loading) return loadingBody;
      return (
        <ScatterPlotCard
          data={sc}
          xName={active.xAxisTitle || `${active.valueAttribute}${sc.xUnit ? ` (${sc.xUnit})` : ''}`}
          yName={active.yAxisTitle || `${active.scatterYAttribute ?? 'Y'}${sc.yUnit ? ` (${sc.yUnit})` : ''}`}
          showAxisLabels={active.showAxisLabels ?? true}
        />
      );
    }
    if (ct === 'hbar' || ct === 'grouped-bar') {
      const data = buildPivotCategory(buildCfg, results, model, snapshotWeight);
      if (data.loading) return loadingBody;
      return data.labels.length
        ? (
          <CategoryBarCard
            data={data} mode={ct} stacked={active.stacked} unit={unit}
            title={compact ? '' : active.valueAttribute} description={compact ? '' : unit}
            showLegend={active.showLegend ?? true} showAxisLabels={active.showAxisLabels ?? true}
            xAxisTitle={active.xAxisTitle} yAxisTitle={active.yAxisTitle || unit} xLabelAngle={active.xLabelAngle ?? 0}
          />
        )
        : emptyBody('No data for current selection.');
    }
    if (ct === 'duration') {
      const { values, color, unit: u, loading } = buildPivotDurationCurve(buildCfg, results, model, snapshotWeight);
      if (loading) return loadingBody;
      return values.length ? <DurationCurveCard title={compact ? '' : active.valueAttribute} data={values} unit={u} color={color} /> : emptyBody('No data for current selection.');
    }
    // line / area / bar (time axis) and daily-profile all feed InteractiveTimeSeriesCard.
    const { rows, series, loading } = ct === 'daily-profile'
      ? buildPivotDailyProfile(buildCfg, results, model, snapshotWeight)
      : buildPivotSeries(buildCfg, results, model, snapshotWeight);
    if (loading) return loadingBody;
    return (
      <InteractiveTimeSeriesCard
        title={compact ? '' : active.valueAttribute}
        description={compact ? '' : (ct === 'daily-profile' ? `${unit} · by hour-of-day` : unit)}
        data={rows}
        series={series}
        mode={ct === 'daily-profile' ? 'bar' : (ct as ChartMode)}
        stacked={active.stacked}
        xAxisTitle={active.xAxisTitle}
        yAxisTitle={active.yAxisTitle || unit}
        showLegend={active.showLegend ?? true}
        showAxisLabels={active.showAxisLabels ?? true}
        xLabelAngle={active.xLabelAngle ?? 0}
      />
    );
  })();

  // ── Settings panel ────────────────────────────────────────────────────────
  const settingsPanel = (
    <>
      <div className="chart-builder-controls">
        <label className="chart-control">
          <span>Component</span>
          <SearchableSelect value={active.sheet} options={components} onChange={handleSheet} />
        </label>
        <label className="chart-control">
          <span>{active.chartType === 'scatter' ? 'X attribute' : 'Attribute'}</span>
          <SearchableSelect
            value={active.valueAttribute}
            disabled={!results}
            options={[{ value: '', label: 'Select attribute' }, ...valueAttrs.map((a) => ({ value: a.value, label: a.label }))]}
            onChange={handleValue}
          />
        </label>
        {active.chartType === 'scatter' && (
          <label className="chart-control">
            <span>Y attribute</span>
            <SearchableSelect
              value={active.scatterYAttribute ?? ''}
              disabled={!results}
              options={[{ value: '', label: 'Select Y attribute' }, ...valueAttrs.map((a) => ({ value: a.value, label: a.label }))]}
              onChange={(v) => patch({ ...active, scatterYAttribute: v })}
            />
          </label>
        )}
        {active.chartType !== 'scatter' && (
          <label className="chart-control">
            <span>Aggregate</span>
            <SearchableSelect value={active.aggregate} options={AGG_OPTIONS} onChange={(v) => patch({ ...active, aggregate: v as PivotChartConfig['aggregate'] })} />
          </label>
        )}
        <label className="chart-control">
          <span>Chart</span>
          <SearchableSelect value={active.chartType} disabled={!hasValue} options={chartTypeOptions} onChange={(v) => patch({ ...active, chartType: v as PivotChartType })} />
        </label>
        {isSeries && !['donut', 'scatter', 'duration', 'daily-profile'].includes(active.chartType) && (
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
        {STACKABLE.includes(active.chartType) && (
          <label className="chart-control">
            <span>Stack</span>
            <SearchableSelect
              value={active.stacked ? 'stacked' : 'normal'}
              options={[{ value: 'stacked', label: 'Stacked' }, { value: 'normal', label: 'Normal' }]}
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
            <input type="text" value={active.xAxisTitle ?? ''} placeholder="none" onChange={(e) => patch({ ...active, xAxisTitle: e.target.value })} />
          </label>
          <label className="chart-control">
            <span>Y-axis title</span>
            <input type="text" value={active.yAxisTitle ?? ''} placeholder={unit || 'none'} onChange={(e) => patch({ ...active, yAxisTitle: e.target.value })} />
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

      {/* Group by — multiple input dimensions */}
      <div className="chart-control-row">
        <span className="chart-control-label">Group by</span>
        <SearchableMultiSelect
          values={active.groupBy}
          options={dimFields}
          placeholder="Per component"
          onChange={(keys) => patch({ ...active, groupBy: keys })}
        />
      </div>

      {/* Filters */}
      <div className="chart-control-row chart-control-row--stack">
        <span className="chart-control-label">Filters</span>
        <div className="pivot-filters">
          {active.filters.map((f, i) => {
            const numeric = f.scope === 'value' || (f.field && pivotFieldNumeric(active.sheet, model, f.field));
            const ops = numeric ? NUMERIC_OPS : ['in' as PivotFilterOp];
            return (
              <div className="pivot-filter-row" key={i}>
                <SearchableSelect
                  className="pivot-filter-scope"
                  value={f.scope}
                  options={[{ value: 'component', label: 'Component' }, { value: 'value', label: 'Per-hour value' }]}
                  onChange={(v) => updateFilter(i, { scope: v as PivotFilter['scope'], field: v === 'value' ? '' : (dimFields[0] ?? ''), op: v === 'value' ? '>' : 'in', values: [], value: undefined })}
                />
                {f.scope === 'component' && (
                  <SearchableSelect
                    className="pivot-filter-field"
                    value={f.field}
                    options={dimFields}
                    onChange={(v) => { const num = pivotFieldNumeric(active.sheet, model, v); updateFilter(i, { ...f, field: v, op: num ? '>' : 'in', values: [], value: undefined }); }}
                  />
                )}
                <SearchableSelect
                  className="pivot-filter-op"
                  value={f.op}
                  options={ops.map((o) => ({ value: o, label: o === 'in' ? 'is one of' : o }))}
                  onChange={(v) => updateFilter(i, { ...f, op: v as PivotFilterOp })}
                />
                {f.op === 'in' ? (
                  <SearchableMultiSelect
                    className="pivot-filter-val"
                    values={f.values ?? []}
                    options={pivotUniqueValues(active.sheet, model, f.field)}
                    onChange={(vals) => updateFilter(i, { ...f, values: vals })}
                  />
                ) : (
                  <input
                    className="ss-input pivot-filter-num"
                    type="number"
                    value={f.value ?? ''}
                    onChange={(e) => updateFilter(i, { ...f, value: e.target.value === '' ? undefined : Number(e.target.value) })}
                  />
                )}
                <button type="button" className="pivot-filter-x" onClick={() => removeFilter(i)} aria-label="Remove filter">×</button>
              </div>
            );
          })}
          <button type="button" className="tb-btn pivot-filter-add" onClick={addFilter}>+ Add filter</button>
        </div>
      </div>

      {/* Timeline window (series, time-series charts only) */}
      {isSeries && !['donut', 'scatter'].includes(active.chartType) && fullTimeline.length > 0 && (
        <TimelineSlider
          data={fullTimeline}
          startIndex={effStart}
          endIndex={effEnd}
          onChange={(lo, hi) => patch({ ...active, startIndex: lo, endIndex: hi })}
        />
      )}
    </>
  );

  if (!compact) {
    return (
      <section className="chart-card chart-builder-card">
        {settingsPanel}
        <div className="chart-body" ref={chartContainerRef}>{chartBody}</div>
      </section>
    );
  }

  return (
    <div className={`chart-builder-compact${settingsOpen ? ' is-settings-open' : ''}`}>
      <button type="button" className="chart-builder-gear" onClick={openSettings} aria-label="Chart settings" title="Chart settings" />
      <div className="chart-body" ref={chartContainerRef}>{chartBody}</div>
      {settingsOpen && createPortal(
        <div className="chart-modal-backdrop" onClick={cancelSettings} role="dialog" aria-modal="true">
          <div className="chart-modal" onClick={(e) => e.stopPropagation()}>
            <div className="chart-modal-head">
              <div><strong>Configure chart</strong>{hasValue && <p className="chart-modal-sub">{active.sheet} · {active.valueAttribute}{unit ? ` (${unit})` : ''}</p>}</div>
              <div className="chart-modal-actions">
                {hasValue && <button className="tb-btn" onClick={handleExport}>Export</button>}
                <button className="tb-btn" onClick={onClean}>Clean</button>
                <button className="tb-btn" onClick={cancelSettings}>Cancel</button>
                <button className="tb-btn tb-btn--active" onClick={applySettings}>Apply</button>
                <button className="chart-modal-close" onClick={cancelSettings} aria-label="Close settings" title="Cancel (Esc)">×</button>
              </div>
            </div>
            <div className="chart-modal-body">
              {onTitleChange && (
                <div className="chart-modal-meta-row">
                  <label className="chart-control">
                    <span>Card title</span>
                    <input type="text" value={activeTitle} placeholder="auto" onChange={(e) => setDraftTitle(e.target.value)} />
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
