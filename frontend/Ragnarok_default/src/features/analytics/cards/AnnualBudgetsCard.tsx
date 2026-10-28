/**
 * AnnualBudgetsCard — each annual budget the run applied, against what the solve achieved.
 *
 * The annual-budgets module turns a per-year budget into the horizon total PyPSA needs (`annual x sum(w) / 8760`). This card
 * shows that total beside the value read back from the solved network and, for a GlobalConstraint, its dual. All of it is
 * served by `GET /api/runs/{name}/annual-budgets`; the browser computes nothing.
 */
import React from 'react';
import { fetchRunAnnualBudgets } from 'lib/api/resultsDerived';
import { useAsync } from '../../../shared/hooks/useAsync';

interface Props {
  runName?: string | null;
}

const num = (v: number): string => v.toLocaleString(undefined, { maximumFractionDigits: 3 });

export function AnnualBudgetsCard({ runName }: Props) {
  const { data, loading, error } = useAsync(runName ? `${runName}|annual-budgets` : null, () => fetchRunAnnualBudgets(runName as string));
  if (!runName) return <p className="dashboard-cell-missing">Budgets are read back from a stored run; this result has none.</p>;
  if (error) return <p className="dashboard-cell-missing" role="alert">Could not load the budgets: {error}</p>;
  if (loading || !data) return <p className="dashboard-cell-missing" aria-busy="true">Loading the budgets…</p>;
  if (data.items.length === 0) return <p className="dashboard-cell-missing">This run applied no annual budgets.</p>;

  return (
    <div className="result-table-card" data-tour="annual-budgets">
      <table className="sg-table">
        <thead>
          <tr>
            <th>Target</th><th>Attribute</th>
            <th className="sg-table__num">Budget per year</th><th className="sg-table__num">Horizon total (PyPSA)</th>
            <th className="sg-table__num">Achieved</th><th>Status</th><th className="sg-table__num">Dual</th>
          </tr>
        </thead>
        <tbody>
          {data.items.map((r) => (
            <tr key={`${r.component}.${r.name}.${r.attribute}`}>
              <td>{r.component} / {r.name}</td>
              <td>{r.attribute}</td>
              <td className="sg-table__num">{num(r.annual)}</td>
              <td className="sg-table__num">{num(r.value)}</td>
              <td className="sg-table__num" title={r.achieved === null ? r.achievedUnit : undefined}>
                {r.achieved === null ? 'not reported' : `${num(r.achieved)} ${r.achievedUnit}`}
              </td>
              <td className={r.binding ? 'budget-status--binding' : 'budget-status--slack'}>
                {r.binding === null ? '—' : r.binding ? 'Binding' : 'Slack'}
              </td>
              <td className="sg-table__num">{r.dual === null ? '—' : num(r.dual)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="result-table-card__note">
        The horizon total is what the module wrote into PyPSA: annual x the horizon's weighted hours / 8760 (see the run notes).
        Achieved is read from the solved network: the generator's energy (n.statistics.supply) for an e_sum, the constraint's
        left-hand side for a CO2 cap. A dual is the constraint's price per unit of the budget (negative on a cap); PyPSA stores
        none for an e_sum, and a slack budget has a zero dual.
      </p>
    </div>
  );
}
