/**
 * FreqCurveChart — return-period (exceedance) curve for a physical-risk peril.
 *
 * Ported from the standalone climaterisk app's dependency-free SVG chart
 * (`components/FreqCurveChart.tsx`). Kept as raw SVG rather than an ECharts
 * option builder — it's a one-off log-x/linear-y curve shape not covered by
 * `lib/charts/options`, and the source is small enough that a dependency-free
 * port is simpler than adding a new option builder for one chart. Colors use
 * Ragnarok's design tokens (`--border` / `--muted` / `--brand`), not
 * climaterisk's own token names.
 */
import React from 'react';
import { FreqCurve } from 'lib/physicalRisk/types';

interface Props {
  curve: FreqCurve;
  currencySymbol: string;
}

export function FreqCurveChart({ curve, currencySymbol }: Props) {
  const W = 460;
  const H = 240;
  const m = { l: 72, r: 16, t: 16, b: 36 };
  const iw = W - m.l - m.r;
  const ih = H - m.t - m.b;

  const rps = curve.returnPeriods;
  const ys = curve.losses;
  if (rps.length === 0) return null;

  const xMin = Math.log10(Math.min(...rps));
  const xMax = Math.log10(Math.max(...rps));
  const yMax = Math.max(...ys, 1);

  const px = (rp: number) =>
    m.l + (xMax === xMin ? iw / 2 : ((Math.log10(rp) - xMin) / (xMax - xMin)) * iw);
  const py = (v: number) => m.t + ih - (v / yMax) * ih;

  const points = rps.map((rp, i) => `${px(rp)},${py(ys[i])}`).join(' ');
  const money = (v: number) => `${currencySymbol}${Math.round(v).toLocaleString()}`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Return-period loss curve">
      <line x1={m.l} y1={m.t} x2={m.l} y2={m.t + ih} stroke="var(--border)" />
      <line x1={m.l} y1={m.t + ih} x2={m.l + iw} y2={m.t + ih} stroke="var(--border)" />
      {[0, 0.5, 1].map((f) => (
        <g key={f}>
          <line
            x1={m.l}
            y1={py(yMax * f)}
            x2={m.l + iw}
            y2={py(yMax * f)}
            stroke="var(--border)"
            strokeDasharray="2 4"
            opacity={0.5}
          />
          <text x={m.l - 8} y={py(yMax * f) + 4} textAnchor="end" fontSize="10" fill="var(--muted)">
            {money(yMax * f)}
          </text>
        </g>
      ))}
      {rps.map((rp) => (
        <text key={rp} x={px(rp)} y={m.t + ih + 16} textAnchor="middle" fontSize="10" fill="var(--muted)">
          {rp}
        </text>
      ))}
      <text x={m.l + iw / 2} y={H - 2} textAnchor="middle" fontSize="10" fill="var(--muted)">
        return period (years)
      </text>
      <polyline points={points} fill="none" stroke="var(--brand)" strokeWidth={2} />
      {rps.map((rp, i) => (
        <circle key={rp} cx={px(rp)} cy={py(ys[i])} r={3} fill="var(--brand)" />
      ))}
    </svg>
  );
}
