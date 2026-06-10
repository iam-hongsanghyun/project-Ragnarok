/**
 * Solver section — HiGHS thread and algorithm settings.
 */
import React from 'react';
import { SolveAcceptance, SolverType } from '../../features/settings/useSettings';
import { SETTINGS_CONFIG } from 'lib/constants';
import { NumberDraftInput } from '../../shared/components/NumberDraftInput';

export interface SolverSectionProps {
  solverThreads: number;
  solverType: SolverType;
  solveAcceptance: SolveAcceptance;
  objectiveAutoScale: boolean;
  queuePollSeconds: number;
  onSolverThreadsChange: (v: number) => void;
  onSolverTypeChange: (v: SolverType) => void;
  onSolveAcceptanceChange: (v: SolveAcceptance) => void;
  onObjectiveAutoScaleChange: (v: boolean) => void;
  onQueuePollSecondsChange: (v: number) => void;
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
        <label className="sg-setting-label">Method</label>
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
          HiGHS is always the solver; this picks its LP method. <b>Auto</b> lets
          HiGHS choose the fastest one (recommended). Simplex / IPM / PDLP pin a
          specific method. <b>HiPO</b> is HiGHS's newer interior-point solver —
          excellent on large energy LPs, but only in HiGHS builds compiled with
          it; where it's absent it falls back to IPM automatically, so it's safe
          to pick anywhere. (MIP / unit-commitment runs ignore this choice.)
        </p>
      </div>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Solution acceptance</label>
        <div className="sg-btn-row">
          {(SETTINGS_CONFIG.solveAcceptanceOptions as Array<{ value: SolveAcceptance; label: string }>).map(
            ({ value, label }) => (
              <button
                key={value}
                className={`tb-btn sg-solver-btn${props.solveAcceptance === value ? '' : ' tb-btn--muted'}`}
                onClick={() => props.onSolveAcceptanceChange(value)}
              >
                {label}
              </button>
            ),
          )}
        </div>
        <p className="sg-setting-hint">
          What counts as a successful solve. <b>Lenient</b> (recommended) accepts
          any solution the solver toolchain validated, including interior-point
          (IPM / HiPO) runs that finish without crossover and report
          condition=&apos;unknown&apos;. <b>Strict</b> requires
          condition=&apos;optimal&apos; — vertex-optimal solutions with exact
          shadow prices — and fails the run otherwise. Infeasible or unbounded
          models fail in both modes.
        </p>
      </div>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Auto-scale objective</label>
        <div className="sg-btn-row">
          {[
            { value: false, label: 'Off' },
            { value: true, label: 'On' },
          ].map(({ value, label }) => (
            <button
              key={label}
              className={`tb-btn sg-solver-btn${props.objectiveAutoScale === value ? '' : ' tb-btn--muted'}`}
              onClick={() => props.onObjectiveAutoScaleChange(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="sg-setting-hint">
          Passes HiGHS <code>user_objective_scale=-1</code> so a wide-ranging
          objective (costs spanning many orders of magnitude) is auto-scaled.
          <b>Results-neutral</b> — the reported objective is unscaled — and a
          no-op when already well-scaled, but it can markedly speed up simplex
          and PDLP on badly-scaled LPs. Recommended on.
        </p>
      </div>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Queue poll interval</label>
        <div className="sg-btn-row">
          <NumberDraftInput
            min={0.5}
            step={0.5}
            value={props.queuePollSeconds}
            emptyValue={props.queuePollSeconds}
            onCommit={(v) => props.onQueuePollSecondsChange(v)}
            style={{ width: 90 }}
          />
          <span className="sg-setting-hint" style={{ alignSelf: 'center' }}>seconds</span>
        </div>
        <p className="sg-setting-hint">
          How often the Queue tab refreshes <b>while a run is active</b> (live
          status + the "finished" notification). When the queue is idle it backs
          off automatically. Lower = snappier updates, more backend requests.
        </p>
      </div>
    </section>
  );
}
