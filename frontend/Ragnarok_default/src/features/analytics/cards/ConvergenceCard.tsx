/**
 * ConvergenceCard — convergence-controlled sampling + maintenance placement
 * reliability results.
 *
 * KPI row from the backend summary (estimate ± CI, achieved members,
 * converged), a convergence trace line chart (running estimate vs members
 * sampled), and — when maintenance placement was enabled — a schedule table.
 */
import React, { useMemo } from 'react';
import { ConvergenceResult } from 'lib/types';
import { buildTimeSeriesOption } from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../../shared/echarts/useEChart';

interface Props {
  data: ConvergenceResult;
}

function toSeriesRows(points: { label: string; value: number }[], key: string) {
  return points.map((p) => ({ label: p.label, timestamp: p.label, [key]: p.value }));
}

function TraceChart({ data }: { data: ConvergenceResult }) {
  const trace = useMemo(() => (Array.isArray(data.trace) ? data.trace : []), [data.trace]);
  const points = useMemo(
    () => trace.map((t) => ({ label: t.members.toLocaleString(), value: t.estimate })),
    [trace],
  );
  const option = useMemo(() => {
    if (!points.length) return null;
    return buildTimeSeriesOption({
      xLabels: points.map((p) => p.label),
      rows: toSeriesRows(points, 'estimate'),
      series: [{ key: 'estimate', label: `${data.targetMetric.toUpperCase()} estimate`, color: 'var(--brand, #0f766e)' }],
      mode: 'line',
      stacked: false,
      xAxisTitle: 'Members sampled',
      yAxisTitle: data.unit,
      showAxisLabels: true,
      xLabelAngle: 0,
      theme: readChartTheme(),
    });
  }, [points, data.targetMetric, data.unit]);
  const hostRef = useEChart<HTMLDivElement>(option);

  if (!points.length) {
    return <p className="econ-note">No convergence trace for this run.</p>;
  }
  return <div ref={hostRef} className="echart-host" role="img" style={{ minHeight: 220 }} />;
}

export function ConvergenceCard({ data }: Props) {
  if (!data || !data.enabled) return null;

  const summary = Array.isArray(data.summary) ? data.summary : [];
  const schedule = data.maintenance && Array.isArray(data.maintenance.schedule) ? data.maintenance.schedule : [];

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
          <div className="econ-kpi-label">{data.targetMetric.toUpperCase()} estimate (95% CI)</div>
          <div className="econ-kpi-value">
            {data.estimate.toLocaleString()} {data.unit}
          </div>
          <div className="econ-kpi-unit">
            {data.ciLow.toLocaleString()} &ndash; {data.ciHigh.toLocaleString()} {data.unit}
          </div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Achieved members</div>
          <div className="econ-kpi-value">{data.achievedMembers.toLocaleString()}</div>
          <div className="econ-kpi-unit">tolerance {(data.tolerance * 100).toFixed(1)}%</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Converged</div>
          <div className="econ-kpi-value">{data.converged ? 'Yes' : 'No'}</div>
        </div>
      </div>

      <div className="econ-body">
        <div className="econ-table-col" style={{ flex: '1 1 320px' }}>
          <p className="econ-section-label">Convergence trace</p>
          <TraceChart data={data} />
        </div>
      </div>

      {data.maintenance?.enabled && schedule.length > 0 && (
        <div className="econ-body">
          <div className="econ-table-col">
            <p className="econ-section-label">Maintenance schedule</p>
            {data.maintenance.summary.length > 0 && (
              <div className="econ-kpi-row">
                {data.maintenance.summary.map((s) => (
                  <div className="econ-kpi" key={s.label}>
                    <div className="econ-kpi-label">{s.label}</div>
                    <div className="econ-kpi-value">{s.value}</div>
                    {s.detail && <div className="econ-kpi-unit">{s.detail}</div>}
                  </div>
                ))}
              </div>
            )}
            <div className="econ-table-wrap">
              <table className="econ-table">
                <thead>
                  <tr>
                    <th>Unit</th>
                    <th>Carrier</th>
                    <th>Start</th>
                    <th className="num">Weeks</th>
                  </tr>
                </thead>
                <tbody>
                  {schedule.map((entry) => (
                    <tr key={`${entry.unit}-${entry.startLabel}`}>
                      <td>{entry.unit}</td>
                      <td>{entry.carrier}</td>
                      <td>{entry.startLabel}</td>
                      <td className="num">{entry.weeks}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {data.note && <p className="econ-note">{data.note}</p>}
    </div>
  );
}
