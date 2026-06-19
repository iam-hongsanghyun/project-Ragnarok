import React, { useMemo } from 'react';
import { buildScatterOption } from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../../shared/echarts/useEChart';
import { PivotScatterResult } from 'lib/results/pivot';

/** Renders a pivot scatter — one point per component (or group): X vs Y. */
export function ScatterPlotCard({
  data, xName, yName, showAxisLabels = true,
}: {
  data: PivotScatterResult;
  xName: string;
  yName: string;
  showAxisLabels?: boolean;
}) {
  const option = useMemo(() => {
    if (!data.points.length) return null;
    return buildScatterOption({ points: data.points, xName, yName, showAxisLabels, theme: readChartTheme() });
  }, [data, xName, yName, showAxisLabels]);

  // The host is rendered unconditionally so useEChart's one-time mount effect
  // always attaches its ResizeObserver (a host that only appears on a later
  // render would never initialise). The empty hint overlays it.
  const hostRef = useEChart<HTMLDivElement>(option);

  return (
    <section className="chart-card chart-card-wide">
      <div className="chart-shell">
        <div className="chart-main" style={{ position: 'relative' }}>
          <div ref={hostRef} className="echart-host" role="img" />
          {!option && (
            <p className="empty-text" style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              Pick an X and Y attribute to plot a scatter.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
