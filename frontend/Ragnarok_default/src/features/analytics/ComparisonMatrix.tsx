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
 * Data tiers:
 *   - LIGHT topics (Key metrics, Generation mix) render straight from the
 *     in-memory run meta (`summary`, `carrierMix`) — instant, no fetch.
 *   - FULL topics (cost, emissions, capacity, generation-over-time) need a run's
 *     full results. Those are loaded LAZILY by the parent only once such a row
 *     is switched on, then passed in via `scenario.full`. Until then the cell
 *     shows a loading placeholder. (Loading every run's full year of series up
 *     front froze the tab — hence the tiering.)
 */
import React, { useMemo, useState } from 'react';
import type { EChartsCoreOption } from 'echarts/core';
import { MixItem, RunResults, SummaryItem } from 'lib/types';
import { readChartTheme } from 'lib/charts/theme';
import { buildDonutOption, buildExpansionOption, buildTimeSeriesOption, fmtNum } from 'lib/charts/options';
import { useEChart } from '../../shared/echarts/useEChart';

/** A scenario column. `full` is undefined until a FULL topic asks for it, then
 *  'loading', then the loaded results (or 'error'). */
export interface ComparisonScenario {
  name: string;
  label: string;
  carrierMix: MixItem[];
  summary: SummaryItem[];
  full?: RunResults | 'loading' | 'error';
}

// Cap on points drawn per time-series cell — a full year is 8760×carriers and,
// across several columns, freezes the tab. Striding keeps the shape, cheaply.
const MAX_TS_POINTS = 600;

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
  id: string;
  title: string;
  chartTypes: ChartType[];
  hasStacked: boolean;
  needsFull: boolean;
  defaults: TopicSettings;
}

export const TOPICS: TopicDef[] = [
  { id: 'kpi', title: 'Key metrics', chartTypes: [], hasStacked: false, needsFull: false, defaults: { chartType: 'donut', stacked: false } },
  { id: 'generation-mix', title: 'Annual generation mix', chartTypes: ['donut', 'bar'], hasStacked: false, needsFull: false, defaults: { chartType: 'donut', stacked: false } },
  { id: 'generation-time', title: 'Generation over time', chartTypes: ['area', 'line', 'bar'], hasStacked: true, needsFull: true, defaults: { chartType: 'area', stacked: true } },
  { id: 'cost', title: 'Cost breakdown', chartTypes: ['donut', 'bar'], hasStacked: false, needsFull: true, defaults: { chartType: 'donut', stacked: false } },
  { id: 'emissions', title: 'Emissions by carrier', chartTypes: ['donut', 'bar'], hasStacked: false, needsFull: true, defaults: { chartType: 'bar', stacked: false } },
  { id: 'capacity', title: 'Capacity expansion', chartTypes: [], hasStacked: false, needsFull: true, defaults: { chartType: 'bar', stacked: false } },
];

export function topicNeedsFull(id: string): boolean {
  return TOPICS.find((t) => t.id === id)?.needsFull ?? false;
}

function unitFor(topicId: string, currencySymbol: string): string {
  switch (topicId) {
    case 'generation-mix': return 'MWh';
    case 'generation-time': return 'MW';
    case 'cost': return currencySymbol;
    case 'emissions': return 'tCO₂e';
    default: return '';
  }
}

const fullOf = (s: ComparisonScenario): RunResults | null =>
  s.full && s.full !== 'loading' && s.full !== 'error' ? s.full : null;

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

function generationTimeOption(r: RunResults, colorOf: Map<string, string>, settings: TopicSettings): EChartsCoreOption | null {
  const all = r.dispatchSeries ?? [];
  if (all.length === 0) return null;
  const stride = all.length > MAX_TS_POINTS ? Math.ceil(all.length / MAX_TS_POINTS) : 1;
  const points = stride === 1 ? all : all.filter((_, i) => i % stride === 0);
  const keys = Array.from(colorOf.keys());
  return buildTimeSeriesOption({
    xLabels: points.map((p) => p.label || p.timestamp),
    rows: points.map((p) => ({ label: p.label || p.timestamp, ...p.values })),
    series: keys.map((k) => ({ key: k, label: k, color: colorOf.get(k)! })),
    mode: settings.chartType === 'line' ? 'line' : settings.chartType === 'bar' ? 'bar' : 'area',
    stacked: settings.stacked, showAxisLabels: true, xLabelAngle: 0, theme: readChartTheme(),
  });
}

function expansionCellOption(r: RunResults, colorOf: Map<string, string>): EChartsCoreOption | null {
  const assets = r.expansionResults ?? [];
  if (assets.length === 0) return null;
  const rows = assets.map((a) => ({ name: a.name, installed: a.p_nom_mw, optimised: a.p_nom_opt_mw, color: colorOf.get(a.carrier) ?? '#2563eb' }));
  return { ...buildExpansionOption(rows, readChartTheme()), legend: { show: false } } as EChartsCoreOption;
}

// ── Unified legend / colour map per row ───────────────────────────────────────

