/**
 * RiskBarChart — horizontal labeled bar chart for a "name -> value" breakdown
 * (supply-chain indirect impact by sector, forecast near-term impact series).
 *
 * Dependency-free SVG, matching `FreqCurveChart`'s visual language (same
 * design tokens, same axis/gridline treatment) rather than pulling in a
 * charting library or a second option-builder — this is the same
 * one-off-shape case FreqCurveChart already carved out for the physical-risk
 * sub-tabs. Ported in spirit from the standalone climaterisk app's
 * `components/BarsChart.tsx` (there Recharts-based; here plain SVG so no new
 * npm dependency is introduced).
 */
import React from 'react';

export interface RiskBarDatum {
  name: string;
  value: number;
}

interface Props {
  data: RiskBarDatum[];
  formatValue: (v: number) => string;
}

export function RiskBarChart({ data, formatValue }: Props) {
  if (data.length === 0) return null;

  const rowHeight = 28;
  const W = 460;
  const m = { l: 140, r: 56, t: 8, b: 8 };
  const iw = W - m.l - m.r;
  const H = data.length * rowHeight + m.t + m.b;
  const vMax = Math.max(...data.map((d) => d.value), 1);
  const barW = (v: number) => (v / vMax) * iw;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Bar chart">
      {data.map((d, i) => {
        const y = m.t + i * rowHeight;
        const w = Math.max(0, barW(d.value));
        return (
          <g key={d.name}>
            <text x={m.l - 8} y={y + rowHeight / 2 + 4} textAnchor="end" fontSize="11" fill="var(--muted)">
              {d.name}
            </text>
            <rect x={m.l} y={y + 4} width={iw} height={rowHeight - 12} fill="var(--border)" opacity={0.4} />
            <rect x={m.l} y={y + 4} width={w} height={rowHeight - 12} fill="var(--brand)" />
            <text x={m.l + w + 6} y={y + rowHeight / 2 + 4} fontSize="11" fill="var(--muted)">
              {formatValue(d.value)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
