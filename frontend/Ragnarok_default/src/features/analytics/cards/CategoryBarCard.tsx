import React, { useMemo } from 'react';
import { buildGroupedBarOption, buildHorizontalBarOption } from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../../shared/echarts/useEChart';
import { PivotCategoryResult } from 'lib/results/pivot';

/** Renders a pivot category bar (vertical grouped/stacked, or horizontal). */
export function CategoryBarCard({
  data, mode, stacked, unit, title, description, showLegend = true, showAxisLabels = true, xAxisTitle, yAxisTitle, xLabelAngle = 0,
}: {
  data: PivotCategoryResult;
  mode: 'hbar' | 'grouped-bar';
  stacked: boolean;
  unit: string;
  title: string;
  description: string;
  showLegend?: boolean;
  showAxisLabels?: boolean;
  xAxisTitle?: string;
  yAxisTitle?: string;
  xLabelAngle?: number;
}) {
  const option = useMemo(() => {
    if (!data.labels.length || !data.series.length) return null;
    const input = {
      labels: data.labels,
      series: data.series,
      stacked,
      barColors: data.barColors,
      unit,
      xAxisTitle,
      yAxisTitle,
      showAxisLabels,
      xLabelAngle,
      theme: readChartTheme(),
    };
    return mode === 'hbar' ? buildHorizontalBarOption(input) : buildGroupedBarOption(input);
  }, [data, mode, stacked, unit, xAxisTitle, yAxisTitle, showAxisLabels, xLabelAngle]);

  // The host is rendered unconditionally so useEChart's one-time mount effect
  // always attaches (a host that only appears on a later render would never
  // initialise). The empty hint overlays it.
  const hostRef = useEChart<HTMLDivElement>(option);
  // A side legend is meaningful only when there are multiple stacked/clustered
  // series; the single-series "by category" bar colours each bar individually.
  const multi = data.series.length > 1;

  return (
    <section className="chart-card chart-card-wide">
      {(title || description) && (
        <div className="chart-card-header"><div><h3>{title}</h3><p>{description}</p></div></div>
      )}
      <div className="chart-shell">
        <div className="chart-main" style={{ position: 'relative' }}>
          <div ref={hostRef} className="echart-host" role="img" />
          {!option && (
            <p className="empty-text" style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              No data for current selection.
            </p>
          )}
        </div>
        {showLegend && multi && (
          <div className="chart-legend chart-legend-side">
            <div className="map-legend-title" style={{ marginBottom: 4 }}>Series</div>
            {data.series.map((s) => (
              <div key={s.key} className="legend-item-inline">
                <span className="legend-swatch" style={{ backgroundColor: s.color }} />
                <span>{s.label}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
