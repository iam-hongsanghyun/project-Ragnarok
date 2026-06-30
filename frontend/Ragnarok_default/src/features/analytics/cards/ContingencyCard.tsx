/**
 * ContingencyCard — results of an N-1 contingency analysis run.
 *
 * Shows the overall N-1 verdict and a per-contingency table (worst post-outage
 * branch loading, the branch hit, and overload count). Physics-only.
 */
import React from 'react';
import { ContingencyResult } from 'lib/types';

interface Props {
  data: ContingencyResult;
}

export function ContingencyCard({ data }: Props) {
  if (data.error) {
    return (
      <div className="econ-card">
        <div className="econ-kpi-row">
          <div className="econ-kpi">
            <div className="econ-kpi-label">N-1 contingency</div>
            <div className="econ-kpi-value econ-shortfall">Failed</div>
            <div className="econ-kpi-unit">did not run</div>
          </div>
        </div>
        <p className="econ-note">{data.error}</p>
      </div>
    );
  }

  const worst = data.contingencies[0] ?? null;

  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">N-1 security</div>
          <div className={`econ-kpi-value ${data.secure ? 'econ-recovered' : 'econ-shortfall'}`}>
            {data.outagesTested === 0 ? 'n/a' : data.secure ? 'Secure' : 'Insecure'}
          </div>
          <div className="econ-kpi-unit">
            {data.outagesTested === 0
              ? 'no testable outages'
              : `${data.insecureCount} of ${data.outagesTested} overload a branch`}
          </div>
        </div>
        {worst && (
          <div className="econ-kpi">
            <div className="econ-kpi-label">Worst contingency</div>
            <div className={`econ-kpi-value ${worst.worstLoadingPct > 100 ? 'econ-shortfall' : ''}`}>
              {worst.worstLoadingPct.toFixed(0)}%
            </div>
            <div className="econ-kpi-unit">
              {worst.worstBranch ? `${worst.worstBranch} after ${worst.outage} out` : `after ${worst.outage} out`}
            </div>
          </div>
        )}
        <div className="econ-kpi">
          <div className="econ-kpi-label">Base-case peak</div>
          <div className="econ-kpi-value">{data.baseMaxLoadingPct.toFixed(0)}%</div>
          <div className="econ-kpi-unit">highest branch, no outage</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Outages tested</div>
          <div className="econ-kpi-value">{data.outagesTested}</div>
          <div className="econ-kpi-unit">single branch (N-1)</div>
        </div>
      </div>

      {data.contingencies.length > 0 ? (
        <div className="econ-body">
          <div className="econ-table-col">
            <p className="econ-section-label">Per-contingency (worst first)</p>
            <div className="econ-table-wrap">
              <table className="econ-table">
                <thead>
                  <tr>
                    <th>Outaged branch</th>
                    <th className="num">Worst loading</th>
                    <th>On branch</th>
                    <th className="num">Overloads</th>
                  </tr>
                </thead>
                <tbody>
                  {data.contingencies.map((c) => (
                    <tr key={c.outage}>
                      <td>{c.outage}</td>
                      <td className={`num ${c.worstLoadingPct > 100 ? 'econ-shortfall' : ''}`}>
                        {c.worstLoadingPct.toFixed(0)}%
                      </td>
                      <td>{c.worstBranch ?? '—'}</td>
                      <td className={`num ${c.overloadCount > 0 ? 'econ-shortfall' : 'econ-muted'}`}>
                        {c.overloadCount}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : (
        <p className="econ-note">No N-1 contingencies to test — the network has no redundant branches.</p>
      )}

      <p className="econ-note">
        Evaluated at the peak-demand snapshot ({data.snapshot}), linear (LODF). Physics only — no costs or prices.
      </p>
    </div>
  );
}
