/**
 * PathwayOverviewCard — a multi-period (pathway) run across all of its investment periods at once.
 *
 * One row per period plus the whole run. Every figure is the server's (the only client arithmetic is the horizon length: the
 * periods' years added up).
 *  - capacity (generators, storage) is `result.pathway.summaries[].installedCapacityMw` / `storageCapacityMw`
 *    (assets active in that period only: build year and lifetime applied; capacity is a level, so the whole-run row has none);
 *  - generation, total cost, emissions, average price and peak load are the KPI strip of the period
 *    (`GET /api/runs/{name}/kpis?period=`) and of the whole horizon (no `period`). The whole-run cost and emissions are the
 *    periods' figures added by the server (money carries each period's objective weight, emissions its years weight).
 */
import React from 'react';
import type { RunResults } from 'lib/types';
import { fetchRunKpis, type RunKpis } from 'lib/api/resultsDerived';
import { useAsync } from '../../../shared/hooks/useAsync';

interface Props {
  results: RunResults;
  runName?: string | null;
  currencySymbol?: string;
}

const mw = (v: number | null | undefined): string => (v === null || v === undefined ? '—' : `${Math.round(v).toLocaleString()} MW`);
const mwh = (v: number): string => `${Math.round(v).toLocaleString()} MWh`;

export function PathwayOverviewCard({ results, runName, currencySymbol = '$' }: Props) {
  const summaries = results.pathway?.summaries ?? [];
  const periods = summaries.map((s) => s.period);
  const { data, loading, error } = useAsync(
    runName && periods.length ? `${runName}|${currencySymbol}|${periods.join(',')}` : null,
    async () => {
      const whole = await fetchRunKpis(runName as string, currencySymbol);
      const each = await Promise.all(periods.map((p) => fetchRunKpis(runName as string, currencySymbol, p)));
      return { whole: whole.kpis, byPeriod: Object.fromEntries(periods.map((p, i) => [p, each[i].kpis])) as Record<number, RunKpis> };
    },
  );
  if (!runName) return <p className="dashboard-cell-missing">The pathway overview is read from a stored run; this result has none.</p>;
  if (periods.length === 0) return <p className="dashboard-cell-missing">This run has no pathway periods.</p>;
  if (error) return <p className="dashboard-cell-missing" role="alert">Could not load the pathway overview: {error}</p>;
  if (loading || !data) return <p className="dashboard-cell-missing" aria-busy="true">Loading the pathway overview…</p>;

  const cells = (k: RunKpis) => [
    mwh(k.dispatchMwh),
    k.totalCost ?? '—',
    k.emissions ?? '—',
    `${currencySymbol}${k.avgPrice.toFixed(1)}/MWh`,
    k.peakLoadMw === null ? '—' : `${Math.round(k.peakLoadMw).toLocaleString()} MW`,
  ];

  return (
    <div className="result-table-card" data-tour="pathway-overview">
      <table className="sg-table">
        <thead>
          <tr>
            <th>Period</th><th className="sg-table__num">Years</th>
            <th className="sg-table__num">Generator capacity</th><th className="sg-table__num">Storage</th>
            <th className="sg-table__num">Generation</th><th className="sg-table__num">Total cost</th>
            <th className="sg-table__num">Emissions</th><th className="sg-table__num">Average price</th>
            <th className="sg-table__num">Peak load</th>
          </tr>
        </thead>
        <tbody>
          {summaries.map((s) => (
            <tr key={s.period}>
              <td>{s.period}</td>
              <td className="sg-table__num">{s.yearsWeight}</td>
              <td className="sg-table__num">{mw(s.installedCapacityMw)}</td>
              <td className="sg-table__num">{mw(s.storageCapacityMw)}</td>
              {cells(data.byPeriod[s.period]).map((c, i) => <td key={i} className="sg-table__num">{c}</td>)}
            </tr>
          ))}
          <tr className="sg-table__total">
            <td>Whole run</td>
            <td className="sg-table__num">{summaries.reduce((acc, s) => acc + s.yearsWeight, 0)}</td>
            <td className="sg-table__num">—</td><td className="sg-table__num">—</td>
            {cells(data.whole).map((c, i) => <td key={i} className="sg-table__num">{c}</td>)}
          </tr>
        </tbody>
      </table>
      <p className="result-table-card__note">
        Capacity counts only the assets active in the period (build year and lifetime), so it is a level and has no whole-run
        figure. Cost carries each period's objective weight and emissions its years weight, so the periods add up to the
        whole-run row. Generation is physical energy summed over the periods' modelled snapshots.
      </p>
    </div>
  );
}
