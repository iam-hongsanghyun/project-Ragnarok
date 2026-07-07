/**
 * Physical Risk — Adaptation sub-tab.
 *
 * Cost-benefit analysis of adaptation measures (retrofits, risk-transfer
 * layers) against the avoided-damage they buy — ported from climaterisk's
 * `AdaptationView.tsx` onto Ragnarok's own primitives (`chart-card`,
 * `econ-kpi-row`, `data-table`), submitting a `kind: 'cost-benefit'` run
 * through the shared `/session/{sid}/run` + poll endpoints (`RUN_POLLING`,
 * mirroring `PhysicalRiskView`'s `aliveRef` + `setTimeout` poll pattern).
 *
 * Submit/poll state and the last result must survive switching to another
 * sub-tab and back (this section unmounts on tab switch, unlike the shared
 * `run` owned by the view) — a module-level cache holds the in-flight/last
 * run per portfolio session and this component rehydrates from it on mount.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useToast } from '../../shared/components/Toast';
import { RUN_POLLING } from 'lib/constants';
import { PhysicalRiskSectionProps } from 'lib/physicalRisk/types';
import {
  CostBenefitResult,
  MeasureSpec,
  getPhysicalRiskRun,
  submitCostBenefitRun,
} from 'lib/physicalRisk/mapAdaptation';
import { Run } from 'lib/physicalRisk/types';

const DEFAULT_MEASURES: MeasureSpec[] = [
  { name: 'Retrofit', cost: 1_000_000, damageReduction: 0.3, riskTransfAttach: 0, riskTransfCover: 0 },
];

// Module-level cache keyed by session id: survives this section unmounting on
// sub-tab switch (the view itself does not own an adaptation run, unlike the
// physical `run` in Results). Rehydrated on mount, updated on every submit/poll.
const cache = new Map<string, { measures: MeasureSpec[]; run: Run | null }>();

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="econ-kpi">
      <div className="econ-kpi-label">{label}</div>
      <div className="econ-kpi-value">{value}</div>
    </div>
  );
}

export function AdaptationSection({ portfolio }: PhysicalRiskSectionProps) {
  const { showToast } = useToast();
  const sessionId = portfolio?.sessionId ?? null;
  const cached = sessionId ? cache.get(sessionId) : undefined;

  const [measures, setMeasures] = useState<MeasureSpec[]>(cached?.measures ?? DEFAULT_MEASURES);
  const [run, setRun] = useState<Run | null>(cached?.run ?? null);
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

  const persist = useCallback((next: Partial<{ measures: MeasureSpec[]; run: Run | null }>) => {
    if (!sessionId) return;
    const entry = cache.get(sessionId) ?? { measures: DEFAULT_MEASURES, run: null };
    cache.set(sessionId, { ...entry, ...next });
  }, [sessionId]);

  const updateMeasures = useCallback((updater: (ms: MeasureSpec[]) => MeasureSpec[]) => {
    setMeasures((prev) => {
      const next = updater(prev);
      persist({ measures: next });
      return next;
    });
  }, [persist]);

  const pollRun = useCallback((sid: string, runId: string) => {
    const poll = () => {
      void getPhysicalRiskRun(sid, runId)
        .then((r) => {
          if (!aliveRef.current) return;
          setRun(r);
          persist({ run: r });
          if (r.status === 'queued' || r.status === 'running') {
            pollTimer.current = window.setTimeout(poll, RUN_POLLING.runningDelayMs);
          } else if (r.status === 'error') {
            showToast(r.error ?? 'Cost-benefit run failed', 'error');
          }
        })
        .catch((err) => {
          if (!aliveRef.current) return;
          showToast(err instanceof Error ? err.message : 'Failed to poll the run', 'error');
          // Don't leave the run stuck on queued/running forever (which would
          // permanently disable the submit button) — mark it errored so the
          // user can retry.
          setRun((prev) => {
            const next: Run | null = prev ? { ...prev, status: 'error', error: 'Failed to poll the run' } : prev;
            if (next) persist({ run: next });
            return next;
          });
        });
    };
    pollTimer.current = window.setTimeout(poll, RUN_POLLING.initialDelayMs);
  }, [showToast, persist]);

  // Rehydrate when the session id changes (e.g. a fresh portfolio was seeded).
  // If the rehydrated run is still queued/running, resume polling it — otherwise
  // a run left in flight when this section unmounted is stuck on "Running…"
  // forever, since nothing else restarts the poll loop.
  useEffect(() => {
    if (!sessionId) return;
    const entry = cache.get(sessionId);
    setMeasures(entry?.measures ?? DEFAULT_MEASURES);
    setRun(entry?.run ?? null);
    if (entry?.run && (entry.run.status === 'queued' || entry.run.status === 'running')) {
      pollRun(sessionId, entry.run.id);
    }
  }, [sessionId, pollRun]);

  const runCostBenefit = useCallback(async () => {
    if (!portfolio) { showToast('Load the fleet on the Assets tab first', 'error'); return; }
    if (pollTimer.current) window.clearTimeout(pollTimer.current);
    setSubmitting(true);
    try {
      const queued = await submitCostBenefitRun(portfolio.sessionId, { measures });
      if (!aliveRef.current) return;
      setRun(queued);
      persist({ run: queued });
      pollRun(portfolio.sessionId, queued.id);
    } catch (err) {
      if (aliveRef.current) showToast(err instanceof Error ? err.message : 'Failed to submit the run', 'error');
    } finally {
      if (aliveRef.current) setSubmitting(false);
    }
  }, [portfolio, measures, pollRun, showToast, persist]);

  const update = (i: number, patch: Partial<MeasureSpec>) =>
    updateMeasures((ms) => ms.map((m, j) => (j === i ? { ...m, ...patch } : m)));
  const addMeasure = () =>
    updateMeasures((ms) => [...ms, { name: `Measure ${ms.length + 1}`, cost: 0, damageReduction: 0, riskTransfAttach: 0, riskTransfCover: 0 }]);
  const removeMeasure = (i: number) => updateMeasures((ms) => ms.filter((_, j) => j !== i));

  const currency = portfolio?.assets[0]?.currency ?? 'USD';
  const money = (v: number) => `${currency === 'USD' ? '$' : currency + ' '}${Math.round(v).toLocaleString()}`;

  const running = run?.status === 'queued' || run?.status === 'running';
  const cb = run?.status === 'done' && run.result ? (run.result as unknown as CostBenefitResult) : null;

  return (
    <div className="pane">
      <div className="pane-header">
        <div>
          <h2>Adaptation</h2>
          <p className="chart-card p">
            Define adaptation measures — retrofits, early-warning systems, risk-transfer layers — and
            compute the NPV of averted damage (benefit) against their cost.
          </p>
        </div>
      </div>

      <div className="chart-card" style={{ marginBottom: 16 }}>
        <p className="sg-setting-hint">
          Damage reduction scales the vulnerability curve; insurance attach/cover models a
          risk-transfer layer. Peril defaults to the portfolio's primary selected peril.
        </p>
        {measures.map((m, i) => (
          <div key={i} className="subcard" style={{ marginBottom: 10 }}>
            <div className="sg-setting-row">
              <label className="sg-setting-label">Name</label>
              <input value={m.name} onChange={(e) => update(i, { name: e.target.value })} />
            </div>
            <div className="sg-setting-row">
              <label className="sg-setting-label">Cost ({currency})</label>
              <input
                type="number"
                className="sg-number-input"
                min={0}
                value={m.cost}
                onChange={(e) => update(i, { cost: Number(e.target.value) || 0 })}
              />
            </div>
            <div className="sg-setting-row">
              <label className="sg-setting-label">Damage reduction (%)</label>
              <input
                type="number"
                className="sg-number-input"
                min={0}
                max={100}
                value={Math.round(m.damageReduction * 100)}
                onChange={(e) => update(i, { damageReduction: (Number(e.target.value) || 0) / 100 })}
              />
            </div>
            <div className="sg-setting-row">
              <label className="sg-setting-label">Insurance attach / cover</label>
              <input
                type="number"
                className="sg-number-input"
                min={0}
                placeholder="attach"
                value={m.riskTransfAttach ?? 0}
                onChange={(e) => update(i, { riskTransfAttach: Number(e.target.value) || 0 })}
              />
              <input
                type="number"
                className="sg-number-input"
                min={0}
                placeholder="cover"
                value={m.riskTransfCover ?? 0}
                onChange={(e) => update(i, { riskTransfCover: Number(e.target.value) || 0 })}
              />
            </div>
            {measures.length > 1 && (
              <div className="sg-setting-row">
                <button className="tb-btn tb-btn--danger" onClick={() => removeMeasure(i)}>Remove</button>
              </div>
            )}
          </div>
        ))}
        <div className="sg-setting-row">
          <button className="tb-btn" onClick={addMeasure}>Add measure</button>
          <button
            className="tb-btn tb-btn--primary"
            onClick={() => void runCostBenefit()}
            disabled={submitting || running || !portfolio || portfolio.assets.length === 0}
          >
            {running ? 'Running…' : submitting ? 'Submitting…' : 'Run cost-benefit'}
          </button>
          {!portfolio && <p className="sg-setting-hint">Load the fleet on the Assets tab first.</p>}
        </div>
      </div>

      {run?.status === 'error' && <p className="sg-error-text">{run.error ?? 'Run failed'}</p>}

      {cb && cb.status === 'ok' && (
        <div className="chart-card">
          <div className="chart-card-header">
            <div>
              <h3>Result &middot; {cb.peril.replace(/_/g, ' ')}</h3>
              <p>
                Horizon {cb.futureYear} &middot; discount rate {(cb.discountRate * 100).toFixed(1)}%
              </p>
            </div>
          </div>
          <div className="econ-kpi-row">
            <Kpi label="Total climate risk (NPV, unaverted)" value={money(cb.totClimateRisk)} />
            <Kpi label="Discount rate" value={`${(cb.discountRate * 100).toFixed(1)}%`} />
            <Kpi label="Horizon year" value={String(cb.futureYear ?? '—')} />
          </div>
          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Measure</th>
                  <th>Cost</th>
                  <th>Benefit (NPV averted)</th>
                  <th>Benefit / cost</th>
                </tr>
              </thead>
              <tbody>
                {cb.measures.map((m) => {
                  const bc = m.benefitCostRatio;
                  const effective = bc != null && bc >= 1;
                  return (
                    <tr key={m.name}>
                      <td>{m.name}</td>
                      <td>{money(m.cost)}</td>
                      <td>{money(m.benefit)}</td>
                      <td style={{ color: bc == null ? undefined : effective ? 'var(--brand)' : 'var(--muted)' }}>
                        {bc == null ? '—' : `${bc.toFixed(2)}${effective ? ' (cost-effective)' : ''}`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {cb.detail && <p className="sg-setting-hint" style={{ marginTop: 8 }}>{cb.detail}</p>}
        </div>
      )}

      {!run && (
        <div className="analytics-empty">
          <h3>No run yet</h3>
          <p>Define measures above, then run the cost-benefit analysis.</p>
        </div>
      )}
    </div>
  );
}
