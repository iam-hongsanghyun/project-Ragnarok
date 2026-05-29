import React, { useState } from 'react';
import { MixItem } from '../../../shared/types';

export function DonutChart({ data }: { data: MixItem[] }) {
  const cx = 190, cy = 190, outerR = 168, innerR = 100;
  const total = data.reduce((sum, item) => sum + item.value, 0) || 1;
  const [tooltip, setTooltip] = useState<{ label: string; value: number; x: number; y: number } | null>(null);

  const arc = (startAngle: number, endAngle: number): string => {
    const gap = 0.012;
    const s = startAngle + gap / 2;
    const e = endAngle - gap / 2;
    const cos = Math.cos, sin = Math.sin;
    const ox1 = cx + outerR * cos(s), oy1 = cy + outerR * sin(s);
    const ox2 = cx + outerR * cos(e), oy2 = cy + outerR * sin(e);
    const ix1 = cx + innerR * cos(e), iy1 = cy + innerR * sin(e);
    const ix2 = cx + innerR * cos(s), iy2 = cy + innerR * sin(s);
    const large = endAngle - startAngle > Math.PI ? 1 : 0;
    return `M${ox1} ${oy1} A${outerR} ${outerR} 0 ${large} 1 ${ox2} ${oy2} L${ix1} ${iy1} A${innerR} ${innerR} 0 ${large} 0 ${ix2} ${iy2} Z`;
  };

  const handleMove = (e: React.MouseEvent<SVGPathElement>, label: string, value: number) => {
    const svgEl = e.currentTarget.ownerSVGElement as SVGSVGElement;
    const pt = svgEl.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const p = pt.matrixTransform(svgEl.getScreenCTM()!.inverse());
    setTooltip({ label, value, x: p.x, y: p.y });
  };

  let angle = -Math.PI / 2;

  return (
    <div className="donut-layout">
      <svg className="donut-chart" viewBox="0 0 380 380" role="img" aria-label="Mix chart"
        onMouseLeave={() => setTooltip(null)}>
        {data.map((item) => {
          const sweep = (item.value / total) * 2 * Math.PI;
          const endAngle = angle + sweep;
          const d = arc(angle, endAngle);
          angle = endAngle;
          return (
            <path
              key={item.label}
              d={d}
              fill={item.color}
              style={{ cursor: 'pointer' }}
              onMouseEnter={(e) => handleMove(e, item.label, item.value)}
              onMouseMove={(e) => handleMove(e, item.label, item.value)}
              onMouseLeave={() => setTooltip(null)}
            />
          );
        })}
        <circle cx={cx} cy={cy} r={innerR} fill="#ffffff" />
        <text x={cx} y={cy - 8} textAnchor="middle" className="donut-total-label">Total</text>
        <text x={cx} y={cy + 20} textAnchor="middle" className="donut-total-value">
          {Math.round(total).toLocaleString()}
        </text>
        {tooltip && (() => {
          const tx = tooltip.x + 14 + 160 > 370 ? tooltip.x - 174 : tooltip.x + 14;
          const ty = Math.max(8, Math.min(tooltip.y - 30, 380 - 56));
          return (
            <g transform={`translate(${tx},${ty})`} style={{ pointerEvents: 'none' }}>
              <rect rx="7" ry="7" width="160" height="48" fill="rgba(15,23,42,0.88)" />
              <text y="18" x="10" className="chart-tip-label">{tooltip.label}</text>
              <text y="36" x="10" className="chart-tip-value">
                {Math.round(tooltip.value).toLocaleString()}
              </text>
            </g>
          );
        })()}
      </svg>
      <div className="legend-list">
        <div className="map-legend-title" style={{ marginBottom: 4 }}>Breakdown</div>
        {data.map((item) => (
          <div key={item.label} className="legend-item">
            <span className="legend-swatch" style={{ backgroundColor: item.color }} />
            <span>{item.label}</span>
            <strong>{Math.round(item.value).toLocaleString()}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}
