/**
 * Scenario-comparison matrix — the Analytics → Comparison surface.
 *
 * Layout: one ROW per result topic, one COLUMN per scenario, so the same chart
 * reads left-to-right across scenarios. Rules the design hangs on:
 *   - **One legend per row, never per chart.** Each row computes a *unified*
 *     category→colour map from the union of all its scenarios, draws every cell
 *     with that shared palette (a carrier is the same colour in every column),
 *     and shows the legend ONCE in the right-most column.
 *   - **One settings control per row** (the gear), driving every chart in it.
 *   - **Columns are draggable** (header cells) to reorder left/right.
 *
 * Data: every cell reads the server's comparison entry for its run
 * (`GET /api/results/compare`, WA7). The parent requests the entries for the
 * shown topics only and passes the request `status`; a cell whose data has not
 * arrived shows a loading placeholder, a failed request shows the error.
 */
import React, { useMemo, useState } from 'react';
import type { EChartsCoreOption } from 'echarts/core';
import { MixItem, SummaryItem } from 'lib/types';
import type { ComparisonEntry, ComparisonTopicId, LabelledValue } from 'lib/api/resultsDerived';
import { carrierColor } from 'lib/utils/helpers';
import { readChartTheme } from 'lib/charts/theme';
import { buildDonutOption, buildExpansionOption, buildTimeSeriesOption, fmtNum } from 'lib/charts/options';
import { useEChart } from '../../shared/echarts/useEChart';

/** A scenario column: the server entry (absent until the first response) plus the
 *  carrier colours the run meta carries (the server sends values only). */
export interface ComparisonScenario {
  name: string;
  label: string;
  entry?: ComparisonEntry;
  carrierColors: Record<string, string>;
}

/** State of the comparison request that feeds the matrix. */
export type ComparisonStatus = { state: 'loading' } | { state: 'ready' } | { state: 'error'; message: string };

const PALETTE = [
  '#2563eb', '#16a34a', '#f59e0b', '#db2777', '#7c3aed',
  '#0891b2', '#dc2626', '#65a30d', '#9333ea', '#0d9488',
  '#ea580c', '#4f46e5', '#0ea5e9', '#84cc16', '#e11d48',
];

interface LegendItem { key: string; label: string; color: string }
interface CategoryItem { label: string; value: number; color?: string }
type ChartType = 'donut' | 'bar' | 'area' | 'line';
interface TopicSettings { chartType: ChartType; stacked: boolean }

interface TopicDef {
  id: ComparisonTopicId;
  title: string;
  chartTypes: ChartType[];
  hasStacked: boolean;
  defaults: TopicSettings;
}

export const TOPICS: TopicDef[] = [
  { id: 'kpi', title: 'Key metrics', chartTypes: [], hasStacked: false, defaults: { chartType: 'donut', stacked: false } },
  { id: 'generation-mix', title: 'Generation mix (modelled window)', chartTypes: ['donut', 'bar'], hasStacked: false, defaults: { chartType: 'donut', stacked: false } },
  { id: 'installed-capacity', title: 'Installed capacity by carrier', chartTypes: ['donut', 'bar'], hasStacked: false, defaults: { chartType: 'bar', stacked: false } },
  { id: 'generation-time', title: 'Generation over time', chartTypes: ['area', 'line', 'bar'], hasStacked: true, defaults: { chartType: 'area', stacked: true } },
  { id: 'cost', title: 'Cost breakdown', chartTypes: ['donut', 'bar'], hasStacked: false, defaults: { chartType: 'donut', stacked: false } },
  { id: 'emissions', title: 'Emissions by carrier', chartTypes: ['donut', 'bar'], hasStacked: false, defaults: { chartType: 'bar', stacked: false } },
  { id: 'capacity', title: 'Capacity expansion', chartTypes: [], hasStacked: false, defaults: { chartType: 'bar', stacked: false } },
];

function unitFor(topicId: string, currencySymbol: string): string {
  switch (topicId) {
    case 'generation-mix': return 'MWh';
    case 'installed-capacity': return 'MW';
    case 'generation-time': return 'MW';
    case 'cost': return currencySymbol;
    case 'emissions': return 'tCO₂e';
    default: return '';
  }
}

