/**
 * Physical Risk — Finance sub-tab.
 *
 * Two panels, ported from the standalone climaterisk app's Finance tab (real
 * math on both — `backend/app/physical_risk/{transition,finance}.py`):
 *
 *  (a) Transition risk — "Run transition" against the portfolio's stored NGFS
 *      scenario, rendering the NPV KPI, an annual-carbon-cost-by-year chart
 *      and a per-asset table. Synchronous (no queued/poll lifecycle).
 *  (b) Climate risk premium (finance) — needs a DONE physical run (the `run`
 *      prop, owned by `PhysicalRiskView`); computes the counterfactual CRP
 *      (baseline vs climate-stressed NPV/DSCR/rating/spread) for the
 *      portfolio's financial profile, edited here.
 *
 * `run` in `PhysicalRiskSectionProps` is the latest run of ANY kind routed
 * through the view's poller; finance only accepts a done run of kind
 * 'physical' (enforced server-side), so a supply-chain/forecast run in
 * progress just shows the same "run physical risk first" hint.
 *
 * Persistence: last transition result + finance inputs/result survive
 * sub-tab switches via a module-level cache (rehydrated on mount), same as
 * every other in-memory-only Physical Risk sub-tab; an `aliveRef` guards
 * every async `setState` against a mid-flight unmount.
 *
 * Methodology comparison: `finance.methodsCompared` is always computed
 * server-side for every methodology selected on the portfolio's financial
 * profile (`financialProfile.ratingMethods` — `finance.py::selected_method_ids`).
 * The methodology multi-select below patches that same profile field (through
 * the section's existing debounced `patchProfile`/`saveFinancialProfile`
 * path), so picking methodologies re-computes them server-side on the next
 * "Compute climate risk premium" click; the table additionally filters the
 * already-fetched result client-side so narrowing the selection updates the
 * display immediately without waiting for a re-run.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useToast } from '../../shared/components/Toast';
import { TransitionCostChart } from '../../features/physicalRisk/TransitionCostChart';
import { SearchableMultiSelect } from '../../shared/components/SearchableMultiSelect';
import { PhysicalRiskSectionProps } from 'lib/physicalRisk/types';
import { FullLibraries, FullPortfolio, getFullLibraries } from 'lib/physicalRisk/configViews';
import {
  FinanceResult,
  TransitionResult,
  formatMoney,
  getFullPortfolio,
  runFinance,
  runTransition,
  saveFinancialProfile,
} from 'lib/physicalRisk/financeViews';

// ── module-level cache: last inputs/results per session, so switching to ────
// another Physical Risk sub-tab and back doesn't lose a just-computed result ─
interface SectionCache {
  sessionId: string;
  transition: TransitionResult | null;
  finance: FinanceResult | null;
}
let cache: SectionCache | null = null;

function ratingColor(rating: string): string {
  if (['AAA', 'AA', 'A', 'BBB'].includes(rating)) return 'var(--brand)';
  if (['BB', 'B'].includes(rating)) return 'var(--warn, #b58900)';
  return 'var(--danger, #b91c1c)';
}

export function FinanceSection({ portfolio, onPortfolioChange, run }: PhysicalRiskSectionProps) {
  const { showToast } = useToast();
  const aliveRef = useRef(true);
  useEffect(() => {
    aliveRef.current = true;
    return () => { aliveRef.current = false; };
  }, []);

  const [libraries, setLibraries] = useState<FullLibraries | null>(null);
  useEffect(() => {
    void getFullLibraries()
      .then((libs) => { if (aliveRef.current) setLibraries(libs); })
      .catch((err) => { showToast(err instanceof Error ? err.message : 'Failed to load libraries', 'error'); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sessionId = portfolio?.sessionId ?? null;

  const [fullPortfolio, setFullPortfolio] = useState<FullPortfolio | null>(null);
  const [transition, setTransition] = useState<TransitionResult | null>(
    cache && sessionId && cache.sessionId === sessionId ? cache.transition : null,
  );
  const [transitionBusy, setTransitionBusy] = useState(false);
  const [transitionErr, setTransitionErr] = useState<string | null>(null);

  const [finance, setFinance] = useState<FinanceResult | null>(
    cache && sessionId && cache.sessionId === sessionId ? cache.finance : null,
  );
  const [financeBusy, setFinanceBusy] = useState(false);
  const [financeErr, setFinanceErr] = useState<string | null>(null);

  // Rehydrate the full portfolio (scenario.financialProfile) whenever the
  // session id changes; drop any cached results from a different session.
  useEffect(() => {
    if (!sessionId) { setFullPortfolio(null); return; }
    if (!cache || cache.sessionId !== sessionId) {
      cache = { sessionId, transition: null, finance: null };
      setTransition(null);
      setFinance(null);
    }
    void getFullPortfolio(sessionId)
      .then((p) => { if (aliveRef.current) setFullPortfolio(p); })
      .catch(() => { /* the plain Portfolio prop still lets the rest of the panel render */ });
  }, [sessionId]);

  const persist = useCallback((patch: Partial<SectionCache>) => {
    if (!sessionId) return;
    cache = { sessionId, transition: null, finance: null, ...cache, ...patch };
  }, [sessionId]);

  const doRunTransition = useCallback(async () => {
    if (!sessionId) { showToast('Load the fleet on the Assets tab first', 'error'); return; }
    setTransitionBusy(true);
    setTransitionErr(null);
    try {
      const result = await runTransition(sessionId);
      if (!aliveRef.current) return;
      setTransition(result);
      persist({ transition: result });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to compute transition risk';
      if (aliveRef.current) setTransitionErr(message);
    } finally {
      if (aliveRef.current) setTransitionBusy(false);
    }
  }, [sessionId, showToast, persist]);

  const physicalRunDone = run?.status === 'done' && run.result != null;
  const lastTransitionCost = transition && transition.totalCostByYear.length > 0
    ? transition.totalCostByYear[transition.totalCostByYear.length - 1]
    : 0;

  const doRunFinance = useCallback(async () => {
    if (!sessionId || !run || !physicalRunDone) return;
    setFinanceBusy(true);
    setFinanceErr(null);
    try {
      const result = await runFinance(sessionId, run.id, lastTransitionCost);
      if (!aliveRef.current) return;
      setFinance(result);
      persist({ finance: result });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to compute the climate risk premium';
      if (aliveRef.current) setFinanceErr(message);
    } finally {
      if (aliveRef.current) setFinanceBusy(false);
    }
  }, [sessionId, run, physicalRunDone, lastTransitionCost, persist]);

  // Full-portfolio PUT debounce for financial-profile edits — mirrors
  // AssetsSection's latestRef pattern exactly: synchronously propagate the
  // updated portfolio via `onPortfolioChange` (so the view's shared state,
  // and any later full-document PUT from Assets/Scenarios, never wipes this
  // edit) AND keep the debounced save so a flood of edits coalesces into one
  // trailing PUT.
  const latestRef = useRef<FullPortfolio | null>(fullPortfolio);
  useEffect(() => { latestRef.current = fullPortfolio; }, [fullPortfolio]);
  const saveTimer = useRef<number | null>(null);

  const doSaveProfile = useCallback((patch: Record<string, unknown>) => {
    const p = latestRef.current;
    if (!p) return;
    void saveFinancialProfile(p, patch).catch((err) => {
      showToast(err instanceof Error ? err.message : 'Failed to save the financial profile', 'error');
    });
  }, [showToast]);

  // Flush any pending save when the section unmounts so an in-flight edit is not lost.
  const pendingPatchRef = useRef<Record<string, unknown> | null>(null);
  useEffect(() => () => {
    if (saveTimer.current !== null) {
      window.clearTimeout(saveTimer.current);
      saveTimer.current = null;
      if (pendingPatchRef.current) doSaveProfile(pendingPatchRef.current);
    }
  }, [doSaveProfile]);

  const patchProfile = useCallback((patch: Record<string, unknown>) => {
    const base = latestRef.current;
    if (!base) return;
    const updated: FullPortfolio = {
      ...base,
      scenario: { ...base.scenario, financialProfile: { ...base.scenario.financialProfile, ...patch } },
    };
    latestRef.current = updated;
    setFullPortfolio(updated);
    onPortfolioChange(updated);
    pendingPatchRef.current = { ...pendingPatchRef.current, ...patch };
    if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      saveTimer.current = null;
      const pending = pendingPatchRef.current;
      pendingPatchRef.current = null;
      if (pending) doSaveProfile(pending);
    }, 500);
  }, [onPortfolioChange, doSaveProfile]);

  const profile = fullPortfolio?.scenario.financialProfile ?? {};
  const currency = portfolio?.assets[0]?.currency ?? 'USD';
  const currencySymbol = currency === 'USD' ? '$' : `${currency} `;
  const money = (v: number) => formatMoney(v, currencySymbol);
  const isPower = profile.financialModel === 'power_gen';
  const genReady = !!profile.capacityMw && !!profile.powerPrice && (!!profile.capacityFactor || !!profile.plantFuel);
  const financeReady = physicalRunDone && !!profile.capex && (isPower ? genReady : !!profile.annualEbitda);

  const numField = (label: string, key: string, step: string) => (
    <div className="sg-setting-row" key={key}>
      <label className="sg-setting-label">{label}</label>
      <input
        type="number"
        step={step}
        className="sg-number-input"
        value={(profile as Record<string, unknown>)[key] as number | undefined ?? ''}
        onChange={(e) => patchProfile({ [key]: e.target.value === '' ? null : Number(e.target.value) })}
      />
    </div>
  );

  // The full DSCR-to-rating methodology catalog (backend `finance_reference.json::rating_methods`,
  // served at `financeChannels.reference.ratingMethods` — no client-side catalog). The multi-select
  // patches `financialProfile.ratingMethods` (drives `finance.methodsCompared` server-side, per
  // `finance.py::selected_method_ids`); the table also filters the already-fetched result
  // client-side so narrowing the selection updates the display before the next re-run.
  const ratingMethodOptions = useMemo(() => {
    const catalog = libraries?.financeChannels.reference.ratingMethods ?? {};
    return Object.entries(catalog).map(([id, m]) => ({ value: id, label: m.label }));
  }, [libraries]);
  const selectedMethodIds = useMemo(() => profile.ratingMethods ?? [], [profile.ratingMethods]);
  const visibleMethods = useMemo(() => {
    if (!finance) return [];
    if (selectedMethodIds.length === 0) return finance.methodsCompared;
    const wanted = new Set(selectedMethodIds);
    const filtered = finance.methodsCompared.filter((m) => wanted.has(m.method));
    return filtered.length > 0 ? filtered : finance.methodsCompared;
  }, [finance, selectedMethodIds]);

  return (
    <div className="pane">
      <div className="pane-header">
        <div>
          <h2>Finance</h2>
          <p className="chart-card p">
            Transition (carbon-cost) risk and the climate-risk premium — translating physical and
            transition risk into project-economics and credit-rating impact.
          </p>
        </div>
      </div>

      {!portfolio && (
        <div className="analytics-empty">
          <h3>No portfolio loaded</h3>
          <p>Load the fleet on the Assets tab first.</p>
        </div>
      )}

      {portfolio && (
        <div className="analytics-grid">
          <div className="chart-card chart-card-wide">
            <div className="chart-card-header">
              <div>
                <h3>Transition risk</h3>
                <p>NGFS carbon-cost passthrough under the portfolio&apos;s stored transition scenario.</p>
              </div>
              <button className="tb-btn tb-btn--primary" onClick={() => void doRunTransition()} disabled={transitionBusy}>
                {transitionBusy ? 'Running…' : 'Run transition'}
              </button>
            </div>
            {transitionErr && <p className="sg-error-text">{transitionErr}</p>}
            {!transition && !transitionErr && (
              <div className="analytics-empty">
                <h3>No transition run yet</h3>
                <p>Click "Run transition" to compute the portfolio&apos;s carbon-cost trajectory.</p>
              </div>
            )}
            {transition && transition.years.length === 0 && (
              <p className="sg-setting-hint">{transition.detail ?? 'No carbon-price trajectory for this scenario.'}</p>
            )}
            {transition && transition.years.length > 0 && (
              <>
                <div className="econ-kpi-row">
                  <div className="econ-kpi">
                    <div className="econ-kpi-label">Carbon-cost NPV</div>
                    <div className="econ-kpi-value">{money(transition.totalNpv)}</div>
                    <div className="econ-kpi-unit">discounted at {(transition.discountRate * 100).toFixed(1)}%</div>
                  </div>
                  <div className="econ-kpi">
                    <div className="econ-kpi-label">Carbon cost {transition.years[transition.years.length - 1]}</div>
                    <div className="econ-kpi-value">{money(lastTransitionCost)}/yr</div>
                  </div>
                  <div className="econ-kpi">
                    <div className="econ-kpi-label">Carbon cost {transition.baseYear}</div>
                    <div className="econ-kpi-value">{money(transition.totalCostByYear[0])}/yr</div>
                  </div>
                </div>
                <div className="econ-body">
                  <div className="econ-table-col" style={{ flex: '1 1 320px' }}>
                    <p className="econ-section-label">Annual carbon cost by year — {transition.scenario.replace(/_/g, ' ')}</p>
                    <TransitionCostChart years={transition.years} values={transition.totalCostByYear} formatValue={money} />
                  </div>
                  <div className="econ-table-col" style={{ flex: '1 1 320px' }}>
                    <p className="econ-section-label">Per-asset carbon-cost NPV</p>
                    <div className="table-wrap">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Asset</th>
                            <th>Emissions (tCO2e/yr)</th>
                            <th>Source</th>
                            <th>NPV</th>
                          </tr>
                        </thead>
                        <tbody>
                          {transition.perAsset.map((a) => (
                            <tr key={a.assetId}>
                              <td>{a.name}</td>
                              <td>{a.emissionsTco2e.toLocaleString()}</td>
                              <td>{a.emissionsSource === 'reported' ? 'Reported' : 'Sector proxy'}</td>
                              <td>{money(a.npv)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
                <p className="sg-setting-hint">{transition.method}</p>
              </>
            )}
          </div>

          <div className="chart-card chart-card-wide">
            <div className="chart-card-header">
              <div>
                <h3>Climate risk premium</h3>
                <p>
                  Baseline-vs-climate-stressed NPV / DSCR / rating -&gt; the counterfactual credit-spread
                  premium (CRP), for a completed physical run.
                </p>
              </div>
              <button
                className="tb-btn tb-btn--primary"
                onClick={() => void doRunFinance()}
                disabled={financeBusy || !financeReady}
              >
                {financeBusy ? 'Computing…' : 'Compute climate risk premium'}
              </button>
            </div>

            {!physicalRunDone && <p className="sg-setting-hint">Run a physical-risk analysis first (Results tab).</p>}
            {physicalRunDone && !financeReady && (
              <p className="sg-setting-hint">
                {isPower
                  ? 'Enter CAPEX + capacity (MW) + price + capacity factor (or fuel) below.'
                  : 'Enter CAPEX + annual EBITDA below.'}
              </p>
            )}
            {financeErr && <p className="sg-error-text">{financeErr}</p>}

            <p className="econ-section-label" style={{ marginTop: 12 }}>Project financial profile (portfolio default)</p>
            <div className="sg-setting-row">
              <label className="sg-setting-label">Financial model</label>
              <select
                value={profile.financialModel ?? 'generic'}
                onChange={(e) => patchProfile({ financialModel: e.target.value })}
              >
                <option value="generic">Generic — damage (AAI) + carbon</option>
                <option value="power_gen">Power generation — capacity factor</option>
              </select>
            </div>
            <div className="sg-setting-row">
              <label className="sg-setting-label">DSCR-to-rating methodologies</label>
              <SearchableMultiSelect
                values={selectedMethodIds}
                options={ratingMethodOptions}
                onChange={(next) => patchProfile({ ratingMethods: next.length > 0 ? next : null })}
                placeholder="All methodologies (library default)"
              />
            </div>
            <p className="sg-setting-hint">
              Selecting methodologies here re-computes them server-side on the next "Compute climate
              risk premium" click; the comparison table below also filters the current result to the
              selection (the full set is always computed server-side).
            </p>
            {numField(`CAPEX (${currency})`, 'capex', '1000000')}
            {!isPower && numField(`Annual EBITDA (${currency})`, 'annualEbitda', '1000000')}
            {isPower && (
              <>
                {numField('Capacity (MW)', 'capacityMw', '10')}
                {numField(`Price (${currency}/MWh)`, 'powerPrice', '1')}
                {numField('Capacity factor', 'capacityFactor', '0.01')}
                {numField(`Var O&M (${currency}/MWh)`, 'opexPerMwh', '1')}
                {numField(`Fixed O&M (${currency}/yr)`, 'fixedOpex', '100000')}
                {numField('Dispatch penalty (policy)', 'dispatchPenalty', '0.01')}
                {numField('Efficiency loss (heat)', 'efficiencyLoss', '0.01')}
                {numField('Capacity derate (drought)', 'capacityDerate', '0.01')}
                {numField('Outage rate (wildfire/storm)', 'outageRate', '0.01')}
              </>
            )}

            {finance && (
              <>
                <div className="econ-kpi-row" style={{ marginTop: 16 }}>
                  <div className="econ-kpi">
                    <div className="econ-kpi-label">Climate risk premium</div>
                    <div className="econ-kpi-value" style={{ color: finance.portfolio.crpBps > 0 ? 'var(--danger, #b91c1c)' : 'var(--brand)' }}>
                      {finance.portfolio.crpBps >= 0 ? '+' : ''}{finance.portfolio.crpBps.toFixed(0)} bps
                    </div>
                    <div className="econ-kpi-unit">
                      {finance.portfolio.baseline.rating} to {finance.portfolio.stressed.rating}
                      {finance.portfolio.downgrade ? ' (downgrade)' : ''}
                    </div>
                  </div>
                  <div className="econ-kpi">
                    <div className="econ-kpi-label">Baseline</div>
                    <div className="econ-kpi-value" style={{ color: ratingColor(finance.portfolio.baseline.rating) }}>
                      {finance.portfolio.baseline.rating}
                    </div>
                    <div className="econ-kpi-unit">
                      DSCR {finance.portfolio.baseline.minDscr >= 1e9 ? 'inf' : finance.portfolio.baseline.minDscr.toFixed(2)}
                      {' · '}NPV {money(finance.portfolio.baseline.npv)}
                    </div>
                  </div>
                  <div className="econ-kpi">
                    <div className="econ-kpi-label">Climate-stressed</div>
                    <div className="econ-kpi-value" style={{ color: ratingColor(finance.portfolio.stressed.rating) }}>
                      {finance.portfolio.stressed.rating}
                    </div>
                    <div className="econ-kpi-unit">
                      DSCR {finance.portfolio.stressed.minDscr >= 1e9 ? 'inf' : finance.portfolio.stressed.minDscr.toFixed(2)}
                      {' · '}NPV {money(finance.portfolio.stressed.npv)}
                    </div>
                  </div>
                </div>
                <p className="sg-setting-hint" style={{ marginTop: 8 }}>
                  Rated under <strong>{finance.ratingMethodLabel}</strong>
                  {finance.ratingMethodSource ? ` (${finance.ratingMethodSource})` : ''} - annual climate loss{' '}
                  {money(finance.totalPhysicalAai + finance.transitionAnnualCost)} (physical AAI {money(finance.totalPhysicalAai)} +
                  transition {money(finance.transitionAnnualCost)}) - NPV loss {money(finance.portfolio.npvLoss)} (
                  {finance.portfolio.npvLossPctCapex.toFixed(1)}% of CAPEX).
                </p>

                {finance.methodsCompared.length > 1 && (
                  <div style={{ marginTop: 12 }}>
                    <p className="econ-section-label">Methodology comparison</p>
                    <div className="table-wrap">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Methodology</th>
                            <th>Baseline</th>
                            <th>Stressed</th>
                            <th>CRP (bps)</th>
                            <th>NPV loss</th>
                          </tr>
                        </thead>
                        <tbody>
                          {visibleMethods.map((m) => (
                            <tr key={m.method}>
                              <td>{m.code}{m.method === finance.methodsCompared[0].method ? ' (primary)' : ''}</td>
                              <td style={{ color: ratingColor(m.scenario.baseline.rating) }}>{m.scenario.baseline.rating}</td>
                              <td style={{ color: ratingColor(m.scenario.stressed.rating) }}>{m.scenario.stressed.rating}</td>
                              <td>{m.scenario.crpBps >= 0 ? '+' : ''}{m.scenario.crpBps.toFixed(0)}</td>
                              <td>{money(m.scenario.npvLoss)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {finance.perAsset.length > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <p className="econ-section-label">Per-asset (overridden facilities)</p>
                    <div className="table-wrap">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Facility</th>
                            <th>Climate loss/yr</th>
                            <th>Baseline</th>
                            <th>Stressed</th>
                            <th>CRP (bps)</th>
                          </tr>
                        </thead>
                        <tbody>
                          {finance.perAsset.map((a) => (
                            <tr key={a.assetId}>
                              <td>{a.name}</td>
                              <td>{money(a.assessment.annualClimateLoss)}</td>
                              <td style={{ color: ratingColor(a.assessment.baseline.rating) }}>{a.assessment.baseline.rating}</td>
                              <td style={{ color: ratingColor(a.assessment.stressed.rating) }}>{a.assessment.stressed.rating}</td>
                              <td>{a.assessment.crpBps >= 0 ? '+' : ''}{a.assessment.crpBps.toFixed(0)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {finance.detail && <p className="sg-setting-hint" style={{ marginTop: 8 }}>{finance.detail}</p>}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
