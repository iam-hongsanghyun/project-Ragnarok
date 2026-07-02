/**
 * MarketSimulationCard (B2) — rule-based market outcome.
 *
 * Headline: average/peak price, cost to load and unserved energy under the
 * chosen settlement, then the per-unit market economics: energy, revenue,
 * profit, capacity factor and — the market-power lens — how many hours each
 * unit set the price.
 */
import React from 'react';
import { MarketSimulationResult } from 'lib/types';

interface Props {
  data: MarketSimulationResult;
}

const num = (v: number) => Math.round(v).toLocaleString();

export function MarketSimulationCard({ data }: Props) {
  const c = data.currency;
  const s = data.summary;
  const setters = data.units.filter((u) => u.priceSettingHours > 0).length;

  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Average price</div>
          <div className="econ-kpi-value">{c}{s.avgPrice.toFixed(2)}</div>
          <div className="econ-kpi-unit">/MWh · {data.pricing === 'payAsBid' ? 'pay-as-bid' : 'uniform'} settlement</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Peak price</div>
          <div className="econ-kpi-value">{c}{s.peakPrice.toFixed(0)}</div>
          <div className="econ-kpi-unit">/MWh · VOLL {c}{num(data.voll)}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Cost to load</div>
          <div className="econ-kpi-value">{c}{num(s.totalCost)}</div>
          <div className="econ-kpi-unit">{num(s.totalLoadMWh)} MWh demanded</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Unserved energy</div>
          <div className={`econ-kpi-value${s.unservedMWh > 0 ? ' econ-negative' : ''}`}>
            {s.unservedMWh > 0 ? `${num(s.unservedMWh)} MWh` : 'none'}
          </div>
          <div className="econ-kpi-unit">
            {s.unservedMWh > 0 ? `${s.unservedHours} hour(s) short` : 'demand met every hour'}
          </div>
        </div>
      </div>

      <div className="econ-table-wrap">
        <table className="econ-table">
          <thead>
            <tr>
              <th>Unit</th><th>Carrier</th><th>Bid</th><th>Energy (MWh)</th>
              <th>Revenue</th><th>Profit</th><th>CF</th><th>Price-setting h</th>
            </tr>
          </thead>
          <tbody>
            {data.units.map((u) => (
              <tr key={u.name}>
                <td>{u.name}</td>
                <td>{u.carrier}</td>
                <td>{c}{u.bid.toFixed(1)}</td>
                <td>{num(u.energyMWh)}</td>
                <td>{c}{num(u.revenue)}</td>
                <td className={u.profit < 0 ? 'econ-negative' : undefined}>{c}{num(u.profit)}</td>
                <td>{(u.capacityFactor * 100).toFixed(0)}%</td>
                <td>{u.priceSettingHours}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.storage.length > 0 && (
        <div className="econ-table-wrap">
          <table className="econ-table">
            <thead>
              <tr><th>Storage</th><th>Charged (MWh)</th><th>Discharged (MWh)</th><th>Arbitrage</th></tr>
            </thead>
            <tbody>
              {data.storage.map((r) => (
                <tr key={r.name}>
                  <td>{r.name}</td>
                  <td>{num(r.energyChargedMWh)}</td>
                  <td>{num(r.energyDischargedMWh)}</td>
                  <td className={r.arbitrageRevenue < 0 ? 'econ-negative' : undefined}>
                    {c}{num(r.arbitrageRevenue)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="econ-footnote">
        Rule-based simulation ({setters} unit(s) ever set the price) on a single zone —
        network limits are not enforced. Profit = revenue − true marginal cost × energy.
      </p>
    </div>
  );
}
