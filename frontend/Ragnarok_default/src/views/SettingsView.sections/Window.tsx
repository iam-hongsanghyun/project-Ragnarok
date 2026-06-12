/**
 * Window section — simulation window (snapshot range), resolution weight, and
 * the sampled-blocks test-run mode (solve N blocks of B snapshots weighted to
 * represent the whole window).
 */
import React from 'react';
import { PathwayConfig, SamplingConfig } from 'lib/types';
import { DualRangeSlider } from '../../shared/components/DualRangeSlider';
import { NumberDraftInput } from '../../shared/components/NumberDraftInput';
import { RUN_WINDOW } from 'lib/constants';
import { computeSamplingPreview } from 'lib/results/sampling';
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
      <div className="sg-setting-row">
        <label className="sg-setting-label">Resolution — every {props.snapshotWeight}h</label>
        <div className="sg-btn-row">
          {RUN_WINDOW.weightOptions.map((n) => (
            <button
              key={n}
              className={`tb-btn sg-solver-btn${props.snapshotWeight === n ? '' : ' tb-btn--muted'}`}
              onClick={() => props.onSnapshotWeightChange(n)}
            >
              {n}h
            </button>
          ))}
        </div>
      </div>
      <SamplingRow {...props} windowSteps={steps} />
    </section>
  );
}

/** Sampled-blocks test run: solve N disjoint blocks of B snapshots, weighted
 *  so totals represent the full window. Disabled under pathway mode (the
 *  backend also rejects the combination). */
function SamplingRow(props: WindowSectionProps & { windowSteps: number }) {
  const cfg = props.samplingConfig;
  const patch = (next: Partial<SamplingConfig>) =>
    props.onSamplingConfigChange({ ...cfg, ...next });
  const preview = computeSamplingPreview(props.windowSteps, props.snapshotWeight, cfg);
  const summary = cfg.enabled
    ? `${preview.blockCount} block(s) · ${preview.sampledSnapshots} of ${props.windowSteps} steps solved · weight ×${preview.scale.toFixed(2)}`
    : 'off — the full window is solved contiguously';

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
            {cfg.mode === 'count' ? (
              <label>
                Blocks
                <NumberDraftInput
                  min={1}
                  max={Math.max(1, Math.floor(props.windowSteps / Math.max(1, cfg.blockSize)))}
                  value={cfg.blockCount}
                  onCommit={(v) => patch({ blockCount: Math.max(1, Math.round(v)) })}
                />
              </label>
            ) : (
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
            Totals (energy, cost, emissions, constraint budgets) are scaled to represent the
            full window. Storage and ramping stitch across block boundaries — use as a fast
            preview, not for storage sizing or peak adequacy.
          </div>
        </>
      )}
    </div>
  );
}
