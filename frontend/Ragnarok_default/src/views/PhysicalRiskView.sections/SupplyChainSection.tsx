/**
 * Physical Risk — Supply chain sub-tab.
 *
 * Ported from the standalone climaterisk app's Supply-chain tab: propagates
 * the portfolio's direct climate damage through a Multi-Regional
 * Input-Output table (Leontief model) to estimate indirect losses rippling
 * across economic sectors. Submits a 'supply-chain' analysis run, polls it
 * to completion (queued -> running -> done), and renders KPIs + a by-sector
 * table + bar chart. STUB engine today (see `detail` provenance note) —
 * shape is faithful to the eventual CLIMADA-worker result.
 *
 * Persistence: last result survives sub-tab switches via a module-level
 * cache (rehydrated on mount); `aliveRef` guards every async `setState`
 * against a mid-flight unmount or poll after navigating away.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useToast } from '../../shared/components/Toast';
import { RiskBarChart } from '../../features/physicalRisk/RiskBarChart';
import { RUN_POLLING } from 'lib/constants';
import { PhysicalRiskSectionProps } from 'lib/physicalRisk/types';
import { AnalysisRun, SupplyChainResult, formatMoney, pollAnalysisRun, submitAnalysisRun } from 'lib/physicalRisk/financeViews';

interface SectionCache {
  sessionId: string;
  run: AnalysisRun<SupplyChainResult> | null;
}
let cache: SectionCache | null = null;

export function SupplyChainSection({ portfolio }: PhysicalRiskSectionProps) {
  const { showToast } = useToast();
  const sessionId = portfolio?.sessionId ?? null;

  const [run, setRun] = useState<AnalysisRun<SupplyChainResult> | null>(
    cache && sessionId && cache.sessionId === sessionId ? cache.run : null,
  );
  const [submitting, setSubmitting] = useState(false);
  const pollTimer = useRef<number | null>(null);
  const aliveRef = useRef(true);

  // Reset (not just set-once) on every mount so React StrictMode's dev
  // double-mount, or a real remount, doesn't leave this permanently `false`
  // from the first mount's cleanup — which would silently suppress every
  // async setState/toast below.
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      if (pollTimer.current) window.clearTimeout(pollTimer.current);
    };
  }, []);

  const persist = useCallback((next: AnalysisRun<SupplyChainResult> | null) => {
    if (!sessionId) return;
    cache = { sessionId, run: next };
  }, [sessionId]);

  const poll = useCallback((sid: string, runId: string) => {
    const step = () => {
      void pollAnalysisRun<SupplyChainResult>(sid, runId)
        .then((r) => {
          if (!aliveRef.current) return;
          setRun(r);
          persist(r);
          if (r.status === 'queued' || r.status === 'running') {
            pollTimer.current = window.setTimeout(step, RUN_POLLING.runningDelayMs);
          } else if (r.status === 'error') {
            showToast(r.error ?? 'Supply-chain run failed', 'error');
          }
        })
        .catch((err) => {
          if (!aliveRef.current) return;
          showToast(err instanceof Error ? err.message : 'Failed to poll the run', 'error');
          // Don't leave the run stuck on queued/running forever (which would
          // permanently disable the submit button) — mark it errored so the
          // user can retry.
          setRun((prev) => {
            const next: AnalysisRun<SupplyChainResult> | null = prev
              ? { ...prev, status: 'error', error: 'Failed to poll the run' }
              : prev;
            if (next) persist(next);
            return next;
          });
        });
    };
    pollTimer.current = window.setTimeout(step, RUN_POLLING.initialDelayMs);
  }, [showToast, persist]);

  // Rehydrate when the session id changes (e.g. a fresh portfolio was seeded).
  // If the rehydrated run is still queued/running, resume polling it — otherwise
  // a run left in flight when this section unmounted is stuck on "Running…"
  // forever, since nothing else restarts the poll loop.
  useEffect(() => {
    if (!sessionId) { setRun(null); return; }
    if (!cache || cache.sessionId !== sessionId) {
      cache = { sessionId, run: null };
      setRun(null);
      return;
    }
    setRun(cache.run);
    if (cache.run && (cache.run.status === 'queued' || cache.run.status === 'running')) {
      poll(sessionId, cache.run.id);
    }
  }, [sessionId, poll]);

  const doRun = useCallback(async () => {
    if (!portfolio) { showToast('Load the fleet on the Assets tab first', 'error'); return; }
    if (pollTimer.current) window.clearTimeout(pollTimer.current);
    setSubmitting(true);
    try {
      const queued = await submitAnalysisRun<SupplyChainResult>(portfolio.sessionId, { kind: 'supply-chain' });
      if (!aliveRef.current) return;
      setRun(queued);
      persist(queued);
      poll(portfolio.sessionId, queued.id);
    } catch (err) {
      if (aliveRef.current) showToast(err instanceof Error ? err.message : 'Failed to submit the run', 'error');
    } finally {
      if (aliveRef.current) setSubmitting(false);
    }
  }, [portfolio, poll, showToast, persist]);

  const running = run?.status === 'queued' || run?.status === 'running';
  const out = run?.status === 'done' ? run.result ?? null : null;
  const currencySymbol = out && out.currency !== 'USD' ? `${out.currency} ` : '$';
  const money = (v: number) => formatMoney(v, currencySymbol);

  return (
    <div className="pane">
      <div className="pane-header">
        <div>
          <h2>Supply chain</h2>
          <p className="chart-card p">
            Indirect/supply-chain loss propagation from directly-damaged assets to dependent
            facilities, via a Multi-Regional Input-Output (MRIOT) table.
          </p>
        </div>
        <button
          className="tb-btn tb-btn--primary"
          onClick={() => void doRun()}
          disabled={submitting || running || !portfolio || portfolio.assets.length === 0}
        >
          {running ? 'Running…' : submitting ? 'Submitting…' : 'Run supply-chain'}
        </button>
      </div>

      {!portfolio && (
        <div className="analytics-empty">
          <h3>No portfolio loaded</h3>
          <p>Load the fleet on the Assets tab first.</p>
        </div>
      )}

      {run?.status === 'error' && <p className="sg-error-text">{run.error ?? 'Run failed'}</p>}

      {out && (
        <div className="chart-card chart-card-wide">
          <div className="chart-card-header">
            <div>
              <h3>Indirect impact</h3>
              <p>{out.mriot}</p>
            </div>
          </div>
          <div className="econ-kpi-row">
            <div className="econ-kpi">
              <div className="econ-kpi-label">Direct AAI/yr</div>
              <div className="econ-kpi-value">{money(out.totalDirect)}</div>
            </div>
            <div className="econ-kpi">
              <div className="econ-kpi-label">Indirect (rippled)</div>
              <div className="econ-kpi-value">{money(out.totalIndirect)}</div>
            </div>
            <div className="econ-kpi">
              <div className="econ-kpi-label">Amplification</div>
              <div className="econ-kpi-value">{out.amplification != null ? `${out.amplification.toFixed(2)}x` : '—'}</div>
            </div>
          </div>
          {out.bySector.length > 0 && (
            <div className="econ-body">
              <div className="econ-table-col" style={{ flex: '1 1 320px' }}>
                <p className="econ-section-label">Indirect impact by sector</p>
                <RiskBarChart data={out.bySector.map((s) => ({ name: s.sector, value: s.indirect }))} formatValue={money} />
              </div>
              <div className="econ-table-col" style={{ flex: '1 1 320px' }}>
                <p className="econ-section-label">By sector</p>
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Sector</th>
                        <th>Indirect</th>
                        <th>Share of total indirect</th>
                      </tr>
                    </thead>
                    <tbody>
                      {out.bySector.map((s) => (
                        <tr key={s.sector}>
                          <td>{s.sector}</td>
                          <td>{money(s.indirect)}</td>
                          <td>{out.totalIndirect > 0 ? `${((s.indirect / out.totalIndirect) * 100).toFixed(1)}%` : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
          {out.detail && <p className="sg-setting-hint">{out.detail}</p>}
        </div>
      )}

      {!run && portfolio && (
        <div className="analytics-empty">
          <h3>No run yet</h3>
          <p>Click "Run supply-chain" to propagate direct damage through the I/O table.</p>
        </div>
      )}
    </div>
  );
}
