/**
 * PpaExplorerCard (DW4) — candidate PPA shapes ranked by capture price.
 *
 * Companion to the single-PPA card: at the same strike, which contract shape
 * captures the most spot value? A generation (as-produced) PPA captures the price
 * only when the asset runs; a flat block earns the mean; a peak block earns the
 * peak. The capture price is the shape's fair-strike anchor and the ranking key.
 */
import React from 'react';
import { PpaExplorerResult } from 'lib/types';

function money(v: number, currency: string): string {
  const abs = Math.abs(v), sign = v < 0 ? '-' : '';
  if (abs >= 1e9) return `${sign}${currency}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${currency}${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}${currency}${(abs / 1e3).toFixed(1)}k`;
  return `${sign}${currency}${Math.round(abs).toLocaleString()}`;
}
const gwh = (mwh: number) => (mwh >= 1e4 ? `${(mwh / 1e3).toFixed(1)} GWh` : `${Math.round(mwh).toLocaleString()} MWh`);

interface Props {
  data: PpaExplorerResult;
}

export function PpaExplorerCard({ data }: Props) {
  const { currency, strikePrice, shapes } = data;
  if (!shapes.length) {
    return <p className="dashboard-cell-missing">No PPA shapes to explore for this run.</p>;
  }
  const best = shapes[0];

  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Highest-capture shape</div>
          <div className="econ-kpi-value" style={{ fontSize: '0.95rem' }}>{best.shape}</div>
          <div className="econ-kpi-unit">captures {money(best.avgSpotPrice, currency)}/MWh</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Strike compared</div>
          <div className="econ-kpi-value">{money(strikePrice, currency)}<span className="econ-kpi-sub"> /MWh</span></div>
          <div className="econ-kpi-unit">same strike across all shapes</div>
        </div>
      </div>

      <div className="econ-table-wrap">
        <table className="econ-table">
          <thead>
            <tr>
              <th>Contract shape</th>
              <th className="num">Energy</th>
              <th className="num">Capture price</th>
              <th className="num">vs strike</th>
              <th className="num">Seller net (CfD)</th>
            </tr>
          </thead>
          <tbody>
            {shapes.map((s) => {
              const beatsStrike = s.avgSpotPrice <= strikePrice; // seller gains when strike ≥ capture
              return (
                <tr key={s.shape}>
                  <td>{s.shape}</td>
                  <td className="num">{gwh(s.energyMWh)}</td>
                  <td className="num">{money(s.avgSpotPrice, currency)}</td>
                  <td className={`num ${beatsStrike ? 'econ-recovered' : 'econ-shortfall'}`}>
                    {s.avgSpotPrice <= strikePrice ? '' : '+'}{money(s.avgSpotPrice - strikePrice, currency)}
                  </td>
                  <td className={`num ${s.sellerNet >= 0 ? 'econ-recovered' : 'econ-shortfall'}`}>
                    {s.sellerNet >= 0 ? '+' : ''}{money(s.sellerNet, currency)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="econ-note">
        Each shape is valued at the {money(strikePrice, currency)}/MWh strike against this run's LMP.
        The <strong>capture price</strong> is the volume-weighted spot each shape earns — a shape's
        fair strike. A seller wins where strike ≥ capture (a low-capture shape like as-produced solar
        needs a lower strike to break even); a buyer's gain is the mirror. A screen over shapes at a
        fixed strike — it does not optimise volumes or model contract terms, curtailment, or credit.
      </p>
    </div>
  );
}
