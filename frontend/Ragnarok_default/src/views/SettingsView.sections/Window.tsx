/**
 * Window section — simulation window (snapshot range), the workbook's resolution
 * (changed by a visible Resample transform), and the sampled-blocks test-run
 * module (N blocks of B snapshots whose weightings are written to represent the
 * whole window).
 */
import React from 'react';
import { PathwayConfig, SamplingConfig } from 'lib/types';
import { DualRangeSlider } from '../../shared/components/DualRangeSlider';
import { NumberDraftInput } from '../../shared/components/NumberDraftInput';
import { computeSamplingPreview } from 'lib/results/sampling';
import { RESOLUTION_CHOICES_HOURS, type WorkbookResolution } from 'lib/results/resolution';
import {
  endIndexForTime,
  isDatedAxis,
  snapshotInputValueAt,
  snapshotLabelAt,
  startIndexForTime,
} from 'lib/results/snapshotWindow';

export interface WindowSectionProps {
  pathwayConfig: PathwayConfig;
  maxSnapshots: number;
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  samplingConfig: SamplingConfig;
  /** Ordered ISO timestamps of the run axis, for the date-range picker. */
  snapshotTimestamps: string[];
  /** The workbook's own resolution: the weighting of its snapshots and their timestamp spacing. */
  resolution?: WorkbookResolution;
  /** Resample the working workbook to `hours` (Forge → Temporal, written into the workbook). */
  onApplyResolution?: (hours: number) => Promise<void> | void;
  /** Fill the snapshot weightings from the timestamp spacing (a visible action). */
  onSetWeightingsFromSpacing?: () => Promise<void> | void;
  onSnapshotStartChange: (v: number) => void;
  onSnapshotEndChange: (v: number) => void;
  onSnapshotWeightChange: (v: number) => void;
  onSamplingConfigChange: (config: SamplingConfig) => void;
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(v, hi));

export function WindowSection(props: WindowSectionProps) {
  const ts = props.snapshotTimestamps;
  const dated = isDatedAxis(ts);
  const firstValue = snapshotInputValueAt(ts, 0);
  const lastValue = snapshotInputValueAt(ts, ts.length - 1);
  const startValue = snapshotInputValueAt(ts, props.snapshotStart);
  // snapshotEnd is exclusive, so the last *included* snapshot is end − 1.
  const endValue = snapshotInputValueAt(ts, Math.max(props.snapshotStart, props.snapshotEnd - 1));
  const startLabel = snapshotLabelAt(ts, props.snapshotStart);
  const endLabel = snapshotLabelAt(ts, Math.max(props.snapshotStart, props.snapshotEnd - 1));

  const steps = props.snapshotEnd - props.snapshotStart;
  const windowLabel = props.pathwayConfig.enabled
    ? `${props.maxSnapshots} steps (pathway uses full horizon)`
    : dated && startLabel && endLabel
      ? `${startLabel} → ${endLabel} · ${steps} of ${props.maxSnapshots} steps`
      : `${steps} of ${props.maxSnapshots} steps`;

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Simulation window</h3>
        <p>Snapshots the solver sees, and the time-weight applied to each.</p>
      </header>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Window — {windowLabel}</label>
        {!props.pathwayConfig.enabled && props.maxSnapshots > 1 && (
          <>
            <DualRangeSlider
              min={0}
              max={props.maxSnapshots}
              low={props.snapshotStart}
              high={props.snapshotEnd}
              onChange={(lo, hi) => { props.onSnapshotStartChange(lo); props.onSnapshotEndChange(hi); }}
            />
            {/* Datetime-range picker — maps the chosen snapshots (date + time)
                onto indices. Shown only when the axis carries real datetimes. */}
            {dated && (
              <div className="sg-window-inputs">
                <label>
                  From
                  <input
                    type="datetime-local"
                    min={firstValue}
                    max={lastValue}
                    value={startValue}
                    onChange={(e) => {
                      if (!e.target.value) return;
                      const i = startIndexForTime(ts, e.target.value);
                      props.onSnapshotStartChange(clamp(i, 0, props.snapshotEnd - 1));
                    }}
                  />
                </label>
                <label>
                  To
                  <input
                    type="datetime-local"
                    min={startValue || firstValue}
                    max={lastValue}
                    value={endValue}
                    onChange={(e) => {
                      if (!e.target.value) return;
                      const end = endIndexForTime(ts, e.target.value);
                      props.onSnapshotEndChange(clamp(end, props.snapshotStart + 1, props.maxSnapshots));
                    }}
                  />
                </label>
              </div>
            )}
            {/* Typed boxes for an exact window — dragging a slider to e.g. 8784
                is impractical for a full-year run. */}
            <div className="sg-window-inputs">
              <label>
                Start
                <NumberDraftInput
                  min={0}
                  max={props.snapshotEnd}
                  value={props.snapshotStart}
                  onCommit={(v) => props.onSnapshotStartChange(Math.max(0, Math.min(Math.round(v), props.snapshotEnd)))}
                />
              </label>
              <label>
                End
                <NumberDraftInput
                  min={props.snapshotStart}
                  max={props.maxSnapshots}
                  value={props.snapshotEnd}
                  emptyValue={props.maxSnapshots}
                  onCommit={(v) => props.onSnapshotEndChange(Math.max(props.snapshotStart, Math.min(Math.round(v), props.maxSnapshots)))}
                />
              </label>
            </div>
          </>
        )}
      </div>
      <ResolutionRow {...props} />
      <SamplingRow {...props} windowSteps={steps} />
    </section>
  );
}