/** The entry field a topic reads; a cell is "loading" until the response carries it. */
const ENTRY_FIELD: Record<ComparisonTopicId, keyof ComparisonEntry> = {
  'kpi': 'summary',
  'generation-mix': 'carrierMix',
  'installed-capacity': 'capacityMix',
  'cost': 'costBreakdown',
  'emissions': 'emissionsByCarrier',
  'capacity': 'expansion',
  'generation-time': 'dispatchSeries',
};

const mixOf = (s: ComparisonScenario): MixItem[] =>
  (s.entry?.carrierMix ?? []).map((m) => ({ ...m, color: s.carrierColors[m.label] ?? carrierColor(m.label) }));
const capacityMixOf = (s: ComparisonScenario): MixItem[] =>
  (s.entry?.capacityMix ?? []).map((m) => ({ ...m, color: carrierColor(m.label) }));

// ── Cells ─────────────────────────────────────────────────────────────────────

function ChartCell({ option }: { option: EChartsCoreOption | null }) {
  const ref = useEChart<HTMLDivElement>(option);
  if (!option) return <div className="cmp-cell--empty">no data</div>;
  return <div ref={ref} className="cmp-cell-chart" role="img" aria-label="comparison chart" />;
}

function LoadingCell() {
  return <div className="cmp-cell--loading"><span className="topbar-spinner" /> loading…</div>;
}

function KpiCell({ summary }: { summary: SummaryItem[] }) {
  return (
    <div className="cmp-kpi-cell">
      {summary.slice(0, 10).map((s) => (
        <div key={s.label} className="cmp-kpi-row">
          <span className="cmp-kpi-label" title={s.label}>{s.label}</span>
          <span className="cmp-kpi-value">{s.value}</span>
        </div>
      ))}
    </div>
  );
}

// ── Chart options ─────────────────────────────────────────────────────────────

function categoryBarOption(items: CategoryItem[], colorOf: Map<string, string>, unit: string): EChartsCoreOption {
  const theme = readChartTheme();
  return {
    animation: false,
    grid: { left: 4, right: 16, top: 8, bottom: 8, containLabel: true },
    tooltip: {
      backgroundColor: theme.tooltipBg, borderWidth: 0, confine: true,
      textStyle: { color: '#fff', fontSize: 11, fontFamily: theme.fontSans },
      trigger: 'axis', axisPointer: { type: 'shadow' },
      valueFormatter: (v: number | string) => `${fmtNum(v)}${unit ? ` ${unit}` : ''}`,
    },
    xAxis: {
      type: 'value', axisLine: { show: false }, axisTick: { show: false },
      splitLine: { show: true, lineStyle: { color: theme.gridLine, type: [4, 6] } },
      axisLabel: { color: theme.muted, fontSize: 11, fontFamily: theme.fontSans, formatter: fmtNum },
    },
    yAxis: {
      type: 'category', inverse: true, data: items.map((i) => i.label),
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: theme.muted, fontSize: 11, fontFamily: theme.fontSans, width: 90, overflow: 'truncate' },
    },
    series: [{ type: 'bar', barMaxWidth: 22, data: items.map((i) => ({ value: i.value, itemStyle: { color: colorOf.get(i.label) ?? '#94a3b8' } })) }],
  };
}

function categoryCellOption(items: CategoryItem[], colorOf: Map<string, string>, settings: TopicSettings, unit: string): EChartsCoreOption | null {
  if (items.length === 0 || items.every((i) => i.value === 0)) return null;
  if (settings.chartType === 'bar') return categoryBarOption(items, colorOf, unit);
  const data = items.map((i) => ({ label: i.label, value: i.value, color: colorOf.get(i.label) ?? '#94a3b8' }));
  return buildDonutOption({ data, unit, theme: readChartTheme() });
}

