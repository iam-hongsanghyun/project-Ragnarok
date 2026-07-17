import React, { useEffect, useMemo, useState } from 'react';
import type { EChartsCoreOption } from 'echarts/core';
import { GridRow } from 'lib/types';
import { stringValue } from 'lib/utils/helpers';
import { axisName, buildDurationCurveOption, darkTooltip, fmtNum, tickLabel } from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../shared/echarts/useEChart';
import { SearchableSelect } from '../../shared/components/SearchableSelect';

// ── Helpers ───────────────────────────────────────────────────────────────────

function numVal(v: unknown): number {
  if (typeof v === 'number') return v;
  const n = parseFloat(String(v ?? ''));
  return Number.isFinite(n) ? n : 0;
}

function isNumericCol(rows: GridRow[], col: string): boolean {
  const sample = rows.slice(0, 20).map((r) => r[col]);
  const numeric = sample.filter((v) => v !== null && v !== '' && Number.isFinite(Number(v)));
  return numeric.length > Math.max(sample.length * 0.5, 1);
}

function isStringCol(rows: GridRow[], col: string): boolean {
  return !isNumericCol(rows, col);
}

// Extract hour-of-day (0–23) from a label like "2020-01-01 04:00" or "04:00"
function extractHour(label: string): number | null {
  const m = label.match(/(\d{1,2}):(\d{2})/);
  if (m) return parseInt(m[1], 10);
  return null;
}

const PALETTE = [
  '#0f766e','#f97316','#16a34a','#dc2626','#7c3aed',
  '#0891b2','#d97706','#be185d','#065f46','#1e40af',
  '#84cc16','#ec4899','#6366f1','#14b8a6','#f59e0b',
];

// ── Shared chart primitives ───────────────────────────────────────────────────

function NoData({ msg = 'No data to display.' }: { msg?: string }) {
  return <p style={{ padding: '16px', fontSize: '0.82rem', color: 'var(--muted)', textAlign: 'center' }}>{msg}</p>;
}

/** Fixed-size ECharts host for the analyser's mini charts. */
function MiniChart({ option, height, width, maxWidth }: {
  option: EChartsCoreOption; height: number; width?: number; maxWidth?: number;
}) {
  const ref = useEChart<HTMLDivElement>(option);
  return <div ref={ref} role="img" style={{ width: width ?? '100%', maxWidth, height, flexShrink: width ? 0 : undefined }} />;
}

function dashedGrid(theme: ReturnType<typeof readChartTheme>): Record<string, unknown> {
  return { show: true, lineStyle: { color: theme.gridLine, type: [4, 6] } };
}

/** Bare value axis: no line/tick, dashed grid, muted labels. */
function bareValueAxis(theme: ReturnType<typeof readChartTheme>): Record<string, unknown> {
  return {
    type: 'value',
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: dashedGrid(theme),
    axisLabel: { ...tickLabel(theme), formatter: fmtNum },
  };
}

// ── 1. Horizontal Bar (static, one value per row) ─────────────────────────────

function fmtBarVal(v: number): string {
  return v === 0 ? '—' : v < 1 ? v.toFixed(3) : v.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function HBar({ labels, values, colors, unit }: {
  labels: string[]; values: number[]; colors?: string[]; unit: string;
}) {
  const theme = readChartTheme();
  const withUnit = (v: number) => `${fmtBarVal(v)}${unit ? ` ${unit}` : ''}`;
  const option: EChartsCoreOption = {
    animation: false,
    grid: { left: 4, right: 86, top: 4, bottom: 4, containLabel: true },
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'item',
      formatter: (p: { name: string; value: number }) => `${p.name}: <b>${withUnit(p.value)}</b>`,
    },
    xAxis: bareValueAxis(theme),
    yAxis: {
      type: 'category',
      inverse: true,
      data: labels,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { ...tickLabel(theme), width: 124, overflow: 'truncate' as const },
    },
    series: [{
      type: 'bar',
      barWidth: 14,
      showBackground: true,
      backgroundStyle: { color: theme.bgHover },
      label: {
        show: true,
        position: 'right',
        color: theme.text,
        fontSize: 11,
        fontFamily: theme.fontSans,
        formatter: (p: { value: number }) => withUnit(p.value),
      },
      data: values.map((v, i) => ({ value: v, itemStyle: { color: colors?.[i] ?? '#0f766e', opacity: 0.85 } })),
    }],
  };
  if (!labels.length) return <NoData />;
  return <MiniChart option={option} height={Math.max(labels.length * 26 + 16, 90)} maxWidth={560} />;
}

