/**
 * Settings view — every "how do I want this to solve" + project-level
 * preferences knob lives here, exactly once.
 *
 * Left rail = section nav. Main area = the active section's editor.
 * No tabs within tabs, no overlays, no close buttons.
 */
import React, { useState } from 'react';
import {
  CarbonPriceScheduleEntry,
  CustomConstraint,
  GridRow,
  PathwayConfig,
  Primitive,
  RollingHorizonConfig,
  ScenarioCatalog,
  ScenarioPreset,
  SecurityConstrainedConfig,
  StochasticConfig,
  WorkbookModel,
} from '../shared/types';
import {
  CarbonPriceTab,
  PlanningTab,
  RollingTab,
  SclopfTab,
  StochasticTab,
  WindowAndWeightsTab,
} from '../features/run-setup/RunSetupWorkspaceView';
import {
  AppearanceTab,
  ProjectDefaultsTab,
  SolverTab,
} from '../features/settings/SettingsWorkspaceView';
import { GlobalConstraintsTableEditor } from '../features/constraints/ConstraintsWorkspaceView';
import { GlobalConstraintsSection as CustomConstraintsEditor } from '../features/constraints/GlobalConstraintsSection';
import { DateFormat, SolverType } from '../features/settings/useSettings';
import {
  PYPSA_STANDARD_LINE_TYPES,
  PYPSA_STANDARD_TRANSFORMER_TYPES,
  PYPSA_STANDARD_TYPES_SOURCE,
} from '../constants/pypsa_standard_types';
import { stringValue } from '../shared/utils/helpers';

type SectionId =
  | 'scenarios'
  | 'window'
  | 'carbon'
  | 'planning'
  | 'rolling'
  | 'stochastic'
  | 'sclopf'
  | 'constraints'
  | 'types'
  | 'appearance'
  | 'projectDefaults'
  | 'solver';

interface Section {
  id: SectionId;
  label: string;
  group: 'Run' | 'Solve' | 'App';
}

const SECTIONS: Section[] = [
  // Run (per-solve)
  { id: 'scenarios',  label: 'Scenarios',         group: 'Run' },
  { id: 'window',     label: 'Simulation window', group: 'Run' },
  { id: 'carbon',     label: 'Carbon price',      group: 'Run' },
  { id: 'planning',   label: 'Multi-year planning', group: 'Run' },
  { id: 'rolling',    label: 'Rolling horizon',   group: 'Run' },
  { id: 'stochastic', label: 'Stochastic',        group: 'Run' },
  { id: 'sclopf',     label: 'Security-constrained (SCLOPF)', group: 'Run' },
  // Model setup
  { id: 'constraints', label: 'Constraints',       group: 'Solve' },
  { id: 'types',       label: 'Component types',   group: 'Solve' },
  // Project / app preferences
  { id: 'appearance',       label: 'Appearance',       group: 'App' },
  { id: 'projectDefaults',  label: 'Project defaults', group: 'App' },
  { id: 'solver',           label: 'Solver',           group: 'App' },
];

interface Props {
  model: WorkbookModel;

  // Scenarios
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

  // Run setup
  pathwayConfig: PathwayConfig;
  onPathwayConfigChange: (config: PathwayConfig) => void;
  rollingConfig: RollingHorizonConfig;
  onRollingConfigChange: (config: RollingHorizonConfig) => void;
  stochasticConfig: StochasticConfig;
  onStochasticConfigChange: (config: StochasticConfig) => void;
  sclopfConfig: SecurityConstrainedConfig;
  onSclopfConfigChange: (config: SecurityConstrainedConfig) => void;
  maxSnapshots: number;
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  onSnapshotStartChange: (v: number) => void;
  onSnapshotEndChange: (v: number) => void;
  onSnapshotWeightChange: (v: number) => void;
  carbonPrice: number;
  onCarbonPriceChange: (v: number) => void;
  carbonPriceSchedule: CarbonPriceScheduleEntry[];
  onCarbonPriceScheduleChange: (next: CarbonPriceScheduleEntry[]) => void;

  // Constraints
  constraints: CustomConstraint[];
  onConstraintsChange: (next: CustomConstraint[]) => void;
  onUpdateRow: (sheet: 'global_constraints', rowIndex: number, key: string, value: Primitive) => void;
  onAddRow: (sheet: 'global_constraints') => void;
  onDeleteRow: (sheet: 'global_constraints', rowIndex: number) => void;
  onAddStandardType: (sheet: 'line_types' | 'transformer_types', row: GridRow) => void;

