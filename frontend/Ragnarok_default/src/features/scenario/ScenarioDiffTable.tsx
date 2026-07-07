/**
 * Scenario difference table — the Settings → Scenarios surface.
 *
 * ONE ROW PER SCENARIO. Columns are only the settings that DIFFER across the
 * scenarios (a "show all" toggle reveals the rest). Settings are authored via
 * the Run console ("Add as Scenario") and are read-only here; MODEL OVERRIDE
 * columns (capacity, etc.) are editable inline — that's how a scenario varies
 * the network. "Run all" queues the selected scenarios sequentially (queue
 * concurrency 1) or in parallel (N). Results are compared in Analytics.
 */
import React, { useMemo, useState } from 'react';
import type { ModelOverride, ScenarioCatalog, ScenarioPreset, WorkbookModel } from 'lib/types';
import { SearchableSelect } from 'shared/components/SearchableSelect';
import { getComponentSchema } from 'lib/constants/pypsa_schema';
import {
  cellValue,
  flattenScenario,
  overridePath,
  parseOverridePath,
  scenarioDiffColumns,
  setOverride,
} from './scenarioFields';

export type BatchMode = 'sequential' | 'parallel';

interface Props {
  catalog: ScenarioCatalog;
  model: WorkbookModel;
  maxConcurrency: number;
  onCatalogChange: (catalog: ScenarioCatalog) => void;
  onLoadScenario: (id: string) => void;
  onRunBatch: (ids: string[], mode: BatchMode, concurrency: number) => void;
  onGoToComparison: () => void;
  busy?: boolean;
}

export function ScenarioDiffTable({
  catalog, model, maxConcurrency, onCatalogChange, onLoadScenario, onRunBatch, onGoToComparison, busy,
}: Props) {
  const scenarios = catalog.scenarios;
  const [showAll, setShowAll] = useState(false);
  const [mode, setMode] = useState<BatchMode>('sequential');
  // The backend clamps to the real core count; keep the UI max at least 2 so the
  // parallel selector is usable even before the first queue poll reports cpuCount.
  const parallelMax = Math.max(2, maxConcurrency);
  const [concurrency, setConcurrency] = useState(2);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // Override columns added via the form but not yet valued on any scenario.
  const [extraOverrideCols, setExtraOverrideCols] = useState<string[]>([]);

  const diffColumns = useMemo(() => scenarioDiffColumns(scenarios, { includeAll: showAll }), [scenarios, showAll]);
  // Union the pending (empty) override columns so a just-added one is visible.
  const columns = useMemo(() => {
    const seen = new Set(diffColumns.map((c) => c.path));
    const extras = extraOverrideCols
      .filter((p) => !seen.has(p))
      .map((p) => ({ path: p, label: p.split('.').slice(1).join(' · '), group: 'Model', isOverride: true }));
    return [...diffColumns, ...extras];
  }, [diffColumns, extraOverrideCols]);

  const runIds = selected.size > 0 ? scenarios.filter((s) => selected.has(s.id)).map((s) => s.id) : scenarios.map((s) => s.id);

  const patchScenario = (id: string, next: ScenarioPreset) =>
    onCatalogChange({ ...catalog, scenarios: scenarios.map((s) => (s.id === id ? next : s)) });

  const editOverride = (id: string, path: string, value: string) => {
    const parsed = parseOverridePath(path);
    const scenario = scenarios.find((s) => s.id === id);
    if (!parsed || !scenario) return;
    const nextOverrides: ModelOverride[] = setOverride(scenario.modelOverrides ?? [], parsed.sheet, parsed.name, parsed.column, value);
    patchScenario(id, { ...scenario, modelOverrides: nextOverrides });
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
          Each scenario is a saved run configuration — add one from the <b>Run console</b> ("Add as Scenario").
          This table shows one row per scenario and only the settings that <b>differ</b>. Set a different
          <b> capacity</b> (or any model value) per scenario with a model override column. The network topology
          and custom-DSL constraints are shared across all scenarios. Compare <b>results</b> in Analytics → Comparison.
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

      <AddOverride model={model} onAdd={(path) => setExtraOverrideCols((prev) => (prev.includes(path) ? prev : [...prev, path]))} />

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
                  <td className="scenario-diff-td--name">{s.label}</td>
                  {columns.map((c) => (
                    <td key={c.path} className={c.isOverride ? 'scenario-diff-td--override' : ''}>
                      {c.isOverride ? (
                        <input
                          className="scenario-diff-input"
                          defaultValue={flat[c.path] ?? ''}
                          placeholder="—"
                          onBlur={(e) => editOverride(s.id, c.path, e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
                        />
                      ) : (
                        <span className={cellDiffers(scenarios, c.path) ? 'scenario-diff-cell--diff' : ''}>{cellValue(s, c.path)}</span>
                      )}
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
        <p className="sg-setting-hint">All scenarios have identical settings. Toggle “show all settings”, or add a model override to make them differ.</p>
      )}
    </section>
  );
}

function cellDiffers(scenarios: ScenarioPreset[], path: string): boolean {
  const vals = new Set(scenarios.map((s) => flattenScenario(s)[path] ?? ''));
  return vals.size > 1;
}

// ── add a model-override column (component · name · attribute) ────────────────────

function AddOverride({ model, onAdd }: { model: WorkbookModel; onAdd: (path: string) => void }) {
  const [open, setOpen] = useState(false);
  const [sheet, setSheet] = useState('');
  const [name, setName] = useState('');
  const [column, setColumn] = useState('');

  const sheetOptions = useMemo(
    () => Object.keys(model).filter((k) => Array.isArray(model[k]) && (model[k] as unknown[]).length > 0 && !k.startsWith('RAGNAROK_') && !k.includes('-')),
    [model],
  );
  const nameOptions = useMemo(() => {
    const rows = (model[sheet] as Array<Record<string, unknown>> | undefined) ?? [];
    return rows.map((r) => String(r.name ?? '')).filter(Boolean);
  }, [model, sheet]);
  const columnOptions = useMemo(() => {
    const comp = getComponentSchema(sheet);
    return comp ? comp.input_static_attributes.filter((a) => a !== 'name') : [];
  }, [sheet]);

  if (!open) {
    return (
      <div className="scenario-addoverride">
        <button className="tb-btn tb-btn--muted" onClick={() => setOpen(true)}>+ Add model override (e.g. capacity)</button>
      </div>
    );
  }
  return (
    <div className="scenario-addoverride is-open">
      <SearchableSelect className="forge-adjust-select" value={sheet} placeholder="component" options={sheetOptions} onChange={(v) => { setSheet(v); setName(''); setColumn(''); }} />
      <SearchableSelect className="forge-adjust-select" value={name} placeholder="which one" options={nameOptions} onChange={setName} />
      <SearchableSelect className="forge-adjust-select" value={column} placeholder="attribute (e.g. p_nom)" options={columnOptions} onChange={setColumn} />
      <button
        className="tb-btn"
        disabled={!sheet || !name || !column}
        onClick={() => { onAdd(overridePath(sheet, name, column)); setOpen(false); setSheet(''); setName(''); setColumn(''); }}
      >
        Add column
      </button>
      <button className="tb-btn tb-btn--muted" onClick={() => setOpen(false)}>Cancel</button>
    </div>
  );
}
