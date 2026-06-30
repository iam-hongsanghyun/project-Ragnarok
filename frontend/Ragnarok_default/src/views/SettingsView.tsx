/**
 * Settings view — left section nav + active section editor.
 *
 * The view file is intentionally a thin shell: it owns layout + the
 * section enum, nothing else. Each section is one file under
 * `SettingsView.sections/`.
 */
import React from 'react';
import { usePersistedState } from 'shared/hooks/usePersistedState';
import { ResizablePanels } from '../layout/ResizablePanels';
import { LeftRail } from '../shared/components/primitives';
import {
  AppliedConstraint,
  CarbonPriceScheduleEntry,
  CarbonScheduleProfile,
  CustomConstraint,
  PathwayConfig,
  PowerFlowConfig,
  Primitive,
  RollingHorizonConfig,
  SamplingConfig,
  ScenarioCatalog,
  SecurityConstrainedConfig,
  StochasticConfig,
  WorkbookModel,
} from 'lib/types';
import { DateFormat, SolveAcceptance, SolverType } from '../features/settings/useSettings';

import { snapshotTimestamps } from 'lib/results/snapshotWindow';
import { ScenariosSection } from './SettingsView.sections/Scenarios';
import { WindowSection } from './SettingsView.sections/Window';
import { CarbonSection } from './SettingsView.sections/Carbon';
import { PlanningSection } from './SettingsView.sections/Planning';
import { RollingSection } from './SettingsView.sections/Rolling';
import { StochasticSection } from './SettingsView.sections/Stochastic/Stochastic';
import { SclopfSection } from './SettingsView.sections/Sclopf';
import { PowerFlowSection } from './SettingsView.sections/PowerFlow';
import { StandardConstraintsSection, AdvancedConstraintsSection } from './SettingsView.sections/Constraints';
import { AppearanceSection } from './SettingsView.sections/Appearance';
import { ProjectDefaultsSection } from './SettingsView.sections/ProjectDefaults';
import { SolverSection } from './SettingsView.sections/Solver';
import { ApiKeysSection } from './SettingsView.sections/ApiKeys';

type SectionId =
  | 'scenarios'
  | 'window'
  | 'carbon'
  | 'planning'
  | 'rolling'
  | 'stochastic'
  | 'sclopf'
  | 'powerflow'
  | 'constraints'
  | 'constraintsAdvanced'
  | 'appearance'
  | 'projectDefaults'
  | 'apiKeys'
  | 'solver';

type SectionGroup = 'Setup' | 'Policy' | 'Solve' | 'Data' | 'App';

interface Section {
  id: SectionId;
  label: string;
  group: SectionGroup;
}

const GROUPS: SectionGroup[] = ['Setup', 'Policy', 'Solve', 'Data', 'App'];

const SECTIONS: Section[] = [
  // Setup — what scenario and time span we're solving over
  { id: 'scenarios',  label: 'Scenarios',           group: 'Setup' },
  { id: 'window',     label: 'Simulation window',   group: 'Setup' },
  { id: 'planning',   label: 'Multi-year planning', group: 'Setup' },
  { id: 'rolling',    label: 'Rolling horizon',     group: 'Setup' },
  // Policy — economic / regulatory assumptions imposed on the model
  { id: 'carbon',             label: 'Carbon price',          group: 'Policy' },
  { id: 'constraints',        label: 'Standard Constraints',  group: 'Policy' },
  { id: 'constraintsAdvanced', label: 'Advanced Constraints', group: 'Policy' },
  // Solve — how the optimiser is run
  { id: 'stochastic', label: 'Stochastic',                    group: 'Solve' },
  { id: 'sclopf',     label: 'Security-constrained (SCLOPF)',  group: 'Solve' },
  { id: 'powerflow', label: 'Power flow',                     group: 'Solve' },
  { id: 'solver',     label: 'Solver',                        group: 'Solve' },
  // Data — external-source credentials
  { id: 'apiKeys',    label: 'API keys',                      group: 'Data' },
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
  samplingConfig: SamplingConfig;
  onSamplingConfigChange: (config: SamplingConfig) => void;
  stochasticConfig: StochasticConfig;
  onStochasticConfigChange: (config: StochasticConfig) => void;
  sclopfConfig: SecurityConstrainedConfig;
  onSclopfConfigChange: (config: SecurityConstrainedConfig) => void;
  powerFlowConfig: PowerFlowConfig;
  onPowerFlowConfigChange: (config: PowerFlowConfig) => void;
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
  carbonLibrary: CarbonScheduleProfile[];
  onCarbonLibraryChange: (next: CarbonScheduleProfile[]) => void;
  carbonCheck: { emittingGenerators: number; hasCo2Column: boolean; totalGenerators: number };
  currencySymbol: string;
  lineCount: number;
  transformerCount: number;

  // Constraints
  constraints: CustomConstraint[];
  onConstraintsChange: (next: CustomConstraint[]) => void;
  customDsl: string;
  onCustomDslChange: (text: string) => void;
  appliedConstraints?: AppliedConstraint[];
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
  solveAcceptance: SolveAcceptance;
  objectiveAutoScale: boolean;
  queuePollSeconds: number;
  onSolverThreadsChange: (v: number) => void;
  onSolverTypeChange: (v: SolverType) => void;
  onSolveAcceptanceChange: (v: SolveAcceptance) => void;
  onObjectiveAutoScaleChange: (v: boolean) => void;
  onQueuePollSecondsChange: (v: number) => void;
  onCarrierColorChange: (rowIndex: number, color: string) => void;
  onCarrierReorder: (fromIndex: number, toIndex: number) => void;
}

export function SettingsView(props: SettingsViewProps) {
  const [section, setSection] = usePersistedState<SectionId>('ui:settings-section', 'scenarios');
  const groups = GROUPS;

  return (
    <ResizablePanels id="settings-rail" direction="horizontal" className="settings-view" initialSizes={[20, 80]} minSize={180}>
      <LeftRail
        title="Settings"
        ariaLabel="Settings sections"
        className="settings-section-nav"
      >
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
      </LeftRail>

      <main className="settings-section-main">
        {section === 'scenarios'      && <ScenariosSection {...props} />}
        {section === 'window'         && <WindowSection {...props} snapshotTimestamps={snapshotTimestamps(props.model.snapshots)} />}
        {section === 'carbon'         && <CarbonSection {...props} />}
        {section === 'planning'       && <PlanningSection {...props} />}
        {section === 'rolling'        && <RollingSection {...props} />}
        {section === 'stochastic'     && <StochasticSection {...props} />}
        {section === 'sclopf'         && <SclopfSection {...props} />}
        {section === 'powerflow'      && <PowerFlowSection {...props} />}
        {section === 'constraints'    && <StandardConstraintsSection {...props} />}
        {section === 'constraintsAdvanced' && <AdvancedConstraintsSection {...props} />}
        {section === 'appearance'     && <AppearanceSection {...props} />}
        {section === 'projectDefaults' && <ProjectDefaultsSection {...props} />}
        {section === 'apiKeys'        && <ApiKeysSection />}
        {section === 'solver'         && <SolverSection {...props} />}
      </main>
    </ResizablePanels>
  );
}
