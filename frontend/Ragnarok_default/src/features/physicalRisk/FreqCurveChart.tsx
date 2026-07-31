/**
 * FreqCurveChart — return-period (exceedance) curve for a physical-risk peril.
 *
 * Ported to ECharts (lib/charts/options.ts's `buildFreqCurveOption`) from the
 * standalone climaterisk app's dependency-free SVG chart. The log-x/linear-y
 * return-period shape, units and labels are preserved exactly; the chart now
 * gains a real tooltip, hover, dataZoom and a save-as-image toolbox like every
 * other chart in the app instead of being a one-off static drawing.
 */
import React, { useMemo } from 'react';
import { FreqCurve } from 'lib/physicalRisk/types';
import { buildFreqCurveOption } from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../shared/echarts/useEChart';

interface Props {
  curve: FreqCurve;
  currencySymbol: string;
}

export function FreqCurveChart({ curve, currencySymbol }: Props) {
  const option = useMemo(() => {
    if (curve.returnPeriods.length === 0) return null;
    return buildFreqCurveOption({ curve, currencySymbol, theme: readChartTheme() });
  }, [curve, currencySymbol]);
  // The host is rendered unconditionally so useEChart's one-time mount effect
  // always attaches (a host that only appears on a later render would never
  // initialise). The empty hint overlays it.
  const hostRef = useEChart<HTMLDivElement>(option);

  return (
    <div style={{ position: 'relative', height: 240 }}>
      <div ref={hostRef} className="echart-host" role="img" aria-label="Return-period loss curve" />
      {!option && (
        <p className="empty-text" style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          No return-period data for this peril.
        </p>
      )}
    </div>
  );
}
