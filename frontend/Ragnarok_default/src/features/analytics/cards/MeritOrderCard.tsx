/**
 * MeritOrderCard — supply stack (merit order) chart.
 *
 * Classic power-market chart: x-axis = cumulative installed capacity (MW),
 * y-axis = marginal cost ($/MWh). Each generator is a vertical block
 * (width = p_nom, height = marginal_cost) coloured by carrier.
 */
import React, { useState } from 'react';
import { MeritOrderEntry } from '../../../shared/types';

interface Props {
  entries: MeritOrderEntry[];
  systemLoad?: number; // peak system load in MW — draws a vertical demand line
  currencySymbol?: string;
}

export function MeritOrderCard({ entries, systemLoad, currencySymbol = '$' }: Props) {
  const [hovered, setHovered] = useState<MeritOrderEntry | null>(null);

  if (!entries.length) {
    return (
      <div className="merit-empty">
        No dispatchable generators found — add generators with p_nom &gt; 0 to see the merit order.
      </div>
    );
  }

  const totalMW = entries.reduce((s, e) => s + e.p_nom, 0);
  const maxCost = Math.max(...entries.map((e) => e.marginal_cost), 1);

  // SVG dimensions
  const W = 760, H = 300;
  const PAD = { top: 16, right: 16, bottom: 40, left: 56 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  // Scale helpers
  const xScale = (mw: number) => (mw / totalMW) * innerW;
  const yScale = (cost: number) => innerH - (cost / maxCost) * innerH;

  // Y-axis ticks
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((t) => ({
    value: Math.round(maxCost * t),
    y: yScale(maxCost * t),
  }));

  // Demand line x-position
  const demandX = systemLoad != null ? xScale(Math.min(systemLoad, totalMW)) : null;

  return (
    <div className="merit-card">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="merit-svg"
        style={{ width: '100%', display: 'block' }}
        onMouseLeave={() => setHovered(null)}
      >
        <g transform={`translate(${PAD.left},${PAD.top})`}>
          {/* Grid lines + Y-axis labels */}
          {yTicks.map((tick) => (
            <g key={tick.value}>
              <line
                x1={0} y1={tick.y} x2={innerW} y2={tick.y}
                stroke="rgba(15,23,42,0.07)" strokeWidth={1}
              />
              <text x={-6} y={tick.y + 4} textAnchor="end" className="chart-tick">
                {tick.value}
              </text>
            </g>
          ))}

          {/* Generator blocks */}
          {entries.map((entry) => {
            const x = xScale(entry.cumulative_mw);
            const w = Math.max(xScale(entry.p_nom), 1);
            const barH = Math.max((entry.marginal_cost / maxCost) * innerH, 2);
            const y = innerH - barH;
            const isHovered = hovered?.name === entry.name;
            return (
              <rect
                key={entry.name}
                x={x} y={y}
                width={w} height={barH}
                fill={entry.color}
                fillOpacity={isHovered ? 1 : 0.78}
                stroke={isHovered ? '#0f172a' : entry.color}
                strokeWidth={isHovered ? 1.5 : 0.5}
                style={{ cursor: 'pointer' }}
                onMouseEnter={() => setHovered(entry)}
              />
            );
          })}

          {/* Demand line */}
          {demandX != null && (
            <g>
              <line
                x1={demandX} y1={0} x2={demandX} y2={innerH}
                stroke="#dc2626" strokeWidth={2} strokeDasharray="6 3"
              />
              <text x={demandX + 4} y={12} className="chart-peak-label">
                Peak load
              </text>
            </g>
          )}

          {/* Axes */}
          <line x1={0} y1={0} x2={0} y2={innerH} stroke="#cbd5e1" strokeWidth={1} />
          <line x1={0} y1={innerH} x2={innerW} y2={innerH} stroke="#cbd5e1" strokeWidth={1} />

          {/* X-axis label */}
          <text x={innerW / 2} y={innerH + 32} textAnchor="middle" className="chart-axis-title">
            Cumulative capacity (MW)
          </text>

          {/* Y-axis label */}
          <text
            x={-(innerH / 2)} y={-42}
            textAnchor="middle"
            transform="rotate(-90)"
            className="chart-axis-title"
          >
            Marginal cost ({currencySymbol}/MWh)
          </text>

          {/* X-axis capacity ticks */}
          {[0, 0.25, 0.5, 0.75, 1].map((t) => {
            const mw = Math.round(totalMW * t);
            const x = xScale(mw);
            return (
              <g key={t}>
                <line x1={x} y1={innerH} x2={x} y2={innerH + 4} stroke="#cbd5e1" strokeWidth={1} />
                <text x={x} y={innerH + 14} textAnchor="middle" className="chart-tick">
                  {mw.toLocaleString()}
                </text>
              </g>
            );
          })}

          {/* Hover tooltip */}
          {hovered && (() => {
            const tx = Math.min(
              xScale(hovered.cumulative_mw + hovered.p_nom / 2),
              innerW - 160,
            );
            const ty = Math.max(yScale(hovered.marginal_cost) - 70, 4);
            return (
              <g transform={`translate(${tx},${ty})`} style={{ pointerEvents: 'none' }}>
                <rect rx={6} width={160} height={68} fill="rgba(15,23,42,0.9)" />
                <text x={10} y={18} className="chart-tip-name">
                  {hovered.name.length > 18 ? hovered.name.slice(0, 16) + '…' : hovered.name}
                </text>
                <text x={10} y={34} className="chart-tip-sub">
                  {hovered.carrier} · {hovered.bus}
                </text>
                <text x={10} y={50} className="chart-tip-line">
                  Cost: <tspan fontWeight={700}>{currencySymbol}{hovered.marginal_cost.toLocaleString()}/MWh</tspan>
                </text>
                <text x={10} y={64} className="chart-tip-line">
                  Capacity: <tspan fontWeight={700}>{hovered.p_nom.toLocaleString()} MW</tspan>
                </text>
              </g>
            );
          })()}
        </g>
      </svg>

      {/* Carrier legend */}
      <div className="merit-legend">
        {Array.from(new Map(entries.map((e) => [e.carrier, e.color])).entries()).map(
          ([carrier, color]) => (
            <div key={carrier} className="legend-item-inline">
              <span className="legend-swatch" style={{ backgroundColor: color }} />
              <span>{carrier}</span>
            </div>
          ),
        )}
        {systemLoad != null && (
          <div className="legend-item-inline">
            <span className="legend-swatch" style={{ backgroundColor: '#dc2626' }} />
            <span>Peak load ({Math.round(systemLoad).toLocaleString()} MW)</span>
          </div>
        )}
      </div>

      {/* Summary stats */}
      <div className="merit-stats">
        <span>Total installed: <strong>{Math.round(totalMW).toLocaleString()} MW</strong></span>
        <span>Generators: <strong>{entries.length}</strong></span>
        <span>Price range: <strong>
          {currencySymbol}{Math.min(...entries.map((e) => e.marginal_cost)).toLocaleString()} –
          {currencySymbol}{Math.max(...entries.map((e) => e.marginal_cost)).toLocaleString()} /MWh
        </strong></span>
      </div>
    </div>
  );
}
