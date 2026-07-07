/**
 * RunDialog — minimal modal for kicking off a solve. Uses the same visual
 * language as the Validation pane: eyebrow + h2 header, bordered sections
 * with uppercase section titles, tb-btn pills for choices.
 *
 * Two sections only — a planning summary and optimisation toggles.
 * Editable scenario, pathway, and rolling-horizon controls live in the sidebar.
 */
import React from 'react';
import { PathwayConfig, RollingHorizonConfig, SamplingConfig } from 'lib/types';
import { computeSamplingPreview } from 'lib/results/sampling';

export interface RunDialogProps {
  open: boolean;
  onClose: () => void;

  forceLp: boolean;
  dryRun: boolean;
  activeScenarioLabel: string | null;
  activeConstraintCount: number;
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  pathwayConfig: PathwayConfig;
  rollingConfig: RollingHorizonConfig;
  samplingConfig: SamplingConfig;

  onForceLpChange: (v: boolean) => void;
  onDryRunChange: (v: boolean) => void;

  /** "Run model" — runs now if the queue is idle, else next in line. */
  onRun: () => void;
  /** "Queue next Run" — parks the job as staged; the user activates it later. */
  onQueueNext: () => void;
  /** "Add as Scenario" — save the current run configuration as a named scenario
   *  (compare + batch-run them from Settings → Scenarios). */
  onAddScenario: () => void;
}

export function RunDialog({
  open,
  onClose,
  forceLp,
  dryRun,
  activeScenarioLabel,
  activeConstraintCount,
  snapshotStart,
  snapshotEnd,
  snapshotWeight,
  pathwayConfig,
  rollingConfig,
  samplingConfig,
  onForceLpChange,
  onDryRunChange,
  onRun,
  onQueueNext,
  onAddScenario,
}: RunDialogProps) {
  if (!open) return null;

  const pathwayEnabled = pathwayConfig.enabled;
  const rollingEnabled = rollingConfig.enabled;
  const samplingEnabled = samplingConfig.enabled && !pathwayEnabled && !rollingEnabled;
  const samplingPreview = samplingEnabled
    ? computeSamplingPreview(Math.max(0, snapshotEnd - snapshotStart), snapshotWeight, samplingConfig)
    : null;

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
              {samplingPreview && samplingConfig.mode === 'average' && (
                <span>
                  Averaged test run: {samplingPreview.blockCount} periods → one {samplingConfig.blockSize}-step
                  {' '}profile (weight ×{samplingPreview.scale.toFixed(2)})
                </span>
              )}
              {samplingPreview && samplingConfig.mode !== 'average' && (
                <span>
                  Sampled test run: {samplingPreview.blockCount}×{samplingConfig.blockSize} blocks,
                  {' '}{samplingPreview.sampledSnapshots} snapshots solved (weight ×{samplingPreview.scale.toFixed(2)})
                </span>
              )}
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
            </div>
            <p className="run-config-hint">
              Every run is saved automatically on the server — reopen it from History without re-running.
            </p>
          </div>
        </div>

        <div className="modal-actions">
          <button className="secondary-button" onClick={onClose}>Cancel</button>
          {!dryRun && (
            <button className="secondary-button" onClick={onAddScenario} title="Save this run configuration as a named scenario — compare and batch-run them in Settings → Scenarios">
              Add as Scenario
            </button>
          )}
          {!dryRun && (
            <button className="secondary-button" onClick={onQueueNext} title="Stage this run; activate it later from the Queue tab">
              Queue next Run
            </button>
          )}
          <button className="run-button" onClick={onRun}>
            {dryRun ? 'Validate' : 'Run model'}
          </button>
        </div>
      </div>
    </div>
  );
}
