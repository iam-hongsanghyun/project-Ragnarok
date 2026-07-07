/**
 * Physical Risk — Forecast sub-tab.
 *
 * Ported from the standalone climaterisk app's operational-forecast tab:
 * pulls an ensemble tropical-cyclone-track forecast and computes the
 * near-term expected impact on the portfolio (multi-horizon impact
 * trajectory, not just a single point estimate). Submits a 'forecast'
 * analysis run, polls it to completion, and renders KPIs + the near-term
 * series as a bar chart + a per-asset table. STUB engine today (see `detail`
 * provenance note).
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
import { AnalysisRun, ForecastResult, formatMoney, pollAnalysisRun, submitAnalysisRun } from 'lib/physicalRisk/financeViews';

interface SectionCache {
  sessionId: string;
  run: AnalysisRun<ForecastResult> | null;
}
let cache: SectionCache | null = null;

export function ForecastSection({ portfolio }: PhysicalRiskSectionProps) {
  const { showToast } = useToast();
  const sessionId = portfolio?.sessionId ?? null;

  const [run, setRun] = useState<AnalysisRun<ForecastResult> | null>(
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

  const persist = useCallback((next: AnalysisRun<ForecastResult> | null) => {
    if (!sessionId) return;
    cache = { sessionId, run: next };
  }, [sessionId]);

  const poll = useCallback((sid: string, runId: string) => {
    const step = () => {
      void pollAnalysisRun<ForecastResult>(sid, runId)
        .then((r) => {
          if (!aliveRef.current) return;
          setRun(r);
          persist(r);
          if (r.status === 'queued' || r.status === 'running') {
            pollTimer.current = window.setTimeout(step, RUN_POLLING.runningDelayMs);
          } else if (r.status === 'error') {
            showToast(r.error ?? 'Forecast run failed', 'error');
          }
        })
        .catch((err) => {
          if (!aliveRef.current) return;
          showToast(err instanceof Error ? err.message : 'Failed to poll the run', 'error');
          // Don't leave the run stuck on queued/running forever (which would
          // permanently disable the submit button) — mark it errored so the
          // user can retry.
          setRun((prev) => {
            const next: AnalysisRun<ForecastResult> | null = prev
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
      const queued = await submitAnalysisRun<ForecastResult>(portfolio.sessionId, { kind: 'forecast' });
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
          <h2>Forecast</h2>
          <p className="chart-card p">
            Multi-horizon impact forecast — near-term expected impact by season, so risk
            trajectories, not just point estimates, are visible.
          </p>
        </div>
        <button
          className="tb-btn tb-btn--primary"
          onClick={() => void doRun()}
          disabled={submitting || running || !portfolio || portfolio.assets.length === 0}
        >
          {running ? 'Running…' : submitting ? 'Submitting…' : 'Run forecast'}
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
              <h3>Forecast impact — {out.peril.replace(/_/g, ' ')}</h3>
              <p>{out.nTracks} ensemble track{out.nTracks === 1 ? '' : 's'}</p>
            </div>
          </div>
          {out.nTracks === 0 ? (
            <p className="sg-setting-hint">{out.detail ?? 'No active tracks.'}</p>
          ) : (
            <>
              <div className="econ-kpi-row">
                <div className="econ-kpi">
                  <div className="econ-kpi-label">Peril</div>
                  <div className="econ-kpi-value">{out.peril.replace(/_/g, ' ')}</div>
                </div>
                <div className="econ-kpi">
                  <div className="econ-kpi-label">Ensemble tracks</div>
                  <div className="econ-kpi-value">{out.nTracks}</div>
                </div>
                <div className="econ-kpi">
                  <div className="econ-kpi-label">Ensemble-mean impact</div>
                  <div className="econ-kpi-value">{money(out.totalImpact)}</div>
                </div>
              </div>
              <div className="econ-body">
                {out.series.length > 0 && (
                  <div className="econ-table-col" style={{ flex: '1 1 320px' }}>
                    <p className="econ-section-label">Near-term expected impact</p>
                    <RiskBarChart data={out.series.map((p) => ({ name: p.label, value: p.value }))} formatValue={money} />
                  </div>
                )}
                {out.perAsset.length > 0 && (
                  <div className="econ-table-col" style={{ flex: '1 1 320px' }}>
                    <p className="econ-section-label">Per-asset expected impact</p>
                    <div className="table-wrap">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Asset id</th>
                            <th>EAI</th>
                          </tr>
                        </thead>
                        <tbody>
                          {out.perAsset.map((row) => (
                            <tr key={row.assetId}>
                              <td>{row.assetId}</td>
                              <td>{money(row.eai)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
              {out.detail && <p className="sg-setting-hint">{out.detail}</p>}
            </>
          )}
        </div>
      )}

      {!run && portfolio && (
        <div className="analytics-empty">
          <h3>No run yet</h3>
          <p>Click "Run forecast" to compute the near-term expected impact.</p>
        </div>
      )}
    </div>
  );
}