function carrierColorMap(scenarios: ComparisonScenario[]): { legend: LegendItem[]; colorOf: Map<string, string> } {
  const colorOf = new Map<string, string>();
  const order: string[] = [];
  for (const s of scenarios) for (const m of s.carrierMix) if (!colorOf.has(m.label)) { colorOf.set(m.label, m.color); order.push(m.label); }
  return { legend: order.map((l) => ({ key: l, label: l, color: colorOf.get(l)! })), colorOf };
}

/** Union of categories from each scenario's FULL results, palette-coloured. */
function unifyFull(scenarios: ComparisonScenario[], get: (r: RunResults) => CategoryItem[]): { legend: LegendItem[]; colorOf: Map<string, string> } {
  const colorOf = new Map<string, string>();
  const order: string[] = [];
  for (const s of scenarios) {
    const r = fullOf(s);
    if (!r) continue;
    for (const it of get(r)) if (!colorOf.has(it.label)) { colorOf.set(it.label, it.color ?? PALETTE[order.length % PALETTE.length]); order.push(it.label); }
  }
  return { legend: order.map((l) => ({ key: l, label: l, color: colorOf.get(l)! })), colorOf };
}

const costItems = (r: RunResults): CategoryItem[] => (r.costBreakdown ?? []).map((c) => ({ label: c.label, value: c.value }));
const emissionItems = (r: RunResults): CategoryItem[] => (r.emissionsBreakdown?.byCarrier ?? []).map((c) => ({ label: c.carrier, value: c.emissions_tco2 }));

// ── Topic row ───────────────────────────────────────────────────────────────

function TopicRow({ topic, scenarios, settings, onSettings, currencySymbol, gridTemplate }: {
  topic: TopicDef; scenarios: ComparisonScenario[]; settings: TopicSettings;
  onSettings: (s: TopicSettings) => void; currencySymbol: string; gridTemplate: string;
}) {
  const [showGear, setShowGear] = useState(false);
  const unit = unitFor(topic.id, currencySymbol);
  const hasControls = topic.chartTypes.length > 0 || topic.hasStacked;

  const { legend, cells } = useMemo(() => {
    // KPI — light, per-column lists.
    if (topic.id === 'kpi') return { legend: [] as LegendItem[], cells: scenarios.map(() => ({ kind: 'kpi' as const })) };

    // Generation mix — light, carrier-coloured.
    if (topic.id === 'generation-mix') {
      const { legend: lg, colorOf } = carrierColorMap(scenarios);
      return { legend: lg, cells: scenarios.map((s) => ({ kind: 'chart' as const, option: categoryCellOption(s.carrierMix.map((m) => ({ label: m.label, value: m.value, color: m.color })), colorOf, settings, unit) })) };
    }

    // Generation over time — FULL, carrier-coloured.
    if (topic.id === 'generation-time') {
      const { legend: lg, colorOf } = carrierColorMap(scenarios);
      return { legend: lg, cells: scenarios.map((s) => {
        const r = fullOf(s);
        if (s.full === undefined || s.full === 'loading') return { kind: 'loading' as const };
        return { kind: 'chart' as const, option: r ? generationTimeOption(r, colorOf, settings) : null };
      }) };
    }

    // Capacity expansion — FULL, carrier-coloured bars (Installed vs Optimised legend).
    if (topic.id === 'capacity') {
      const { colorOf } = carrierColorMap(scenarios);
      const theme = readChartTheme();
      const lg: LegendItem[] = [
        { key: 'installed', label: 'Installed', color: theme.borderStrong },
        { key: 'optimised', label: 'Optimised', color: '#2563eb' },
      ];
      return { legend: lg, cells: scenarios.map((s) => {
        const r = fullOf(s);
        if (s.full === undefined || s.full === 'loading') return { kind: 'loading' as const };
        return { kind: 'chart' as const, option: r ? expansionCellOption(r, colorOf) : null };
      }) };
    }

    // Cost / emissions — FULL, categorical.
    const get = topic.id === 'cost' ? costItems : emissionItems;
    const { legend: lg, colorOf } = unifyFull(scenarios, get);
    return { legend: lg, cells: scenarios.map((s) => {
      const r = fullOf(s);
      if (s.full === undefined || s.full === 'loading') return { kind: 'loading' as const };
      const order = lg.map((l) => l.label);
      const m = new Map(r ? get(r).map((it) => [it.label, it.value]) : []);
      const items = order.map((l) => ({ label: l, value: m.get(l) ?? 0 }));
      return { kind: 'chart' as const, option: r ? categoryCellOption(items, colorOf, settings, unit) : null };
    }) };
  }, [topic.id, scenarios, settings, unit]);

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
          if (c.kind === 'kpi') return <KpiCell key={key} summary={scenarios[i].summary} />;
          if (c.kind === 'loading') return <LoadingCell key={key} />;
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

export function ComparisonMatrix({ scenarios, activeRunName, currencySymbol = '$', enabled, onToggleTopic, onReorder }: {
  scenarios: ComparisonScenario[];
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
