/**
 * Scenarios section — preset library + active scenario metadata.
 */
import React from 'react';
import { ScenarioCatalog, ScenarioPreset } from 'lib/types';
import { TextDraftInput } from '../../shared/components/TextDraftInput';

export interface ScenariosSectionProps {
  scenarioCatalog: ScenarioCatalog;
  activeScenarioLabel: string | null;
  scenarioDirty: boolean;
  onSelectScenario: (scenarioId: string) => void;
  onCreateScenarioFromCurrent: () => void;
  onDuplicateScenario: () => void;
  onUpdateActiveScenarioFromCurrent: () => void;
  onDeleteScenario: () => void;
  onRenameScenario: (scenarioId: string, label: string) => void;
  onScenarioNotesChange: (scenarioId: string, notes: string) => void;
}

export function ScenariosSection(props: ScenariosSectionProps) {
  const {
    scenarioCatalog, activeScenarioLabel, scenarioDirty,
    onSelectScenario, onCreateScenarioFromCurrent, onDuplicateScenario,
    onUpdateActiveScenarioFromCurrent, onDeleteScenario,
    onRenameScenario, onScenarioNotesChange,
  } = props;
  const activeScenario: ScenarioPreset | null =
    scenarioCatalog.scenarios.find((s) => s.id === scenarioCatalog.activeScenarioId) ?? null;

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Scenarios</h3>
        <p>Capture the current constraints, simulation window, carbon price, pathway, rolling and stochastic settings as a named preset. Switch between presets to compare configurations.</p>
      </header>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Scenario library</label>
        <div className="period-pill-row">
          {scenarioCatalog.scenarios.map((scenario) => (
            <button
              key={scenario.id}
              className={`tb-btn period-pill${scenario.id === scenarioCatalog.activeScenarioId ? '' : ' tb-btn--muted'}`}
              onClick={() => onSelectScenario(scenario.id)}
              title={scenario.notes || scenario.label}
            >
              {scenario.label}
            </button>
          ))}
        </div>
      </div>
      <div className="sg-setting-row">
        <div className="sg-btn-row">
          <button className="tb-btn sg-solver-btn" onClick={onCreateScenarioFromCurrent}>New from current</button>
          <button
            className={`tb-btn sg-solver-btn${scenarioDirty ? '' : ' tb-btn--muted'}`}
            onClick={onUpdateActiveScenarioFromCurrent}
            disabled={!activeScenario}
          >
            Update active
          </button>
          <button className="tb-btn sg-solver-btn tb-btn--muted" onClick={onDuplicateScenario} disabled={!activeScenario}>
            Duplicate
          </button>
          <button
            className="tb-btn sg-solver-btn tb-btn--muted"
            onClick={onDeleteScenario}
            disabled={!activeScenario || scenarioCatalog.scenarios.length <= 1}
          >
            Delete
          </button>
        </div>
        {activeScenario && (
          <div className="sg-scenario-status">
            <span className={`sg-scenario-dot${scenarioDirty ? ' is-dirty' : ''}`} />
            <span>{scenarioDirty ? 'Current controls differ from the active scenario.' : 'Current controls match the active scenario.'}</span>
          </div>
        )}
      </div>
      {activeScenario && (
        <>
          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="set-scenario-label">Active scenario label</label>
            <TextDraftInput
              id="set-scenario-label"
              className="sg-num-input"
              value={activeScenario.label}
              onCommit={(v) => onRenameScenario(activeScenario.id, v)}
            />
          </div>
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="set-scenario-notes">Notes</label>
            <textarea
              id="set-scenario-notes"
              className="sg-scenario-notes"
              rows={3}
              value={activeScenario.notes}
              onChange={(e) => onScenarioNotesChange(activeScenario.id, e.target.value)}
            />
          </div>
          {activeScenarioLabel && (
            <div className="sg-setting-row">
              <div className="sg-scenario-summary">
                <span>Active: {activeScenarioLabel}</span>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
