/**
 * Rolling horizon section — stitch many short solves into one result.
 */
import React from 'react';
import { RollingHorizonConfig } from '../../shared/types';
import { normalizeRollingConfig } from '../../shared/utils/rolling';

export interface RollingSectionProps {
  rollingConfig: RollingHorizonConfig;
  onRollingConfigChange: (config: RollingHorizonConfig) => void;
}

export function RollingSection({ rollingConfig, onRollingConfigChange }: RollingSectionProps) {
  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Rolling horizon</h3>
        <p>Stitch many short solves into one result. Independent from pathway mode; the backend hands each window to PyPSA in turn and forwards storage state.</p>
      </header>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button
            className={`tb-btn sg-solver-btn${!rollingConfig.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => onRollingConfigChange({ ...normalizeRollingConfig(rollingConfig), enabled: false })}
          >
            Off
          </button>
          <button
            className={`tb-btn sg-solver-btn${rollingConfig.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => onRollingConfigChange({ ...normalizeRollingConfig(rollingConfig), enabled: true })}
          >
            On
          </button>
        </div>
      </div>
      {rollingConfig.enabled && (
        <>
          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-rolling-horizon">Horizon (snapshots)</label>
            <input
              id="rs-rolling-horizon"
              type="number"
              min={1}
              step={1}
              className="sg-num-input"
              value={rollingConfig.horizonSnapshots}
              onChange={(e) => onRollingConfigChange({
                ...rollingConfig,
                horizonSnapshots: Number(e.target.value) || 1,
              })}
            />
          </div>
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-rolling-overlap">Overlap (snapshots)</label>
            <input
              id="rs-rolling-overlap"
              type="number"
              min={0}
              step={1}
              className="sg-num-input"
              value={rollingConfig.overlapSnapshots}
              onChange={(e) => onRollingConfigChange({
                ...rollingConfig,
                overlapSnapshots: Math.max(0, Number(e.target.value) || 0),
              })}
            />
          </div>
          <div className="sg-setting-row">
            <label className="sg-setting-label">Effective step</label>
            <div className="sg-setting-value">{rollingConfig.stepSnapshots} snapshots</div>
          </div>
        </>
      )}
    </section>
  );
}
