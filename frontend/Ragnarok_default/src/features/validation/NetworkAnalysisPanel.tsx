/**
 * Network analysis (Analytics -> Validation): the topology of the working model without a solve.
 *
 * Two read-only calls on the session model:
 *  - `POST /api/analysis/network`: synchronous sub-networks ("islands") with their slack bus, plus the PTDF / BODF
 *    factors, cycle matrix, adjacency and incidence matrices on request. More than one sub-network is flagged, since
 *    each island needs its own slack and its own supply.
 *  - `POST /api/analysis/consistency`: PyPSA's `n.consistency_check` findings (errors and warnings).
 */
import React, { useState } from 'react';
import {
  ANALYSIS_PARTS,
  postConsistency,
  postNetworkAnalysis,
  type AnalysisPart,
  type ConsistencyReport,
  type CycleBasisMethod,
  type MatrixPayload,
  type NetworkAnalysis,
} from 'lib/api/networkOps';

export interface NetworkAnalysisPanelProps {
  /** Push the working model to the session so the analysis reads what is on screen. */
  onSessionSync?: () => Promise<void>;
}

const PART_LABEL: Record<AnalysisPart, string> = {
  subnetworks: 'Sub-networks',
  ptdf: 'PTDF',
  bodf: 'BODF',
  cycles: 'Cycle matrix',
  adjacency: 'Adjacency',
  incidence: 'Incidence',
};
const DEFAULT_PARTS: AnalysisPart[] = ['subnetworks', 'cycles'];
/** Matrices are shown up to this many rows and columns; the rest is a count. */
const MATRIX_SHOW = 12;

