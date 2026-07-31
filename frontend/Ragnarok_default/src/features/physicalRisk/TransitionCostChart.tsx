/**
 * TransitionCostChart — annual carbon-cost trajectory (year -> cost) line
 * chart for the Finance sub-tab's transition-risk panel.
 *
 * Ported to ECharts (lib/charts/options.ts's `buildTransitionCostOption`)
 * from the standalone climaterisk app's dependency-free SVG chart. Same
 * shape and value formatting as before; the chart now gains a real tooltip,
 * hover, dataZoom and a save-as-image toolbox instead of being a one-off
 * static drawing.
 */
import React, { useMemo } from 'react';
import { buildTransitionCostOption } from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../shared/echarts/useEChart';

interface Props {
  years: number[];
  values: number[];
  formatValue: (v: number) => string;
}

export function TransitionCostChart({ years, values, formatValue }: Props) {
  const option = useMemo(() => {
    if (years.length === 0) return null;
    return buildTransitionCostOption({ years, values, formatValue, theme: readChartTheme() });
  }, [years, values, formatValue]);
  // The host is rendered unconditionally so useEChart's one-time mount effect
  // always attaches (a host that only appears on a later render would never
  // initialise). The empty hint overlays it.
  const hostRef = useEChart<HTMLDivElement>(option);

  return (
    <div style={{ position: 'relative', height: 240 }}>
      <div ref={hostRef} className="echart-host" role="img" aria-label="Carbon-cost trajectory" />
      {!option && (
        <p className="empty-text" style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          No carbon-cost trajectory for this scenario.
        </p>
      )}
    </div>
  );
}