/** `entry.dispatchSeries` arrives already strided by the server (<= 600 points). */
function generationTimeOption(entry: ComparisonEntry, colorOf: Map<string, string>, settings: TopicSettings): EChartsCoreOption | null {
  const points = entry.dispatchSeries ?? [];
  if (points.length === 0) return null;
  const keys = Array.from(colorOf.keys());
  return buildTimeSeriesOption({
    xLabels: points.map((p) => p.label || p.timestamp),
    rows: points.map((p) => ({ label: p.label || p.timestamp, ...p.values })),
    series: keys.map((k) => ({ key: k, label: k, color: colorOf.get(k)! })),
    mode: settings.chartType === 'line' ? 'line' : settings.chartType === 'bar' ? 'bar' : 'area',
    stacked: settings.stacked, showAxisLabels: true, xLabelAngle: 0, theme: readChartTheme(),
    // The matrix renders one shared legend for the whole scenario row (see
    // `cmp-legend-cell`); a per-cell legend would duplicate it and crowd the
    // small multiple. Same reason expansion cells force `legend.show: false`.
    showLegend: false,
  });
}

function expansionCellOption(entry: ComparisonEntry, colorOf: Map<string, string>): EChartsCoreOption | null {
  const assets = entry.expansion ?? [];
  if (assets.length === 0) return null;
  const rows = assets.map((a) => ({ name: a.name, installed: a.installedMw, optimised: a.optimisedMw, color: colorOf.get(a.carrier) ?? '#2563eb' }));
  return { ...buildExpansionOption(rows, readChartTheme()), legend: { show: false } } as EChartsCoreOption;
}

// ── Unified legend / colour map per row ───────────────────────────────────────

function mixColorMap(scenarios: ComparisonScenario[], get: (s: ComparisonScenario) => MixItem[]): { legend: LegendItem[]; colorOf: Map<string, string> } {
  const colorOf = new Map<string, string>();
  const order: string[] = [];
  for (const s of scenarios) for (const m of get(s)) if (!colorOf.has(m.label)) { colorOf.set(m.label, m.color); order.push(m.label); }
  return { legend: order.map((l) => ({ key: l, label: l, color: colorOf.get(l)! })), colorOf };
}

function carrierColorMap(scenarios: ComparisonScenario[]): { legend: LegendItem[]; colorOf: Map<string, string> } {
  return mixColorMap(scenarios, mixOf);
}

/** Union of categories from each scenario's entry, palette-coloured. */
function unifyEntries(scenarios: ComparisonScenario[], get: (e: ComparisonEntry) => CategoryItem[]): { legend: LegendItem[]; colorOf: Map<string, string> } {
  const colorOf = new Map<string, string>();
  const order: string[] = [];
  for (const s of scenarios) {
    if (!s.entry) continue;
    for (const it of get(s.entry)) if (!colorOf.has(it.label)) { colorOf.set(it.label, it.color ?? PALETTE[order.length % PALETTE.length]); order.push(it.label); }
  }
  return { legend: order.map((l) => ({ key: l, label: l, color: colorOf.get(l)! })), colorOf };
}

const asItems = (rows: LabelledValue[] | undefined): CategoryItem[] => (rows ?? []).map((c) => ({ label: c.label, value: c.value }));
const costItems = (e: ComparisonEntry): CategoryItem[] => asItems(e.costBreakdown);
const emissionItems = (e: ComparisonEntry): CategoryItem[] => asItems(e.emissionsByCarrier);

// ── Topic row ───────────────────────────────────────────────────────────────