  // App preferences
  dateFormat: DateFormat;
  onDateFormatChange: (f: DateFormat) => void;
  currencyCode: string;
  currencySymbol: string;
  onCurrencyChange: (code: string, symbol: string) => void;
  discountRate: number;
  onDiscountRateChange: (v: number) => void;
  enableLoadShedding: boolean;
  onEnableLoadSheddingChange: (v: boolean) => void;
  loadSheddingCost: number;
  onLoadSheddingCostChange: (v: number) => void;
  solverThreads: number;
  solverType: SolverType;
  onSolverThreadsChange: (v: number) => void;
  onSolverTypeChange: (v: SolverType) => void;
  onCarrierColorChange: (rowIndex: number, color: string) => void;
  onCarrierMove: (rowIndex: number, direction: -1 | 1) => void;

  lineCount: number;
  transformerCount: number;
}

export function SettingsView(props: Props) {
  const [section, setSection] = useState<SectionId>('scenarios');
  const groups = ['Run', 'Solve', 'App'] as const;

  return (
    <div className="settings-view">
      <aside className="settings-section-nav" aria-label="Settings sections">
        {groups.map((g) => (
          <div key={g} className="settings-nav-group">
            <div className="settings-nav-group-title">{g}</div>
            {SECTIONS.filter((s) => s.group === g).map((s) => (
              <button
                key={s.id}
                className={`settings-nav-item${section === s.id ? ' settings-nav-item--active' : ''}`}
                onClick={() => setSection(s.id)}
              >
                {s.label}
              </button>
            ))}
          </div>
        ))}
      </aside>

      <main className="settings-section-main">
        {section === 'scenarios'  && <ScenariosSection {...props} />}
        {section === 'window'     && <WindowAndWeightsTab {...props} />}
        {section === 'carbon'     && <CarbonPriceTab {...props} />}
        {section === 'planning'   && <PlanningTab {...props} />}
        {section === 'rolling'    && <RollingTab {...props} />}
        {section === 'stochastic' && <StochasticTab {...props} />}
        {section === 'sclopf'     && <SclopfTab {...props} />}
        {section === 'constraints' && <ConstraintsSection {...props} />}
        {section === 'types'      && <ComponentTypesSection {...props} />}
        {section === 'appearance'      && <AppearanceTab {...props} />}
        {section === 'projectDefaults' && <ProjectDefaultsTab {...props} />}
        {section === 'solver'          && <SolverTab {...props} />}
      </main>
    </div>
  );
}

// ── Scenarios section ───────────────────────────────────────────────────────

