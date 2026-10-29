/**
 * ResultsSection — results of a stored run per composite: the plant results table (output, capacity factor, starts by tier,
 * BESS cycles, H2 share and CO2 avoided, LCOH) and, for a P2X chain, the levelised-cost waterfall, RFNBO compliance and dispatch.
 * Both read the server (`/api/build/plant/results/{run}`, `/api/p2x/results/{run}`); nothing is computed here.
 */
import React from 'react';
import type { WorkbookModel } from 'lib/types';
import { fetchReportRuns } from 'lib/api/reports';
import type { ReportRunOption } from 'lib/reporting/types';
import { CompositesCard } from '../../features/analytics/cards/CompositesCard';
import { P2XResultsPanel } from './P2XResultsPanel';
import { pathwayPeriodsOf } from './pathway';

export function ResultsSection({ model, currencySymbol }: { model: WorkbookModel; currencySymbol?: string }) {
  const [runs, setRuns] = React.useState<ReportRunOption[]>([]);
  const [run, setRun] = React.useState('');
  const [period, setPeriod] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  const hasP2x = (model.RAGNAROK_P2X?.length ?? 0) > 0;
  const pathway = React.useMemo(() => pathwayPeriodsOf(runs.find((r) => r.name === run)), [runs, run]);

  React.useEffect(() => {
    let live = true;
    fetchReportRuns()
      .then((list) => { if (live) { setRuns(list); setRun((cur) => cur || list[0]?.name || ''); } })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, []);
  React.useEffect(() => {
    if (!pathway.isPathway || (period !== '' && !pathway.periods.includes(Number(period)))) setPeriod('');
  }, [pathway, period]);

  return (
    <div className="cmp-results" data-testid="composite-results">
      <div className="cmp-toolbar">
        <label htmlFor="cmp-run">Stored run</label>
        <select id="cmp-run" className="ss-input" value={run} onChange={(e) => setRun(e.target.value)} disabled={runs.length === 0}>
          {runs.map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
        </select>
        {pathway.isPathway && (<>
          <label htmlFor="cmp-period">Period</label>
          <select id="cmp-period" className="ss-input" value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option value="">whole horizon</option>
            {pathway.periods.map((p) => <option key={p} value={String(p)}>{p}</option>)}
          </select>
        </>)}
      </div>
      {error && <p className="cmp-error" role="alert">{error}</p>}
      {runs.length === 0 && !error && <p className="cmp-note">No stored runs yet. Add a composite, solve the model, then come back.</p>}
      {run && <CompositesCard runName={run} period={period === '' ? null : Number(period)} currencySymbol={currencySymbol} />}
      {run && hasP2x && (
        <section className="cmp-section">
          <h3>Power-to-X: levelised cost and RFNBO compliance</h3>
          <P2XResultsPanel runs={runs} run={run} />
        </section>
      )}
    </div>
  );
}
