/**
 * StatisticsCard — PyPSA's statistics() table, surfaced verbatim.
 *
 * One row per (component, carrier) with PyPSA's canonical metrics: optimal /
 * installed capacity, supply, capacity factor, curtailment, capex / opex,
 * revenue, market value, … Columns are whatever the backend emitted, so this
 * stays correct across PyPSA versions.
 *
 * P31: a collapsed "Query parameters" panel (groupby, bus carrier, aggregate time,
 * at port, components, carrier) asks POST /api/statistics/query for the stored run
 * and shows that table instead; "Back to default" restores the solve-time table.
 */
import React, { useState } from 'react';
import { StatisticsQueryResponse, StatisticsResult } from 'lib/types';
import { postStatisticsQuery, splitList } from 'lib/api/statistics';
import { carrierColor } from 'lib/utils/helpers';

function fmt(v: number | null): string {
  if (v == null) return '—';
  const abs = Math.abs(v);
  if (abs !== 0 && abs < 1) return v.toFixed(3); // capacity factor etc.
  if (abs >= 1000) return Math.round(v).toLocaleString();
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

interface Props {
  data: StatisticsResult;
  /** Stored-run name; the parameter panel is disabled without it. */
  runName?: string | null;
}

/** `n.statistics` method names (mirror of backend STATISTIC_METRICS; an unknown one answers 400 with the list). */
const METRICS = [
  'energy_balance', 'supply', 'withdrawal', 'curtailment', 'capacity_factor',
  'optimal_capacity', 'installed_capacity', 'expanded_capacity',
  'capex', 'opex', 'installed_capex', 'expanded_capex', 'overnight_cost', 'fom',
  'system_cost', 'revenue', 'market_value', 'prices', 'transmission',
];

function QueryPanel({ runName, onResult }: { runName: string | null; onResult: (r: StatisticsQueryResponse | null) => void }) {
  const [metric, setMetric] = useState('energy_balance');
  const [groupby, setGroupby] = useState('');
  const [busCarrier, setBusCarrier] = useState('');
  const [aggregate, setAggregate] = useState<'sum' | 'mean' | 'none'>('sum');
  const [atPort, setAtPort] = useState(false);
  const [components, setComponents] = useState('');
  const [carrier, setCarrier] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    if (!runName) return;
    setBusy(true);
    setError(null);
    try {
      onResult(await postStatisticsQuery({
        runName,
        metric,
        groupby: splitList(groupby),
        busCarrier: splitList(busCarrier),
        aggregateTime: aggregate === 'none' ? false : aggregate,
        atPort,
        components: splitList(components),
        carrier: splitList(carrier),
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Statistics query failed.');
    } finally {
      setBusy(false);
    }
  };

  const field = (label: string, value: string, set: (v: string) => void, placeholder: string) => (
    <label className="econ-sub" style={{ display: 'inline-flex', flexDirection: 'column', gap: 2, marginRight: 12 }}>
      {label}
      <input type="text" value={value} placeholder={placeholder} onChange={(e) => set(e.target.value)} aria-label={label} style={{ width: 150 }} />
    </label>
  );

  return (
    <details className="econ-note">
      <summary>Query parameters</summary>
      {!runName && <p>Save the run (or open it from History) to query PyPSA statistics with parameters.</p>}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 4, marginTop: 6 }}>
        <label className="econ-sub" style={{ display: 'inline-flex', flexDirection: 'column', gap: 2, marginRight: 12 }}>
          Metric
          <select value={metric} onChange={(e) => setMetric(e.target.value)} aria-label="Metric">
            {METRICS.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </label>
        {field('Group by', groupby, setGroupby, 'carrier, bus')}
        {field('Bus carrier', busCarrier, setBusCarrier, 'AC, gas')}
        <label className="econ-sub" style={{ display: 'inline-flex', flexDirection: 'column', gap: 2, marginRight: 12 }}>
          Aggregate time
          <select value={aggregate} onChange={(e) => setAggregate(e.target.value as 'sum' | 'mean' | 'none')} aria-label="Aggregate time">
            <option value="sum">sum</option>
            <option value="mean">mean</option>
            <option value="none">none (time series)</option>
          </select>
        </label>
        {field('Components', components, setComponents, 'Generator, Link')}
        {field('Carrier', carrier, setCarrier, 'wind, solar')}
        <label className="econ-sub" style={{ marginRight: 12 }}>
          <input type="checkbox" checked={atPort} onChange={(e) => setAtPort(e.target.checked)} aria-label="At port" /> At port
        </label>
        <button type="button" className="secondary-button" onClick={run} disabled={!runName || busy}>
          {busy ? 'Querying…' : 'Run query'}
        </button>
        <button type="button" className="tb-btn tb-btn--muted" onClick={() => { setError(null); onResult(null); }}>
          Back to default
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
    </details>
  );
}

function QueryTable({ q }: { q: StatisticsQueryResponse }) {
  if (!q.rows.length) return <p className="dashboard-cell-missing">The query returned no rows.</p>;
  return (
    <div className="econ-table-wrap">
      <table className="econ-table">
        <thead>
          <tr>
            {q.levels.map((l) => <th key={`l-${l}`}>{l}</th>)}
            {q.columns.map((c) => <th key={`c-${c}`} className="num">{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {q.rows.map((r, i) => (
            <tr key={i}>
              {q.levels.map((l) => <td key={`l-${l}`}>{r.key[l] || '—'}</td>)}
              {q.columns.map((c) => <td key={`c-${c}`} className="num">{fmt(r.values[c] ?? null)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function StatisticsCard({ data, runName = null }: Props) {
  const [query, setQuery] = useState<StatisticsQueryResponse | null>(null);
  if (!data.rows.length || !data.columns.length) {
    return <p className="dashboard-cell-missing">No statistics for this run.</p>;
  }
  return (
    <div className="econ-card">
      <QueryPanel runName={runName} onResult={setQuery} />
      {query && (
        <div className="econ-body">
          <div className="econ-table-col">
            <p className="econ-section-label">
              n.statistics.{query.metric} — grouped by {query.groupby?.length ? query.groupby.join(', ') : 'component, carrier'}
              {query.ignoredParameters.length > 0 && ` (ignored for this metric: ${query.ignoredParameters.join(', ')})`}
            </p>
            <QueryTable q={query} />
          </div>
        </div>
      )}
      {!query && (<>
      <div className="econ-body">
        <div className="econ-table-col">
          <p className="econ-section-label">PyPSA statistics — by component &amp; carrier</p>
          <div className="econ-table-wrap">
            <table className="econ-table">
              <thead>
                <tr>
                  <th>Component</th>
                  <th>Carrier</th>
                  {data.columns.map((c) => <th key={c} className="num">{c}</th>)}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r, i) => (
                  <tr key={`${r.component}-${r.carrier}-${i}`}>
                    <td>{r.component}</td>
                    <td>
                      {r.carrier && <span className="carrier-dot" style={{ backgroundColor: carrierColor(r.carrier) }} />}
                      {r.carrier || '—'}
                    </td>
                    {data.columns.map((c) => <td key={c} className="num">{fmt(r.values[c] ?? null)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      </>)}
      <p className="econ-note">Computed by PyPSA's <code>n.statistics()</code> — capacity in MW, energy in MWh, expenditure/revenue in the run currency, capacity factor and curtailment dimensionless.</p>
    </div>
  );
}
