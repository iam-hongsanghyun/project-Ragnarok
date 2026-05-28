/**
 * Settings view — left section nav + active section editor.
 *
 * The view file is intentionally a thin shell: it owns layout + the
 * section enum, nothing else. Each section is one file under
 * `SettingsView.sections/`.
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
  SecurityConstrainedConfig,
  StochasticConfig,
  WorkbookModel,
} from '../shared/types';
import { DateFormat, SolverType } from '../features/settings/useSettings';

import { ScenariosSection } from './SettingsView.sections/Scenarios';
import { WindowSection } from './SettingsView.sections/Window';
import { CarbonSection } from './SettingsView.sections/Carbon';
import { PlanningSection } from './SettingsView.sections/Planning';
import { RollingSection } from './SettingsView.sections/Rolling';
import { StochasticSection } from './SettingsView.sections/Stochastic/Stochastic';
import { SclopfSection } from './SettingsView.sections/Sclopf';
import { ConstraintsSection } from './SettingsView.sections/Constraints';
import { ComponentTypesSection } from './SettingsView.sections/ComponentTypes';
import { AppearanceSection } from './SettingsView.sections/Appearance';
import { ProjectDefaultsSection } from './SettingsView.sections/ProjectDefaults';
import { SolverSection } from './SettingsView.sections/Solver';

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
  { id: 'scenarios',  label: 'Scenarios',         group: 'Run' },
  { id: 'window',     label: 'Simulation window', group: 'Run' },
  { id: 'carbon',     label: 'Carbon price',      group: 'Run' },
  { id: 'planning',   label: 'Multi-year planning', group: 'Run' },
  { id: 'rolling',    label: 'Rolling horizon',   group: 'Run' },
  { id: 'stochastic', label: 'Stochastic',        group: 'Run' },
  { id: 'sclopf',     label: 'Security-constrained (SCLOPF)', group: 'Run' },
  { id: 'constraints', label: 'Constraints',       group: 'Solve' },
  { id: 'types',       label: 'Component types',   group: 'Solve' },
  { id: 'appearance',       label: 'Appearance',       group: 'App' },
  { id: 'projectDefaults',  label: 'Project defaults', group: 'App' },
  { id: 'solver',           label: 'Solver',           group: 'App' },
];

export interface SettingsViewProps {
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
  currencySymbol: string;
  lineCount: number;
  transformerCount: number;

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
}

export function SettingsView(props: SettingsViewProps) {
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
        {section === 'scenarios'      && <ScenariosSection {...props} />}
        {section === 'window'         && <WindowSection {...props} />}
        {section === 'carbon'         && <CarbonSection {...props} />}
        {section === 'planning'       && <PlanningSection {...props} />}
        {section === 'rolling'        && <RollingSection {...props} />}
        {section === 'stochastic'     && <StochasticSection {...props} />}
        {section === 'sclopf'         && <SclopfSection {...props} />}
        {section === 'constraints'    && <ConstraintsSection {...props} />}
        {section === 'types'          && <ComponentTypesSection {...props} />}
        {section === 'appearance'     && <AppearanceSection {...props} />}
        {section === 'projectDefaults' && <ProjectDefaultsSection {...props} />}
        {section === 'solver'         && <SolverSection {...props} />}
      </main>
    </div>
  );
}
