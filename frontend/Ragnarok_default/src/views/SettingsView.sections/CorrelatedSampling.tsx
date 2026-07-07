/**
 * Correlated multi-driver Monte Carlo section — reliability run mode.
 */
import React from 'react';
import { CorrelatedSamplingConfig } from 'lib/types';

export interface CorrelatedSamplingSectionProps {
  correlatedSamplingConfig: CorrelatedSamplingConfig;
  onCorrelatedSamplingConfigChange: (config: CorrelatedSamplingConfig) => void;
}

export function CorrelatedSamplingSection(props: CorrelatedSamplingSectionProps) {
  const cfg = props.correlatedSamplingConfig;
  const set = (patch: Partial<CorrelatedSamplingConfig>) => props.onCorrelatedSamplingConfigChange({ ...cfg, ...patch });

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Correlated sampling</h3>
        <p>
          Correlated Monte-Carlo over weather-driven stress: a common stress
          factor drives demand UP while renewable output and hydro inflow drop
          together (a cold-calm event), so the reliability distribution
          captures co-movement independent draws miss. Reports LOLE/EUE
          P50/P95.
        </p>
      </header>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button
            className={`tb-btn sg-solver-btn${!cfg.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => set({ enabled: false })}
          >
            Off
          </button>
          <button
            className={`tb-btn sg-solver-btn${cfg.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => set({ enabled: true })}
          >
            On
          </button>
        </div>
      </div>

      {cfg.enabled && (
        <>
          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label">Monte-Carlo samples</label>
            <input
              type="number"
              className="sg-number-input"
              min={50}
              max={2000}
              step={50}
              value={cfg.nMembers}
              onChange={(e) => set({ nMembers: Math.min(2000, Math.max(50, Number(e.target.value) || 0)) })}
            />
            <p className="sg-setting-hint">Number of synthetic years drawn from the correlated stress distribution.</p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Random seed</label>
            <input
              type="number"
              className="sg-number-input"
              step={1}
              value={cfg.seed}
              onChange={(e) => set({ seed: Number(e.target.value) || 0 })}
            />
            <p className="sg-setting-hint">Fixed seed makes the ensemble reproducible.</p>
          </div>

          <div className="sg-setting-divider" />

          <div className="sg-setting-row">
            <label className="sg-setting-label">Demand sensitivity</label>
            <input
              type="number"
              className="sg-number-input"
              min={0}
              max={2}
              step={0.05}
              value={cfg.loadSensitivity}
              onChange={(e) => set({ loadSensitivity: Math.max(0, Number(e.target.value) || 0) })}
            />
            <p className="sg-setting-hint">How strongly demand rises with the common stress factor (a cold snap).</p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Demand idiosyncratic std</label>
            <input
              type="number"
              className="sg-number-input"
              min={0}
              max={1}
              step={0.01}
              value={cfg.loadStd}
              onChange={(e) => set({ loadStd: Math.max(0, Number(e.target.value) || 0) })}
            />
            <p className="sg-setting-hint">Independent (non-correlated) demand noise, std dev.</p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Renewable CF sensitivity</label>
            <input
              type="number"
              className="sg-number-input"
              min={0}
              max={2}
              step={0.05}
              value={cfg.renewableSensitivity}
              onChange={(e) => set({ renewableSensitivity: Math.max(0, Number(e.target.value) || 0) })}
            />
            <p className="sg-setting-hint">How strongly renewable output falls with the common stress factor (calm wind/low sun).</p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Renewable idiosyncratic std</label>
            <input
              type="number"
              className="sg-number-input"
              min={0}
              max={1}
              step={0.01}
              value={cfg.renewableStd}
              onChange={(e) => set({ renewableStd: Math.max(0, Number(e.target.value) || 0) })}
            />
            <p className="sg-setting-hint">Independent (non-correlated) renewable capacity-factor noise, std dev.</p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Hydro inflow sensitivity</label>
            <input
              type="number"
              className="sg-number-input"
              min={0}
              max={2}
              step={0.05}
              value={cfg.inflowSensitivity}
              onChange={(e) => set({ inflowSensitivity: Math.max(0, Number(e.target.value) || 0) })}
            />
            <p className="sg-setting-hint">How strongly hydro inflow falls with the common stress factor (dry spell).</p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Hydro inflow idiosyncratic std</label>
            <input
              type="number"
              className="sg-number-input"
              min={0}
              max={1}
              step={0.01}
              value={cfg.inflowStd}
              onChange={(e) => set({ inflowStd: Math.max(0, Number(e.target.value) || 0) })}
            />
            <p className="sg-setting-hint">Independent (non-correlated) hydro inflow noise, std dev.</p>
          </div>
        </>
      )}
    </section>
  );
}
