/**
 * PriceElasticCard (M2) — price-elastic demand outcome.
 *
 * How much demand voluntarily reduced because the clearing price beat its
 * willingness-to-pay, per load and system-wide. Distinct from shedding: only the
 * blocks whose value fell below the price step down — high-value demand is still
 * served. The volume-weighted WTP shows how valuable the reduced demand was.
 */
import React from 'react';
import { PriceElasticResult } from 'lib/types';

const gwh = (mwh: number) => (mwh >= 1e4 ? `${(mwh / 1e3).toFixed(1)} GWh` : `${Math.round(mwh).toLocaleString()} MWh`);

interface Props {
  data: PriceElasticResult;
}

export function PriceElasticCard({ data }: Props) {
  if (!data.loads.length) {
    return <p className="dashboard-cell-missing">No price-elastic demand response in this run.</p>;
  }
  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Demand reduced</div>
          <div className="econ-kpi-value">{gwh(data.totalReducedMWh)}</div>
          <div className="econ-kpi-unit">voluntarily, where price beat its value</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Responsive loads</div>
          <div className="econ-kpi-value">{data.loads.length}</div>
          <div className="econ-kpi-unit">loads that stepped down</div>
        </div>
      </div>

      <div className="econ-table-wrap">
        <table className="econ-table">
          <thead>
            <tr>
              <th>Load</th>
              <th className="num">Demand reduced</th>
              <th className="num">Avg WTP of reduced</th>
            </tr>
          </thead>
          <tbody>
            {data.loads.map((l) => (
              <tr key={l.name}>
                <td>{l.name}</td>
                <td className="num">{gwh(l.reducedMWh)}</td>
                <td className="num">{Math.round(l.avgWtp).toLocaleString()}/MWh</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="econ-note">
        A slice of demand carries a stepped willingness-to-pay curve; each block is served only when
        the clearing price is below its value, so demand steps down as price rises. Unlike load
        shedding (one high VOLL penalty), this reflects that different demand has different value —
        the reduced blocks are the least-valued. Avoided-supply and consumer-surplus effects beyond
        the modelled WTP steps are not shown.
      </p>
    </div>
  );
}
