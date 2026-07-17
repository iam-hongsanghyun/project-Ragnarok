import React, { useMemo } from 'react';
import { buildDurationCurveOption, DurationCurveSeriesInput } from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../../shared/echarts/useEChart';

interface Props {
  title: string;
  /** One curve per group — each already sorted descending by the caller,
   *  independently of every other group's own ranking. A single-series caller
   *  (e.g. system price/load) passes an array of one. */
  data: DurationCurveSeriesInput[];
  unit: string;
  showLegend?: boolean;
}

export function DurationCurveCard({ title, data, unit, showLegend = true }: Props) {
  const hasData = data.some((s) => s.values.length > 0);
  const option = useMemo(() => {
    if (!hasData) return null;
    // CSS variables (e.g. 'var(--warm)') come through from the dashboard
    // config; resolve them since ECharts SVG attributes need literal colours.
    const resolveColor = (color: string): string =>
      color.startsWith('var(')
        ? getComputedStyle(document.documentElement)
            .getPropertyValue(color.slice(4, -1)).trim() || '#0f766e'
        : color;
    const series = data.map((s) => ({ ...s, color: resolveColor(s.color) }));
    return buildDurationCurveOption({ series, title, unit, theme: readChartTheme(), showLegend });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, title, unit, showLegend, hasData]);
  const hostRef = useEChart<HTMLDivElement>(option);

  if (!hasData) {
    return (
      <div className="duration-curve-card">
        <p className="empty-text">No data available.</p>
      </div>
    );
  }

  return (
    <div className="duration-curve-card">
      <div ref={hostRef} className="duration-curve-host" role="img" />
    </div>
  );
}
