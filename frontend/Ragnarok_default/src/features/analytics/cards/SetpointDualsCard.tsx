/**
 * SetpointDualsCard (P30) — shadow prices of ramp limits and set points.
 *
 * `mu_ramp_limit_up/down` (generators, links, processes), `mu_p_set`
 * (generators, links, processes) and `mu_state_of_charge_set` (storage units)
 * are the duals of those constraints, currency per MWh. A non-zero dual means the
 * constraint bound in that snapshot: relaxing it by 1 MWh would change the
 * objective by that amount. One row per asset and constraint that binds at least
 * once: how many hours, the strongest shadow price and when it occurred, the mean
 * over the binding hours, and a strip of when it bound. Slack assets are counted,
 * not listed.
 *
 * The duals are generic output series sheets. A full result carries them in
 * `outputs.series`; a stored run's light bundle lists them in `outputs.seriesSheets`
 * and they are fetched from the run on demand.
 */
import React from 'react';
import { RunResults } from 'lib/types';
import { fetchRunAnalysis } from 'lib/api/resultsDerived';
import { DUAL_LABEL, dualSheetsOf, parseDualSheet } from 'lib/results/dualViews';
import { useAsync } from '../../../shared/hooks/useAsync';
import { Strip } from './MaintenanceCard';

const num = (v: number, d = 2) => v.toLocaleString(undefined, { maximumFractionDigits: d });

interface Props {
  results: RunResults;
  /** Stored run the summary is read from (`GET /api/runs/{name}/analysis/setpoint-duals`). */
  runName?: string | null;
  /** Pathway investment period; null = the whole horizon. */
  period?: number | null;
  currencySymbol?: string;
}

export function SetpointDualsCard({ results, runName, period = null, currencySymbol = '' }: Props) {
  const sheets = React.useMemo(() => dualSheetsOf(results), [results]);
  const { data, loading, error } = useAsync(
    runName && sheets.length > 0 ? `${runName}|setpoint-duals|${period ?? ''}` : null,
    () => fetchRunAnalysis(runName as string, 'setpoint-duals', { period }),
  );

  if (sheets.length === 0) {
    return <p className="dashboard-cell-missing">No ramp or set-point duals in this run (set <code>ramp_limit_up</code> / <code>ramp_limit_down</code> on a generator, link or process).</p>;
  }
  if (!runName) return <p className="dashboard-cell-missing">Set-point duals need a stored run.</p>;
  if (error) return <p className="dashboard-cell-missing" role="alert">Could not load the dual series: {error}</p>;
  if (loading || !data) return <p className="dashboard-cell-missing" aria-busy="true">Loading dual series…</p>;

  const { rows, assetsChecked, totalSnapshots, bindingHours } = data;
  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Constraints with a dual</div>
          <div className="econ-kpi-value">{assetsChecked.toLocaleString()}</div>
          <div className="econ-kpi-unit">{sheets.map((s) => DUAL_LABEL[parseDualSheet(s)!.attribute]).filter((v, i, a) => a.indexOf(v) === i).join(', ')}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Binding</div>
          <div className="econ-kpi-value">{rows.length.toLocaleString()}</div>
          <div className="econ-kpi-unit">at least once</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Binding hours</div>
          <div className="econ-kpi-value">{num(bindingHours, 0)}</div>
          <div className="econ-kpi-unit">summed over constraints</div>
        </div>
      </div>
      {rows.length === 0 ? (
        <p className="dashboard-cell-missing">All {assetsChecked.toLocaleString()} ramp / set-point constraints were slack: no shadow price.</p>
      ) : (
        <div className="econ-table-wrap">
          <table className="econ-table">
            <thead>
              <tr>
                <th>Asset</th>
                <th>Constraint</th>
                <th>When bound</th>
                <th className="num">Hours</th>
                <th className="num">Peak ({currencySymbol}/MWh)</th>
                <th>Peak at</th>
                <th className="num">Mean ({currencySymbol}/MWh)</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.component}-${r.attribute}-${r.asset}`}>
                  <td>{r.asset} <span className="econ-sub">{r.component}</span></td>
                  <td>{DUAL_LABEL[r.attribute as keyof typeof DUAL_LABEL] ?? r.attribute}</td>
                  <td style={{ width: '30%' }}><Strip segments={r.segments} total={r.totalSnapshots} label={`${r.asset} ${r.attribute} binding pattern`} /></td>
                  <td className="num">{num(r.bindingHours, 1)}</td>
                  <td className="num">{num(r.peakShadowPrice)}</td>
                  <td>{r.peakAt}</td>
                  <td className="num">{num(r.meanShadowPrice)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="econ-note">
        A shadow price is the change in the objective per MWh the constraint were relaxed; zero means slack.
        Hours are weighted by the snapshot weighting ({totalSnapshots.toLocaleString()} snapshots shown).
      </p>
    </div>
  );
}
