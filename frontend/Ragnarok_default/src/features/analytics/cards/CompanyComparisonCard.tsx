/**
 * CompanyComparisonCard — rank companies side by side.
 *
 * Joins the three per-company result blocks by company name — F1 breakdown
 * (capacity / energy / revenue / emissions), F2 finance (NPV / IRR / payback),
 * and the consolidated statement (net margin) — into one sortable table with an
 * inline bar for the selected metric. The join and the sort come from the server
 * (`GET /api/runs/{name}/companies`, with `period` for one investment period of a
 * pathway run); the browser joins nothing. Results imported from a file are stored
 * as runs, so they take the same route.
 */
import React from 'react';
import { CompanyComparison, CompanyRow, fetchRunCompanies } from 'lib/api/resultsDerived';
import { useAsync } from '../../../shared/hooks/useAsync';

type CompanyComparisonData = Pick<CompanyComparison, 'currency' | 'sortedBy' | 'metrics' | 'items'>;

interface Props {
  /** Stored run to read the comparison from. */
  runName?: string | null;
  /** Pathway investment period; null/absent = the whole horizon. */
  period?: number | null;
}

const money = (v: number, cur: string) => `${v < 0 ? '−' : ''}${cur}${Math.abs(Math.round(v)).toLocaleString()}`;
const num0 = (v: number) => Math.round(v).toLocaleString();

/** How each metric key prints; the labels and sort direction come with the data. */
const FORMAT: Record<string, (v: number, cur: string) => string> = {
  npv: money,
  netMargin: money,
  irr: (v) => `${(v * 100).toFixed(1)}%`,
  revenue: money,
  capacityMW: (v) => `${num0(v)} MW`,
  emissionsTonnes: (v) => `${num0(v)} t`,
};

const valueOf = (r: CompanyRow, key: string): number | null => {
  const v = (r as unknown as Record<string, number | null | undefined>)[key];
  return v === undefined ? null : v;
};

function ComparisonTable({ data, sortKey, onSort, busy }: {
  data: CompanyComparisonData;
  sortKey: string;
  onSort: (key: string) => void;
  busy: boolean;
}) {
  const cur = data.currency;
  const { metrics } = data;
  const [barKey, setBarKey] = React.useState<string | null>(null);
  const sortMetric = metrics.find((m) => m.key === sortKey) ?? metrics[0];
  const barMetric = metrics.find((m) => m.key === barKey) ?? metrics[0];
  const barMax = Math.max(1, ...data.items.map((r) => Math.abs(valueOf(r, barMetric.key) ?? 0)));

  if (data.items.length === 0) {
    return <p className="dashboard-cell-missing">No owner-tagged companies to compare.</p>;
  }

  return (
    <div className="econ-card" aria-busy={busy}>
      <div className="econ-kpi-row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <span className="sg-setting-hint" style={{ margin: 0 }}>Bar metric:</span>
        {metrics.map((m) => (
          <button
            key={m.key}
            className={`tb-btn sg-solver-btn${barMetric.key === m.key ? '' : ' tb-btn--muted'}`}
            onClick={() => { setBarKey(m.key); onSort(m.key); }}
          >
            {m.label}
          </button>
        ))}
      </div>

      <div className="econ-table-wrap">
        <table className="econ-table">
          <thead>
            <tr>
              <th>Company</th>
              {metrics.map((m) => (
                <th
                  key={m.key}
                  className="num"
                  style={{ cursor: 'pointer' }}
                  title="Sort by this metric"
                  onClick={() => onSort(m.key)}
                >
                  {m.label}{sortMetric.key === m.key ? ' ▾' : ''}
                </th>
              ))}
              <th style={{ minWidth: 110 }}>{barMetric.label}</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((r) => {
              const bv = valueOf(r, barMetric.key) ?? 0;
              return (
                <tr key={r.company}>
                  <td>{r.company}</td>
                  {metrics.map((m) => {
                    const v = valueOf(r, m.key);
                    return <td key={m.key} className="num">{v === null ? '—' : (FORMAT[m.key] ?? num0 as (v: number, c: string) => string)(v, cur)}</td>;
                  })}
                  <td>
                    <div className="sb-bar">
                      <span style={{ width: `${Math.max(2, (Math.abs(bv) / barMax) * 100)}%`, background: bv < 0 ? 'var(--danger, #dc2626)' : undefined }} />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="econ-footnote">
        Companies ranked by {sortMetric.label}. Joins the per-company breakdown, finance,
        and P&amp;L blocks by owner tag — click a column header to re-sort.
      </p>
    </div>
  );
}

export function CompanyComparisonCard({ runName, period = null }: Props) {
  const [sortKey, setSortKey] = React.useState<string | undefined>(undefined);
  const { data, loading, error } = useAsync(
    runName ? `${runName}|${sortKey ?? ''}|${period ?? ''}` : null,
    () => fetchRunCompanies(runName as string, sortKey, period),
  );
  if (!runName) return <p className="dashboard-cell-missing">The company comparison is read from a stored run; this result has none.</p>;
  if (error) return <p className="dashboard-cell-missing" role="alert">Could not load the company comparison: {error}</p>;
  if (!data) return <p className="dashboard-cell-missing" aria-busy="true">Loading company comparison…</p>;
  return <ComparisonTable data={data} sortKey={sortKey ?? data.sortedBy} onSort={setSortKey} busy={loading} />;
}
