/**
 * Physical Risk — Method sub-tab.
 *
 * Ported from climaterisk's `MethodView`: an honest account of what each
 * number is, sourced from the actual engine/transition/finance docstrings in
 * this backend (not climaterisk's own text, which describes a different
 * implementation) — this native engine is a deterministic STUB pending the
 * CLIMADA worker, so that caveat is stated up front rather than implied.
 *
 * Also fetches and renders the session report (`GET .../report`) when a
 * portfolio is loaded: a compact "current session" summary (asset count,
 * total value, transition NPV, finance headline if computed).
 *
 * A module-scope cache holds the last-fetched report per session id so
 * switching sub-tabs and back doesn't need a re-fetch flash; every async
 * setState is guarded by an alive-ref so nothing fires after unmount.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useToast } from '../../shared/components/Toast';
import {
  FullLibraries,
  FullPortfolio,
  ReportBundle,
  getFullLibraries,
  getReport,
} from 'lib/physicalRisk/configViews';
import { PhysicalRiskSectionProps } from 'lib/physicalRisk/types';

// Represent flood MDR at a few depths, same selection climaterisk used.
const SHOW_DEPTHS = [0.5, 1, 2, 3];

// Module-scope cache so switching away from Method and back doesn't re-fetch
// (and doesn't flash empty while it does) — keyed by session id.
const reportCache = new Map<string, ReportBundle>();
let librariesCache: FullLibraries | null = null;

export function MethodSection({ portfolio }: PhysicalRiskSectionProps) {
  const { showToast } = useToast();
  const full = portfolio as FullPortfolio | null;
  const sessionId = full?.sessionId ?? null;

  const [libraries, setLibraries] = useState<FullLibraries | null>(librariesCache);
  const [report, setReport] = useState<ReportBundle | null>(sessionId ? reportCache.get(sessionId) ?? null : null);
  const [loadingReport, setLoadingReport] = useState(false);
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    return () => { aliveRef.current = false; };
  }, []);

  useEffect(() => {
    if (librariesCache) return;
    void getFullLibraries()
      .then((libs) => {
        librariesCache = libs;
        if (aliveRef.current) setLibraries(libs);
      })
      .catch((err) => { if (aliveRef.current) showToast(err instanceof Error ? err.message : 'Failed to load libraries', 'error'); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadReport = useCallback((sid: string) => {
    setLoadingReport(true);
    void getReport(sid)
      .then((r) => {
        reportCache.set(sid, r);
        if (aliveRef.current) setReport(r);
      })
      .catch((err) => {
        if (aliveRef.current) showToast(err instanceof Error ? err.message : 'Failed to load the session report', 'error');
      })
      .finally(() => { if (aliveRef.current) setLoadingReport(false); });
  }, [showToast]);

  useEffect(() => {
    if (sessionId) setReport(reportCache.get(sessionId) ?? null);
    else setReport(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  if (!libraries) {
    return (
      <div className="pane">
        <div className="pane-header">
          <div>
            <h2>Method</h2>
            <p className="chart-card p">Methodology and data provenance.</p>
          </div>
        </div>
        <div className="analytics-empty">
          <h3>Loading libraries…</h3>
        </div>
      </div>
    );
  }

  const classes = libraries.vulnerabilityClasses;
  const depths = libraries.impactFunctions.floodDepthM;
  const depthIdx = SHOW_DEPTHS.map((d) => depths.indexOf(d)).filter((i) => i >= 0);
  const money = (v: number, currency: string) => `${currency} ${Math.round(v).toLocaleString()}`;

  return (
    <div className="pane">
      <div className="pane-header">
        <div>
          <h2>Method</h2>
          <p className="chart-card p">
            How each number on this tab is computed — the actual engines wired into this session, not aspirational
            scope. Risk is framed as probability times impact.
          </p>
        </div>
      </div>

      <div className="chart-card" style={{ marginBottom: 16 }}>
        <h3>Physical risk — hazard x exposure x vulnerability</h3>
        <p>
          A run evaluates <strong>Risk = Hazard x Exposure x Vulnerability</strong> per asset: a peril's severity
          factor times the asset's value gives its expected annual impact (EAI); summed across assets and perils it
          is the portfolio's average annual impact (AAI). A return-period (exceedance) curve gives the loss expected
          on average once per N years; <code>deltaPct</code> is the future-horizon impact versus the present-day
          baseline.
        </p>
        <p className="sg-setting-hint">
          Current engine status: the physical, uncertainty, cost-benefit, supply-chain, calibration and forecast run
          kinds are all deterministic STUB implementations (backend/app/physical_risk/engine.py) — every number is a
          pure function of asset value, its index in the portfolio and a per-peril factor, with no randomness and no
          CLIMADA import. The seam (<code>run_kind</code>) is in place for a real CLIMADA worker subprocess
          (request.json / result.json contract) to replace the stub without an API change.
        </p>
      </div>

      <div className="chart-card" style={{ marginBottom: 16 }}>
        <h3>Impact functions (vulnerability classes)</h3>
        <p>
          Each asset maps to a vulnerability class (by sector default, or chosen explicitly on Assets). The class
          carries the parameters each peril's damage function needs; edit them on the Vulnerability tab.
        </p>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Class</th>
                <th>TC v-half (m/s)</th>
                <th>Wildfire max MDR</th>
                {depthIdx.map((i) => <th key={i}>Flood MDR @ {depths[i]}m</th>)}
              </tr>
            </thead>
            <tbody>
              {classes.map((c) => (
                <tr key={c.id}>
                  <td>{c.label}</td>
                  <td>{c.tcVHalf}</td>
                  <td>{c.wfMaxMdd.toFixed(2)}</td>
                  {depthIdx.map((i) => <td key={i}>{c.floodMdr[i]?.toFixed(2)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="sg-setting-hint">
          TC: Emanuel (2011) wind-damage curve; v-half is the wind speed (m/s) at 50% mean damage (lower = more
          vulnerable). Wildfire: step function on brightness temperature rising to the class max MDR. Flood:
          depth-damage curve (mean damage ratio vs water depth), Huizinga (2017) style. Lower v-half and higher MDR
          mean a more vulnerable asset.
        </p>
      </div>

      <div className="chart-card" style={{ marginBottom: 16 }}>
        <h3>Perils and data availability</h3>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Peril</th>
                <th>Status</th>
                <th>Hazard / source</th>
              </tr>
            </thead>
            <tbody>
              {libraries.perils.map((p) => (
                <tr key={p.id}>
                  <td>{p.label}</td>
                  <td>
                    {p.supportedMvp ? (
                      <span className="sg-badge">
                        {p.historicalOnly ? 'historical' : p.coverage ? p.coverage : 'active'}
                      </span>
                    ) : (
                      <span className="sg-badge">unavailable</span>
                    )}
                  </td>
                  <td>{p.supportedMvp ? p.futureSource : p.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="sg-setting-hint">
          Hazard availability was verified against the live CLIMADA Data API. Every peril above is presently served
          by the deterministic stub engine regardless of its listed data source, until the CLIMADA worker is
          attached (<code>workerGated</code> on each entry).
        </p>
      </div>

      <div className="chart-card" style={{ marginBottom: 16 }}>
        <h3>Transition (policy) risk</h3>
        <p>
          Real math, not a stub: <code>emissions_i = reported Scope-1, else (value_i / 1e6) x sector_factor</code>;
          <code> carbon_cost_i(t) = emissions_i x carbon_price(scenario, t)</code>, summed across assets and
          discounted to NPV at the portfolio's discount rate. The carbon price is the NGFS Phase 5 shadow price for
          the selected transition scenario, linearly interpolated between vendored trajectory anchors
          (backend/app/physical_risk/transition.py).
        </p>
      </div>

      <div className="chart-card" style={{ marginBottom: 16 }}>
        <h3>Finance — climate risk premium</h3>
        <p>
          Also real math: an annual project-finance cashflow (EBITDA discounted at WACC, minus CAPEX) is assessed
          twice — baseline and climate-stressed (EBITDA reduced by physical AAI plus transition carbon cost, or for
          a <code>power_gen</code> profile, generation rebuilt through operational channels: dispatch penalty,
          forced-outage rate, capacity/water derate, heat efficiency loss). Debt-service coverage (DSCR) sets a
          credit rating from a cited DSCR-to-rating grid; the climate risk premium (CRP, in bps) is the credit-spread
          difference between the two ratings (backend/app/physical_risk/finance.py). Only computed when the
          portfolio's scenario carries a financial profile with CAPEX set (Finance tab).
        </p>
      </div>

      <div className="chart-card" style={{ marginBottom: 16 }}>
        <h3>Data sources</h3>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Input</th>
                <th>Source</th>
                <th>Notes / licence</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Hazard (all perils)</td>
                <td>CLIMADA Data API and vendored petals/ingest sources (data.iac.ethz.ch)</td>
                <td>Not yet wired to this engine (stub) — see the Perils table above for the real path per peril.</td>
              </tr>
              <tr>
                <td>TC vulnerability</td>
                <td>Emanuel (2011); windstorm: Schwierz et al.</td>
                <td>Calibrated impact functions; presets from Eberenz et al. (2021) regional calibration.</td>
              </tr>
              <tr>
                <td>Carbon price</td>
                <td>NGFS Phase 5 ({libraries.ngfsScenarios.source || 'IIASA'})</td>
                <td>Real — {libraries.ngfsScenarios.model}, {libraries.ngfsScenarios.units}, frozen trajectory snapshot.</td>
              </tr>
              <tr>
                <td>Emission factors</td>
                <td>Sector-intensity heuristic</td>
                <td>Order-of-magnitude proxy (tCO2e per $M asset value); reported Scope-1 preferred when an asset has it.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="chart-card">
        <h3>Provenance caveat</h3>
        <p className="sg-setting-hint">
          NGFS carbon prices and the finance cashflow math are real. The physical-risk engine is a deterministic stub
          (no CLIMADA import yet) — every physical, uncertainty, cost-benefit, supply-chain, calibration and forecast
          number is reproducible but not yet a genuine hazard/exposure/vulnerability computation. Vulnerability-curve
          values (TC v-half, wildfire MDR, flood depth-damage, earthquake MMI) and sector emission intensities are
          indicative MVP values, vendored verbatim from climaterisk's methodology libraries.
        </p>
      </div>

      <div className="pane-header" style={{ marginTop: 24 }}>
        <div>
          <h2>Current session</h2>
          <p className="chart-card p">Compact summary of this portfolio's report bundle.</p>
        </div>
        {sessionId && (
          <button className="tb-btn" onClick={() => loadReport(sessionId)} disabled={loadingReport}>
            {loadingReport ? 'Loading…' : report ? 'Refresh report' : 'Load report'}
          </button>
        )}
      </div>

      {!sessionId && (
        <div className="analytics-empty">
          <h3>No portfolio loaded</h3>
          <p>Load the fleet on the Assets tab to see a session summary here.</p>
        </div>
      )}

      {sessionId && !report && !loadingReport && (
        <div className="analytics-empty">
          <h3>No report loaded yet</h3>
          <p>Click "Load report" to fetch the current session's summary.</p>
        </div>
      )}

      {report && (
        <div className="table-wrap">
          <table className="data-table">
            <tbody>
              <tr>
                <th>Assets</th>
                <td>{report.summary.assetCount}</td>
              </tr>
              <tr>
                <th>Total value</th>
                <td>{money(report.summary.totalValue, report.summary.currency)}</td>
              </tr>
              <tr>
                <th>Transition scenario</th>
                <td>{report.transition.scenario}</td>
              </tr>
              <tr>
                <th>Transition NPV</th>
                <td>{money(report.transition.totalNpv, report.summary.currency)} (discounted at {(report.transition.discountRate * 100).toFixed(1)}%)</td>
              </tr>
              {report.finance && (
                <>
                  <tr>
                    <th>Rating method</th>
                    <td>{report.finance.ratingMethodLabel}</td>
                  </tr>
                  <tr>
                    <th>Climate risk premium</th>
                    <td>
                      {report.finance.portfolio.crpBps >= 0 ? '+' : ''}{report.finance.portfolio.crpBps.toFixed(0)} bps
                      {' '}({report.finance.portfolio.baseline.rating} to {report.finance.portfolio.stressed.rating})
                    </td>
                  </tr>
                </>
              )}
              {!report.finance && (
                <tr>
                  <th>Finance</th>
                  <td>Not computed (set a financial profile with CAPEX on the Scenarios tab and complete a physical run first).</td>
                </tr>
              )}
              <tr>
                <th>Generated</th>
                <td>{new Date(report.generatedAt).toLocaleString()}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