function ScenariosSection(props: Props): JSX.Element {
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
            <input
              id="set-scenario-label"
              type="text"
              className="sg-num-input"
              value={activeScenario.label}
              onChange={(e) => onRenameScenario(activeScenario.id, e.target.value)}
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

// ── Constraints section (custom + global stacked, no internal tabs) ──────────

function ConstraintsSection(props: Props): JSX.Element {
  const carriers = Array.from(
    new Set(props.model.carriers.map((c) => String(c.name ?? '')).filter(Boolean)),
  );
  const globalRows = (props.model.global_constraints ?? []) as GridRow[];
  return (
    <>
      <section className="constraints-workspace-section">
        <header className="constraints-workspace-section-header">
          <h3>Custom solver constraints</h3>
          <p>Applied as <code>linopy</code> constraints during the solve. Preset rows are always present; custom rows append to the list.</p>
        </header>
        <CustomConstraintsEditor
          constraints={props.constraints}
          carriers={carriers}
          onChange={props.onConstraintsChange}
        />
      </section>
      <div className="sg-setting-divider" style={{ margin: '24px 0' }} />
      <section className="constraints-workspace-section">
        <header className="constraints-workspace-section-header">
          <h3>PyPSA <code>global_constraints</code> sheet</h3>
          <p>Native PyPSA constraints that flow through the generic import path and persist as rows in the <code>global_constraints</code> workbook sheet.</p>
        </header>
        <GlobalConstraintsTableEditor
          rows={globalRows}
          carriers={carriers}
          onAdd={() => props.onAddRow('global_constraints')}
          onDelete={(rowIndex) => props.onDeleteRow('global_constraints', rowIndex)}
          onSet={(rowIndex, key, value) => props.onUpdateRow('global_constraints', rowIndex, key, value)}
        />
      </section>
    </>
  );
}

// ── Component types catalogue (read-only + "Add to model") ──────────────────

function ComponentTypesSection(props: Props): JSX.Element {
  const lineTypes = (props.model.line_types ?? []) as GridRow[];
  const transformerTypes = (props.model.transformer_types ?? []) as GridRow[];
  const modelLineNames = new Set(lineTypes.map((r) => stringValue(r.name)));
  const modelXfmrNames = new Set(transformerTypes.map((r) => stringValue(r.name)));

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Component types</h3>
        <p>
          PyPSA-native <code>line_types</code> and <code>transformer_types</code> catalogues.
          The {PYPSA_STANDARD_LINE_TYPES.length} standard line types and {PYPSA_STANDARD_TRANSFORMER_TYPES.length} standard transformer types ship with PyPSA
          ({PYPSA_STANDARD_TYPES_SOURCE.repo} @ {(PYPSA_STANDARD_TYPES_SOURCE.commit ?? '').slice(0, 7) || 'unknown'}).
          They're already available for use in the <code>type</code> column of lines / transformers — clicking <em>Add to model</em> only copies the row into your workbook so you can edit it.
        </p>
      </header>

      <h4 style={{ marginTop: 16, marginBottom: 6 }}>Line types — standard catalogue ({PYPSA_STANDARD_LINE_TYPES.length})</h4>
      <CatalogueTable
        rows={PYPSA_STANDARD_LINE_TYPES}
        cols={[
          { key: 'name', label: 'Name' },
          { key: 'f_nom', label: 'f_nom (Hz)' },
          { key: 'r_per_length', label: 'r (Ω/km)' },
          { key: 'x_per_length', label: 'x (Ω/km)' },
          { key: 'c_per_length', label: 'c (nF/km)' },
          { key: 'i_nom', label: 'i_nom (kA)' },
          { key: 'mounting', label: 'Mounting' },
          { key: 'cross_section', label: 'Cross section (mm²)' },
        ]}
        alreadyInModel={modelLineNames}
        onAdd={(row) => props.onAddStandardType('line_types', row)}
      />

      <h4 style={{ marginTop: 24, marginBottom: 6 }}>Transformer types — standard catalogue ({PYPSA_STANDARD_TRANSFORMER_TYPES.length})</h4>
      <CatalogueTable
        rows={PYPSA_STANDARD_TRANSFORMER_TYPES}
        cols={[
          { key: 'name', label: 'Name' },
          { key: 's_nom', label: 's_nom (MVA)' },
          { key: 'v_nom_0', label: 'v_nom_0 (kV)' },
          { key: 'v_nom_1', label: 'v_nom_1 (kV)' },
          { key: 'vsc', label: 'vsc (%)' },
          { key: 'vscr', label: 'vscr (%)' },
          { key: 'pfe', label: 'pfe (kW)' },
          { key: 'i0', label: 'i0 (%)' },
        ]}
        alreadyInModel={modelXfmrNames}
        onAdd={(row) => props.onAddStandardType('transformer_types', row)}
      />
    </section>
  );
}

function CatalogueTable({
  rows, cols, alreadyInModel, onAdd,
}: {
  rows: GridRow[];
  cols: Array<{ key: string; label: string }>;
  alreadyInModel: Set<string>;
  onAdd: (row: GridRow) => void;
}): JSX.Element {
  const [filter, setFilter] = useState('');
  const filtered = filter.trim()
    ? rows.filter((row) => Object.values(row).some((v) => String(v ?? '').toLowerCase().includes(filter.toLowerCase())))
    : rows;
  return (
    <div className="constraints-table-wrap">
      <input
        type="text"
        className="constraints-cell-input"
        placeholder="Filter…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        style={{ maxWidth: 240, marginBottom: 6 }}
      />
      <table className="constraints-table">
        <thead>
          <tr>
            {cols.map((c) => <th key={c.key}>{c.label}</th>)}
            <th aria-label="actions" />
          </tr>
        </thead>
        <tbody>
          {filtered.map((row, i) => {
            const name = stringValue(row.name);
            const inModel = alreadyInModel.has(name);
            return (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c.key}>{stringValue(row[c.key]) || <span style={{ color: 'var(--muted)' }}>—</span>}</td>
                ))}
                <td>
                  <button className="tb-btn" disabled={inModel} onClick={() => onAdd(row)}>
                    {inModel ? 'In model' : 'Add'}
                  </button>
                </td>
              </tr>
            );
          })}
          {filtered.length === 0 && (
            <tr><td colSpan={cols.length + 1} style={{ color: 'var(--muted)', textAlign: 'center', padding: '12px 0' }}>No matches.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