/** Resolution is a property of the workbook (its snapshots and weightings), changed by a visible Resample transform. */
function ResolutionRow(props: WindowSectionProps) {
  const res = props.resolution;
  const [busy, setBusy] = React.useState(false);
  const run = async (action?: () => Promise<void> | void) => {
    if (!action || busy) return;
    setBusy(true);
    try { await action(); } finally { setBusy(false); }
  };
  return (
    <div className="sg-setting-row">
      <label className="sg-setting-label">
        Resolution — {res ? `each snapshot is ${res.weightingHours}h in the solve` : 'from the workbook'}
        {res?.spacingHours != null && res.spacingHours !== res.weightingHours ? ` (timestamps ${res.spacingHours}h apart)` : ''}
      </label>
      <div className="sg-btn-row">
        {RESOLUTION_CHOICES_HOURS.map((n) => (
          <button
            key={n}
            disabled={busy || !props.onApplyResolution}
            className={`tb-btn sg-solver-btn${res && res.weightingHours === n ? '' : ' tb-btn--muted'}`}
            title={`Resample the workbook to ${n}h: block-mean series, weights ${n}, written into the workbook (Forge → Temporal)`}
            onClick={() => void run(() => props.onApplyResolution?.(n))}
          >
            {n}h
          </button>
        ))}
      </div>
      {res?.mismatch && (
        <div className="rolling-summary">
          The timestamps are {res.spacingHours}h apart but the weighting is {res.weightingHours}h, so PyPSA books
          {' '}{(res.weightingHours / (res.spacingHours ?? 1)).toFixed(2)}× the real energy.{' '}
          <button className="tb-btn" disabled={busy || !props.onSetWeightingsFromSpacing} onClick={() => void run(props.onSetWeightingsFromSpacing)}>
            Set weightings from timestamp spacing
          </button>
        </div>
      )}
      <div className="rolling-summary">
        Resampling is a visible transform: it writes the reduced snapshots, their weightings and the block-mean series into
        the workbook. The run never strides the snapshots itself.
      </div>
    </div>
  );
}

/** Sampled-blocks test run: solve N disjoint blocks of B snapshots, weighted
 *  so totals represent the full window. Disabled under pathway mode (the
 *  backend also rejects the combination). */
