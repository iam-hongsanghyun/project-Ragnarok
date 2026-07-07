/**
 * OutageMcCard — thermal forced-outage Monte-Carlo reliability results.
 *
 * KPI row from the backend summary, then the EUE distribution as a histogram
 * (with P50/P95 callouts), a per-snapshot LOLP line, and a by-carrier donut of
 * mean lost load.
 */
import React, { useMemo } from 'react';
import { OutageMcResult } from 'lib/types';
import { buildTimeSeriesOption, buildGroupedBarOption } from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../../shared/echarts/useEChart';
import { DonutChart } from './DonutChart';

interface Props {
  data: OutageMcResult;
}

function toSeriesRows(points: { label: string; value: number }[], key: string) {
  return points.map((p) => ({ label: p.label, timestamp: p.label, [key]: p.value }));
}

function LolpChart({ data }: { data: OutageMcResult }) {
  const series = useMemo(() => (Array.isArray(data.lolpSeries) ? data.lolpSeries : []), [data.lolpSeries]);
  const option = useMemo(() => {
    if (!series.length) return null;
    return buildTimeSeriesOption({
      xLabels: series.map((p) => p.label),
      rows: toSeriesRows(series, 'lolp'),
      series: [{ key: 'lolp', label: 'Loss-of-load probability', color: 'var(--danger, #dc2626)' }],
      mode: 'line',
      stacked: false,
      yAxisTitle: 'LOLP',
      showAxisLabels: true,
      xLabelAngle: 0,
      theme: readChartTheme(),
    });
  }, [series]);
  const hostRef = useEChart<HTMLDivElement>(option);

  if (!series.length) {
    return <p className="econ-note">No LOLP series for this run.</p>;
  }
  return <div ref={hostRef} className="echart-host" role="img" style={{ minHeight: 220 }} />;
}

function EueHistogram({ data }: { data: OutageMcResult }) {
  const bins = useMemo(() => (Array.isArray(data.eueHistogram) ? data.eueHistogram : []), [data.eueHistogram]);
  const option = useMemo(() => {
    if (!bins.length) return null;
    return buildGroupedBarOption({
      labels: bins.map((b) => (Number.isFinite(b.bin) ? b.bin.toLocaleString() : '—')),
      series: [{ key: 'count', label: 'Samples', color: 'var(--brand, #0f766e)', values: bins.map((b) => b.count ?? 0) }],
      stacked: false,
      unit: 'samples',
      xAxisTitle: 'EUE (MWh/yr)',
      yAxisTitle: 'Samples',
      showAxisLabels: true,
      xLabelAngle: 0,
      theme: readChartTheme(),
    });
  }, [bins]);
  const hostRef = useEChart<HTMLDivElement>(option);

  if (!bins.length) {
    return <p className="econ-note">No EUE histogram for this run.</p>;
  }
  return <div ref={hostRef} className="echart-host" role="img" style={{ minHeight: 220 }} />;
}

export function OutageMcCard({ data }: Props) {
  if (!data || !data.enabled) return null;

  const summary = Array.isArray(data.summary) ? data.summary : [];
  const byCarrier = Array.isArray(data.byCarrierLostLoad) ? data.byCarrierLostLoad : [];

  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        {summary.map((s) => (
          <div className="econ-kpi" key={s.label}>
            <div className="econ-kpi-label">{s.label}</div>
            <div className="econ-kpi-value">{s.value}</div>
            {s.detail && <div className="econ-kpi-unit">{s.detail}</div>}
          </div>
        ))}
        <div className="econ-kpi">
          <div className="econ-kpi-label">LOLE (P50 / P95)</div>
          <div className="econ-kpi-value">
            {data.loleDistribution?.p50?.toFixed(1) ?? '—'} / {data.loleDistribution?.p95?.toFixed(1) ?? '—'} h/yr
          </div>
          <div className="econ-kpi-unit">mean {data.loleDistribution?.mean?.toFixed(1) ?? '—'} · max {data.loleDistribution?.max?.toFixed(1) ?? '—'}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">EUE (P50 / P95)</div>
          <div className="econ-kpi-value">
            {data.eueDistribution?.p50?.toLocaleString() ?? '—'} / {data.eueDistribution?.p95?.toLocaleString() ?? '—'} MWh/yr
          </div>
          <div className="econ-kpi-unit">mean {data.eueDistribution?.mean?.toLocaleString() ?? '—'} · max {data.eueDistribution?.max?.toLocaleString() ?? '—'}</div>
        </div>
      </div>

      <div className="econ-body">
        <div className="econ-table-col" style={{ flex: '1 1 320px' }}>
          <p className="econ-section-label">EUE distribution ({data.nMembers} samples)</p>
          <EueHistogram data={data} />
        </div>
        <div className="econ-table-col" style={{ flex: '1 1 320px' }}>
          <p className="econ-section-label">Loss-of-load probability</p>
          <LolpChart data={data} />
        </div>
      </div>

      {byCarrier.length > 0 && (
        <div className="econ-body">
          <div className="econ-table-col">
            <p className="econ-section-label">Mean lost load by carrier</p>
            <DonutChart data={byCarrier.map((c) => ({ label: c.label, value: c.value, color: c.color ?? 'var(--muted, #6b7280)' }))} unit="MWh" />
          </div>
        </div>
      )}

      {data.note && <p className="econ-note">{data.note}</p>}
    </div>
  );
}
