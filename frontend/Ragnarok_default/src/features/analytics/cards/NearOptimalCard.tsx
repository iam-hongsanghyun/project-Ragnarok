/**
 * NearOptimalCard — the MGA near-optimal capacity corridor.
 *
 * For each explored carrier we draw the [min … max] capacity buildable within
 * the cost slack as a horizontal corridor, with the cost-optimum marked. A wide
 * corridor means the system is *indifferent* to that technology near the
 * optimum (lots of structural freedom); a narrow one means it is pinned.
 */
import React from 'react';
import { NearOptimalResult } from 'lib/types';
import { carrierColor } from 'lib/utils/helpers';

function fmtMw(v: number): string {
  if (Math.abs(v) >= 1000) return `${Math.round(v).toLocaleString()} MW`;
  return `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })} MW`;
}

interface Props {
  data: NearOptimalResult;
}

interface Corridor {
  carrier: string;
  min: number;
  max: number;
  opt: number;
}

export function NearOptimalCard({ data }: Props) {
  const slackPct = Math.round(data.slack * 1000) / 10;

  const corridors: Corridor[] = data.carriers.map((c) => {
    const opt = data.optimum.capacityByCarrier[c] ?? 0;
    const vals = data.alternatives
      .filter((a) => a.carrier === c)
      .map((a) => a.capacityByCarrier[c] ?? opt);
    const all = [opt, ...vals];
    return { carrier: c, min: Math.min(...all), max: Math.max(...all), opt };
  });

  if (!corridors.length) {
    return <p className="dashboard-cell-missing">No near-optimal corridor for this run.</p>;
  }

  const globalMax = Math.max(1, ...corridors.map((c) => c.max));
  // SVG geometry — a horizontal track per carrier.
  const ROW_H = 38;
  const PAD_L = 110;
  const PAD_R = 70;
  const PAD_T = 8;
  const W = 640;
  const trackW = W - PAD_L - PAD_R;
  const H = PAD_T * 2 + corridors.length * ROW_H;
  const x = (v: number) => PAD_L + (v / globalMax) * trackW;

  return (
    <div className="econ-card">
      <div className="econ-body">
        <div className="econ-table-col">
          <p className="econ-section-label">
            Near-optimal capacity corridor — within {slackPct}% of least cost
          </p>
          <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxWidth: W, overflow: 'visible' }} role="img">
            {corridors.map((c, i) => {
              const cy = PAD_T + i * ROW_H + ROW_H / 2;
              const color = carrierColor(c.carrier);
              const x0 = x(c.min);
              const x1 = x(c.max);
              const xo = x(c.opt);
              const pinned = x1 - x0 < 1.5;
              return (
                <g key={c.carrier}>
                  {/* baseline track */}
                  <line x1={PAD_L} y1={cy} x2={PAD_L + trackW} y2={cy} stroke="var(--border, #e5e7eb)" strokeWidth={1} />
                  {/* corridor [min..max] */}
                  <rect
                    x={x0}
                    y={cy - 6}
                    width={Math.max(pinned ? 3 : x1 - x0, 3)}
                    height={12}
                    rx={3}
                    fill={color}
                    fillOpacity={0.32}
                    stroke={color}
                    strokeWidth={1}
                  />
                  {/* optimum marker */}
                  <circle cx={xo} cy={cy} r={4} fill={color} stroke="var(--surface, #fff)" strokeWidth={1.5} />
                  {/* carrier label */}
                  <text x={PAD_L - 10} y={cy + 4} textAnchor="end" fontSize={12} fill="var(--text, #111)">
                    {c.carrier}
                  </text>
                  {/* max value at the end */}
                  <text x={x1 + 8} y={cy + 4} fontSize={11} fill="var(--muted, #6b7280)">
                    {Math.round(c.max).toLocaleString()}
                  </text>
                </g>
              );
            })}
          </svg>
          <p className="econ-note">
            Bar = the min–max capacity range across near-optimal solutions; ● = the cost optimum.
            Axis in MW (peak: {Math.round(globalMax).toLocaleString()} MW).
          </p>
        </div>
      </div>

      <div className="econ-table-wrap">
        <table className="econ-table">
          <thead>
            <tr>
              <th>Carrier</th>
              <th className="num">Optimum</th>
              <th className="num">Min (near-opt)</th>
              <th className="num">Max (near-opt)</th>
              <th className="num">Spread</th>
            </tr>
          </thead>
          <tbody>
            {corridors.map((c) => (
              <tr key={c.carrier}>
                <td>
                  <span className="carrier-dot" style={{ backgroundColor: carrierColor(c.carrier) }} />
                  {c.carrier}
                </td>
                <td className="num">{fmtMw(c.opt)}</td>
                <td className="num">{fmtMw(c.min)}</td>
                <td className="num">{fmtMw(c.max)}</td>
                <td className="num">{fmtMw(c.max - c.min)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="econ-note">
        MGA (modelling-to-generate-alternatives): each carrier is pushed to its least and most
        deployment while total system cost stays within {slackPct}% of the optimum
        ({data.currency} {Math.round(data.optimum.cost).toLocaleString()}). A wide spread = the
        plan is indifferent to that technology; a narrow one = it is pinned by the optimum.
        {data.droppedCarriers.length > 0 && (
          <> Not explored (per-run cap): {data.droppedCarriers.join(', ')}.</>
        )}
      </p>
    </div>
  );
}
