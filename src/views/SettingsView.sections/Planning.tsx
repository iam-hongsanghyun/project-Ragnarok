/**
 * Planning section — single-period vs. multi-year pathway investment.
 */
import React from 'react';
import { PathwayConfig } from '../../shared/types';

export interface PlanningSectionProps {
  pathwayConfig: PathwayConfig;
  onPathwayConfigChange: (config: PathwayConfig) => void;
}

export function PlanningSection({ pathwayConfig, onPathwayConfigChange }: PlanningSectionProps) {
  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Multi-year planning</h3>
        <p>Single period solves one snapshot window. Pathway optimises investment + dispatch jointly across configured periods.</p>
      </header>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button
            className={`tb-btn sg-solver-btn${!pathwayConfig.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => onPathwayConfigChange({ ...pathwayConfig, enabled: false, planningMode: 'single_period' })}
          >
            Single period
          </button>
          <button
            className={`tb-btn sg-solver-btn${pathwayConfig.enabled ? '' : ' tb-btn--muted'}`}
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
      {pathwayConfig.enabled && (
        <>
          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label">Investment periods</label>
            <div className="sg-pathway-grid">
              <strong>Period</strong>
              <strong>Obj. weight</strong>
              <strong>Years</strong>
              <span />
              {pathwayConfig.periods.map((row, index) => (
                <React.Fragment key={`pathway-row-${index}`}>
                  <input
                    type="number"
                    className="sg-pathway-input"
                    value={row.period}
                    onChange={(e) => onPathwayConfigChange({
                      ...pathwayConfig,
                      periods: pathwayConfig.periods.map((item, i) =>
                        i === index ? { ...item, period: Number(e.target.value) || item.period } : item,
                      ),
                    })}
                  />
                  <input
                    type="number"
                    step="0.1"
                    className="sg-pathway-input"
                    value={row.objectiveWeight}
                    onChange={(e) => onPathwayConfigChange({
                      ...pathwayConfig,
                      periods: pathwayConfig.periods.map((item, i) =>
                        i === index ? { ...item, objectiveWeight: Number(e.target.value) || 1 } : item,
                      ),
                    })}
                  />
                  <input
                    type="number"
                    step="0.1"
                    className="sg-pathway-input"
                    value={row.yearsWeight}
                    onChange={(e) => onPathwayConfigChange({
                      ...pathwayConfig,
                      periods: pathwayConfig.periods.map((item, i) =>
                        i === index ? { ...item, yearsWeight: Number(e.target.value) || 1 } : item,
                      ),
                    })}
                  />
                  <button
                    className="tb-btn tb-btn--muted sg-pathway-remove"
                    onClick={() => onPathwayConfigChange({
                      ...pathwayConfig,
                      periods: pathwayConfig.periods.filter((_, i) => i !== index),
                    })}
                  >
                    ×
                  </button>
                </React.Fragment>
              ))}
            </div>
            <button
              className="tb-btn sg-full"
              style={{ marginTop: 8 }}
              onClick={() => {
                const last = pathwayConfig.periods[pathwayConfig.periods.length - 1]?.period ?? 2030;
                onPathwayConfigChange({
                  ...pathwayConfig,
                  periods: [...pathwayConfig.periods, { period: last + 10, objectiveWeight: 1, yearsWeight: 10 }],
                });
              }}
            >
              Add period
            </button>
          </div>
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-pathway-mapping">Snapshot mapping</label>
            <select
              id="rs-pathway-mapping"
              className="sg-setting-select"
              value={pathwayConfig.snapshotMappingMode}
              onChange={(e) => onPathwayConfigChange({
                ...pathwayConfig,
                snapshotMappingMode: e.target.value as PathwayConfig['snapshotMappingMode'],
              })}
            >
              <option value="explicit_period_column">Use snapshots.period column</option>
              <option value="repeat_all_snapshots">Repeat all snapshots for each period</option>
            </select>
            <p className="sg-setting-hint">
              Pathway runs need either a <code>period</code> column on the snapshots sheet, or repeat-all mapping.
            </p>
          </div>
        </>
      )}
    </section>
  );
}