// ── 2. Donut (grouped by a string col) ───────────────────────────────────────

function Donut({ data }: { data: { label: string; value: number; color: string }[] }) {
  const theme = readChartTheme();
  const option: EChartsCoreOption = {
    animation: true,
    animationDuration: 250,
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'item',
      formatter: (p: { name: string; value: number; percent: number }) =>
        `${p.name}: <b>${p.value.toLocaleString(undefined, { maximumFractionDigits: 1 })}</b> (${p.percent.toFixed(1)}%)`,
    },
    series: [{
      type: 'pie',
      radius: ['46%', '82%'],
      center: ['50%', '50%'],
      label: { show: false },
      itemStyle: { borderColor: '#ffffff', borderWidth: 2 },
      emphasis: { scale: true, scaleSize: 4 },
      data: data.map((d) => ({ name: d.label, value: d.value, itemStyle: { color: d.color } })),
    }],
  };
  if (!data.length) return <NoData />;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
      <MiniChart option={option} height={190} width={190} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {data.map((d) => (
          <div key={d.label} style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 12 }}>
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: d.color, flexShrink: 0 }} />
            <span style={{ color: 'var(--muted)' }}>{d.label}</span>
            <span style={{ fontWeight: 600, color: 'var(--text)', marginLeft: 4 }}>
              {d.value.toLocaleString(undefined, { maximumFractionDigits: 1 })}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── 3. Scatter ────────────────────────────────────────────────────────────────

function Scatter({ xVals, yVals, labels, xCol, yCol }: {
  xVals: number[]; yVals: number[]; labels: string[]; xCol: string; yCol: string;
}) {
  const theme = readChartTheme();
  const option: EChartsCoreOption = {
    animation: false,
    grid: { left: 16, right: 20, top: 12, bottom: 22, containLabel: true },
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'item',
      formatter: (p: { dataIndex: number; value: [number, number] }) =>
        `<b>${labels[p.dataIndex] ?? ''}</b><br/>${xCol}: ${p.value[0].toLocaleString()}<br/>${yCol}: ${p.value[1].toLocaleString()}`,
    },
    xAxis: {
      ...bareValueAxis(theme),
      name: xCol,
      nameLocation: 'middle',
      nameGap: 26,
      nameTextStyle: axisName(theme),
      scale: true,
    },
    yAxis: {
      ...bareValueAxis(theme),
      name: yCol,
      nameLocation: 'middle',
      nameGap: 48,
      nameTextStyle: axisName(theme),
      scale: true,
    },
    series: [{
      type: 'scatter',
      symbolSize: 10,
      itemStyle: { color: '#0f766e', opacity: 0.8 },
      emphasis: { scale: 1.4 },
      data: xVals.map((x, i) => [x, yVals[i]]),
    }],
  };
  if (!xVals.length) return <NoData />;
  return <MiniChart option={option} height={260} maxWidth={480} />;
}

// ── 4. Multi-line / Stacked-area ──────────────────────────────────────────────

function LineArea({ xLabels, series, stacked }: {
  xLabels: string[];
  series: { key: string; values: number[]; color: string }[];
  stacked: boolean;
}) {
  const theme = readChartTheme();
  const option: EChartsCoreOption = {
    animation: false,
    grid: { left: 8, right: 16, top: 12, bottom: 4, containLabel: true },
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'axis',
      valueFormatter: (v: number | string) =>
        typeof v === 'number' && Math.abs(v) < 1 ? v.toFixed(2) : fmtNum(v),
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: xLabels,
      axisLine: { lineStyle: { color: theme.border } },
      axisTick: { show: false },
      axisLabel: { ...tickLabel(theme), fontSize: 10, hideOverlap: true },
    },
    yAxis: bareValueAxis(theme),
    series: series.map((s) => ({
      name: s.key,
      type: 'line' as const,
      data: s.values,
      showSymbol: false,
      stack: stacked ? 'total' : undefined,
      lineStyle: { width: stacked ? 1 : 1.8, color: s.color },
      itemStyle: { color: s.color },
      areaStyle: stacked ? { opacity: 0.45 } : undefined,
      emphasis: { focus: series.length > 1 ? ('series' as const) : ('none' as const) },
    })),
  };
  if (!xLabels.length || !series.length) return <NoData />;
  return <MiniChart option={option} height={230} maxWidth={640} />;
}

