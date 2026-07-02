/**
 * CompanyStatementCard — the consolidated per-company annual P&L.
 *
 * Reads top-to-bottom like an operating statement: revenue, then the cost
 * lines backed out of dispatch (carbon, fuel + variable O&M), gross margin,
 * annualised capex, EBIT, interest, and the net operating result — one column
 * per company plus a system total. Costs show as negatives; margins are
 * colour-coded by sign.
 */
import React from 'react';
import { CompanyStatementResult, CompanyStatementEntry } from 'lib/types';

interface Props {
  data: CompanyStatementResult;
}

type Line = {
  key: keyof Omit<CompanyStatementEntry, 'company'>;
  label: string;
  kind: 'revenue' | 'cost' | 'subtotal' | 'net';
};

// Statement order. Costs render as negative; subtotals/net are emphasised.
const LINES: Line[] = [
  { key: 'revenue', label: 'Revenue', kind: 'revenue' },
  { key: 'carbonCost', label: 'Carbon cost', kind: 'cost' },
  { key: 'fuelVomCost', label: 'Fuel + variable O&M', kind: 'cost' },
  { key: 'grossMargin', label: 'Gross margin', kind: 'subtotal' },
  { key: 'capexAnnual', label: 'Annualised capex / fixed O&M', kind: 'cost' },
  { key: 'ebit', label: 'EBIT', kind: 'subtotal' },
  { key: 'interest', label: 'Interest', kind: 'cost' },
  { key: 'netMargin', label: 'Net operating result', kind: 'net' },
];

const fmt = (v: number, cur: string): string => {
  const sign = v < 0 ? '−' : '';
  return `${sign}${cur}${Math.abs(Math.round(v)).toLocaleString()}`;
};

export function CompanyStatementCard({ data }: Props) {
  const cur = data.currency || '';
  const companies = data.companies;
  if (companies.length === 0) {
    return <p className="dashboard-cell-missing">No owner-tagged companies to report.</p>;
  }
  const cellValue = (e: Omit<CompanyStatementEntry, 'company'>, line: Line): number => {
    const raw = Number(e[line.key] ?? 0);
    // Costs are stored positive; show them as outflows.
    return line.kind === 'cost' ? -raw : raw;
  };

  return (
    <div className="econ-card">
      <div className="econ-table-wrap">
        <table className="econ-table company-statement">
          <thead>
            <tr>
              <th>Annual P&amp;L ({cur}/yr)</th>
              {companies.map((c) => <th key={c.company} className="num">{c.company}</th>)}
              <th className="num total-col">All</th>
            </tr>
          </thead>
          <tbody>
            {LINES.map((line) => (
              <tr key={line.key} className={`stmt-${line.kind}`}>
                <td>{line.label}</td>
                {companies.map((c) => {
                  const v = cellValue(c, line);
                  const cls = (line.kind === 'subtotal' || line.kind === 'net')
                    ? (v >= 0 ? 'num econ-recovered' : 'num econ-negative')
                    : 'num';
                  return <td key={c.company} className={cls}>{fmt(v, cur)}</td>;
                })}
                <td className={`num total-col${(line.kind === 'subtotal' || line.kind === 'net') ? (cellValue(data.totals, line) >= 0 ? ' econ-recovered' : ' econ-negative') : ''}`}>
                  {fmt(cellValue(data.totals, line), cur)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="econ-footnote">
        Competitive-benchmark statement from the solved dispatch (revenue = LMP × output).
        Carbon cost is emissions × the {cur}{Math.round(data.carbonPrice)}/t carbon price, backed
        out of dispatch cost so fuel and carbon don't double-count. Capex is the annualised
        capital charge on optimal capacity; interest applies to the debt share if configured.
      </p>
    </div>
  );
}
