/**
 * Physical Risk — Results sub-tab.
 *
 * Peril multi-select + scenario (rcp, horizon) inputs and a "Run physical risk"
 * button, plus per-peril result cards (KPIs, per-asset EAI table, return-period
 * loss curve).
 *
 * This is a CONTROLLED section: the `run` state and its polling live in
 * `PhysicalRiskView` (which stays mounted across sub-tab switches), so a
 * just-computed result survives navigating to Assets and back, and no poll
 * callback ever fires setState on an unmounted section. Here we only hold the
 * local input drafts (perils, scenario) and delegate execution via `onRun`.
 */
import React, { useState } from 'react';
import { SearchableMultiSelect } from '../../shared/components/SearchableMultiSelect';
import { FreqCurveChart } from '../../features/physicalRisk/FreqCurveChart';
import { Libraries, PhysicalRunResult, Portfolio, Run, Scenario } from 'lib/physicalRisk/types';

const RCP_OPTIONS = [
  { value: 'rcp26', label: 'RCP 2.6 (low emissions)' },
  { value: 'rcp45', label: 'RCP 4.5 (moderate)' },
  { value: 'rcp60', label: 'RCP 6.0 (high)' },
  { value: 'rcp85', label: 'RCP 8.5 (very high)' },
];

interface Props {
  portfolio: Portfolio | null;
  libraries: Libraries | null;
  run: Run | null;
  submitting: boolean;
  onRun: (perils: string[], scenario: Scenario) => void;
}

function PerilResultCard({ result, currencySymbol }: { result: PhysicalRunResult; currencySymbol: string }) {
  const money = (v: number) => `${currencySymbol}${Math.round(v).toLocaleString()}`;
  return (
    <div className="chart-card chart-card-wide">
      <div className="chart-card-header">
        <div>
          <h3>{result.peril.replace(/_/g, ' ')}</h3>
          <p>
            Average annual impact {money(result.aaiAgg)}/yr
            {result.deltaPct != null && (
              <> · {result.deltaPct >= 0 ? '+' : ''}{result.deltaPct.toFixed(1)}% vs present-day baseline</>
            )}
          </p>
        </div>
      </div>
      <div className="econ-body">
        <div className="econ-table-col" style={{ flex: '1 1 320px' }}>
          <p className="econ-section-label">Per-asset expected annual impact</p>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Asset id</th>
                  <th>EAI</th>
                </tr>
              </thead>
              <tbody>
                {result.perAsset.map((row) => (
                  <tr key={row.assetId}>
                    <td>{row.assetId}</td>
                    <td>{money(row.eai)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="econ-table-col" style={{ flex: '1 1 320px' }}>
          <p className="econ-section-label">Return-period losses</p>
          <FreqCurveChart curve={result.freqCurve} currencySymbol={currencySymbol} />
        </div>
      </div>
    </div>
  );
}

export function ResultsSection({ portfolio, libraries, run, submitting, onRun }: Props) {
  const [perils, setPerils] = useState<string[]>([]);
  const [scenario, setScenario] = useState<Scenario>({ rcp: 'rcp45', horizon: 2050 });

  const running = run?.status === 'queued' || run?.status === 'running';
  const perilOptions = libraries?.perils.map((p) => ({ value: p.id, label: p.label })) ?? [];
  const currencySymbol = run?.result?.currency === 'USD' || !run?.result ? '$' : run.result.currency + ' ';

  return (
    <div className="pane">
      <div className="pane-header">
        <div>
          <h2>Results</h2>
          <p className="chart-card p">
            Run a physical-risk analysis for the loaded portfolio under a climate scenario.
          </p>
        </div>
      </div>

      <div className="chart-card" style={{ marginBottom: 16 }}>
        <div className="sg-setting-row">
          <label className="sg-setting-label">Perils</label>
          <SearchableMultiSelect
            values={perils}
            options={perilOptions.length > 0 ? perilOptions : []}
            onChange={setPerils}
            placeholder="Select perils"
          />
        </div>
        <div className="sg-setting-row">
          <label className="sg-setting-label">RCP scenario</label>
          <select
            value={scenario.rcp}
            onChange={(e) => setScenario((s) => ({ ...s, rcp: e.target.value }))}
          >
            {RCP_OPTIONS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
          </select>
        </div>
        <div className="sg-setting-row">
          <label className="sg-setting-label">Horizon year</label>
          <input
            type="number"
            className="sg-number-input"
            min={2020}
            max={2100}
            step={5}
            value={scenario.horizon}
            onChange={(e) => setScenario((s) => ({ ...s, horizon: Number(e.target.value) || s.horizon }))}
          />
        </div>
        <div className="sg-setting-row">
          <button className="tb-btn tb-btn--primary" onClick={() => onRun(perils, scenario)} disabled={submitting || running}>
            {running ? 'Running…' : submitting ? 'Submitting…' : 'Run physical risk'}
          </button>
          {!portfolio && <p className="sg-setting-hint">Load the fleet on the Assets tab first.</p>}
        </div>
      </div>

      {run?.status === 'error' && <p className="sg-error-text">{run.error ?? 'Run failed'}</p>}

      {run?.status === 'done' && run.result && run.result.perils.length > 0 && (
        <div className="analytics-grid">
          {run.result.perils.map((result) => (
            <PerilResultCard key={result.peril} result={result} currencySymbol={currencySymbol} />
          ))}
        </div>
      )}

      {!run && (
        <div className="analytics-empty">
          <h3>No run yet</h3>
          <p>Select perils and a scenario above, then run the analysis.</p>
        </div>
      )}
    </div>
  );
}
