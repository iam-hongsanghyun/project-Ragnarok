import { useEffect, useRef } from 'react';
import type { EChartsCoreOption } from 'echarts/core';
import { echarts, EChartsType } from './setup';

/**
 * Mount an ECharts instance (SVG renderer) on the returned ref's element and
 * keep it in sync:
 *   - defers init until the host has a non-zero size (hosts inside flex /
 *     container-query layouts are often 0x0 on the first paint), then applies
 *     the latest option;
 *   - re-applies `option` whenever it changes (callers should useMemo large
 *     options so this doesn't run on unrelated re-renders);
 *   - resizes with the host element via ResizeObserver, which is what lets a
 *     chart re-fit its dashboard cell during a drag-resize;
 *   - disposes on unmount.
 */
export function useEChart<T extends HTMLElement>(
  option: EChartsCoreOption | null,
): React.RefObject<T | null> {
  const ref = useRef<T>(null);
  const chartRef = useRef<EChartsType | null>(null);
  const optionRef = useRef<EChartsCoreOption | null>(option);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ensureChart = () => {
      if (el.clientWidth === 0 || el.clientHeight === 0) return;
      if (!chartRef.current) {
        const chart = echarts.init(el, undefined, { renderer: 'svg' });
        chartRef.current = chart;
        if (optionRef.current) chart.setOption(optionRef.current, { notMerge: true });
      } else if (!chartRef.current.isDisposed()) {
        chartRef.current.resize();
      }
    };
    ensureChart();
    const ro = new ResizeObserver(ensureChart);
    ro.observe(el);
    return () => {
      ro.disconnect();
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    optionRef.current = option;
    const chart = chartRef.current;
    if (chart && option && !chart.isDisposed()) {
      chart.setOption(option, { notMerge: true });
    }
  }, [option]);

  return ref;
}
