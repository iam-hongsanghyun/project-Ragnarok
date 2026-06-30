/**
 * Power-flow section — run network physics (pf/lpf) instead of an optimisation.
 *
 * AC = full Newton-Raphson (voltages + losses); Linear = DC approximation
 * (fast, lossless). Mutually exclusive with the optimise-only solve modes.
 */
import React from 'react';
import {
  PathwayConfig,
  PowerFlowConfig,
  RollingHorizonConfig,
  SamplingConfig,
  SecurityConstrainedConfig,
  StochasticConfig,
} from 'lib/types';

export interface PowerFlowSectionProps {
  powerFlowConfig: PowerFlowConfig;
  onPowerFlowConfigChange: (config: PowerFlowConfig) => void;
  rollingConfig: RollingHorizonConfig;
  stochasticConfig: StochasticConfig;
  pathwayConfig: PathwayConfig;
  samplingConfig: SamplingConfig;
  sclopfConfig: SecurityConstrainedConfig;
}

export function PowerFlowSection(props: PowerFlowSectionProps) {
  const cfg = props.powerFlowConfig;
  const blockReason =
    props.rollingConfig.enabled ? 'rolling horizon' :
    props.stochasticConfig.enabled ? 'stochastic mode' :
    props.pathwayConfig.enabled ? 'pathway mode' :
    props.sclopfConfig.enabled ? 'security-constrained (SCLOPF)' :
    props.samplingConfig.enabled ? 'sampled snapshot blocks' : '';
  const blocked = blockReason !== '';

  const set = (patch: Partial<PowerFlowConfig>) =>
    props.onPowerFlowConfigChange({ ...cfg, ...patch });

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Power flow</h3>
        <p>
          Solve the network physics for branch flows and bus voltages from the
          given injections — not an optimisation. No costs, prices, or emissions
          are produced. Needs branch reactance (x) and a generator in each
          connected sub-network (the slack).
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button
            className={`tb-btn sg-solver-btn${!cfg.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => set({ enabled: false })}
          >
            Off (optimise)
          </button>
          <button
            className={`tb-btn sg-solver-btn${cfg.enabled ? '' : ' tb-btn--muted'}`}
            disabled={blocked}
            title={blocked ? `Disable ${blockReason} to enable power flow` : undefined}
            onClick={() => set({ enabled: true })}
          >
            On
          </button>
        </div>
        {blocked && (
          <p className="sg-setting-hint" style={{ color: 'var(--danger, #dc2626)' }}>
            <strong>Disable {blockReason} to enable power flow.</strong>
          </p>
        )}
      </div>

      {cfg.enabled && (
        <>
          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label">Method</label>
            <div className="sg-btn-row">
              <button
                className={`tb-btn sg-solver-btn${!cfg.linear ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ linear: false })}
              >
                AC (Newton-Raphson)
              </button>
              <button
                className={`tb-btn sg-solver-btn${cfg.linear ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ linear: true })}
              >
                Linear (DC)
              </button>
            </div>
            <p className="sg-setting-hint">
              {cfg.linear
                ? 'Linear (DC): fast and robust, but lossless and assumes unit voltage magnitude.'
                : 'AC: full voltages and active losses; can fail to converge on ill-conditioned networks.'}
            </p>
          </div>
        </>
      )}
    </section>
  );
}
