/**
 * ESS business-case section (DW3).
 *
 * Sweep battery sizes; the run prices each size's energy-arbitrage revenue
 * against the system marginal price and reports NPV / IRR / payback, picking the
 * NPV-maximising size. Mutually exclusive with the LP-reshaping modes.
 */
import React from 'react';
import {
  ContingencyConfig,
  EssConfig,
  PowerFlowConfig,
  RollingHorizonConfig,
  SamplingConfig,
  SecurityConstrainedConfig,
  StochasticConfig,
} from 'lib/types';

export interface EssSectionProps {
  essConfig: EssConfig;
  onEssConfigChange: (config: EssConfig) => void;
  modelBuses: string[];
  rollingConfig: RollingHorizonConfig;
  stochasticConfig: StochasticConfig;
  samplingConfig: SamplingConfig;
  sclopfConfig: SecurityConstrainedConfig;
  powerFlowConfig: PowerFlowConfig;
  contingencyConfig: ContingencyConfig;
}

export function EssSection(props: EssSectionProps) {
  const cfg = props.essConfig;
  const buses = props.modelBuses;
  const blockReason =
    props.rollingConfig.enabled ? 'rolling horizon' :
    props.stochasticConfig.enabled ? 'stochastic mode' :
    props.sclopfConfig.enabled ? 'security-constrained (SCLOPF)' :
    props.samplingConfig.enabled ? 'sampled snapshot blocks' :
    props.powerFlowConfig.enabled ? 'power flow' :
    props.contingencyConfig.enabled ? 'N-1 contingency' : '';
  const blocked = blockReason !== '';
  const set = (patch: Partial<EssConfig>) => props.onEssConfigChange({ ...cfg, ...patch });
  const num = (v: string, f: (n: number) => void) => { const n = parseFloat(v); if (Number.isFinite(n)) f(n); };
  const effPct = Math.round((cfg.roundTripEfficiency || 0) * 1000) / 10;

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>ESS business case</h3>
        <p>
          Is a battery viable here, and at what size? Sweep storage sizes; each is
          run as a price-taker against the system marginal price (charge cheap,
          discharge dear) and turned into NPV / IRR / payback. The run reports the
          size curve and the NPV-maximising size. Energy-arbitrage revenue only —
          capacity value and ancillary services are not modelled.
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button className={`tb-btn sg-solver-btn${!cfg.enabled ? '' : ' tb-btn--muted'}`} onClick={() => set({ enabled: false })}>Off</button>
          <button
            className={`tb-btn sg-solver-btn${cfg.enabled ? '' : ' tb-btn--muted'}`}
            disabled={blocked}
            title={blocked ? `Disable ${blockReason} to enable the ESS business case` : undefined}
            onClick={() => set({ enabled: true })}
          >
            Size sweep
          </button>
        </div>
        {blocked && (
          <p className="sg-setting-hint" style={{ color: 'var(--danger, #dc2626)' }}>
            <strong>Disable {blockReason} to enable the ESS business case.</strong>
          </p>
        )}
      </div>

      {cfg.enabled && (
        <>
          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-ess-bus">Bus</label>
            {buses.length > 0 ? (
              <select id="rs-ess-bus" className="sg-num-input" value={cfg.bus} onChange={(e) => set({ bus: e.target.value })}>
                <option value="">Auto (most volatile)</option>
                {buses.map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
            ) : (
              <input id="rs-ess-bus" type="text" className="sg-num-input" placeholder="auto" value={cfg.bus} onChange={(e) => set({ bus: e.target.value })} />
            )}
            <p className="sg-setting-hint">Where to site the battery. Auto picks the most price-volatile bus.</p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-ess-hours">Duration (hours)</label>
            <input id="rs-ess-hours" type="number" min={0.5} step={0.5} className="sg-num-input" value={cfg.maxHours} onChange={(e) => num(e.target.value, (n) => set({ maxHours: Math.max(0.5, n) }))} />
            <p className="sg-setting-hint">Energy capacity = power × duration (e.g. 4 h = a 4-hour battery).</p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-ess-capex">Capital cost (/MW/yr)</label>
            <input id="rs-ess-capex" type="number" min={0} step={1000} className="sg-num-input" value={cfg.capitalCostPerMW} onChange={(e) => num(e.target.value, (n) => set({ capitalCostPerMW: Math.max(0, n) }))} />
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-ess-eff">Round-trip efficiency (%)</label>
            <input id="rs-ess-eff" type="number" min={10} max={100} step={1} className="sg-num-input" value={effPct} onChange={(e) => num(e.target.value, (n) => set({ roundTripEfficiency: Math.min(1, Math.max(0.1, n / 100)) }))} />
          </div>

          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-ess-min">Min size (MW)</label>
            <input id="rs-ess-min" type="number" min={0} step={5} className="sg-num-input" value={cfg.minSizeMW} onChange={(e) => num(e.target.value, (n) => set({ minSizeMW: Math.max(0, n) }))} />
          </div>
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-ess-max">Max size (MW)</label>
            <input id="rs-ess-max" type="number" min={0} step={10} className="sg-num-input" value={cfg.maxSizeMW} onChange={(e) => num(e.target.value, (n) => set({ maxSizeMW: Math.max(0, n) }))} />
          </div>
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-ess-steps">Sweep steps</label>
            <input id="rs-ess-steps" type="number" min={1} max={12} step={1} className="sg-num-input" value={cfg.steps} onChange={(e) => num(e.target.value, (n) => set({ steps: Math.max(1, Math.min(12, Math.round(n))) }))} />
            <p className="sg-setting-hint">Sizes between min and max; one re-solve per step.</p>
          </div>
        </>
      )}
    </section>
  );
}
