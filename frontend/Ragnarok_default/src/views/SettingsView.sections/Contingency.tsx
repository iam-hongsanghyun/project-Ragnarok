/**
 * N-1 contingency section — branch loading under every single outage.
 *
 * Linear (LODF-based) analysis of the given operating point. Distinct from
 * SCLOPF, which instead *constrains the dispatch* to stay N-1 feasible.
 * Mutually exclusive with the other solve / study modes.
 */
import React from 'react';
import {
  ContingencyConfig,
  PathwayConfig,
  PowerFlowConfig,
  RollingHorizonConfig,
  SamplingConfig,
  SecurityConstrainedConfig,
  StochasticConfig,
} from 'lib/types';

export interface ContingencySectionProps {
  contingencyConfig: ContingencyConfig;
  onContingencyConfigChange: (config: ContingencyConfig) => void;
  rollingConfig: RollingHorizonConfig;
  stochasticConfig: StochasticConfig;
  pathwayConfig: PathwayConfig;
  samplingConfig: SamplingConfig;
  sclopfConfig: SecurityConstrainedConfig;
  powerFlowConfig: PowerFlowConfig;
  lineCount: number;
  transformerCount: number;
}

export function ContingencySection(props: ContingencySectionProps) {
  const cfg = props.contingencyConfig;
  const blockReason =
    props.rollingConfig.enabled ? 'rolling horizon' :
    props.stochasticConfig.enabled ? 'stochastic mode' :
    props.pathwayConfig.enabled ? 'pathway mode' :
    props.sclopfConfig.enabled ? 'security-constrained (SCLOPF)' :
    props.samplingConfig.enabled ? 'sampled snapshot blocks' :
    props.powerFlowConfig.enabled ? 'power flow' : '';
  const blocked = blockReason !== '';

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>N-1 contingency</h3>
        <p>
          For the given operating point, test the outage of every single passive
          branch and report which leave a remaining branch overloaded. Linear
          (LODF) analysis at the peak-demand snapshot. Network physics only — no
          costs or prices. Distinct from SCLOPF, which constrains dispatch to be
          N-1 feasible.
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button
            className={`tb-btn sg-solver-btn${!cfg.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => props.onContingencyConfigChange({ enabled: false })}
          >
            Off (optimise)
          </button>
          <button
            className={`tb-btn sg-solver-btn${cfg.enabled ? '' : ' tb-btn--muted'}`}
            disabled={blocked}
            title={blocked ? `Disable ${blockReason} to enable N-1 contingency` : undefined}
            onClick={() => props.onContingencyConfigChange({ enabled: true })}
          >
            On
          </button>
        </div>
        {blocked && (
          <p className="sg-setting-hint" style={{ color: 'var(--danger, #dc2626)' }}>
            <strong>Disable {blockReason} to enable N-1 contingency.</strong>
          </p>
        )}
      </div>

      {cfg.enabled && (
        <>
          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label">N-1 coverage</label>
            <div className="sg-setting-value">
              {props.lineCount + props.transformerCount} branches
              {props.transformerCount > 0 && (
                <span style={{ color: 'var(--muted)', fontSize: '0.78rem', marginLeft: 4 }}>
                  ({props.lineCount} line{props.lineCount === 1 ? '' : 's'} + {props.transformerCount} transformer{props.transformerCount === 1 ? '' : 's'})
                </span>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