function TopicRow({ topic, scenarios, status, settings, onSettings, currencySymbol, gridTemplate }: {
  topic: TopicDef; scenarios: ComparisonScenario[]; status: ComparisonStatus; settings: TopicSettings;
  onSettings: (s: TopicSettings) => void; currencySymbol: string; gridTemplate: string;
}) {
  const [showGear, setShowGear] = useState(false);
  const unit = unitFor(topic.id, currencySymbol);
  const hasControls = topic.chartTypes.length > 0 || topic.hasStacked;

  const { legend, cells } = useMemo(() => {
    type Cell =
      | { kind: 'kpi' }
      | { kind: 'loading' }
      | { kind: 'error'; message: string }
      | { kind: 'chart'; option: EChartsCoreOption | null };
    // A cell has no data until the response carries this topic's field.
    const pending = (s: ComparisonScenario): Cell | null => {
      if (s.entry?.[ENTRY_FIELD[topic.id]] !== undefined) return null;
      return status.state === 'error' ? { kind: 'error', message: status.message } : { kind: 'loading' };
    };
    const build = (lg: LegendItem[], cell: (s: ComparisonScenario) => Cell) =>
      ({ legend: lg, cells: scenarios.map((s) => pending(s) ?? cell(s)) });

    if (topic.id === 'kpi') return build([], () => ({ kind: 'kpi' }));

    if (topic.id === 'generation-mix') {
      const { legend: lg, colorOf } = carrierColorMap(scenarios);
      return build(lg, (s) => ({ kind: 'chart', option: categoryCellOption(mixOf(s).map((m) => ({ label: m.label, value: m.value, color: m.color })), colorOf, settings, unit) }));
    }

    // Installed capacity by carrier — the capacity analogue of the generation mix
    // (solved p_nom_opt where present, else input p_nom; the server decides).
    if (topic.id === 'installed-capacity') {
      const { legend: lg, colorOf } = mixColorMap(scenarios, capacityMixOf);
      return build(lg, (s) => ({ kind: 'chart', option: categoryCellOption(capacityMixOf(s).map((m) => ({ label: m.label, value: m.value, color: m.color })), colorOf, settings, unit) }));
    }

    if (topic.id === 'generation-time') {
      const { legend: lg, colorOf } = carrierColorMap(scenarios);
      return build(lg, (s) => ({ kind: 'chart', option: generationTimeOption(s.entry!, colorOf, settings) }));
    }

    // Capacity expansion — carrier-coloured bars (Installed vs Optimised legend).
    if (topic.id === 'capacity') {
      const { colorOf } = carrierColorMap(scenarios);
      const theme = readChartTheme();
      const lg: LegendItem[] = [
        { key: 'installed', label: 'Installed', color: theme.borderStrong },
        { key: 'optimised', label: 'Optimised', color: '#2563eb' },
      ];
      return build(lg, (s) => ({ kind: 'chart', option: expansionCellOption(s.entry!, colorOf) }));
    }

    // Cost / emissions — categorical.
    const get = topic.id === 'cost' ? costItems : emissionItems;
    const { legend: lg, colorOf } = unifyEntries(scenarios, get);
    const order = lg.map((l) => l.label);
    return build(lg, (s) => {
      const m = new Map(get(s.entry!).map((it) => [it.label, it.value]));
      const items = order.map((l) => ({ label: l, value: m.get(l) ?? 0 }));
      return { kind: 'chart', option: categoryCellOption(items, colorOf, settings, unit) };
    });
  }, [topic.id, scenarios, status, settings, unit]);

  return (
    <section className="cmp-topic">
      <div className="cmp-topic-head">
        <h4 className="cmp-topic-title">{topic.title}{unit ? <span className="cmp-topic-unit"> ({unit})</span> : null}</h4>
        {hasControls && (
          <button type="button" className={`cmp-gear${showGear ? ' cmp-gear--on' : ''}`} title="Chart settings for this row" onClick={() => setShowGear((v) => !v)}>⚙</button>
        )}
        {hasControls && showGear && (
          <div className="cmp-gear-controls">
            {topic.chartTypes.length > 0 && (
              <div className="cmp-seg">
                {topic.chartTypes.map((ct) => (
                  <button key={ct} type="button" className={`cmp-seg-btn${settings.chartType === ct ? ' cmp-seg-btn--on' : ''}`} onClick={() => onSettings({ ...settings, chartType: ct })}>{ct}</button>
                ))}
              </div>
            )}
            {topic.hasStacked && (
              <label className="cmp-check"><input type="checkbox" checked={settings.stacked} onChange={(e) => onSettings({ ...settings, stacked: e.target.checked })} />stacked</label>
            )}
          </div>
        )}
      </div>

      <div className="cmp-topic-grid" style={{ gridTemplateColumns: gridTemplate }}>
        {cells.map((c, i) => {
          const key = scenarios[i].name;
          if (c.kind === 'kpi') return <KpiCell key={key} summary={scenarios[i].entry?.summary ?? []} />;
          if (c.kind === 'loading') return <LoadingCell key={key} />;
          if (c.kind === 'error') return <div key={key} className="cmp-cell--empty" role="alert">{c.message}</div>;
          return <ChartCell key={key} option={c.option} />;
        })}
        <div className="cmp-legend-cell">
          {legend.length > 0 ? legend.map((l) => (
            <div key={l.key} className="cmp-legend-item">
              <span className="cmp-legend-swatch" style={{ backgroundColor: l.color }} />
              <span className="cmp-legend-label" title={l.label}>{l.label}</span>
            </div>
          )) : <span className="cmp-legend-empty">—</span>}
        </div>
      </div>
    </section>
  );
}

