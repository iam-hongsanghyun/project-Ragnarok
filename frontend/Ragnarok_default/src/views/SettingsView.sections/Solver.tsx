/**
 * Solver section — HiGHS thread and algorithm settings.
 */
import React from 'react';
import { SolverType } from '../../features/settings/useSettings';
import { SETTINGS_CONFIG } from 'lib/constants';

export interface SolverSectionProps {
  solverThreads: number;
  solverType: SolverType;
  onSolverThreadsChange: (v: number) => void;
  onSolverTypeChange: (v: SolverType) => void;
}

export function SolverSection(props: SolverSectionProps) {
  const solverThreadOptions = SETTINGS_CONFIG.solverThreads.options;
  const solverTypes = SETTINGS_CONFIG.solverTypes as Array<{ value: SolverType; label: string }>;

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Solver settings</h3>
        <p>HiGHS configuration for the optimisation step.</p>
      </header>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Threads</label>
        <div className="sg-btn-row">
          {solverThreadOptions.map((n) => (
            <button
              key={n}
              className={`tb-btn sg-solver-btn${props.solverThreads === n ? '' : ' tb-btn--muted'}`}
              onClick={() => props.onSolverThreadsChange(n)}
            >
              {n === 0 ? 'auto' : String(n)}
            </button>
          ))}
        </div>
        <p className="sg-setting-hint">auto = HiGHS uses all available cores.</p>
      </div>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Algorithm</label>
        <div className="sg-btn-row">
          {solverTypes.map(({ value, label }) => (
            <button
              key={value}
              className={`tb-btn sg-solver-btn${props.solverType === value ? '' : ' tb-btn--muted'}`}
              onClick={() => props.onSolverTypeChange(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="sg-setting-hint">
          IPM (interior point) is often faster for large LP models. Use Simplex for MIP / unit-commitment runs.
        </p>
      </div>
    </section>
  );
}
