/**
 * MarketParticipantsCard — who profits from the day-ahead auction.
 *
 * Aggregates the auction clearing by owner: each participant's cleared energy,
 * market revenue (at the clearing price, or their own bid under pay-as-bid),
 * production cost, profit, and share of price-setting hours. Profit is at true
 * marginal cost, so a price-setting unit shows the (small) rent it earns above
 * cost. Inline bar ranks profit.
 */
import React from 'react';
import { MarketSimulationResult } from 'lib/types';

interface Props {
  data: MarketSimulationResult;
}

const money = (v: number, cur: string) => `${v < 0 ? '−' : ''}${cur}${Math.abs(Math.round(v)).toLocaleString()}`;
const num0 = (v: number) => Math.round(v).toLocaleString();

export function MarketParticipantsCard({ data }: Props) {
  const cur = data.currency || '';
  const parts = data.participants ?? [];
  if (parts.length === 0) {
    return <p className="dashboard-cell-missing">No participants — tag generators with an owner to see per-participant profit.</p>;
  }
  const maxProfit = Math.max(1, ...parts.map((p) => Math.abs(p.profit)));

  return (
    <div className="econ-card">
      <div className="econ-table-wrap">
        <table className="econ-table">
          <thead>
            <tr>
              <th>Participant</th>
              <th className="num">Cleared (MWh)</th>
              <th className="num">Revenue</th>
              <th className="num">Cost</th>
              <th className="num">Profit</th>
              <th></th>
              <th className="num">Price-setting h</th>
              <th className="num">Units</th>
            </tr>
          </thead>
          <tbody>
            {parts.map((p) => (
              <tr key={p.participant}>
                <td>{p.participant}</td>
                <td className="num">{num0(p.energyMWh)}</td>
                <td className="num">{money(p.revenue, cur)}</td>
                <td className="num">{money(p.cost, cur)}</td>
                <td className={`num${p.profit >= 0 ? ' econ-recovered' : ' econ-negative'}`}>{money(p.profit, cur)}</td>
                <td style={{ minWidth: 90 }}>
                  <div className="sb-bar">
                    <span style={{ width: `${Math.max(2, (Math.abs(p.profit) / maxProfit) * 100)}%`, background: p.profit < 0 ? 'var(--danger, #dc2626)' : undefined }} />
                  </div>
                </td>
                <td className="num">{p.priceSettingHours}</td>
                <td className="num">{p.unitCount}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="econ-footnote">
        Per-participant profit from the {data.clearingModel === 'twoSided' ? 'two-sided auction' : 'merit-order auction'} ({data.pricing} settlement).
        Revenue is the auction settlement; profit is revenue − true marginal cost, so inframarginal owners keep the rent above the clearing price.
      </p>
    </div>
  );
}
