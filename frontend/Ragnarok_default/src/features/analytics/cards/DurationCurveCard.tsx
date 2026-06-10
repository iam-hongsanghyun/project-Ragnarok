import React, { useMemo } from 'react';
import { buildDurationCurveOption } from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../../shared/echarts/useEChart';

interface Props {
  title: string;
  /** Values in rank order (sorted descending by the caller). */
  data: number[];
  unit: string;
  color: string;
}

export function DurationCurveCard({ title, data, unit, color }: Props) {
  const option = useMemo(() => {
    if (!data.length) return null;
    // CSS variables (e.g. 'var(--warm)') come through from the dashboard
    // config; resolve them since ECharts SVG attributes need literal colours.
    const resolved = color.startsWith('var(')
      ? getComputedStyle(document.documentElement)
          .getPropertyValue(color.slice(4, -1)).trim() || '#0f766e'
      : color;
    return buildDurationCurveOption({ data, title, unit, color: resolved, theme: readChartTheme() });
  }, [data, title, unit, color]);
  const hostRef = useEChart<HTMLDivElement>(option);

  if (!data.length) {
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
