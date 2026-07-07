/**
 * Thermal forced-outage Monte Carlo section — reliability run mode.
 */
import React from 'react';
import { OutageMcConfig } from 'lib/types';

export interface OutageMcSectionProps {
  outageMcConfig: OutageMcConfig;
  onOutageMcConfigChange: (config: OutageMcConfig) => void;
}

export function OutageMcSection(props: OutageMcSectionProps) {
  const cfg = props.outageMcConfig;
  const set = (patch: Partial<OutageMcConfig>) => props.onOutageMcConfigChange({ ...cfg, ...patch });

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Outage Monte Carlo</h3>
        <p>
          Monte-Carlo forced-outage reliability: samples random generator up/down
          states (EFOR + repair time) across many synthetic years and reports the
          DISTRIBUTION of loss-of-load (LOLE) and expected unserved energy (EUE) —
          P50/P95, not a point estimate.
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
            <p className="sg-setting-hint">Number of synthetic years drawn from the outage/repair distribution.</p>
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

          <div className="sg-setting-row">
            <label className="sg-setting-label">Forced outage rate (%)</label>
            <input
              type="number"
              className="sg-number-input"
              min={0}
              max={100}
              step={0.5}
              value={Math.round(cfg.forcedOutageRate * 1000) / 10}
              onChange={(e) => set({ forcedOutageRate: Math.min(1, Math.max(0, (Number(e.target.value) || 0) / 100)) })}
            />
            <p className="sg-setting-hint">EFOR fallback applied to generators without an explicit forced-outage rate.</p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Mean time to repair (h)</label>
            <input
              type="number"
              className="sg-number-input"
              min={0}
              step={1}
              value={cfg.mttrHours}
              onChange={(e) => set({ mttrHours: Math.max(0, Number(e.target.value) || 0) })}
            />
            <p className="sg-setting-hint">Average hours a unit stays down once it forces an outage.</p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Renewable ensemble</label>
            <div className="sg-btn-row">
              <button
                className={`tb-btn sg-solver-btn${!cfg.includeRenewableEnsemble ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ includeRenewableEnsemble: false })}
              >
                Thermal only
              </button>
              <button
                className={`tb-btn sg-solver-btn${cfg.includeRenewableEnsemble ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ includeRenewableEnsemble: true })}
              >
                Include renewables
              </button>
            </div>
            <p className="sg-setting-hint">
              {cfg.includeRenewableEnsemble
                ? 'Each Monte-Carlo draw also samples renewable output variability, combining weather and forced-outage risk.'
                : 'Only thermal forced-outage risk is sampled; renewable output follows the base profile.'}
            </p>
          </div>
        </>
      )}
    </section>
  );
}
