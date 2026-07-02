/**
 * StrategicBiddingCard (B4) — what market power is worth, and what it costs.
 *
 * Headline: the owner's best-response strategy level, the profit uplift vs
 * bidding true cost, the price impact, and the consumer-cost delta. Below: the
 * full strategy curve (profit per level, with an inline bar), and the
 * best-response rounds when a rival owner was in the game.
 */
import React from 'react';
import { StrategicBiddingResult } from 'lib/types';

interface Props {
  data: StrategicBiddingResult;
}

const num = (v: number) => Math.round(v).toLocaleString();

export function StrategicBiddingCard({ data }: Props) {
  const c = data.currency;
  const isMarkup = data.strategy === 'markup';
  const lvl = (v: number) => (isMarkup ? `+${c}${v.toFixed(1)}/MWh` : `${(v * 100).toFixed(1)}%`);
  const maxProfit = Math.max(1, ...data.curve.map((p) => Math.abs(p.ownerProfit)));

  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Best strategy</div>
          <div className="econ-kpi-value">{lvl(data.best.level)}</div>
          <div className="econ-kpi-unit">{isMarkup ? 'bid adder' : 'capacity withheld'} · {data.owner}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Profit uplift</div>
          <div className={`econ-kpi-value${data.best.profitUplift >= 0 ? ' econ-recovered' : ' econ-negative'}`}>
            {c}{num(data.best.profitUplift)}
          </div>
          <div className="econ-kpi-unit">vs bidding true cost ({c}{num(data.baseline.profit)})</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Price impact</div>
          <div className="econ-kpi-value">{data.best.priceUplift >= 0 ? '+' : ''}{c}{data.best.priceUplift.toFixed(2)}</div>
          <div className="econ-kpi-unit">avg /MWh ({c}{data.baseline.avgPrice.toFixed(2)} → {c}{data.best.avgPrice.toFixed(2)})</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Consumer cost</div>
          <div className={`econ-kpi-value${data.best.consumerCostDelta > 0 ? ' econ-negative' : ''}`}>
            {data.best.consumerCostDelta >= 0 ? '+' : ''}{c}{num(data.best.consumerCostDelta)}
          </div>
          <div className="econ-kpi-unit">extra paid by load at the best response</div>
        </div>
      </div>

      <div className="econ-table-wrap">
        <table className="econ-table">
          <thead>
            <tr>
              <th>{isMarkup ? 'Bid adder' : 'Withheld'}</th>
              <th>Owner profit</th>
              <th></th>
              <th>Avg price</th>
              <th>Consumer cost</th>
              <th>Unserved</th>
            </tr>
          </thead>
          <tbody>
            {data.curve.map((p) => {
              const isBest = p.level === data.best.level;
              return (
                <tr key={p.level} style={isBest ? { fontWeight: 600 } : undefined}>
                  <td>{lvl(p.level)}{isBest ? ' ◀' : ''}</td>
                  <td>{c}{num(p.ownerProfit)}</td>
                  <td style={{ minWidth: 120 }}>
                    <div className="sb-bar">
                      <span style={{ width: `${Math.max(1, (p.ownerProfit / maxProfit) * 100)}%` }} />
                    </div>
                  </td>
                  <td>{c}{p.avgPrice.toFixed(1)}</td>
                  <td>{c}{num(p.consumerCost)}</td>
                  <td>{p.unservedMWh > 0 ? `${num(p.unservedMWh)} MWh` : '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {data.equilibrium && (
        <div className="econ-table-wrap">
          <table className="econ-table">
            <thead>
              <tr>
                <th>Round</th>
                <th>{data.owner}</th>
                <th>{data.equilibrium.rivalOwner}</th>
              </tr>
            </thead>
            <tbody>
              {data.equilibrium.rounds.map((r) => (
                <tr key={r.round}>
                  <td>{r.round}</td>
                  <td>{lvl(r.ownerLevel)}</td>
                  <td>{lvl(r.rivalLevel)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="econ-footnote">
            Best-response dynamics {data.equilibrium.converged ? 'converged' : 'did not converge'} —
            final: {data.owner} {lvl(data.equilibrium.ownerLevel)}, {data.equilibrium.rivalOwner} {lvl(data.equilibrium.rivalLevel)}.
          </p>
        </div>
      )}

      <p className="econ-footnote">
        Best response over the simulated merit-order market (uniform settlement).
        Profits at true marginal cost; the curve shows every strategy level swept.
      </p>
    </div>
  );
}
