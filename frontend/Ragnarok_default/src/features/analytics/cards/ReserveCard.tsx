/**
 * ReserveCard — operating-reserve co-optimization results.
 *
 * KPI row from the backend summary, then the reserve price over time,
 * requirement vs provided MW, and a by-carrier donut of mean reserve holding.
 */
import React, { useMemo } from 'react';
import { ReserveResult } from 'lib/types';
import { buildTimeSeriesOption } from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../../shared/echarts/useEChart';
import { DonutChart } from './DonutChart';

interface Props {
  data: ReserveResult;
  currencySymbol?: string;
}

function toSeriesRows(points: { label: string; value: number }[], key: string) {
  return points.map((p) => ({ label: p.label, timestamp: p.label, [key]: p.value }));
}

function PriceChart({ data, currencySymbol }: { data: ReserveResult; currencySymbol: string }) {
  const option = useMemo(() => {
    if (!data.priceSeries.length) return null;
    return buildTimeSeriesOption({
      xLabels: data.priceSeries.map((p) => p.label),
      rows: toSeriesRows(data.priceSeries, 'price'),
      series: [{ key: 'price', label: `Reserve price (${currencySymbol}/MW)`, color: 'var(--brand, #0f766e)' }],
      mode: 'line',
      stacked: false,
      yAxisTitle: `${currencySymbol}/MW`,
      showAxisLabels: true,
      xLabelAngle: 0,
      theme: readChartTheme(),
    });
  }, [data.priceSeries, currencySymbol]);
  const hostRef = useEChart<HTMLDivElement>(option);

  if (!data.priceSeries.length) {
    return <p className="econ-note">No reserve price series (MILP runs report holdings only, not a shadow price).</p>;
  }
  return <div ref={hostRef} className="echart-host" role="img" style={{ minHeight: 220 }} />;
}

function RequirementChart({ data }: { data: ReserveResult }) {
  const option = useMemo(() => {
    if (!data.requirementMwSeries.length) return null;
    const rows = data.requirementMwSeries.map((p, i) => ({
      label: p.label,
      timestamp: p.label,
      requirement: p.value,
      provided: data.providedMwSeries[i]?.value ?? 0,
    }));
    return buildTimeSeriesOption({
      xLabels: rows.map((r) => r.label),
      rows,
      series: [
        { key: 'requirement', label: 'Requirement (MW)', color: 'var(--danger, #dc2626)' },
        { key: 'provided', label: 'Provided (MW)', color: 'var(--brand, #0f766e)' },
      ],
      mode: 'line',
      stacked: false,
      yAxisTitle: 'MW',
      showAxisLabels: true,
      xLabelAngle: 0,
      theme: readChartTheme(),
    });
  }, [data.requirementMwSeries, data.providedMwSeries]);
  const hostRef = useEChart<HTMLDivElement>(option);

  if (!data.requirementMwSeries.length) {
    return <p className="econ-note">No requirement series for this run.</p>;
  }
  return <div ref={hostRef} className="echart-host" role="img" style={{ minHeight: 220 }} />;
}

export function ReserveCard({ data, currencySymbol = '$' }: Props) {
  if (!data.enabled) return null;

  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        {data.summary.map((s) => (
          <div className="econ-kpi" key={s.label}>
            <div className="econ-kpi-label">{s.label}</div>
            <div className="econ-kpi-value">{s.value}</div>
            {s.detail && <div className="econ-kpi-unit">{s.detail}</div>}
          </div>
        ))}
      </div>

      <div className="econ-body">
        <div className="econ-table-col" style={{ flex: '1 1 320px' }}>
          <p className="econ-section-label">Reserve price</p>
          <PriceChart data={data} currencySymbol={currencySymbol} />
        </div>
        <div className="econ-table-col" style={{ flex: '1 1 320px' }}>
          <p className="econ-section-label">Requirement vs provided</p>
          <RequirementChart data={data} />
        </div>
      </div>

      {data.byCarrier.length > 0 && (
        <div className="econ-body">
          <div className="econ-table-col">
            <p className="econ-section-label">Mean reserve held by carrier</p>
            <DonutChart data={data.byCarrier.map((c) => ({ label: c.label, value: c.value, color: c.color ?? 'var(--muted, #6b7280)' }))} unit="MW" />
          </div>
        </div>
      )}

      {data.byGenerator.length > 0 && (
        <div className="econ-table-wrap">
          <table className="econ-table">
            <thead>
              <tr>
                <th>Generator</th>
                <th>Carrier</th>
                <th className="num">Mean reserve (MW)</th>
                <th className="num">Reserve revenue ({currencySymbol})</th>
              </tr>
            </thead>
            <tbody>
              {data.byGenerator.map((g) => (
                <tr key={g.name}>
                  <td>{g.name}</td>
                  <td>{g.carrier}</td>
                  <td className="num">{g.meanReserveMw.toLocaleString()}</td>
                  <td className="num">{Math.round(g.meanReservePriceRevenue).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.scarcityHours > 0 && (
        <p className="econ-note">
          Reserve requirement was binding (scarcity) in {data.scarcityHours} snapshot(s).
        </p>
      )}
      {data.note && <p className="econ-note">{data.note}</p>}
    </div>
  );
}
