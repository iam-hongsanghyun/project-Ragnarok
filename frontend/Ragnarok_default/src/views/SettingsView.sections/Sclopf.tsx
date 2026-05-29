/**
 * Security-constrained section — N-1 contingency dispatch.
 */
import React from 'react';
import {
  PathwayConfig,
  RollingHorizonConfig,
  SecurityConstrainedConfig,
  StochasticConfig,
} from '../../shared/types';

export interface SclopfSectionProps {
  sclopfConfig: SecurityConstrainedConfig;
  onSclopfConfigChange: (config: SecurityConstrainedConfig) => void;
  rollingConfig: RollingHorizonConfig;
  stochasticConfig: StochasticConfig;
  pathwayConfig: PathwayConfig;
  lineCount: number;
  transformerCount: number;
}

export function SclopfSection(props: SclopfSectionProps) {
  const blocked = props.rollingConfig.enabled || props.stochasticConfig.enabled || props.pathwayConfig.enabled;
  const blockReason =
    props.rollingConfig.enabled ? 'rolling horizon' :
    props.stochasticConfig.enabled ? 'stochastic mode' :
    props.pathwayConfig.enabled ? 'pathway mode' : '';

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Security-constrained (SCLOPF)</h3>
        <p>Dispatch must remain feasible under the outage of any single passive branch. Defaults to N-1 against every line and transformer in the network.</p>
      </header>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button
            className={`tb-btn sg-solver-btn${!props.sclopfConfig.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => props.onSclopfConfigChange({ enabled: false })}
          >
            Off
          </button>
          <button
            className={`tb-btn sg-solver-btn${props.sclopfConfig.enabled ? '' : ' tb-btn--muted'}`}
            disabled={blocked}
            title={blocked ? `Disable ${blockReason} to enable SCLOPF` : undefined}
            onClick={() => props.onSclopfConfigChange({ enabled: true })}
          >
            On
          </button>
        </div>
        {blocked && (
          <p className="sg-setting-hint" style={{ color: 'var(--danger, #dc2626)' }}>
            <strong>Disable {blockReason} to enable SCLOPF.</strong>
          </p>
        )}
      </div>
      {props.sclopfConfig.enabled && (
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
