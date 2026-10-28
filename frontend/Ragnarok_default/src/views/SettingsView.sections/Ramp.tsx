/**
 * Ramp-rate limits section — timestep-weighted ramp constraint.
 */
import React from 'react';
import { RampConfig } from 'lib/types';

export interface RampSectionProps {
  rampConfig: RampConfig;
  onRampConfigChange: (config: RampConfig) => void;
}

export function RampSection(props: RampSectionProps) {
  const cfg = props.rampConfig;
  const set = (patch: Partial<RampConfig>) => props.onRampConfigChange({ ...cfg, ...patch });

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Ramp-rate limits</h3>
        <p>
          Default ramp rate for units that have none of their own. PyPSA's ramp limit is a fraction of
          capacity per SNAPSHOT, so the rate you state here (%/hour) is written for the run as
          min(1, rate × hours per snapshot) using the weights the run uses (blank when ≥ 100 % per snapshot),
          and PyPSA's own constraint enforces it, including across rolling windows. A unit's own rate lives
          in the RAGNAROK_TimeUnits sheet (per hour or per minute).
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
            <label className="sg-setting-label">Ramp up limit (%/hour)</label>
            <input
              type="number"
              className="sg-number-input"
              min={0}
              max={100}
              step={1}
              value={Math.round(cfg.rampLimitUp * 100)}
              onChange={(e) => set({ rampLimitUp: Math.min(1, Math.max(0, (Number(e.target.value) || 0) / 100)) })}
            />
            <p className="sg-setting-hint">Max upward ramp, as a fraction of capacity per hour.</p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Ramp down limit (%/hour)</label>
            <input
              type="number"
              className="sg-number-input"
              min={0}
              max={100}
              step={1}
              value={Math.round(cfg.rampLimitDown * 100)}
              onChange={(e) => set({ rampLimitDown: Math.min(1, Math.max(0, (Number(e.target.value) || 0) / 100)) })}
            />
            <p className="sg-setting-hint">Max downward ramp, as a fraction of capacity per hour.</p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Applies to</label>
            <div className="sg-btn-row">
              <button
                className={`tb-btn sg-solver-btn${cfg.appliesTo === 'all' ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ appliesTo: 'all' })}
              >
                All units
              </button>
              <button
                className={`tb-btn sg-solver-btn${cfg.appliesTo === 'thermal' ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ appliesTo: 'thermal' })}
              >
                Thermal only
              </button>
            </div>
            <p className="sg-setting-hint">
              {cfg.appliesTo === 'thermal'
                ? 'Variable renewables are excluded from the ramp limit.'
                : 'Every generator is subject to the ramp limit.'}
            </p>
          </div>
        </>
      )}
    </section>
  );
}