// ── Matrix ──────────────────────────────────────────────────────────────────

export function ComparisonMatrix({ scenarios, status, activeRunName, currencySymbol = '$', enabled, onToggleTopic, onReorder }: {
  scenarios: ComparisonScenario[];
  status: ComparisonStatus;
  activeRunName: string | null;
  currencySymbol?: string;
  enabled: string[];
  onToggleTopic: (id: string) => void;
  onReorder: (names: string[]) => void;
}) {
  const [settings, setSettings] = useState<Record<string, TopicSettings>>(() => Object.fromEntries(TOPICS.map((t) => [t.id, t.defaults])));
  const [dragName, setDragName] = useState<string | null>(null);

  const gridTemplate = `repeat(${scenarios.length}, minmax(0, 1fr)) var(--cmp-legend-w, 168px)`;
  const enabledSet = useMemo(() => new Set(enabled), [enabled]);
  const shownTopics = TOPICS.filter((t) => enabledSet.has(t.id));

  const reorder = (targetName: string) => {
    if (!dragName || dragName === targetName) { setDragName(null); return; }
    const order = scenarios.map((s) => s.name);
    const from = order.indexOf(dragName);
    const to = order.indexOf(targetName);
    if (from < 0 || to < 0) return;
    order.splice(to, 0, order.splice(from, 1)[0]);
    onReorder(order);
    setDragName(null);
  };

  return (
    <div className="cmp-matrix">
      <div className="cmp-topic-toolbar">
        <span className="cmp-toolbar-label">Show</span>
        {TOPICS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`cmp-chip${enabledSet.has(t.id) ? ' cmp-chip--on' : ''}`}
            aria-pressed={enabledSet.has(t.id)}
            onClick={() => onToggleTopic(t.id)}
          >{t.title}</button>
        ))}
      </div>

      <div className="cmp-col-head" style={{ gridTemplateColumns: gridTemplate }}>
        {scenarios.map((s) => (
          <div
            key={s.name}
            className={`cmp-col-title${s.name === activeRunName ? ' cmp-col-title--active' : ''}${dragName === s.name ? ' cmp-col-title--dragging' : ''}`}
            title={`${s.label}\n(drag to reorder)`}
            draggable
            onDragStart={() => setDragName(s.name)}
            onDragEnd={() => setDragName(null)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => reorder(s.name)}
          >
            <span className="cmp-col-grip" aria-hidden>⠿</span>
            <span className="cmp-col-label">{s.label}</span>
          </div>
        ))}
        <div className="cmp-col-title cmp-col-title--legend">Legend</div>
      </div>

      {shownTopics.map((t) => (
        <TopicRow
          key={t.id}
          topic={t}
          scenarios={scenarios}
          status={status}
          settings={settings[t.id]}
          onSettings={(s) => setSettings((prev) => ({ ...prev, [t.id]: s }))}
          currencySymbol={currencySymbol}
          gridTemplate={gridTemplate}
        />
      ))}

      {shownTopics.length === 0 && <div className="cmp-matrix-empty">No sections shown — add one with the “Show” chips above.</div>}
    </div>
  );
}
