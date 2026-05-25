/**
 * RunDialog — minimal modal for kicking off a solve.
 *
 * Only the two mode toggles (Single period / Pathway, Rolling horizon On / Off)
 * plus Force-LP and Dry-run options live here. Snapshot window, time resolution,
 * investment periods, and rolling-horizon details are configured in the sidebar.
 */
import React from 'react';
import { PathwayConfig, RollingHorizonConfig } from '../../shared/types';

export interface RunDialogProps {
  open: boolean;
  onClose: () => void;

  forceLp: boolean;
  dryRun: boolean;
  pathwayConfig: PathwayConfig;
  rollingConfig: RollingHorizonConfig;

  onForceLpChange: (v: boolean) => void;
  onDryRunChange: (v: boolean) => void;
  onPathwayConfigChange: (config: PathwayConfig) => void;
  onRollingConfigChange: (config: RollingHorizonConfig) => void;

  onRun: () => void;
}

export function RunDialog({
  open,
  onClose,
  forceLp,
  dryRun,
  pathwayConfig,
  rollingConfig,
  onForceLpChange,
  onDryRunChange,
  onPathwayConfigChange,
  onRollingConfigChange,
  onRun,
}: RunDialogProps) {
  if (!open) return null;

  const pathwayEnabled = pathwayConfig.enabled;
  const rollingEnabled = rollingConfig.enabled;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="panel-title-row">
          <div>
            <p className="eyebrow">Run</p>
            <h2>Run configuration</h2>
          </div>
        </div>

        <div className="field">
          <label className="sg-setting-label">Planning</label>
          <div className="sg-btn-row">
            <button
              className={`tb-btn sg-solver-btn${!pathwayEnabled ? '' : ' tb-btn--muted'}`}
              onClick={() => onPathwayConfigChange({ ...pathwayConfig, enabled: false, planningMode: 'single_period' })}
            >
              Single period
            </button>
            <button
              className={`tb-btn sg-solver-btn${pathwayEnabled ? '' : ' tb-btn--muted'}`}
              onClick={() => onPathwayConfigChange({
                ...pathwayConfig,
                enabled: true,
                planningMode: 'pathway',
                periods: pathwayConfig.periods.length
                  ? pathwayConfig.periods
                  : [
                    { period: 2030, objectiveWeight: 1, yearsWeight: 5 },
                    { period: 2040, objectiveWeight: 1, yearsWeight: 10 },
                  ],
                selectedPeriod: pathwayConfig.selectedPeriod ?? 2030,
              })}
            >
              Pathway
            </button>
          </div>
        </div>

        <div className="field">
          <label className="sg-setting-label">Rolling horizon</label>
          <div className="sg-btn-row">
            <button
              className={`tb-btn sg-solver-btn${!rollingEnabled ? '' : ' tb-btn--muted'}`}
              onClick={() => onRollingConfigChange({ ...rollingConfig, enabled: false })}
            >
              Off
            </button>
            <button
              className={`tb-btn sg-solver-btn${rollingEnabled ? '' : ' tb-btn--muted'}`}
              onClick={() => onRollingConfigChange({ ...rollingConfig, enabled: true })}
            >
              On
            </button>
          </div>
        </div>

        <label className="rd-checkbox">
          <input type="checkbox" checked={forceLp} onChange={(e) => onForceLpChange(e.target.checked)} />
          <span>Force LP</span>
        </label>
        <label className="rd-checkbox">
          <input type="checkbox" checked={dryRun} onChange={(e) => onDryRunChange(e.target.checked)} />
          <span>Dry run</span>
        </label>

        <div className="modal-actions">
          <button className="secondary-button" onClick={onClose}>Cancel</button>
          <button className="run-button" onClick={onRun}>
            {dryRun ? 'Validate' : 'Run model'}
          </button>
        </div>
      </div>
    </div>
  );
}
