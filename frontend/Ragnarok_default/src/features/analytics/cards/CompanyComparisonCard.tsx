/**
 * CompanyComparisonCard — rank companies side by side.
 *
 * Joins the three per-company result blocks by company name — F1 breakdown
 * (capacity / energy / revenue / emissions), F2 finance (NPV / IRR / payback),
 * and the consolidated statement (net margin) — into one sortable table with an
 * inline bar for the selected metric. Pure view over data already computed; no
 * backend. Renders whatever blocks exist (at least F1 is required).
 */
import React from 'react';
import {
  CompanyBreakdownResult,
  CompanyFinanceResult,
  CompanyStatementResult,
} from 'lib/types';

interface Props {
  breakdown?: CompanyBreakdownResult;
  finance?: CompanyFinanceResult;
  statement?: CompanyStatementResult;
}

interface Metric {
  key: string;
  label: string;
  get: (r: Row) => number | null;
  fmt: (v: number, cur: string) => string;
  /** Higher is better → sort desc by default; for costs/payback, lower is better. */
  higherBetter: boolean;
}

interface Row {
  company: string;
  capacityMW?: number;
  energyMWh?: number;
  revenue?: number | null;
  emissionsTonnes?: number;
  npv?: number;
  irr?: number | null;
  paybackYears?: number | null;
  netMargin?: number;
}

const money = (v: number, cur: string) => `${v < 0 ? '−' : ''}${cur}${Math.abs(Math.round(v)).toLocaleString()}`;
const num0 = (v: number) => Math.round(v).toLocaleString();

export function CompanyComparisonCard({ breakdown, finance, statement }: Props) {
  const cur = breakdown?.currency || finance?.currency || statement?.currency || '';

  // Join by company name.
  const rows = new Map<string, Row>();
  const get = (name: string): Row => {
    let r = rows.get(name);
    if (!r) { r = { company: name }; rows.set(name, r); }
    return r;
  };
  for (const c of breakdown?.companies ?? []) {
    const r = get(c.company);
    r.capacityMW = c.capacityMW; r.energyMWh = c.energyMWh;
    r.revenue = c.revenue; r.emissionsTonnes = c.emissionsTonnes;
  }
  for (const c of finance?.companies ?? []) {
    const r = get(c.company);
    r.npv = c.npv; r.irr = c.irr; r.paybackYears = c.paybackYears;
  }
  for (const c of statement?.companies ?? []) {
    get(c.company).netMargin = c.netMargin;
  }
  const data = Array.from(rows.values());

  // Available metrics depend on which blocks are present.
  const metrics: Metric[] = [];
  if (finance) metrics.push({ key: 'npv', label: 'NPV', get: (r) => r.npv ?? null, fmt: money, higherBetter: true });
  if (statement) metrics.push({ key: 'netMargin', label: 'Net margin/yr', get: (r) => r.netMargin ?? null, fmt: money, higherBetter: true });
  if (finance) metrics.push({ key: 'irr', label: 'IRR', get: (r) => r.irr ?? null, fmt: (v) => `${(v * 100).toFixed(1)}%`, higherBetter: true });
  metrics.push({ key: 'revenue', label: 'Revenue/yr', get: (r) => r.revenue ?? null, fmt: money, higherBetter: true });
  metrics.push({ key: 'capacityMW', label: 'Capacity', get: (r) => r.capacityMW ?? null, fmt: (v) => `${num0(v)} MW`, higherBetter: true });
  metrics.push({ key: 'emissionsTonnes', label: 'Emissions', get: (r) => r.emissionsTonnes ?? null, fmt: (v) => `${num0(v)} t`, higherBetter: false });

  const [sortKey, setSortKey] = React.useState<string>(metrics[0]?.key ?? 'revenue');
  const [barKey, setBarKey] = React.useState<string>(metrics[0]?.key ?? 'revenue');

  const sortMetric = metrics.find((m) => m.key === sortKey) ?? metrics[0];
  const sorted = [...data].sort((a, b) => {
    const av = sortMetric?.get(a); const bv = sortMetric?.get(b);
    if (av === null || av === undefined) return 1;
    if (bv === null || bv === undefined) return -1;
    return sortMetric!.higherBetter ? bv - av : av - bv;
  });

  const barMetric = metrics.find((m) => m.key === barKey) ?? metrics[0];
  const barMax = Math.max(1, ...data.map((r) => Math.abs(barMetric?.get(r) ?? 0)));

  if (data.length === 0) {
    return <p className="dashboard-cell-missing">No owner-tagged companies to compare.</p>;
  }

  return (
    <div className="econ-card">
      <div className="econ-kpi-row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <span className="sg-setting-hint" style={{ margin: 0 }}>Bar metric:</span>
        {metrics.map((m) => (
          <button
            key={m.key}
            className={`tb-btn sg-solver-btn${barKey === m.key ? '' : ' tb-btn--muted'}`}
            onClick={() => { setBarKey(m.key); setSortKey(m.key); }}
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
                  onClick={() => setSortKey(m.key)}
                >
                  {m.label}{sortKey === m.key ? ' ▾' : ''}
                </th>
              ))}
              <th style={{ minWidth: 110 }}>{barMetric?.label}</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => {
              const bv = barMetric?.get(r) ?? 0;
              return (
                <tr key={r.company}>
                  <td>{r.company}</td>
                  {metrics.map((m) => {
                    const v = m.get(r);
                    return <td key={m.key} className="num">{v === null || v === undefined ? '—' : m.fmt(v, cur)}</td>;
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
        Companies ranked by {sortMetric?.label}. Joins the per-company breakdown, finance,
        and P&amp;L blocks by owner tag — click a column header to re-sort.
      </p>
    </div>
  );
}