function MatrixView({ title, matrix }: { title: string; matrix: MatrixPayload | undefined }) {
  if (!matrix) return null;
  if (matrix.omitted || matrix.error) {
    return <p className="sg-setting-hint">{title}: {matrix.omitted ?? matrix.error}</p>;
  }
  const rows = matrix.rows ?? [];
  const cols = matrix.columns ?? [];
  const data = matrix.data ?? [];
  if (rows.length === 0 || data.length === 0) return <p className="sg-setting-hint">{title}: empty (no loops or branches).</p>;
  const shownCols = Math.min(MATRIX_SHOW, data[0]?.length ?? 0);
  return (
    <details className="net-analysis-matrix">
      <summary>{title} ({rows.length} x {data[0]?.length ?? 0})</summary>
      <div className="net-analysis-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th />
              {Array.from({ length: shownCols }, (_, j) => <th key={j}>{cols[j] ?? j + 1}</th>)}
            </tr>
          </thead>
          <tbody>
            {data.slice(0, MATRIX_SHOW).map((row, i) => (
              <tr key={i}>
                <td>{rows[i]}</td>
                {row.slice(0, shownCols).map((v, j) => <td key={j}>{v}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(rows.length > MATRIX_SHOW || (data[0]?.length ?? 0) > MATRIX_SHOW) && (
        <p className="sg-setting-hint">First {MATRIX_SHOW} rows and columns shown.</p>
      )}
    </details>
  );
}

export function NetworkAnalysisPanel({ onSessionSync }: NetworkAnalysisPanelProps) {
  const [parts, setParts] = useState<AnalysisPart[]>(DEFAULT_PARTS);
  const [method, setMethod] = useState<CycleBasisMethod>('bfs-refined');
  const [strictAll, setStrictAll] = useState(false);
  const [checkDtypes, setCheckDtypes] = useState(false);
  const [busy, setBusy] = useState<'analysis' | 'consistency' | null>(null);
  const [analysis, setAnalysis] = useState<NetworkAnalysis | null>(null);
  const [consistency, setConsistency] = useState<ConsistencyReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const toggle = (p: AnalysisPart) => setParts((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]));

  const run = async (what: 'analysis' | 'consistency') => {
    setBusy(what);
    setError(null);
    try {
      if (onSessionSync) await onSessionSync();
      if (what === 'analysis') {
        // The sub-network table is always requested: it is the summary every other part hangs off.
        setAnalysis(await postNetworkAnalysis(Array.from(new Set<AnalysisPart>(['subnetworks', ...parts])), method));
      } else {
        setConsistency(await postConsistency(strictAll, checkDtypes));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Analysis failed.');
    } finally {
      setBusy(null);
    }
  };

  const subs = analysis?.subNetworks ?? [];
  const loops = analysis?.cycleMatrix?.columns?.length;
  // Sub-networks of different carriers (AC, H2, gas...) are joined by Links, so only same-carrier splits are islands.
  const perCarrier = new Map<string, number>();
  subs.forEach((s) => perCarrier.set(s.carrier, (perCarrier.get(s.carrier) ?? 0) + 1));
  const islanded = Array.from(perCarrier.entries()).filter(([, n]) => n > 1);

  return (
    <div className="validation-report net-analysis" data-tour="network-analysis" role="region" aria-label="Network analysis">
      <div className="validation-report-header">
        <div>
          <p className="eyebrow">Network analysis</p>
          <h2>Topology and consistency</h2>
        </div>
      </div>
      <p className="status-text">
        Reads the working model without solving: which buses form separate synchronous islands, and what PyPSA's consistency check reports.
      </p>

      <div className="validation-section">
        <p className="validation-section-title">Topology</p>
        <div className="net-analysis-parts">
          {ANALYSIS_PARTS.filter((p) => p !== 'subnetworks').map((p) => (
            <label key={p} className="modal-check-row">
              <input type="checkbox" checked={parts.includes(p)} onChange={() => toggle(p)} />
              <span>{PART_LABEL[p]}</span>
            </label>
          ))}
          <label className="net-analysis-method">
            <span className="sg-setting-label">Cycle basis</span>
            <select className="forge-adjust-select" value={method} onChange={(e) => setMethod(e.target.value as CycleBasisMethod)} aria-label="Cycle basis method">
              <option value="bfs-refined">bfs-refined</option>
              <option value="paton">paton</option>
            </select>
          </label>
        </div>
        <div className="master-dialog-row">
          <button type="button" className="tb-btn" disabled={busy !== null} onClick={() => void run('analysis')}>
            {busy === 'analysis' ? 'Analysing' : 'Analyse topology'}
          </button>
        </div>

        {analysis && (
          <>
            <div className="validation-summary-grid">
              <div className="metric-card"><span>Sub-networks</span><strong>{subs.length}</strong></div>
              <div className="metric-card"><span>Buses</span><strong>{subs.reduce((n, s) => n + s.buses.length, 0)}</strong></div>
              <div className="metric-card"><span>Branches</span><strong>{subs.reduce((n, s) => n + s.branches.length, 0)}</strong></div>
              {loops !== undefined && <div className="metric-card"><span>Independent loops</span><strong>{loops}</strong></div>}
            </div>
            {islanded.length > 0 && (
              <div className="validation-section validation-section--warn">
                {islanded.map(([carrier, n]) => `${carrier}: ${n} separate islands`).join('; ')}. Each island needs its own supply;
                Lines and Transformers do not connect them (only a Link could).
              </div>
            )}
            {islanded.length === 0 && perCarrier.size > 1 && (
              <p className="status-text">
                One sub-network per carrier ({Array.from(perCarrier.keys()).join(', ')}); sub-networks of different carriers are connected by Links, not by Lines.
              </p>
            )}
            <table className="data-table">
              <thead>
                <tr><th>Sub-network</th><th>Carrier</th><th>Buses</th><th>Branches</th><th>Slack bus</th><th>Slack generator</th></tr>
              </thead>
              <tbody>
                {subs.map((s) => (
                  <tr key={s.name}>
                    <td>{s.name}</td><td>{s.carrier}</td><td>{s.buses.length}</td><td>{s.branches.length}</td>
                    <td>{s.slackBus || 'none'}</td><td>{s.slackGenerator || 'none'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {subs.map((s) => (
              <div key={s.name}>
                <MatrixView title={`PTDF, sub-network ${s.name}`} matrix={s.ptdf} />
                <MatrixView title={`BODF, sub-network ${s.name}`} matrix={s.bodf} />
              </div>
            ))}
            <MatrixView title="Cycle matrix" matrix={analysis.cycleMatrix} />
            <MatrixView title="Adjacency" matrix={analysis.adjacency} />
            <MatrixView title="Incidence" matrix={analysis.incidence} />
          </>
        )}
      </div>

      <div className="validation-section">
        <p className="validation-section-title">Consistency check</p>
        <label className="modal-check-row">
          <input type="checkbox" checked={strictAll} onChange={(e) => setStrictAll(e.target.checked)} />
          <span>Strict: every finding is an error</span>
        </label>
        <label className="modal-check-row">
          <input type="checkbox" checked={checkDtypes} onChange={(e) => setCheckDtypes(e.target.checked)} />
          <span>Also check attribute dtypes</span>
        </label>
        <div className="master-dialog-row">
          <button type="button" className="tb-btn" disabled={busy !== null} onClick={() => void run('consistency')}>
            {busy === 'consistency' ? 'Checking' : 'Run consistency check'}
          </button>
        </div>
        {consistency && (
          <>
            <p className={consistency.valid ? 'text-ok' : 'text-error'}>
              {consistency.valid ? 'No errors' : `${consistency.errors.length} error${consistency.errors.length === 1 ? '' : 's'}`}
              {`, ${consistency.warnings.length} warning${consistency.warnings.length === 1 ? '' : 's'}`}
            </p>
            {consistency.errors.length > 0 && (
              <div className="validation-section validation-section--error">
                <p className="validation-section-title">Errors</p>
                <ul className="validation-list">{consistency.errors.map((m, i) => <li key={i}>{m}</li>)}</ul>
              </div>
            )}
            {consistency.warnings.length > 0 && (
              <div className="validation-section validation-section--warn">
                <p className="validation-section-title">Warnings</p>
                <ul className="validation-list">{consistency.warnings.map((m, i) => <li key={i}>{m}</li>)}</ul>
              </div>
            )}
          </>
        )}
      </div>
      {error && <p className="sg-setting-hint" role="alert">{error}</p>}
    </div>
  );
}
