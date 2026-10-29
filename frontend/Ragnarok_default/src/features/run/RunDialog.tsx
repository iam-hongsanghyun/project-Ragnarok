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
import { RESOLUTION_CHOICES_HOURS, type WorkbookResolution } from 'lib/results/resolution';

export interface RunDialogProps {
  open: boolean;
  onClose: () => void;

  forceLp: boolean;
  dryRun: boolean;
  activeScenarioLabel: string | null;
  activeConstraintCount: number;
  snapshotStart: number;
  snapshotEnd: number;
  pathwayConfig: PathwayConfig;
  rollingConfig: RollingHorizonConfig;
  samplingConfig: SamplingConfig;
  /** The workbook's resolution (weighting of its snapshots); changed only by the visible Resample transform. */
  resolution?: WorkbookResolution;
  /** Resample the working workbook to `hours` (writes snapshots, weightings and series; Forge → Temporal). */
  onApplyResolution?: (hours: number) => Promise<void> | void;

  onForceLpChange: (v: boolean) => void;
  onDryRunChange: (v: boolean) => void;

  /** "Run model" — runs now if the queue is idle, else next in line. */
  onRun: () => void;
  /** "Queue next Run" — parks the job as staged; the user activates it later. */
  onQueueNext: () => void;
  /** "Add as Scenario" — save the current run configuration as a named scenario
   *  (compare + batch-run them from Settings → Scenarios). */
  onAddScenario: () => void;
  /** "Export LP" - write the problem this run would hand the solver to an LP file and download it, without solving. */
  onExportLp?: () => void;
  /** An export is in progress (the button is disabled). */
  exportLpBusy?: boolean;
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
  pathwayConfig,
  rollingConfig,
  samplingConfig,
  resolution,
  onApplyResolution,
  onForceLpChange,
  onDryRunChange,
  onRun,
  onQueueNext,
  onAddScenario,
  onExportLp,
  exportLpBusy,
}: RunDialogProps) {
  if (!open) return null;

  const pathwayEnabled = pathwayConfig.enabled;
  const rollingEnabled = rollingConfig.enabled;
  const samplingEnabled = samplingConfig.enabled && !pathwayEnabled && !rollingEnabled;
  const samplingPreview = samplingEnabled
    ? computeSamplingPreview(Math.max(0, snapshotEnd - snapshotStart), samplingConfig)
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
              <span>{rollingEnabled ? rollingConfig.horizonHours != null ? `Rolling ${rollingConfig.horizonHours}h / ${rollingConfig.overlapHours ?? 0}h overlap` : `Rolling ${rollingConfig.horizonSnapshots}/${rollingConfig.overlapSnapshots} snapshots` : 'Full-horizon solve'}</span>
              <span>{pathwayEnabled ? 'Window comes from sidebar pathway settings' : `Window ${snapshotStart} → ${snapshotEnd}`}</span>
              <span>{resolution ? `${resolution.weightingHours}h resolution (workbook)` : 'Workbook resolution'}</span>
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
            <p className="validation-section-title">Resolution</p>
            <div className="sg-btn-row">
              {RESOLUTION_CHOICES_HOURS.map((n) => (
                <button
                  key={n}
                  data-tour="resolution"
                  disabled={!onApplyResolution}
                  className={`tb-btn${resolution && resolution.weightingHours === n ? '' : ' tb-btn--muted'}`}
                  title={`Resample the workbook to ${n}h (block means; weights ${n})`}
                  onClick={() => void onApplyResolution?.(n)}
                >
                  {n}h
                </button>
              ))}
            </div>
            <p className="run-config-hint">
              Resolution is written into the workbook by a visible Resample transform (Forge → Temporal): reduced snapshots,
              their weightings and block-mean series. The run does not stride the snapshots itself.
            </p>
          </div>

          <div className="validation-section">
            <p className="validation-section-title">Optimisation settings</p>
            <div className="sg-btn-row">
              {/* `data-tour` is the stable hook the Training walkthrough rings. */}
              <button
                data-tour="force-lp"
                className={`tb-btn${forceLp ? '' : ' tb-btn--muted'}`}
                onClick={() => onForceLpChange(!forceLp)}
              >
                Force LP
              </button>
              <button
                data-tour="dry-run"
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
          {onExportLp && (
            <button
              className="secondary-button" data-tour="export-lp" disabled={exportLpBusy} onClick={onExportLp}
              title="Build the model exactly as a run would and download its LP file, without solving"
            >
              Export LP
            </button>
          )}
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
          <button className="run-button" data-tour="run-submit" onClick={onRun}>
            {dryRun ? 'Validate' : 'Run model'}
          </button>
        </div>
      </div>
    </div>
  );
}
