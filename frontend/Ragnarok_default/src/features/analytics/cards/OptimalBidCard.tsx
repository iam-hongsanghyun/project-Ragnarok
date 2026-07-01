/**
 * OptimalBidCard (Tier 3a) — the profit-maximising markup.
 *
 * Ragnarok's best-response bid: sweeps the owner's markup, re-clears at each
 * level, and picks the profit-maximising point. Shows the profit-vs-markup
 * curve with the optimum marked, and the gain over the price-taker baseline.
 * Single-firm best response (fixed fringe) — not a multi-firm equilibrium.
 */
import React from 'react';
import { OptimalBidResult } from 'lib/types';

function money(v: number, currency: string): string {
  const abs = Math.abs(v), sign = v < 0 ? '-' : '';
  if (abs >= 1e9) return `${sign}${currency}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${currency}${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}${currency}${(abs / 1e3).toFixed(1)}k`;
  return `${sign}${currency}${Math.round(abs).toLocaleString()}`;
}

interface Props {
  data: OptimalBidResult;
}

export function OptimalBidCard({ data }: Props) {
  const { currency, owner, curve, optimalMarkup, optimalProfit, baselineProfit, deltaProfit } = data;
  const fmtMarkup = (m: number) => (data.markupType === 'percent' ? `${Math.round(m * 1000) / 10}%` : `${currency}${m}/MWh`);
  if (!curve.length) {
    return <p className="dashboard-cell-missing">No optimal-bid sweep for this run.</p>;
  }

  // Profit-vs-markup curve.
  const W = 460, H = 240, PAD_L = 56, PAD_B = 34, PAD_T = 12, PAD_R = 12;
  const xs = curve.map((c) => c.markup);
  const ys = curve.map((c) => c.profit);
  const xMax = Math.max(...xs) || 1;
  const yMin = Math.min(0, ...ys), yMax = Math.max(...ys) || 1;
  const plotW = W - PAD_L - PAD_R, plotH = H - PAD_T - PAD_B;
  const px = (v: number) => PAD_L + (v / xMax) * plotW;
  const py = (v: number) => PAD_T + plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH;
  const path = curve.map((c, i) => `${i === 0 ? 'M' : 'L'}${px(c.markup).toFixed(1)},${py(c.profit).toFixed(1)}`).join(' ');

  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Optimal markup</div>
          <div className="econ-kpi-value">{fmtMarkup(optimalMarkup)}</div>
          <div className="econ-kpi-unit">profit-maximising bid for {owner}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Profit at optimum</div>
          <div className={`econ-kpi-value ${optimalProfit >= 0 ? 'econ-recovered' : 'econ-shortfall'}`}>{money(optimalProfit, currency)}</div>
          <div className="econ-kpi-unit">vs {money(baselineProfit, currency)} price-taker</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Gain from bidding</div>
          <div className={`econ-kpi-value ${deltaProfit >= 0 ? 'econ-recovered' : 'econ-shortfall'}`}>+{money(deltaProfit, currency)}</div>
          <div className="econ-kpi-unit">market-power value</div>
        </div>
      </div>

      <div className="econ-body">
        <div className="econ-table-col">
          <p className="econ-section-label">Profit vs markup — swept re-clears, ● = optimum</p>
          <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxWidth: W, overflow: 'visible' }} role="img">
            <line x1={PAD_L} y1={PAD_T} x2={PAD_L} y2={PAD_T + plotH} stroke="var(--border,#e5e7eb)" />
            <line x1={PAD_L} y1={py(0)} x2={PAD_L + plotW} y2={py(0)} stroke="var(--border,#e5e7eb)" />
            <text x={PAD_L - 6} y={py(yMax) + 4} textAnchor="end" fontSize={10} fill="var(--muted,#6b7280)">{money(yMax, currency)}</text>
            <text x={PAD_L - 6} y={py(yMin) + 4} textAnchor="end" fontSize={10} fill="var(--muted,#6b7280)">{money(yMin, currency)}</text>
            <text x={PAD_L} y={PAD_T + plotH + 14} textAnchor="start" fontSize={10} fill="var(--muted,#6b7280)">{fmtMarkup(0)}</text>
            <text x={PAD_L + plotW} y={PAD_T + plotH + 14} textAnchor="end" fontSize={10} fill="var(--muted,#6b7280)">{fmtMarkup(xMax)}</text>
            <text x={PAD_L + plotW / 2} y={H - 2} textAnchor="middle" fontSize={10} fill="var(--text,#111)">Markup</text>
            <path d={path} fill="none" stroke="var(--brand,#0f766e)" strokeWidth={1.6} />
            {curve.map((c, i) => (
              <circle key={i} cx={px(c.markup)} cy={py(c.profit)} r={c.markup === optimalMarkup ? 4 : 2}
                fill={c.markup === optimalMarkup ? 'var(--brand,#0f766e)' : 'var(--muted,#6b7280)'} />
            ))}
          </svg>
          <p className="econ-note">
            Best-response bid for “{owner}”: at each markup the market is re-cleared and profit is
            evaluated at true cost. The optimum ({fmtMarkup(optimalMarkup)}) earns {money(optimalProfit, currency)}
            — {money(deltaProfit, currency)} above bidding at cost. Single strategic firm against a fixed
            competitive fringe; a full multi-firm equilibrium is not modelled.
          </p>
        </div>
      </div>
    </div>
  );
}