// ── 5. Duration curve ─────────────────────────────────────────────────────────

function DurationCurve({ values, label, color }: { values: number[]; label: string; color: string }) {
  const sorted = [...values].sort((a, b) => b - a);
  if (!sorted.length) return <NoData />;
  const option = buildDurationCurveOption({
    series: [{ key: label, label, color, values: sorted }], title: label, unit: '', theme: readChartTheme(),
  });
  return <MiniChart option={option} height={200} maxWidth={480} />;
}

// ── 6. Daily profile (average by hour-of-day) ─────────────────────────────────

function DailyProfile({ xLabels, series }: {
  xLabels: string[];
  series: { key: string; values: number[]; color: string }[];
}) {
  // Group by extracted hour-of-day, take mean
  const hourlyMeans: Record<string, number[]> = {};
  for (let h = 0; h < 24; h++) hourlyMeans[String(h)] = [];
  xLabels.forEach((label, i) => {
    const h = extractHour(label);
    if (h !== null) {
      series.forEach((s) => {
        if (!hourlyMeans[String(h)]) hourlyMeans[String(h)] = [];
        hourlyMeans[String(h)].push(s.values[i]);
      });
    }
  });
  const hours = Array.from({ length: 24 }, (_, h) => h);
  const means = hours.map((h) => {
    const vals = hourlyMeans[String(h)] ?? [];
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
  });
  const color = series[0]?.color ?? '#0f766e';
  const theme = readChartTheme();
  const option: EChartsCoreOption = {
    animation: false,
    grid: { left: 8, right: 12, top: 10, bottom: 26, containLabel: true },
    tooltip: {
      ...darkTooltip(theme),
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: fmtNum,
    },
    xAxis: {
      type: 'category',
      data: hours.map((h) => `${h}:00`),
      name: 'Hour of day (average)',
      nameLocation: 'middle',
      nameGap: 26,
      nameTextStyle: axisName(theme),
      axisLine: { lineStyle: { color: theme.border } },
      axisTick: { show: false },
      axisLabel: { ...tickLabel(theme), fontSize: 10, interval: 5 },
    },
    yAxis: bareValueAxis(theme),
    series: [{
      type: 'bar',
      barWidth: '70%',
      itemStyle: { color, opacity: 0.75 },
      data: means,
    }],
  };
  return <MiniChart option={option} height={190} maxWidth={480} />;
}

// ── Legend ────────────────────────────────────────────────────────────────────

function Legend({ items }: { items: { key: string; color: string }[] }) {
  if (items.length <= 1) return null;
  return (
    <div className="ia-legend">
      {items.map(({ key, color }) => (
        <span key={key} className="ia-legend-item">
          <span className="ia-legend-dot" style={{ background: color }} />
          {key}
        </span>
      ))}
    </div>
  );
}

// ── Control row ───────────────────────────────────────────────────────────────

