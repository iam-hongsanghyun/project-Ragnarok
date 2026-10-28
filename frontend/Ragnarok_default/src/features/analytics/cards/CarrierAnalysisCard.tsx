/**
 * Per-carrier operational analytics - the "Carrier performance" table.
 *
 * Capacity is INSTALLED NAMEPLATE: the solved p_nom_opt of every installed generator of a
 * carrier (input p_nom when no solved value), independent of whether each unit dispatched.
 * "Generated capacity" is the subset that actually produced energy (> 0 MWh), so the two
 * columns together reveal idle capacity. Shares are each carrier's fraction of total nameplate /
 * total energy. The capacity factor is n.statistics.capacity_factor (capacity-weighted per
 * carrier) and curtailment is n.statistics.curtailment. Carriers used only by the load-shedding
 * backstop are excluded.
 *
 * Every number is a server value (`GET /api/runs/{name}/analysis/carrier-performance`, one
 * investment period with `period`); the card only formats it.
 */
import React from 'react';
import { fetchRunAnalysis } from 'lib/api/resultsDerived';
import { useAsync } from '../../../shared/hooks/useAsync';

interface Props {
  /** Stored run backing the view. */
  runName?: string | null;
  /** Pathway investment period; null = the whole horizon. */
  period?: number | null;
  currencySymbol: string;
}

function fmt(n: number, digits = 0): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function pct(frac: number): string {
  return frac > 0 ? `${(frac * 100).toFixed(1)}%` : '—';
}

export function CarrierAnalysisCard({ runName, period = null }: Props) {
  const { data, loading, error } = useAsync(
    runName ? `${runName}|carrier-performance|${period ?? ''}` : null,
    () => fetchRunAnalysis(runName as string, 'carrier-performance', { period }),
  );
  if (!runName) return <p className="dashboard-cell-missing">Carrier performance needs a stored run.</p>;
  if (error) return <p className="dashboard-cell-missing" role="alert">Could not load carrier performance: {error}</p>;
  if (loading || !data) return <p className="dashboard-cell-missing" aria-busy="true">Loading carrier performance…</p>;
  const { rows, totals } = data;
  if (rows.length === 0 || !totals) return null;

  return (
    <div className="stochastic-card">
      <div className="stochastic-card-header">
        <div>
          <h3>Carrier performance</h3>
          <p>
            Capacity is installed nameplate (all units); <b>Generated cap.</b> is the
            portion that produced energy, so the gap is idle capacity. CF is PyPSA's
            capacity factor (n.statistics.capacity_factor). Load-shedding backstop excluded.
          </p>
        </div>
      </div>
      <div className="carrier-table-wrap">
        <table className="stochastic-table carrier-perf-table">
          <thead>
            <tr>
              <th>Carrier</th>
              <th>Generators</th>
              <th>Nameplate cap. (MW)</th>
              <th>Cap. share</th>
              <th>Generated cap. (MW)</th>
              <th>Energy (MWh)</th>
              <th>Gen. share</th>
              <th>CF</th>
              <th>Curtailment (MWh)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.carrier}>
                <td>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 999, background: r.color }} />
                    {r.carrier}
                  </span>
                </td>
                <td>{r.generatorCount}</td>
                <td>{fmt(r.nameplateMw)}</td>
                <td>{pct(r.capacityShare)}</td>
                <td>{fmt(r.generatedMw)}</td>
                <td>{fmt(r.energyMwh)}</td>
                <td>{pct(r.generationShare)}</td>
                <td>{r.capacityFactor != null && r.capacityFactor > 0 ? `${(r.capacityFactor * 100).toFixed(1)}%` : '—'}</td>
                <td>{r.curtailmentMwh === null || r.curtailmentMwh <= 0 ? '—' : fmt(r.curtailmentMwh)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="carrier-perf-total">
              <td>Total</td>
              <td>{totals.generatorCount}</td>
              <td>{fmt(totals.nameplateMw)}</td>
              <td>100%</td>
              <td>{fmt(totals.generatedMw)}</td>
              <td>{fmt(totals.energyMwh)}</td>
              <td>100%</td>
              <td>—</td>
              <td>{totals.curtailmentMwh === null || totals.curtailmentMwh <= 0 ? '—' : fmt(totals.curtailmentMwh)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
