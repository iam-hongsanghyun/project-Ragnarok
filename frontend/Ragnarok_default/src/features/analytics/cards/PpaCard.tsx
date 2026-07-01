/**
 * PpaCard (PP1) — fixed-price PPA settled against spot as a CfD.
 *
 * Headline: the strike vs the volume-weighted average spot price, the contracted
 * energy, and the net settlement to each side. The seller is paid
 * ``(strike − spot) × volume``; the buyer receives its negative. A price-hedge
 * screen, not a full contract appraisal.
 */
import React from 'react';
import { PpaResult } from 'lib/types';

function money(v: number, currency: string): string {
  const abs = Math.abs(v), sign = v < 0 ? '-' : '';
  if (abs >= 1e9) return `${sign}${currency}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${currency}${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}${currency}${(abs / 1e3).toFixed(1)}k`;
  return `${sign}${currency}${Math.round(abs).toLocaleString()}`;
}
const gwh = (mwh: number) => (mwh / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 });

interface Props {
  data: PpaResult;
}

export function PpaCard({ data }: Props) {
  const { currency, strikePrice, avgSpotPrice, energyMWh, spotValue, contractValue, sellerNet, buyerNet, volumeType, owner } = data;
  const sellerWins = sellerNet >= 0; // strike beats spot → seller gains
  const volLabel = volumeType === 'generation' ? `${owner || 'owner'} generation` : 'flat block';

  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Strike vs spot</div>
          <div className="econ-kpi-value">
            {money(strikePrice, currency)}<span className="econ-kpi-sub"> / {money(avgSpotPrice, currency)}</span>
          </div>
          <div className="econ-kpi-unit">/MWh — {sellerWins ? 'strike above spot' : 'strike below spot'}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Contracted energy</div>
          <div className="econ-kpi-value">{gwh(energyMWh)}<span className="econ-kpi-sub"> GWh</span></div>
          <div className="econ-kpi-unit">{volLabel}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Seller net (CfD)</div>
          <div className={`econ-kpi-value ${sellerWins ? 'econ-recovered' : 'econ-shortfall'}`}>
            {sellerNet >= 0 ? '+' : ''}{money(sellerNet, currency)}
          </div>
          <div className="econ-kpi-unit">{sellerWins ? 'floor pays out' : 'floor costs the seller'}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Buyer net (CfD)</div>
          <div className={`econ-kpi-value ${buyerNet >= 0 ? 'econ-recovered' : 'econ-shortfall'}`}>
            {buyerNet >= 0 ? '+' : ''}{money(buyerNet, currency)}
          </div>
          <div className="econ-kpi-unit">{buyerNet >= 0 ? 'cap pays out' : 'cap costs the buyer'}</div>
        </div>
      </div>

      <div className="econ-body">
        <div className="econ-table-col">
          <p className="econ-section-label">Settlement</p>
          <div className="econ-table-wrap">
            <table className="econ-table">
              <thead>
                <tr>
                  <th>Leg</th>
                  <th className="num">Price (/MWh)</th>
                  <th className="num">Value</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Physical energy at spot</td>
                  <td className="num">{money(avgSpotPrice, currency)}</td>
                  <td className="num">{money(spotValue, currency)}</td>
                </tr>
                <tr>
                  <td>Contract at strike</td>
                  <td className="num">{money(strikePrice, currency)}</td>
                  <td className="num">{money(contractValue, currency)}</td>
                </tr>
                <tr>
                  <td><strong>CfD settlement to seller</strong></td>
                  <td className="num">—</td>
                  <td className={`num ${sellerWins ? 'econ-recovered' : 'econ-shortfall'}`}>
                    {sellerNet >= 0 ? '+' : ''}{money(sellerNet, currency)}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <p className="econ-note">
        The physical energy clears at spot ({money(spotValue, currency)} at a {money(avgSpotPrice, currency)}/MWh
        volume-weighted average); the PPA adds a Contract-for-Difference settling{' '}
        <code>(strike − spot) × volume</code> to the seller ({money(sellerNet, currency)}), so the seller's total is
        locked at the {money(contractValue, currency)} contract value. The buyer's net is the mirror image. A price-hedge
        screen against this run's prices — it does not re-optimise dispatch or model contract shape, curtailment risk, or credit.
      </p>
    </div>
  );
}
