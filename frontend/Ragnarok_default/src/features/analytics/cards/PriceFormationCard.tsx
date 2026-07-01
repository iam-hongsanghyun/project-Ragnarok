/**
 * PriceFormationCard (Tier 0) — why is the price what it is?
 *
 * Two scatters coloured by the price-setting carrier: price vs residual demand
 * (demand − variable renewables) and price vs renewable share. Plus a summary
 * of how often — and at what average price — each carrier set the price. Makes
 * the merit-order story visible: low renewables ⇒ high residual demand ⇒ a
 * pricier unit on the margin ⇒ higher price.
 */
import React from 'react';
import { PriceFormationResult, PriceFormationRow } from 'lib/types';
import { carrierColor } from 'lib/utils/helpers';

const MAX_POINTS = 2500; // cap SVG circles for long runs (sample evenly)

function sample<T>(arr: T[], max: number): T[] {
  if (arr.length <= max) return arr;
  const step = arr.length / max;
  const out: T[] = [];
  for (let i = 0; i < arr.length; i += step) out.push(arr[Math.floor(i)]);
  return out;
}

interface ScatterProps {
  rows: PriceFormationRow[];
  xOf: (r: PriceFormationRow) => number;
  xLabel: string;
  yLabel: string;
  xIsPct?: boolean;
  currency: string;
}

function Scatter({ rows, xOf, xLabel, yLabel, xIsPct, currency }: ScatterProps) {
  const W = 360, H = 240, PAD_L = 48, PAD_B = 34, PAD_T = 10, PAD_R = 10;
  const pts = sample(rows, MAX_POINTS);
  const xs = pts.map(xOf);
  const ys = pts.map((r) => r.price);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const yMin = Math.min(0, ...ys), yMax = Math.max(...ys);
  const xSpan = xMax - xMin || 1;
  const ySpan = yMax - yMin || 1;
  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;
  const px = (v: number) => PAD_L + ((v - xMin) / xSpan) * plotW;
  const py = (v: number) => PAD_T + plotH - ((v - yMin) / ySpan) * plotH;
  const fmtX = (v: number) => (xIsPct ? `${Math.round(v * 100)}%` : Math.round(v).toLocaleString());

  return (
    <div className="econ-table-col" style={{ flex: 1, minWidth: 280 }}>
      <p className="econ-section-label">{yLabel} vs {xLabel}</p>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxWidth: W }} role="img">
        {/* axes */}
        <line x1={PAD_L} y1={PAD_T} x2={PAD_L} y2={PAD_T + plotH} stroke="var(--border,#e5e7eb)" />
        <line x1={PAD_L} y1={PAD_T + plotH} x2={PAD_L + plotW} y2={PAD_T + plotH} stroke="var(--border,#e5e7eb)" />
        {/* y ticks (min/max) */}
        <text x={PAD_L - 6} y={py(yMax) + 4} textAnchor="end" fontSize={10} fill="var(--muted,#6b7280)">{Math.round(yMax).toLocaleString()}</text>
        <text x={PAD_L - 6} y={py(yMin) + 4} textAnchor="end" fontSize={10} fill="var(--muted,#6b7280)">{Math.round(yMin).toLocaleString()}</text>
        {/* x ticks (min/max) */}
        <text x={px(xMin)} y={PAD_T + plotH + 14} textAnchor="start" fontSize={10} fill="var(--muted,#6b7280)">{fmtX(xMin)}</text>
        <text x={px(xMax)} y={PAD_T + plotH + 14} textAnchor="end" fontSize={10} fill="var(--muted,#6b7280)">{fmtX(xMax)}</text>
        {/* axis titles */}
        <text x={PAD_L + plotW / 2} y={H - 2} textAnchor="middle" fontSize={10} fill="var(--text,#111)">{xLabel}</text>
        <text x={12} y={PAD_T + plotH / 2} textAnchor="middle" fontSize={10} fill="var(--text,#111)" transform={`rotate(-90 12 ${PAD_T + plotH / 2})`}>{yLabel} ({currency}/MWh)</text>
        {/* points */}
        {pts.map((r, i) => (
          <circle key={i} cx={px(xOf(r))} cy={py(r.price)} r={1.6} fill={carrierColor(r.marginalCarrier || 'other')} fillOpacity={0.55} />
        ))}
      </svg>
    </div>
  );
}

interface Props {
  data: PriceFormationResult;
}

export function PriceFormationCard({ data }: Props) {
  const { currency, series, marginalSummary } = data;
  if (!series.length) {
    return <p className="dashboard-cell-missing">No price data for this run.</p>;
  }
  return (
    <div className="econ-card">
      <div className="econ-body" style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <Scatter rows={series} xOf={(r) => r.residualDemand} xLabel="Residual demand (MW)" yLabel="Price" currency={currency} />
        <Scatter rows={series} xOf={(r) => r.renewableShare} xLabel="Renewable share" yLabel="Price" xIsPct currency={currency} />
      </div>

      <div className="econ-table-wrap">
        <table className="econ-table">
          <thead>
            <tr>
              <th>Price-setting carrier</th>
              <th className="num">Hours</th>
              <th className="num">% of time</th>
              <th className="num">Avg price ({currency}/MWh)</th>
            </tr>
          </thead>
          <tbody>
            {marginalSummary.map((c) => (
              <tr key={c.carrier}>
                <td>
                  <span className="carrier-dot" style={{ backgroundColor: carrierColor(c.carrier) }} />
                  {c.carrier || '—'}
                </td>
                <td className="num">{Math.round(c.hours).toLocaleString()}</td>
                <td className="num">{(c.shareOfHours * 100).toFixed(1)}%</td>
                <td className="num">{c.avgPrice.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="econ-note">
        Each point is one snapshot, coloured by the carrier that set the price (the most expensive
        dispatched unit). Residual demand = demand − variable renewables; as it rises the system climbs
        the merit order into pricier plant. The table shows how often — and at what average price — each
        carrier was on the margin.
      </p>
    </div>
  );
}
