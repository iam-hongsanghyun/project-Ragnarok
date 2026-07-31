/**
 * RiskBarChart — horizontal labeled bar chart for a "name -> value" breakdown
 * (supply-chain indirect impact by sector, forecast near-term impact series).
 *
 * Ported to ECharts (lib/charts/options.ts's `buildRiskBarOption`) from the
 * standalone climaterisk app's dependency-free SVG chart. Same shape and
 * value formatting as before; the chart now gains a real tooltip and hover
 * emphasis instead of being a one-off static drawing.
 */
import React, { useMemo } from 'react';
import { buildRiskBarOption, RiskBarDatum } from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../shared/echarts/useEChart';

export type { RiskBarDatum };

interface Props {
  data: RiskBarDatum[];
  formatValue: (v: number) => string;
}

const ROW_HEIGHT = 28;

export function RiskBarChart({ data, formatValue }: Props) {
  const option = useMemo(() => {
    if (data.length === 0) return null;
    return buildRiskBarOption({ data, formatValue, theme: readChartTheme() });
  }, [data, formatValue]);
  // The host is rendered unconditionally so useEChart's one-time mount effect
  // always attaches (a host that only appears on a later render would never
  // initialise). The empty hint overlays it.
  const hostRef = useEChart<HTMLDivElement>(option);
  const height = Math.max(data.length * ROW_HEIGHT + 16, 90);

  return (
    <div style={{ position: 'relative', height }}>
      <div ref={hostRef} className="echart-host" role="img" aria-label="Bar chart" />
      {!option && (
        <p className="empty-text" style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          No data for this breakdown.
        </p>
      )}
    </div>
  );
}
