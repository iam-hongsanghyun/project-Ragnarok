/**
 * LmpDecompositionCard — energy vs congestion decomposition of locational
 * marginal prices.
 *
 * KPI row from the backend summary, a per-bus table (mean LMP / energy /
 * congestion / congestion cost), a congested-lines table (congestion rent /
 * hours congested / utilization), and a stacked bar of energy + congestion
 * per bus (top 15 by mean LMP).
 */
import React, { useMemo } from 'react';
import { LmpDecompositionResult } from 'lib/types';
import { buildGroupedBarOption } from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../../shared/echarts/useEChart';

interface Props {
  data: LmpDecompositionResult;
}

const MAX_BUSES_IN_CHART = 15;

function BusBarChart({ data }: { data: LmpDecompositionResult }) {
  const buses = useMemo(() => (Array.isArray(data.buses) ? data.buses : []), [data.buses]);
  const top = useMemo(
    () => [...buses].sort((a, b) => b.meanLmp - a.meanLmp).slice(0, MAX_BUSES_IN_CHART),
    [buses],
  );
  const option = useMemo(() => {
    if (!top.length) return null;
    return buildGroupedBarOption({
      labels: top.map((b) => b.bus),
      series: [
        { key: 'energy', label: `Energy (${data.unit})`, color: 'var(--brand, #0f766e)', values: top.map((b) => b.energy) },
        { key: 'congestion', label: `Congestion (${data.unit})`, color: 'var(--danger, #dc2626)', values: top.map((b) => b.congestion) },
      ],
      stacked: true,
      unit: data.unit,
      xAxisTitle: 'Bus',
      yAxisTitle: data.unit,
      showAxisLabels: true,
      xLabelAngle: -30,
      theme: readChartTheme(),
    });
  }, [top, data.unit]);
  const hostRef = useEChart<HTMLDivElement>(option);

  if (!top.length) {
    return <p className="econ-note">No per-bus LMP data for this run.</p>;
  }
  return <div ref={hostRef} className="echart-host" role="img" style={{ minHeight: 220 }} />;
}

export function LmpDecompositionCard({ data }: Props) {
  if (!data || !data.enabled) return null;

  const summary = Array.isArray(data.summary) ? data.summary : [];
  const buses = Array.isArray(data.buses) ? data.buses : [];
  const lines = Array.isArray(data.lines) ? data.lines : [];

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
      </div>

      <div className="econ-body">
        {buses.length > 0 && (
          <div className="econ-table-col" style={{ flex: '1 1 320px' }}>
            <p className="econ-section-label">LMP by bus</p>
            <div className="econ-table-wrap">
              <table className="econ-table">
                <thead>
                  <tr>
                    <th>Bus</th>
                    <th className="num">Mean LMP</th>
                    <th className="num">Energy</th>
                    <th className="num">Congestion</th>
                    <th className="num">Congestion cost</th>
                  </tr>
                </thead>
                <tbody>
                  {buses.map((b) => (
                    <tr key={b.bus}>
                      <td>{b.bus}</td>
                      <td className="num">{b.meanLmp.toLocaleString()} {data.unit}</td>
                      <td className="num">{b.energy.toLocaleString()} {data.unit}</td>
                      <td className="num">{b.congestion.toLocaleString()} {data.unit}</td>
                      <td className="num">{b.congestionCost.toLocaleString()} {data.currency}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        <div className="econ-table-col" style={{ flex: '1 1 320px' }}>
          <p className="econ-section-label">Energy + congestion by bus</p>
          <BusBarChart data={data} />
        </div>
      </div>

      {lines.length > 0 && (
        <div className="econ-body">
          <div className="econ-table-col">
            <p className="econ-section-label">Congested lines</p>
            <div className="econ-table-wrap">
              <table className="econ-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>From &ndash; To</th>
                    <th className="num">Congestion rent</th>
                    <th className="num">Hours congested</th>
                    <th className="num">Utilization</th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((l) => (
                    <tr key={l.name}>
                      <td>{l.name}</td>
                      <td>{l.from} &ndash; {l.to}</td>
                      <td className="num">{l.congestionRent.toLocaleString()} {data.currency}</td>
                      <td className="num">{l.hoursCongested.toLocaleString()}</td>
                      <td className="num">{l.utilizationPct.toFixed(1)}%</td>
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
