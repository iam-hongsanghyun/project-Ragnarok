/**
 * RunDialog — minimal modal for kicking off a solve. Uses the same visual
 * language as the Validation pane: eyebrow + h2 header, bordered sections
 * with uppercase section titles, tb-btn pills for choices.
 *
 * Two sections only — a planning summary and optimisation toggles.
 * Editable scenario, pathway, and rolling-horizon controls live in the sidebar.
 */
import React from 'react';
import { PathwayConfig, RollingHorizonConfig } from 'lib/types';

export interface RunDialogProps {
  open: boolean;
  onClose: () => void;

  forceLp: boolean;
  dryRun: boolean;
  storeInBackend: boolean;
  activeScenarioLabel: string | null;
  activeConstraintCount: number;
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  pathwayConfig: PathwayConfig;
  rollingConfig: RollingHorizonConfig;

  onForceLpChange: (v: boolean) => void;
  onDryRunChange: (v: boolean) => void;
  onStoreInBackendChange: (v: boolean) => void;

  onRun: () => void;
}

export function RunDialog({
  open,
  onClose,
  forceLp,
  dryRun,
  storeInBackend,
  activeScenarioLabel,
  activeConstraintCount,
  snapshotStart,
  snapshotEnd,
  snapshotWeight,
  pathwayConfig,
  rollingConfig,
  onForceLpChange,
  onDryRunChange,
  onStoreInBackendChange,
  onRun,
}: RunDialogProps) {
  if (!open) return null;

  const pathwayEnabled = pathwayConfig.enabled;
  const rollingEnabled = rollingConfig.enabled;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card run-config" onClick={(e) => e.stopPropagation()}>
        <div className="validation-report">
          <div className="validation-report-header">
            <div>
              <p className="eyebrow">Run</p>
              <h2>Run configuration</h2>
            </div>
          </div>

          <div className="validation-section">
            <p className="validation-section-title">Planning</p>
            <div className="sg-scenario-summary">
              <span>{activeScenarioLabel ? `Scenario: ${activeScenarioLabel}` : 'Scenario: ad hoc'}</span>
              <span>{pathwayEnabled ? `${pathwayConfig.periods.length} pathway periods` : 'Single-period solve'}</span>
              <span>{rollingEnabled ? `Rolling ${rollingConfig.horizonSnapshots}/${rollingConfig.overlapSnapshots}` : 'Full-horizon solve'}</span>
              <span>{pathwayEnabled ? 'Window comes from sidebar pathway settings' : `Window ${snapshotStart} → ${snapshotEnd}`}</span>
              <span>{snapshotWeight}h resolution</span>
              <span>{activeConstraintCount} active constraints</span>
            </div>
          </div>

          <div className="validation-section">
            <p className="validation-section-title">Optimisation settings</p>
            <div className="sg-btn-row">
              <button
                className={`tb-btn${forceLp ? '' : ' tb-btn--muted'}`}
                onClick={() => onForceLpChange(!forceLp)}
              >
                Force LP
              </button>
              <button
                className={`tb-btn${dryRun ? '' : ' tb-btn--muted'}`}
                onClick={() => onDryRunChange(!dryRun)}
              >
                Dry run
              </button>
              <button
                className={`tb-btn${storeInBackend ? '' : ' tb-btn--muted'}`}
                onClick={() => onStoreInBackendChange(!storeInBackend)}
              >
                Store in backend
              </button>
            </div>
            <p className="run-config-hint">
              Save this run (model + results) on the server — reopen it from History without re-running.
            </p>
          </div>
        </div>

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
