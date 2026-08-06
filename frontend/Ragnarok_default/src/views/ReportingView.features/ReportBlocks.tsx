/**
 * Report block renderers — one component per block type of the report
 * document payload (`lib/reporting/types.ts`).
 *
 * Charts reuse the shared ECharts option builders so report figures look
 * exactly like their Analytics counterparts; series without a colour get the
 * validated categorical palette in order (never cycled — report charts carry
 * few series by construction).
 */
import React, { useMemo } from 'react';
import type { MixItem, TimeSeriesRow, TimeSeriesSeries } from 'lib/types';
import {
  buildDonutOption,
  buildGroupedBarOption,
  buildTimeSeriesOption,
} from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import type { ChartTheme } from 'lib/charts/theme';
import type { ReportBlock, ReportChart } from 'lib/reporting/types';
import { SummaryCards } from 'shared/components/SummaryCards';
import { useEChart } from '../../shared/echarts/useEChart';

function seriesColor(theme: ChartTheme, explicit: string | null | undefined, index: number): string {
  return explicit ?? theme.seriesPalette[index] ?? theme.muted;
}

function buildOption(chart: ReportChart, theme: ChartTheme) {
  if (chart.kind === 'donut') {
    const data: MixItem[] = (chart.data ?? []).map((d, i) => ({
      label: d.label,
      value: d.value,
      color: seriesColor(theme, d.color, i),
    }));
    return buildDonutOption({ data, unit: chart.unit || undefined, theme });
  }
  if (chart.kind === 'bars') {
    const labels = chart.labels ?? [];
    const series = (chart.series ?? []).map((s, i) => ({
      key: s.key,
      label: s.label,
      color: seriesColor(theme, s.color, i),
      values: s.values.map((v) => v ?? 0),
    }));
    return buildGroupedBarOption({
      labels,
      series,
      stacked: !!chart.stacked,
      unit: chart.unit || undefined,
      showAxisLabels: true,
      xLabelAngle: labels.some((l) => l.length > 8) ? -30 : 0,
      theme,
      showLegend: series.length > 1,
    });
  }
  const xLabels = chart.xLabels ?? [];
  const series: TimeSeriesSeries[] = (chart.series ?? []).map((s, i) => ({
    key: s.key,
    label: s.label,
    color: seriesColor(theme, s.color, i),
  }));
  const rows: TimeSeriesRow[] = xLabels.map((label, i) => {
    const row: TimeSeriesRow = { label };
    for (const s of chart.series ?? []) row[s.key] = s.values[i] ?? undefined;
    return row;
  });
  return buildTimeSeriesOption({
    xLabels,
    rows,
    series,
    mode: chart.area ? 'area' : 'line',
    stacked: !!chart.stacked,
    showAxisLabels: true,
    xLabelAngle: 0,
    theme,
    showLegend: series.length > 1,
  });
}

function ReportChartFigure({ chart }: { chart: ReportChart }) {
  const option = useMemo(() => buildOption(chart, readChartTheme()), [chart]);
  const hostRef = useEChart<HTMLDivElement>(option);
  return (
    <figure className="report-chart">
      <figcaption>
        {chart.title}
        {chart.unit ? ` (${chart.unit})` : ''}
      </figcaption>
      <div ref={hostRef} className="report-chart-host" role="img" aria-label={chart.title} />
    </figure>
  );
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number') {
    return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  }
  return String(value);
}

export function ReportBlockView({ block }: { block: ReportBlock }) {
  if (block.type === 'kpis') {
    return (
      <SummaryCards
        items={block.items.map((item) => ({
          label: item.label,
          value: item.value,
          detail: item.detail ?? '',
        }))}
      />
    );
  }
  if (block.type === 'narrative') {
    return (
      <div className="report-narrative">
        {block.paragraphs.map((paragraph) => (
          <p key={paragraph.slice(0, 48)}>{paragraph}</p>
        ))}
      </div>
    );
  }
  if (block.type === 'table') {
    return (
      <div className="report-table-wrap">
        <div className="report-table-title">{block.title}</div>
        <table className="report-table">
          <thead>
            <tr>
              {block.columns.map((col) => (
                <th key={col.key}>{col.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, i) => (
              // Rows are static payload data; index keys are stable here.
              // eslint-disable-next-line react/no-array-index-key
              <tr key={i}>
                {block.columns.map((col) => (
                  <td key={col.key}>{formatCell(row[col.key])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (block.type === 'chart') {
    return <ReportChartFigure chart={block.chart} />;
  }
  return (
    <div className="report-unavailable">
      <p>{block.reason}</p>
      <p className="report-unavailable-requires">Requires: {block.requires}</p>
    </div>
  );
}
