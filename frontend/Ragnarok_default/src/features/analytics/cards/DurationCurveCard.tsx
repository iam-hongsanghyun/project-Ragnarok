import React, { useState } from 'react';

interface Props {
  title: string;
  data: number[];
  unit: string;
  color: string;
}

export function DurationCurveCard({ title, data, unit, color }: Props) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  if (!data.length) {
    return (
      <div className="duration-curve-card">
        <p className="empty-text">No data available.</p>
      </div>
    );
  }

  const width = 480;
  const height = 240;
  const padL = 44;
  const padR = 12;
  const padT = 12;
  const padB = 28;
  const innerW = width - padL - padR;
  const innerH = height - padT - padB;

  const maxVal = Math.max(...data, 1);
  const minVal = Math.min(...data, 0);
  const range = Math.max(maxVal - minVal, 1);

  const xFor = (i: number) => padL + (i / Math.max(data.length - 1, 1)) * innerW;
  const yFor = (v: number) => padT + innerH - ((v - minVal) / range) * innerH;

  const linePath = data
    .map((v, i) => `${i === 0 ? 'M' : 'L'} ${xFor(i)} ${yFor(v)}`)
    .join(' ');

  const areaPath =
    linePath +
    ` L ${xFor(data.length - 1)} ${padT + innerH}` +
    ` L ${xFor(0)} ${padT + innerH} Z`;

  const ticks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div className="duration-curve-card">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="chart-svg"
        onMouseLeave={() => setHoverIndex(null)}
        onMouseMove={(e) => {
          const svgEl = e.currentTarget as SVGSVGElement;
          const pt = svgEl.createSVGPoint();
          pt.x = e.clientX;
          pt.y = e.clientY;
          const svgPt = pt.matrixTransform(svgEl.getScreenCTM()!.inverse());
          const rawI = Math.round(((svgPt.x - padL) / innerW) * (data.length - 1));
          setHoverIndex(Math.max(0, Math.min(data.length - 1, rawI)));
        }}
      >
        {ticks.map((t) => {
          const y = padT + innerH - t * innerH;
          const val = Math.round(minVal + range * t);
          return (
            <g key={t}>
              <line x1={padL} x2={width - padR} y1={y} y2={y} className="chart-grid" />
              <text x={padL - 4} y={y + 4} textAnchor="end" className="chart-tick">
                {val}
              </text>
            </g>
          );
        })}

        <path d={areaPath} fill={color} fillOpacity={0.15} />
        <path d={linePath} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" />

        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const i = Math.round(t * (data.length - 1));
          return (
            <text key={t} x={xFor(i)} y={height - 4} textAnchor="middle" className="chart-tick">
              {Math.round(t * 100)}%
            </text>
          );
        })}

        {hoverIndex !== null && (() => {
          const hx = xFor(hoverIndex);
          const val = data[hoverIndex];
          const tipW = 120;
          const tx = hx + 12 + tipW > width - padR ? hx - tipW - 12 : hx + 12;
          return (
            <g style={{ pointerEvents: 'none' }}>
              <line x1={hx} x2={hx} y1={padT} y2={padT + innerH} stroke="rgba(15,23,42,0.22)" strokeWidth={1.5} strokeDasharray="4 3" />
              <g transform={`translate(${tx},${padT + 4})`}>
                <rect rx="6" ry="6" width={tipW} height={40} fill="rgba(15,23,42,0.88)" />
                <text x="8" y="14" className="chart-tip-label">
                  Rank {hoverIndex + 1}
                </text>
                <text x="8" y="30" className="chart-tip-value">
                  {Math.round(val).toLocaleString()} {unit}
                </text>
              </g>
            </g>
          );
        })()}

        <text x={padL} y={padT - 2} className="chart-axis-title">
          {title}
        </text>

        <rect x={padL} y={padT} width={innerW} height={innerH} fill="transparent" />
      </svg>
    </div>
  );
}
