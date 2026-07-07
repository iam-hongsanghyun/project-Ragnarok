/**
 * CorrelatedSamplingCard — correlated multi-driver Monte-Carlo reliability
 * results.
 *
 * KPI row from the backend summary, then the EUE distribution as a histogram
 * (with P50/P95 callouts) and a per-driver summary table (mean / P95
 * multiplier relative to the base profile).
 */
import React, { useMemo } from 'react';
import { CorrelatedSamplingResult } from 'lib/types';
import { buildGroupedBarOption } from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../../shared/echarts/useEChart';

interface Props {
  data: CorrelatedSamplingResult;
}

function EueHistogram({ data }: { data: CorrelatedSamplingResult }) {
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

export function CorrelatedSamplingCard({ data }: Props) {
  if (!data || !data.enabled) return null;

  const summary = Array.isArray(data.summary) ? data.summary : [];
  const drivers = Array.isArray(data.driverSummary) ? data.driverSummary : [];

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
        {drivers.length > 0 && (
          <div className="econ-table-col" style={{ flex: '1 1 320px' }}>
            <p className="econ-section-label">Driver summary</p>
            <div className="econ-table-wrap">
              <table className="econ-table">
                <thead>
                  <tr>
                    <th>Driver</th>
                    <th className="num">Mean x</th>
                    <th className="num">P95 x</th>
                  </tr>
                </thead>
                <tbody>
                  {drivers.map((d) => (
                    <tr key={d.driver}>
                      <td>{d.driver}</td>
                      <td className="num">{d.meanMultiplier.toFixed(2)}</td>
                      <td className="num">{d.p95Multiplier.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {data.note && <p className="econ-note">{data.note}</p>}
    </div>
  );
}
