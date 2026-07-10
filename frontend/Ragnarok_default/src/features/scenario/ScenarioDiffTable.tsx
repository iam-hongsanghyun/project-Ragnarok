/**
 * Scenario difference table — the Settings → Scenarios surface.
 *
 * ONE ROW PER SCENARIO. This surface is for naming scenarios and running them:
 * click a name to rename it, add the current run configuration as a new
 * scenario, pick which ones to run, and run them in order or in parallel.
 * Columns are only the settings that DIFFER across the scenarios (a "show all"
 * toggle reveals the rest); settings are authored via the Run console ("Add as
 * Scenario") and are read-only here. Model values are edited in Model/Forge,
 * not per scenario. Results are compared in Analytics.
 */
import React, { useMemo, useState } from 'react';
import type { ScenarioCatalog, ScenarioPreset } from 'lib/types';
import {
  cellValue,
  flattenScenario,
  scenarioDiffColumns,
} from './scenarioFields';

export type BatchMode = 'sequential' | 'parallel';

interface Props {
  catalog: ScenarioCatalog;
  maxConcurrency: number;
  onCatalogChange: (catalog: ScenarioCatalog) => void;
  onLoadScenario: (id: string) => void;
  /** Save the live run configuration as a new named scenario (prompts for the name). */
  onAddScenarioFromCurrent: () => void;
  onRunBatch: (ids: string[], mode: BatchMode, concurrency: number) => void;
  onGoToComparison: () => void;
  busy?: boolean;
}

export function ScenarioDiffTable({
  catalog, maxConcurrency, onCatalogChange, onLoadScenario, onAddScenarioFromCurrent, onRunBatch, onGoToComparison, busy,
}: Props) {
  const scenarios = catalog.scenarios;
  const [showAll, setShowAll] = useState(false);
  const [mode, setMode] = useState<BatchMode>('sequential');
  // The backend clamps to the real core count; keep the UI max at least 2 so the
  // parallel selector is usable even before the first queue poll reports cpuCount.
  const parallelMax = Math.max(2, maxConcurrency);
  const [concurrency, setConcurrency] = useState(2);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const columns = useMemo(() => scenarioDiffColumns(scenarios, { includeAll: showAll }), [scenarios, showAll]);

  const runIds = selected.size > 0 ? scenarios.filter((s) => selected.has(s.id)).map((s) => s.id) : scenarios.map((s) => s.id);

  const patchScenario = (id: string, next: ScenarioPreset) =>
    onCatalogChange({ ...catalog, scenarios: scenarios.map((s) => (s.id === id ? next : s)) });

  const renameScenario = (id: string, label: string) => {
    const scenario = scenarios.find((s) => s.id === id);
    const trimmed = label.trim();
    if (!scenario || !trimmed || trimmed === scenario.label) return;
    patchScenario(id, { ...scenario, label: trimmed });
  };

  const deleteScenario = (id: string) => {
    if (scenarios.length <= 1) return;
    const remaining = scenarios.filter((s) => s.id !== id);
    onCatalogChange({
      activeScenarioId: catalog.activeScenarioId === id ? (remaining[0]?.id ?? null) : catalog.activeScenarioId,
      scenarios: remaining,
    });
  };

  const toggleSelect = (id: string) =>
    setSelected((prev) => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Scenarios</h3>
        <p>
          Each scenario is a saved run configuration. Add one here from the current settings, or from the
          <b> Run console</b> ("Add as Scenario"). <b>Click a name to rename it.</b> The table shows one row per
          scenario and only the settings that <b>differ</b>; the network topology and custom-DSL constraints are
          shared across all scenarios. Compare <b>results</b> in Analytics → Comparison.
        </p>
      </header>

      {/* Run-all bar */}
      <div className="scenario-runbar">
        <div className="sg-btn-row">
          <button className={`tb-btn sg-solver-btn${mode === 'sequential' ? '' : ' tb-btn--muted'}`} onClick={() => setMode('sequential')}>In order</button>
          <button className={`tb-btn sg-solver-btn${mode === 'parallel' ? '' : ' tb-btn--muted'}`} onClick={() => setMode('parallel')}>In parallel</button>
          {mode === 'parallel' && (
            <label className="scenario-runbar__conc">
              up to
              <input
                type="number" min={2} max={parallelMax} value={concurrency}
                onChange={(e) => setConcurrency(Math.max(2, Math.min(parallelMax, Math.trunc(Number(e.target.value) || 2))))}
              />
              at once
            </label>
          )}
        </div>
        <button
          className="run-button"
          disabled={busy || runIds.length === 0}
          onClick={() => onRunBatch(runIds, mode, concurrency)}
        >
          {busy ? 'Queuing…' : `Run ${runIds.length} scenario${runIds.length === 1 ? '' : 's'} ${mode === 'sequential' ? 'in order' : `in parallel (${concurrency})`}`}
        </button>
        <button className="tb-btn tb-btn--muted" onClick={onGoToComparison}>Compare results →</button>
        <label className="scenario-runbar__toggle">
          <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> show all settings
        </label>
      </div>

      <div className="scenario-addcurrent">
        <button
          className="tb-btn tb-btn--muted"
          title="Save the live run configuration (sidebar + Run console settings) as a new named scenario"
          onClick={onAddScenarioFromCurrent}
        >
          + Add current settings as scenario
        </button>
      </div>

      <div className="scenario-diff-scroll">
        <table className="scenario-diff-table">
          <thead>
            <tr>
              <th className="scenario-diff-th--pick" />
              <th className="scenario-diff-th--name">Scenario</th>
              {columns.map((c) => (
                <th key={c.path} title={`${c.group} · ${c.path}`} className={c.isOverride ? 'scenario-diff-th--override' : ''}>
                  {c.label}
                </th>
              ))}
              <th className="scenario-diff-th--actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {scenarios.map((s) => {
              const flat = flattenScenario(s);
              return (
                <tr key={s.id} className={s.id === catalog.activeScenarioId ? 'is-active' : ''}>
                  <td className="scenario-diff-td--pick">
                    <input type="checkbox" checked={selected.has(s.id)} onChange={() => toggleSelect(s.id)} title="Include in Run all" />
                  </td>
                  <td className="scenario-diff-td--name">
                    <input
                      key={`${s.id}:${s.label}`}
                      className="scenario-name-input"
                      defaultValue={s.label}
                      title="Click to rename"
                      onBlur={(e) => renameScenario(s.id, e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
                    />
                  </td>
                  {columns.map((c) => (
                    <td key={c.path} className={c.isOverride ? 'scenario-diff-td--override' : ''}>
                      <span className={cellDiffers(scenarios, c.path) ? 'scenario-diff-cell--diff' : ''}>
                        {c.isOverride ? (flat[c.path] ?? '—') : cellValue(s, c.path)}
                      </span>
                    </td>
                  ))}
                  <td className="scenario-diff-td--actions">
                    <button className="tb-btn tb-btn--muted" title="Load this scenario's settings into the live controls" onClick={() => onLoadScenario(s.id)}>Load</button>
                    <button className="tb-btn tb-btn--muted" disabled={scenarios.length <= 1} onClick={() => deleteScenario(s.id)}>Delete</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {columns.length === 0 && (
        <p className="sg-setting-hint">All scenarios have identical settings — rename one and tweak the run controls, then “Add current settings as scenario”, or toggle “show all settings”.</p>
      )}
    </section>
  );
}

function cellDiffers(scenarios: ScenarioPreset[], path: string): boolean {
  const vals = new Set(scenarios.map((s) => flattenScenario(s)[path] ?? ''));
  return vals.size > 1;
}
