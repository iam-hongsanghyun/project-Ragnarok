/**
 * One interactive ECharts panel with loading / error / empty states.
 *
 * The host div is always rendered so useEChart's mount effect attaches its
 * ResizeObserver; the state message overlays it instead of replacing it.
 */
import React from 'react';
import type { EChartsCoreOption } from 'echarts/core';
import { useEChart } from '../../shared/echarts/useEChart';

interface Props {
  option: EChartsCoreOption | null;
  loading?: boolean;
  error?: string | null;
  /** Shown when there is no option and no error / loading. */
  emptyText: string;
  tall?: boolean;
  label: string;
}

export function ChartPanel({ option, loading = false, error = null, emptyText, tall = false, label }: Props) {
  const hostRef = useEChart<HTMLDivElement>(option);
  let message: string | null = null;
  let isError = false;
  if (error) {
    message = error;
    isError = true;
  } else if (loading && !option) {
    message = 'Loading...';
  } else if (!option) {
    message = emptyText;
  }
  return (
    <div className={`scr-chart${tall ? ' scr-chart--tall' : ''}`} data-loading={loading ? 'true' : undefined}>
      <div ref={hostRef} className="echart-host" role="img" aria-label={label} style={{ width: '100%', height: '100%' }} />
      {message && <div className={`scr-chart-state${isError ? ' scr-error' : ''}`}>{message}</div>}
    </div>
  );
}
