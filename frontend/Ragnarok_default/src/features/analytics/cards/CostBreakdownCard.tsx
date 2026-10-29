/**
 * CostBreakdownCard — the run's objective split into its labelled parts (`results.costBreakdown`), largest first.
 *
 * The lines are the server's: capital, operating, fuel and the surcharges the plants module adds (for example the warm / cold
 * start-up tiers). Nothing is recomputed here; the share column is each line over the sum of the lines.
 */
import React from 'react';
import type { RunResults } from 'lib/types';

interface Props { results: RunResults; currencySymbol?: string }

const money = (v: number, symbol: string): string => `${v < 0 ? '-' : ''}${symbol}${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

export function CostBreakdownCard({ results, currencySymbol = '$' }: Props) {
  const lines = (results.costBreakdown ?? []).filter((l) => Number.isFinite(l.value) && l.value !== 0);
  if (lines.length === 0) return <p className="dashboard-cell-missing">This run reports no cost breakdown.</p>;
  const total = lines.reduce((s, l) => s + l.value, 0);
  const sorted = [...lines].sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
  return (
    <div className="result-table-card" data-tour="cost-breakdown">
      <table className="sg-table">
        <thead><tr><th>Cost line</th><th className="sg-table__num">Value</th><th className="sg-table__num">Share</th></tr></thead>
        <tbody>
          {sorted.map((l) => (
            <tr key={l.label}>
              <td>{l.label}</td>
              <td className="sg-table__num">{money(l.value, currencySymbol)}</td>
              <td className="sg-table__num">{total !== 0 ? `${((l.value / total) * 100).toLocaleString(undefined, { maximumFractionDigits: 1 })} %` : '—'}</td>
            </tr>
          ))}
          <tr><td><strong>Sum of the lines</strong></td><td className="sg-table__num"><strong>{money(total, currencySymbol)}</strong></td><td className="sg-table__num">100 %</td></tr>
        </tbody>
      </table>
    </div>
  );
}