function Ctl({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="ia-control">
      <span className="ia-control-label">{label}</span>
      {children}
    </label>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

interface InputAnalyserProps {
  rows: GridRow[];
  cols: string[];
  isTs: boolean;
  frozenCol: string | null;
  currencySymbol?: string;
  /** When the analyser is opened via "Analyse column", preselect this column as
   *  the value (static) / series (temporal). `null` analyses the whole table. */
  focusCol?: string | null;
}

type StaticChart = 'bar' | 'grouped-bar' | 'donut' | 'scatter';
type TsChart     = 'line' | 'stacked-area' | 'duration' | 'daily-profile';
type AggMethod   = 'sum' | 'mean' | 'max' | 'min' | 'count';

export function InputAnalyser({ rows, cols, isTs, frozenCol, currencySymbol = '$', focusCol = null }: InputAnalyserProps) {
  const numericCols = useMemo(
    () => cols.filter((c) => c !== frozenCol && isNumericCol(rows, c)),
    [rows, cols, frozenCol],
  );
  const stringCols = useMemo(
    () => cols.filter((c) => c !== frozenCol && isStringCol(rows, c)),
    [rows, cols, frozenCol],
  );
  const tsCols = useMemo(
    () => cols.filter((c) => c !== frozenCol),
    [cols, frozenCol],
  );

  // ── Static controls ────────────────────────────────────────────────────────
  const [valueCol,  setValueCol]  = useState('');
  const [groupCol,  setGroupCol]  = useState('none');
  const [scatterY,  setScatterY]  = useState('');
  const [agg,       setAgg]       = useState<AggMethod>('sum');
  const [staticChart, setStaticChart] = useState<StaticChart>('bar');

  // ── TS controls ────────────────────────────────────────────────────────────
  const [tsSeries,  setTsSeries]  = useState('__all__');
  const [tsChart,   setTsChart]   = useState<TsChart>('line');

  // "Analyse column" preselects the right control for the requested column.
  useEffect(() => {
    if (!focusCol) return;
    if (isTs) {
      if (tsCols.includes(focusCol)) setTsSeries(focusCol);
    } else if (numericCols.includes(focusCol)) {
      setValueCol(focusCol);
    }
  }, [focusCol, isTs, tsCols, numericCols]);

  // ── Static derived values (hooks must be unconditional) ───────────────────
  const nameCol     = frozenCol ?? cols[0] ?? '';
  const activeValue = numericCols.includes(valueCol) ? valueCol : (numericCols[0] ?? '');
  const activeScatY = numericCols.includes(scatterY) ? scatterY : (numericCols[1] ?? numericCols[0] ?? '');
  const activeGroup = stringCols.includes(groupCol) ? groupCol : 'none';

  const aggregate = (vals: number[], method: AggMethod): number => {
    if (!vals.length) return 0;
    if (method === 'sum')   return vals.reduce((a, b) => a + b, 0);
    if (method === 'mean')  return vals.reduce((a, b) => a + b, 0) / vals.length;
    if (method === 'max')   return Math.max(...vals);
    if (method === 'min')   return Math.min(...vals);
    if (method === 'count') return vals.length;
    return 0;
  };

  const groupedData = useMemo(() => {
    if (!activeValue) return [];
    if (activeGroup === 'none') {
      return rows.map((r, i) => ({
        label: nameCol ? stringValue(r[nameCol]) || `Row ${i + 1}` : `Row ${i + 1}`,
        value: numVal(r[activeValue]),
        group: '',
      }));
    }
    const map = new Map<string, number[]>();
    rows.forEach((r) => {
      const g = stringValue(r[activeGroup]) || '(blank)';
      if (!map.has(g)) map.set(g, []);
      map.get(g)!.push(numVal(r[activeValue]));
    });
    return Array.from(map.entries())
      .map(([label, vals]) => ({ label, value: aggregate(vals, agg), group: label }))
      .sort((a, b) => b.value - a.value);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, activeValue, activeGroup, agg, nameCol]);

  const colorByGroup = useMemo(() => {
    const groups = Array.from(new Set(groupedData.map((d) => d.group)));
    return Object.fromEntries(groups.map((g, i) => [g, PALETTE[i % PALETTE.length]]));
  }, [groupedData]);

  if (!rows.length) return <div className="ia-empty">No data — add rows to see charts.</div>;

  // ──────────────────────────────────────────────────────────────────────────
  // TEMPORAL rendering
  // ──────────────────────────────────────────────────────────────────────────

  if (isTs) {
    const xLabels = rows.map((r) => frozenCol ? stringValue(r[frozenCol]) : String(Object.values(r)[0] ?? ''));
    const displayCols = (tsSeries === '__all__' ? tsCols : [tsSeries]).slice(0, 15);
    const series = displayCols.map((col, i) => ({
      key: col,
      values: rows.map((r) => numVal(r[col])),
      color: PALETTE[i % PALETTE.length],
    }));

    return (
      <div className="ia-panel">
        <div className="ia-controls">
          <Ctl label="Series">
            <SearchableSelect
              className="ia-select"
              value={tsSeries}
              options={[{ value: '__all__', label: 'All' }, ...tsCols]}
              onChange={(v) => setTsSeries(v)}
            />
          </Ctl>
          <Ctl label="Chart">
            <SearchableSelect
              className="ia-select"
              value={tsChart}
              options={[
                { value: 'line', label: 'Line' },
                { value: 'stacked-area', label: 'Stacked area' },
                { value: 'duration', label: 'Duration curve' },
                { value: 'daily-profile', label: 'Daily profile' },
              ]}
              onChange={(v) => setTsChart(v as TsChart)}
            />
          </Ctl>
          <span className="ia-meta">{rows.length} snapshots · {tsCols.length} series</span>
        </div>

        <div className="ia-chart-wrap">
          {tsChart === 'line' && <LineArea xLabels={xLabels} series={series} stacked={false} />}
          {tsChart === 'stacked-area' && <LineArea xLabels={xLabels} series={series} stacked />}
          {tsChart === 'duration' && (
            series.length === 1
              ? <DurationCurve values={series[0].values} label={series[0].key} color={series[0].color} />
              : <div className="ia-tip">Select a single series for the duration curve.</div>
          )}
          {tsChart === 'daily-profile' && <DailyProfile xLabels={xLabels} series={series} />}
        </div>
        <Legend items={series} />
      </div>
    );
  }

  // ──────────────────────────────────────────────────────────────────────────
  // STATIC rendering
  // ──────────────────────────────────────────────────────────────────────────

  if (!numericCols.length) return <div className="ia-empty">No numeric columns to analyse.</div>;

  const labels = groupedData.map((d) => d.label);
  const values = groupedData.map((d) => d.value);
  const colors = groupedData.map((d) => colorByGroup[d.group] ?? PALETTE[0]);

  // Detect unit from column name
  const unit =
    activeValue.includes('cost') ? `${currencySymbol}/MWh`
    : activeValue === 'p_nom' || activeValue.includes('_mw') ? 'MW'
    : activeValue.includes('efficiency') || activeValue.includes('_pu') ? ''
    : '';

  const donutData = groupedData.map((d, i) => ({
    label: d.label, value: d.value, color: PALETTE[i % PALETTE.length],
  }));

  const scatterXVals = rows.map((r) => numVal(r[activeValue]));
  const scatterYVals = rows.map((r) => numVal(r[activeScatY]));
  const scatterLabels = rows.map((r, i) => nameCol ? stringValue(r[nameCol]) || `Row ${i+1}` : `Row ${i+1}`);

  const showGroupCtl = staticChart !== 'scatter';
  const showAggCtl   = showGroupCtl && activeGroup !== 'none';
  const showScatterY = staticChart === 'scatter';

  return (
    <div className="ia-panel">
      <div className="ia-controls">
        <Ctl label="Value">
          <SearchableSelect className="ia-select" value={activeValue} options={numericCols} onChange={(v) => setValueCol(v)} />
        </Ctl>
        {showScatterY && (
          <Ctl label="Y axis">
            <SearchableSelect className="ia-select" value={activeScatY} options={numericCols} onChange={(v) => setScatterY(v)} />
          </Ctl>
        )}
        {showGroupCtl && (
          <Ctl label="Group by">
            <SearchableSelect
              className="ia-select"
              value={activeGroup}
              options={[{ value: 'none', label: 'None (per row)' }, ...stringCols]}
              onChange={(v) => setGroupCol(v)}
            />
          </Ctl>
        )}
        {showAggCtl && (
          <Ctl label="Aggregate">
            <SearchableSelect
              className="ia-select"
              value={agg}
              options={[
                { value: 'sum', label: 'Sum' },
                { value: 'mean', label: 'Mean' },
                { value: 'max', label: 'Max' },
                { value: 'min', label: 'Min' },
                { value: 'count', label: 'Count' },
              ]}
              onChange={(v) => setAgg(v as AggMethod)}
            />
          </Ctl>
        )}
        <Ctl label="Chart">
          <SearchableSelect
            className="ia-select"
            value={staticChart}
            options={[
              { value: 'bar', label: 'Bar' },
              { value: 'grouped-bar', label: 'Grouped bar' },
              { value: 'donut', label: 'Donut' },
              { value: 'scatter', label: 'Scatter' },
            ]}
            onChange={(v) => setStaticChart(v as StaticChart)}
          />
        </Ctl>
        <span className="ia-meta">{rows.length} rows</span>
      </div>

      <div className="ia-chart-wrap">
        {staticChart === 'bar' && (
          <HBar labels={labels} values={values} colors={colors} unit={unit} />
        )}
        {staticChart === 'grouped-bar' && (
          <HBar labels={labels} values={values} colors={colors} unit={unit} />
        )}
        {staticChart === 'donut' && (
          <Donut data={donutData} />
        )}
        {staticChart === 'scatter' && (
          <Scatter xVals={scatterXVals} yVals={scatterYVals} labels={scatterLabels} xCol={activeValue} yCol={activeScatY} />
        )}
      </div>
    </div>
  );
}
