import React, { useMemo } from 'react';
import { ChartMode, TimeSeriesRow, TimeSeriesSeries } from 'lib/types';
import { numberValue, isoDate, isoTime } from 'lib/utils/helpers';
import { effectiveSpanMs } from 'lib/results/analytics';
import { buildTimeSeriesOption } from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../../shared/echarts/useEChart';

const H24 = 86_400_000;
const H7D = 7 * H24;
const H90D = 90 * H24;

// All x-axis labels use the canonical ISO target format (YYYY-MM-DD), never locale month names.
function formatXLabel(ts: string | undefined, spanMs: number): string {
  if (!ts) return '';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  if (spanMs <= H24)  return isoTime(d);                      // HH:MM
  if (spanMs <= H7D)  return `${isoDate(d)}T${isoTime(d)}`;   // YYYY-MM-DDTHH:MM
  if (spanMs <= H90D) return isoDate(d);                      // YYYY-MM-DD
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; // YYYY-MM
}

export function InteractiveTimeSeriesCard({
  title,
  description,
  data,
  series,
  mode,
  stacked,
  xAxisTitle,
  yAxisTitle,
  showLegend = true,
  showAxisLabels = true,
  xLabelAngle = 0,
}: {
  title: string;
  description: string;
  data: TimeSeriesRow[];
  series: TimeSeriesSeries[];
  mode: ChartMode;
  stacked: boolean;
  xAxisTitle?: string;
  yAxisTitle?: string;
  showLegend?: boolean;
  showAxisLabels?: boolean;
  xLabelAngle?: number;
}) {
  // Series that never leave ~zero are dropped from the chart AND the legend,
  // same as the old SVG renderer did.
  const visibleSeries = useMemo(
    () => series.filter((item) =>
      data.some((row) => Math.abs(numberValue(row[item.key] as string | number | undefined)) > 1e-6),
    ),
    [data, series],
  );

  const option = useMemo(() => {
    if (!data.length || !visibleSeries.length) return null;
    const spanMs = effectiveSpanMs(data);
    const xLabels = data.map((row) => (row.timestamp ? formatXLabel(row.timestamp, spanMs) : row.label));
    return buildTimeSeriesOption({
      xLabels,
      rows: data,
      series: visibleSeries,
      mode,
      stacked,
      xAxisTitle,
      yAxisTitle,
      showAxisLabels,
      xLabelAngle: Number.isFinite(xLabelAngle) ? xLabelAngle : 0,
      theme: readChartTheme(),
    });
  }, [data, visibleSeries, mode, stacked, xAxisTitle, yAxisTitle, showAxisLabels, xLabelAngle]);

  const hostRef = useEChart<HTMLDivElement>(option);

  if (!series.length) {
    return (
      <section className="chart-card chart-card-wide">
        <div className="chart-card-header">
          <div><h3>{title}</h3><p>{description}</p></div>
        </div>
        <p className="empty-text">No chart series are available for this selection.</p>
      </section>
    );
  }

  if (!data.length) {
    return (
      <section className="chart-card">
        <div className="chart-card-header">
          <div><h3>{title}</h3><p>{description}</p></div>
        </div>
        <p className="empty-text">No series available for this selection.</p>
      </section>
    );
  }

  return (
    <section className="chart-card chart-card-wide">
      <div className="chart-card-header">
        <div><h3>{title}</h3><p>{description}</p></div>
      </div>
      <div className="chart-shell">
        <div className="chart-main">
          <div ref={hostRef} className="echart-host" role="img" />
        </div>
        {showLegend && (
        <div className="chart-legend chart-legend-side">
          <div className="map-legend-title" style={{ marginBottom: 4 }}>Series</div>
          {visibleSeries.map((item) => (
            <div key={item.key} className="legend-item-inline">
              <span className="legend-swatch" style={{ backgroundColor: item.color }} />
              <span>{item.label}</span>
            </div>
          ))}
        </div>
        )}
      </div>
    </section>
  );
}
