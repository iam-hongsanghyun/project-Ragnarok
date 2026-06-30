/**
 * MGA section — map the near-optimal capacity space.
 *
 * MGA (modelling-to-generate-alternatives) layers on top of a normal optimise
 * run: it solves the cost optimum, then re-solves to push each technology to
 * its minimum and maximum within a cost slack. Unlike the power-flow /
 * contingency study modes it does NOT replace the optimisation — it extends it.
 * It may combine with multi-investment pathway runs, but not with the modes
 * that change how (or whether) the LP is solved.
 */
import React from 'react';
import {
  ContingencyConfig,
  MgaConfig,
  PowerFlowConfig,
  RollingHorizonConfig,
  SamplingConfig,
  SecurityConstrainedConfig,
  StochasticConfig,
} from 'lib/types';

export interface MgaSectionProps {
  mgaConfig: MgaConfig;
  onMgaConfigChange: (config: MgaConfig) => void;
  rollingConfig: RollingHorizonConfig;
  stochasticConfig: StochasticConfig;
  samplingConfig: SamplingConfig;
  sclopfConfig: SecurityConstrainedConfig;
  powerFlowConfig: PowerFlowConfig;
  contingencyConfig: ContingencyConfig;
}

export function MgaSection(props: MgaSectionProps) {
  const cfg = props.mgaConfig;
  const blockReason =
    props.rollingConfig.enabled ? 'rolling horizon' :
    props.stochasticConfig.enabled ? 'stochastic mode' :
    props.sclopfConfig.enabled ? 'security-constrained (SCLOPF)' :
    props.samplingConfig.enabled ? 'sampled snapshot blocks' :
    props.powerFlowConfig.enabled ? 'power flow' :
    props.contingencyConfig.enabled ? 'N-1 contingency' : '';
  const blocked = blockReason !== '';

  const set = (patch: Partial<MgaConfig>) =>
    props.onMgaConfigChange({ ...cfg, ...patch });

  const slackPct = Math.round(cfg.slack * 1000) / 10;

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Near-optimal (MGA)</h3>
        <p>
          After solving the cost optimum, explore how different the system could
          be while staying near that cost. For each technology MGA finds the
          least and most capacity buildable within the cost slack — the
          decision-relevant corridor, not a single answer. Extends the optimise
          run (capacities must be extendable); combinable with pathway mode.
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button
            className={`tb-btn sg-solver-btn${!cfg.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => set({ enabled: false })}
          >
            Optimise only
          </button>
          <button
            className={`tb-btn sg-solver-btn${cfg.enabled ? '' : ' tb-btn--muted'}`}
            disabled={blocked}
            title={blocked ? `Disable ${blockReason} to enable MGA` : undefined}
            onClick={() => set({ enabled: true })}
          >
            Explore alternatives
          </button>
        </div>
        {blocked && (
          <p className="sg-setting-hint" style={{ color: 'var(--danger, #dc2626)' }}>
            <strong>Disable {blockReason} to enable MGA.</strong>
          </p>
        )}
      </div>

      {cfg.enabled && (
        <>
          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-mga-slack">Cost slack (%)</label>
            <input
              id="rs-mga-slack"
              type="number"
              min={0.5}
              max={50}
              step={0.5}
              className="sg-num-input"
              value={slackPct}
              onChange={(e) => {
                const pct = parseFloat(e.target.value);
                if (Number.isFinite(pct)) set({ slack: Math.min(0.5, Math.max(0.005, pct / 100)) });
              }}
            />
            <p className="sg-setting-hint">
              Alternatives may cost up to {slackPct}% more than the optimum. Wider
              slack = a broader corridor (more structural freedom), but further
              from least-cost.
            </p>
          </div>
          <div className="sg-setting-row">
            <label className="sg-setting-label">Carriers</label>
            <div className="sg-setting-value">
              All extendable-generator carriers (auto)
            </div>
            <p className="sg-setting-hint">
              Each carrier is pushed to its min and max; the backend caps how many
              are explored per run to keep the solve count bounded.
            </p>
          </div>
        </>
      )}
    </section>
  );
}
