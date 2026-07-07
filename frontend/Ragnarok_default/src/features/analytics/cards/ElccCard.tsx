/**
 * ElccCard — Effective Load-Carrying Capability (ELCC / capacity credit)
 * results.
 *
 * KPI row from the backend summary (baseline LOLE, resources evaluated), a
 * per-carrier ELCC table (nameplate / ELCC MW / ELCC %), and a bar chart of
 * ELCC % by carrier.
 */
import React, { useMemo } from 'react';
import { ElccResult } from 'lib/types';
import { buildGroupedBarOption } from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../../shared/echarts/useEChart';

interface Props {
  data: ElccResult;
}

function ElccBarChart({ data }: { data: ElccResult }) {
  const byCarrier = useMemo(() => (Array.isArray(data.byCarrier) ? data.byCarrier : []), [data.byCarrier]);
  const option = useMemo(() => {
    if (!byCarrier.length) return null;
    return buildGroupedBarOption({
      labels: byCarrier.map((c) => c.carrier),
      series: [{ key: 'elccPct', label: 'ELCC %', color: 'var(--brand, #0f766e)', values: byCarrier.map((c) => c.elccPct) }],
      barColors: byCarrier.map((c) => c.color ?? 'var(--brand, #0f766e)'),
      stacked: false,
      unit: '%',
      xAxisTitle: 'Carrier',
      yAxisTitle: 'ELCC %',
      showAxisLabels: true,
      xLabelAngle: 0,
      theme: readChartTheme(),
    });
  }, [byCarrier]);
  const hostRef = useEChart<HTMLDivElement>(option);

  if (!byCarrier.length) {
    return <p className="econ-note">No ELCC results for this run.</p>;
  }
  return <div ref={hostRef} className="echart-host" role="img" style={{ minHeight: 220 }} />;
}

export function ElccCard({ data }: Props) {
  if (!data || !data.enabled) return null;

  const summary = Array.isArray(data.summary) ? data.summary : [];
  const byCarrier = Array.isArray(data.byCarrier) ? data.byCarrier : [];

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
          <div className="econ-kpi-label">Resources evaluated</div>
          <div className="econ-kpi-value">{byCarrier.length}</div>
          <div className="econ-kpi-unit">{data.nMembers} samples · seed {data.seed}</div>
        </div>
      </div>

      <div className="econ-body">
        {byCarrier.length > 0 && (
          <div className="econ-table-col" style={{ flex: '1 1 320px' }}>
            <p className="econ-section-label">ELCC by carrier</p>
            <div className="econ-table-wrap">
              <table className="econ-table">
                <thead>
                  <tr>
                    <th>Carrier</th>
                    <th className="num">Nameplate MW</th>
                    <th className="num">ELCC MW</th>
                    <th className="num">ELCC %</th>
                  </tr>
                </thead>
                <tbody>
                  {byCarrier.map((c) => (
                    <tr key={c.carrier}>
                      <td>{c.carrier}</td>
                      <td className="num">{Math.round(c.nameplateMw).toLocaleString()}</td>
                      <td className="num">{Math.round(c.elccMw).toLocaleString()}</td>
                      <td className="num">{c.elccPct.toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        <div className="econ-table-col" style={{ flex: '1 1 320px' }}>
          <p className="econ-section-label">ELCC % by carrier</p>
          <ElccBarChart data={data} />
        </div>
      </div>

      {data.note && <p className="econ-note">{data.note}</p>}
    </div>
  );
}
