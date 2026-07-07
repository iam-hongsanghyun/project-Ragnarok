/**
 * TransitionCostChart — annual carbon-cost trajectory (year -> cost) line
 * chart for the Finance sub-tab's transition-risk panel.
 *
 * Dependency-free SVG, matching `FreqCurveChart`'s visual language. Ported in
 * spirit from the standalone climaterisk app's `components/TransitionChart.tsx`
 * (linear x/y polyline over the NGFS carbon-cost-by-year series).
 */
import React from 'react';

interface Props {
  years: number[];
  values: number[];
  formatValue: (v: number) => string;
}

export function TransitionCostChart({ years, values, formatValue }: Props) {
  const W = 460;
  const H = 240;
  const m = { l: 72, r: 16, t: 16, b: 36 };
  const iw = W - m.l - m.r;
  const ih = H - m.t - m.b;
  if (years.length === 0) return null;

  const xMin = years[0];
  const xMax = years[years.length - 1];
  const yMax = Math.max(...values, 1);
  const px = (y: number) => m.l + (xMax === xMin ? iw / 2 : ((y - xMin) / (xMax - xMin)) * iw);
  const py = (v: number) => m.t + ih - (v / yMax) * ih;
  const points = years.map((y, i) => `${px(y)},${py(values[i])}`).join(' ');
  const ticks = years.filter((y) => y % 5 === 0);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Carbon-cost trajectory">
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
            {formatValue(yMax * f)}
          </text>
        </g>
      ))}
      {ticks.map((y) => (
        <text key={y} x={px(y)} y={m.t + ih + 16} textAnchor="middle" fontSize="10" fill="var(--muted)">
          {y}
        </text>
      ))}
      <text x={m.l + iw / 2} y={H - 2} textAnchor="middle" fontSize="10" fill="var(--muted)">
        year - annual carbon cost
      </text>
      <polyline points={points} fill="none" stroke="var(--brand)" strokeWidth={2} />
      {years.map((y, i) => (
        <circle key={y} cx={px(y)} cy={py(values[i])} r={3} fill="var(--brand)" />
      ))}
    </svg>
  );
}
