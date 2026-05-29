/**
 * Window section — simulation window (snapshot range) + resolution weight.
 */
import React from 'react';
import { PathwayConfig } from '../../shared/types';
import { DualRangeSlider } from '../../shared/components/DualRangeSlider';
import { RUN_WINDOW } from '../../constants';

export interface WindowSectionProps {
  pathwayConfig: PathwayConfig;
  maxSnapshots: number;
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  onSnapshotStartChange: (v: number) => void;
  onSnapshotEndChange: (v: number) => void;
  onSnapshotWeightChange: (v: number) => void;
}

export function WindowSection(props: WindowSectionProps) {
  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Simulation window</h3>
        <p>Snapshots the solver sees, and the time-weight applied to each.</p>
      </header>
      <div className="sg-setting-row">
        <label className="sg-setting-label">
          Window — {props.pathwayConfig.enabled
            ? `${props.maxSnapshots} steps (pathway uses full horizon)`
            : `${props.snapshotEnd - props.snapshotStart} of ${props.maxSnapshots} steps`}
        </label>
        {!props.pathwayConfig.enabled && props.maxSnapshots > 1 && (
          <DualRangeSlider
            min={0}
            max={props.maxSnapshots}
            low={props.snapshotStart}
            high={props.snapshotEnd}
            onChange={(lo, hi) => { props.onSnapshotStartChange(lo); props.onSnapshotEndChange(hi); }}
          />
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
