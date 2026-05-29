/**
 * Settings view — left section nav + active section editor.
 *
 * The view file is intentionally a thin shell: it owns layout + the
 * section enum, nothing else. Each section is one file under
 * `SettingsView.sections/`.
 */
import React from 'react';
import { usePersistedState } from '../shared/utils/usePersistedState';
import {
  CarbonPriceScheduleEntry,
  CustomConstraint,
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
  | 'appearance'
  | 'projectDefaults'
  | 'solver';

type SectionGroup = 'Setup' | 'Policy' | 'Solve' | 'App';

interface Section {
  id: SectionId;
  label: string;
  group: SectionGroup;
}

const GROUPS: SectionGroup[] = ['Setup', 'Policy', 'Solve', 'App'];

const SECTIONS: Section[] = [
  // Setup — what scenario and time span we're solving over
  { id: 'scenarios',  label: 'Scenarios',           group: 'Setup' },
  { id: 'window',     label: 'Simulation window',   group: 'Setup' },
  { id: 'planning',   label: 'Multi-year planning', group: 'Setup' },
  { id: 'rolling',    label: 'Rolling horizon',     group: 'Setup' },
  // Policy — economic / regulatory assumptions imposed on the model
  { id: 'carbon',      label: 'Carbon price', group: 'Policy' },
  { id: 'constraints', label: 'Constraints',  group: 'Policy' },
  // Solve — how the optimiser is run
  { id: 'stochastic', label: 'Stochastic',                    group: 'Solve' },
  { id: 'sclopf',     label: 'Security-constrained (SCLOPF)',  group: 'Solve' },
  { id: 'solver',     label: 'Solver',                        group: 'Solve' },
  // App — workspace preferences
  { id: 'appearance',      label: 'Appearance',       group: 'App' },
  { id: 'projectDefaults', label: 'Project defaults', group: 'App' },
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
  const [section, setSection] = usePersistedState<SectionId>('ui:settings-section', 'scenarios');
  const groups = GROUPS;

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
        {section === 'appearance'     && <AppearanceSection {...props} />}
        {section === 'projectDefaults' && <ProjectDefaultsSection {...props} />}
        {section === 'solver'         && <SolverSection {...props} />}
      </main>
    </div>
  );
}