function SamplingRow(props: WindowSectionProps & { windowSteps: number }) {
  const cfg = props.samplingConfig;
  const patch = (next: Partial<SamplingConfig>) =>
    props.onSamplingConfigChange({ ...cfg, ...next });
  const preview = computeSamplingPreview(props.windowSteps, cfg);
  const summary = !cfg.enabled
    ? 'off — the full window is solved contiguously'
    : cfg.mode === 'average'
      ? `${preview.blockCount} period(s) averaged into one ${cfg.blockSize}-step profile · ${preview.sampledSnapshots} steps solved · weight ×${preview.scale.toFixed(2)}`
      : `${preview.blockCount} block(s) · ${preview.sampledSnapshots} of ${props.windowSteps} steps solved · weight ×${preview.scale.toFixed(2)}`;

  if (props.pathwayConfig.enabled) {
    return (
      <div className="sg-setting-row">
        <label className="sg-setting-label">Sampling (test run)</label>
        <div className="rolling-summary">Not available in pathway mode — periods already define the horizon.</div>
      </div>
    );
  }

  return (
    <div className="sg-setting-row">
      <label className="sg-setting-label">Sampling (test run) — {summary}</label>
      <div className="sg-btn-row">
        <button
          className={`tb-btn sg-solver-btn${!cfg.enabled ? '' : ' tb-btn--muted'}`}
          onClick={() => patch({ enabled: false })}
        >
          Contiguous window
        </button>
        <button
          className={`tb-btn sg-solver-btn${cfg.enabled ? '' : ' tb-btn--muted'}`}
          onClick={() => patch({ enabled: true })}
        >
          Sampled blocks
        </button>
      </div>
      {cfg.enabled && (
        <>
          <div className="sg-btn-row">
            <button
              className={`tb-btn sg-solver-btn${cfg.mode === 'count' ? '' : ' tb-btn--muted'}`}
              onClick={() => patch({ mode: 'count' })}
            >
              N equal blocks
            </button>
            <button
              className={`tb-btn sg-solver-btn${cfg.mode === 'gap' ? '' : ' tb-btn--muted'}`}
              onClick={() => patch({ mode: 'gap' })}
            >
              Block + gap
            </button>
            <button
              className={`tb-btn sg-solver-btn${cfg.mode === 'average' ? '' : ' tb-btn--muted'}`}
              onClick={() => patch({ mode: 'average' })}
            >
              Averaged profile
            </button>
          </div>
          <div className="sg-window-inputs">
            <label>
              Block size (snapshots)
              <NumberDraftInput
                min={1}
                max={props.windowSteps}
                value={cfg.blockSize}
                onCommit={(v) => patch({ blockSize: Math.max(1, Math.round(v)) })}
              />
            </label>
            {cfg.mode === 'count' && (
              <label>
                Blocks
                <NumberDraftInput
                  min={1}
                  max={Math.max(1, Math.floor(props.windowSteps / Math.max(1, cfg.blockSize)))}
                  value={cfg.blockCount}
                  onCommit={(v) => patch({ blockCount: Math.max(1, Math.round(v)) })}
                />
              </label>
            )}
            {cfg.mode === 'gap' && (
              <label>
                Gap (snapshots)
                <NumberDraftInput
                  min={0}
                  max={props.windowSteps}
                  value={cfg.gapSnapshots}
                  onCommit={(v) => patch({ gapSnapshots: Math.max(0, Math.round(v)) })}
                />
              </label>
            )}
          </div>
          <div className="rolling-summary">
            {cfg.mode === 'average'
              ? 'Every period of the window is averaged into one synthetic profile: annual '
                + 'energy totals are exact, but averaging smooths peaks — curtailment, storage '
                + 'value and scarcity prices will be underestimated. Screening tool only.'
              : 'Totals (energy, cost, emissions, constraint budgets) are scaled to represent '
                + 'the full window. Storage and ramping stitch across block boundaries — use as '
                + 'a fast preview, not for storage sizing or peak adequacy.'}
          </div>
        </>
      )}
    </div>
  );
}
