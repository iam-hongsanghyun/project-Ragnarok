/**
 * BidStrategyCard (Tier 2) — markup vs price-taker baseline.
 *
 * Headline: the change in the owner's profit from bidding above cost, with the
 * baseline (price-taker) and strategic sides side by side — profit, energy,
 * capture price — plus the market-wide price impact. A positive delta is market
 * power; a negative one means the markup backfired (lost dispatch).
 */
import React from 'react';
import { BidStrategyResult } from 'lib/types';

function money(v: number, currency: string): string {
  const abs = Math.abs(v), sign = v < 0 ? '-' : '';
  if (abs >= 1e9) return `${sign}${currency}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${currency}${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}${currency}${(abs / 1e3).toFixed(1)}k`;
  return `${sign}${currency}${Math.round(abs).toLocaleString()}`;
}

interface Props {
  data: BidStrategyResult;
}

export function BidStrategyCard({ data }: Props) {
  const { currency, owner, baseline, strategic, deltaProfit, systemAvgPrice } = data;
  const markupLabel = data.markupType === 'percent'
    ? `+${Math.round(data.markup * 1000) / 10}%`
    : `+${currency}${data.markup}/MWh`;
  const gain = deltaProfit >= 0;
  const gwh = (v: number) => (v / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 });

  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Δ Profit from markup</div>
          <div className={`econ-kpi-value ${gain ? 'econ-recovered' : 'econ-shortfall'}`}>
            {gain ? '+' : ''}{money(deltaProfit, currency)}
          </div>
          <div className="econ-kpi-unit">{gain ? 'market power — markup pays off' : 'backfired — lost dispatch'}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Owner</div>
          <div className="econ-kpi-value">{owner}</div>
          <div className="econ-kpi-unit">{data.generatorCount} generator{data.generatorCount === 1 ? '' : 's'} · offer {markupLabel}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">System avg price</div>
          <div className="econ-kpi-value">
            {currency}{systemAvgPrice.baseline.toLocaleString()}
            {systemAvgPrice.strategic != null && <span className="econ-kpi-sub"> → {currency}{systemAvgPrice.strategic.toLocaleString()}</span>}
          </div>
          <div className="econ-kpi-unit">/MWh, baseline → strategic</div>
        </div>
      </div>

      <div className="econ-body">
        <div className="econ-table-col">
          <p className="econ-section-label">Owner “{owner}” — price-taker vs strategic</p>
          <div className="econ-table-wrap">
            <table className="econ-table">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th className="num">Price-taker (baseline)</th>
                  <th className="num">Strategic (markup)</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Profit</td>
                  <td className="num">{money(baseline.profit, currency)}</td>
                  <td className={`num ${strategic.profit >= baseline.profit ? 'econ-recovered' : 'econ-shortfall'}`}>{money(strategic.profit, currency)}</td>
                </tr>
                <tr>
                  <td>Revenue</td>
                  <td className="num">{money(baseline.revenue, currency)}</td>
                  <td className="num">{money(strategic.revenue, currency)}</td>
                </tr>
                <tr>
                  <td>Energy sold (GWh)</td>
                  <td className="num">{gwh(baseline.energyMWh)}</td>
                  <td className="num">{gwh(strategic.energyMWh)}</td>
                </tr>
                <tr>
                  <td>Capture price ({currency}/MWh)</td>
                  <td className="num">{baseline.capturePrice == null ? '—' : baseline.capturePrice.toLocaleString()}</td>
                  <td className="num">{strategic.capturePrice == null ? '—' : strategic.capturePrice.toLocaleString()}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <p className="econ-note">
        The owner's offers are marked up by {markupLabel} and the market is re-cleared; profit is
        evaluated at the owner's <em>true</em> marginal cost (the markup is only the offer). A positive
        Δ means the owner is pivotal enough to move the price in its favour (market power); a negative Δ
        means the market is competitive enough that withholding just costs it dispatch. Single-firm
        strategic view — full multi-firm equilibrium is not modelled.
      </p>
    </div>
  );
}
