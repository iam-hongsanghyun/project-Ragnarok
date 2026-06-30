/**
 * MerchantCard — one owner's price-taker economics (B1).
 *
 * Headline profit (= revenue − operating cost − annualised capex) for the
 * selected owner against the chosen price signal, then a per-asset breakdown:
 * capacity, energy sold, capture price, and the revenue/cost/profit stack.
 */
import React from 'react';
import { MerchantResult } from 'lib/types';
import { carrierColor } from 'lib/utils/helpers';

function compactMoney(v: number, currency: string): string {
  const abs = Math.abs(v);
  const sign = v < 0 ? '-' : '';
  if (abs >= 1e9) return `${sign}${currency}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${currency}${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}${currency}${(abs / 1e3).toFixed(1)}k`;
  return `${sign}${currency}${abs.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function fullMoney(v: number, currency: string): string {
  const sign = v < 0 ? '-' : '';
  return `${sign}${currency}${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

interface Props {
  data: MerchantResult;
}

export function MerchantCard({ data }: Props) {
  const { currency, totals, priceStats } = data;
  if (!data.assets.length) {
    return <p className="dashboard-cell-missing">No merchant assets for owner “{data.owner}”.</p>;
  }
  const sourceLabel = data.priceSource === 'lmp' ? 'system marginal price' : 'fixed price';

  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Owner profit</div>
          <div className={`econ-kpi-value ${totals.profit >= 0 ? 'econ-recovered' : 'econ-shortfall'}`}>
            {compactMoney(totals.profit, currency)}
          </div>
          <div className="econ-kpi-unit">revenue − opex − capex</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Revenue</div>
          <div className="econ-kpi-value">{compactMoney(totals.revenue, currency)}</div>
          <div className="econ-kpi-unit">at {sourceLabel}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Energy sold</div>
          <div className="econ-kpi-value">
            {(totals.energyMWh / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}
            <span className="econ-kpi-sub"> GWh</span>
          </div>
          <div className="econ-kpi-unit">across {data.assets.length} asset{data.assets.length === 1 ? '' : 's'}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Price</div>
          <div className="econ-kpi-value">
            {priceStats.mean == null ? '—' : `${currency}${priceStats.mean.toLocaleString()}`}
            <span className="econ-kpi-sub">/MWh avg</span>
          </div>
          <div className="econ-kpi-unit">
            {priceStats.min != null && priceStats.max != null
              ? `${currency}${priceStats.min.toLocaleString()}–${priceStats.max.toLocaleString()}`
              : sourceLabel}
          </div>
        </div>
      </div>

      <div className="econ-body">
        <div className="econ-table-col">
          <p className="econ-section-label">Owner “{data.owner}” — assets</p>
          <div className="econ-table-wrap">
            <table className="econ-table">
              <thead>
                <tr>
                  <th>Asset</th>
                  <th>Carrier</th>
                  <th className="num">Capacity (MW)</th>
                  <th className="num">Energy (GWh)</th>
                  <th className="num">Capture ({currency}/MWh)</th>
                  <th className="num">Revenue</th>
                  <th className="num">Op. cost</th>
                  <th className="num">Capex</th>
                  <th className="num">Profit</th>
                </tr>
              </thead>
              <tbody>
                {data.assets.map((a) => (
                  <tr key={`${a.type}-${a.name}`}>
                    <td>{a.name} <span className="econ-muted">({a.type})</span></td>
                    <td>
                      <span className="carrier-dot" style={{ backgroundColor: carrierColor(a.carrier) }} />
                      {a.carrier || '—'}
                    </td>
                    <td className="num">{a.capacityMW.toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>
                    <td className="num">{(a.energyMWh / 1000).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                    <td className="num">{a.capturePrice == null ? '—' : a.capturePrice.toLocaleString()}</td>
                    <td className="num">{fullMoney(a.revenue, currency)}</td>
                    <td className="num">{a.operatingCost > 0 ? fullMoney(a.operatingCost, currency) : '—'}</td>
                    <td className="num">{a.capex > 0 ? fullMoney(a.capex, currency) : '—'}</td>
                    <td className={`num ${a.profit >= 0 ? 'econ-recovered' : 'econ-shortfall'}`}>{fullMoney(a.profit, currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <p className="econ-note">
        Price-taker (B1): owner “{data.owner}” optimises its own dispatch and build against the {sourceLabel}
        {data.priceSource === 'lmp' ? ' from the cost-min run' : ''} — generators run when the price beats
        their marginal cost, storage arbitrages. Capex is the annualised fixed cost of extendable capacity,
        so profit is an annual margin. Does not model market power (that is the deferred strategic case).
      </p>
    </div>
  );
}
