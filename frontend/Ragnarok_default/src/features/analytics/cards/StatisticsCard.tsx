/**
 * StatisticsCard — PyPSA's statistics() table, surfaced verbatim.
 *
 * One row per (component, carrier) with PyPSA's canonical metrics: optimal /
 * installed capacity, supply, capacity factor, curtailment, capex / opex,
 * revenue, market value, … Columns are whatever the backend emitted, so this
 * stays correct across PyPSA versions.
 */
import React from 'react';
import { StatisticsResult } from 'lib/types';
import { carrierColor } from 'lib/utils/helpers';

function fmt(v: number | null): string {
  if (v == null) return '—';
  const abs = Math.abs(v);
  if (abs !== 0 && abs < 1) return v.toFixed(3); // capacity factor etc.
  if (abs >= 1000) return Math.round(v).toLocaleString();
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

interface Props {
  data: StatisticsResult;
}

export function StatisticsCard({ data }: Props) {
  if (!data.rows.length || !data.columns.length) {
    return <p className="dashboard-cell-missing">No statistics for this run.</p>;
  }
  return (
    <div className="econ-card">
      <div className="econ-body">
        <div className="econ-table-col">
          <p className="econ-section-label">PyPSA statistics — by component &amp; carrier</p>
          <div className="econ-table-wrap">
            <table className="econ-table">
              <thead>
                <tr>
                  <th>Component</th>
                  <th>Carrier</th>
                  {data.columns.map((c) => <th key={c} className="num">{c}</th>)}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r, i) => (
                  <tr key={`${r.component}-${r.carrier}-${i}`}>
                    <td>{r.component}</td>
                    <td>
                      {r.carrier && <span className="carrier-dot" style={{ backgroundColor: carrierColor(r.carrier) }} />}
                      {r.carrier || '—'}
                    </td>
                    {data.columns.map((c) => <td key={c} className="num">{fmt(r.values[c] ?? null)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <p className="econ-note">Computed by PyPSA's <code>n.statistics()</code> — capacity in MW, energy in MWh, expenditure/revenue in the run currency, capacity factor and curtailment dimensionless.</p>
    </div>
  );
}
