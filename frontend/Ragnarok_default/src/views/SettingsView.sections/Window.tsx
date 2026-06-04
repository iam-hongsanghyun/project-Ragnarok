/**
 * Window section — simulation window (snapshot range) + resolution weight.
 */
import React from 'react';
import { PathwayConfig } from 'lib/types';
import { DualRangeSlider } from '../../shared/components/DualRangeSlider';
import { RUN_WINDOW } from 'lib/constants';
import {
  endIndexForDate,
  isDatedAxis,
  snapshotDateAt,
  startIndexForDate,
} from 'lib/results/snapshotWindow';

export interface WindowSectionProps {
  pathwayConfig: PathwayConfig;
  maxSnapshots: number;
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  /** Ordered ISO timestamps of the run axis, for the date-range picker. */
  snapshotTimestamps: string[];
  onSnapshotStartChange: (v: number) => void;
  onSnapshotEndChange: (v: number) => void;
  onSnapshotWeightChange: (v: number) => void;
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(v, hi));

export function WindowSection(props: WindowSectionProps) {
  const ts = props.snapshotTimestamps;
  const dated = isDatedAxis(ts);
  const firstDate = snapshotDateAt(ts, 0);
  const lastDate = snapshotDateAt(ts, ts.length - 1);
  const startDate = snapshotDateAt(ts, props.snapshotStart);
  // snapshotEnd is exclusive, so the last *included* snapshot is end − 1.
  const endDate = snapshotDateAt(ts, Math.max(props.snapshotStart, props.snapshotEnd - 1));

  const steps = props.snapshotEnd - props.snapshotStart;
  const windowLabel = props.pathwayConfig.enabled
    ? `${props.maxSnapshots} steps (pathway uses full horizon)`
    : dated && startDate && endDate
      ? `${startDate} → ${endDate} · ${steps} of ${props.maxSnapshots} steps`
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
            {/* Date-range picker — maps the chosen days onto snapshot indices.
                Shown only when the run axis carries real calendar dates. */}
            {dated && (
              <div className="sg-window-inputs">
                <label>
                  From
                  <input
                    type="date"
                    min={firstDate}
                    max={lastDate}
                    value={startDate}
                    onChange={(e) => {
                      if (!e.target.value) return;
                      const i = startIndexForDate(ts, e.target.value);
                      props.onSnapshotStartChange(clamp(i, 0, props.snapshotEnd - 1));
                    }}
                  />
                </label>
                <label>
                  To
                  <input
                    type="date"
                    min={startDate || firstDate}
                    max={lastDate}
                    value={endDate}
                    onChange={(e) => {
                      if (!e.target.value) return;
                      const end = endIndexForDate(ts, e.target.value);
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
                <input
                  type="number"
                  min={0}
                  max={props.snapshotEnd}
                  value={props.snapshotStart}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    if (!Number.isFinite(v)) return;
                    props.onSnapshotStartChange(Math.max(0, Math.min(Math.round(v), props.snapshotEnd)));
                  }}
                />
              </label>
              <label>
                End
                <input
                  type="number"
                  min={props.snapshotStart}
                  max={props.maxSnapshots}
                  value={props.snapshotEnd}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    if (!Number.isFinite(v)) return;
                    props.onSnapshotEndChange(Math.max(props.snapshotStart, Math.min(Math.round(v), props.maxSnapshots)));
                  }}
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
    </section>
  );
}
