/**
 * Planning section — single-period vs. multi-year pathway investment.
 */
import React from 'react';
import { PathwayConfig } from 'lib/types';
import { SearchableSelect } from '../../shared/components/SearchableSelect';
import { NumberDraftInput } from '../../shared/components/NumberDraftInput';

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
                  <NumberDraftInput
                    className="sg-pathway-input"
                    value={row.period}
                    onCommit={(v) => onPathwayConfigChange({
                      ...pathwayConfig,
                      periods: pathwayConfig.periods.map((item, i) =>
                        i === index ? { ...item, period: v || item.period } : item,
                      ),
                    })}
                  />
                  <NumberDraftInput
                    step="0.1"
                    className="sg-pathway-input"
                    value={row.objectiveWeight}
                    onCommit={(v) => onPathwayConfigChange({
                      ...pathwayConfig,
                      periods: pathwayConfig.periods.map((item, i) =>
                        i === index ? { ...item, objectiveWeight: v || 1 } : item,
                      ),
                    })}
                  />
                  <NumberDraftInput
                    step="0.1"
                    className="sg-pathway-input"
                    value={row.yearsWeight}
                    onCommit={(v) => onPathwayConfigChange({
                      ...pathwayConfig,
                      periods: pathwayConfig.periods.map((item, i) =>
                        i === index ? { ...item, yearsWeight: v || 1 } : item,
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
            <SearchableSelect
              className="sg-setting-select"
              value={pathwayConfig.snapshotMappingMode}
              options={[
                { value: 'explicit_period_column', label: 'Use snapshots.period column' },
                { value: 'repeat_all_snapshots', label: 'Repeat all snapshots for each period' },
              ]}
              onChange={(v) => onPathwayConfigChange({
                ...pathwayConfig,
                snapshotMappingMode: v as PathwayConfig['snapshotMappingMode'],
              })}
            />
            <p className="sg-setting-hint">
              Pathway runs need either a <code>period</code> column on the snapshots sheet, or repeat-all mapping.
            </p>
          </div>
        </>
      )}
    </section>
  );
}
