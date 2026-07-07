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
  ContingencyConfig,
  MarketSimConfig,
  PowerFlowConfig,
  MgaConfig,
  MerchantConfig,
  BidStrategyConfig,
  AssetSwapConfig,
  EssConfig,
  PpaConfig,
  DemandResponseConfig,
  FinanceConfig,
  Primitive,
  RollingHorizonConfig,
  SamplingConfig,
  ScenarioCatalog,
  SecurityConstrainedConfig,
  StochasticConfig,
  ValuePoint,
  WorkbookModel,
} from 'lib/types';
import { DateFormat, SolveAcceptance, SolverType } from '../features/settings/useSettings';

import { snapshotTimestamps } from 'lib/results/snapshotWindow';
import { ScenariosSection } from './SettingsView.sections/Scenarios';
import type { BatchMode } from '../features/scenario/ScenarioDiffTable';
import { WindowSection } from './SettingsView.sections/Window';
import { CarbonSection } from './SettingsView.sections/Carbon';
import { PlanningSection } from './SettingsView.sections/Planning';
import { RollingSection } from './SettingsView.sections/Rolling';
import { StochasticSection } from './SettingsView.sections/Stochastic/Stochastic';
import { SclopfSection } from './SettingsView.sections/Sclopf';
import { PowerFlowSection } from './SettingsView.sections/PowerFlow';
import { MarketSimulationSection } from './SettingsView.sections/MarketSimulation';
import { ContingencySection } from './SettingsView.sections/Contingency';
import { MgaSection } from './SettingsView.sections/Mga';
import { MerchantSection } from './SettingsView.sections/Merchant';
import { BiddingSection } from './SettingsView.sections/Bidding';
import { AssetSwapSection } from './SettingsView.sections/AssetSwap';
import { EssSection } from './SettingsView.sections/Ess';
import { PpaSection } from './SettingsView.sections/Ppa';
import { DemandResponseSection } from './SettingsView.sections/DemandResponse';
import { DecisionsSection } from './SettingsView.sections/Decisions';
import { ProcurementSection } from './SettingsView.sections/Procurement';
import { CompanySection } from './SettingsView.sections/Company';
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
  | 'demandResponse'
  | 'stochastic'
  | 'sclopf'
  | 'powerflow'
  | 'marketsim'
  | 'contingency'
  | 'mga'
  | 'decisions'
  | 'procurement'
  | 'merchant'
  | 'bidding'
  | 'assetSwap'
  | 'ess'
  | 'ppa'
  | 'company'
  | 'constraints'
  | 'constraintsAdvanced'
  | 'appearance'
  | 'projectDefaults'
  | 'apiKeys'
  | 'solver';

type SectionGroup = 'Setup' | 'Solve' | 'Data' | 'App' | 'Market' | 'Policy' | 'Analysis';

interface Section {
  id: SectionId;
  label: string;
  group: SectionGroup;
}

// Order across the three views. Technical (Settings) shows Setup/Solve/Data/App;
// Market & Policy shows Market/Policy (inputs that change the solve); Post-analysis
// shows Analysis (tools that read results but don't change the solve).
const GROUPS: SectionGroup[] = ['Setup', 'Solve', 'Data', 'App', 'Market', 'Policy', 'Analysis'];
const TECHNICAL_GROUPS: SectionGroup[] = ['Setup', 'Solve', 'Data', 'App'];
const MARKET_GROUPS: SectionGroup[] = ['Market', 'Policy'];
const ANALYSIS_GROUPS: SectionGroup[] = ['Analysis'];

const SECTIONS: Section[] = [
  // Setup — what scenario and time span we're solving over
  { id: 'scenarios',  label: 'Scenarios',           group: 'Setup' },
  { id: 'window',     label: 'Simulation window',   group: 'Setup' },
  { id: 'planning',   label: 'Multi-year planning', group: 'Setup' },
  { id: 'rolling',    label: 'Rolling horizon',     group: 'Setup' },
  { id: 'demandResponse', label: 'Demand response',  group: 'Setup' },
  // Policy — economic / regulatory assumptions imposed on the model
  { id: 'carbon',             label: 'Carbon price',          group: 'Policy' },
  { id: 'constraints',        label: 'Standard Constraints',  group: 'Policy' },
  { id: 'constraintsAdvanced', label: 'Advanced Constraints', group: 'Policy' },
  // Solve — how the optimiser is run
  { id: 'stochastic', label: 'Stochastic',                    group: 'Solve' },
  { id: 'sclopf',     label: 'Security-constrained (SCLOPF)',  group: 'Solve' },
  { id: 'powerflow', label: 'Power flow',                     group: 'Solve' },
  { id: 'marketsim', label: 'Market simulation',               group: 'Solve' },
  { id: 'contingency', label: 'N-1 contingency',              group: 'Solve' },
  { id: 'mga',        label: 'Near-optimal (MGA)',            group: 'Solve' },
  { id: 'solver',     label: 'Solver',                        group: 'Solve' },
  // Market — inputs that change the solve: re-solving what-if workflows.
  { id: 'assetSwap',  label: 'Asset swap (repowering)',       group: 'Market' },
  { id: 'ess',        label: 'ESS business case',             group: 'Market' },
  // Analysis (Post-analysis tab) — read the optimisation results, don't change
  // the base solve: decision use-cases, procurement, ownership & market-behaviour.
  { id: 'decisions',  label: 'Decisions (use cases)',         group: 'Analysis' },
  { id: 'procurement', label: 'Procurement strategy',         group: 'Analysis' },
  { id: 'company',    label: 'Company / ownership',           group: 'Analysis' },
  { id: 'merchant',   label: 'Merchant (price-taker)',        group: 'Analysis' },
  { id: 'bidding',    label: 'Bid strategy (market power)',   group: 'Analysis' },
  { id: 'ppa',        label: 'PPA contract',                  group: 'Analysis' },
  // Data — external-source credentials
  { id: 'apiKeys',    label: 'API keys',                      group: 'Data' },
  // App — workspace preferences
  { id: 'appearance',      label: 'Appearance',       group: 'App' },
  { id: 'projectDefaults', label: 'Project defaults', group: 'App' },
];

export interface SettingsViewProps {
  /** `settings` = technical (Setup/Solve/Data/App); `market` = Market/Policy
   *  (inputs that change the solve); `analysis` = Post-analysis (reads results). */
  variant?: 'settings' | 'market' | 'analysis';
  /** Navigate to a section that lives in a different tab (host switches tab). */
  onNavigateExternal?: (section: string) => void;
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
  /** Scenario difference table + batch runner (Run all in order / parallel). */
  maxConcurrency: number;
  batchBusy?: boolean;
  onScenarioCatalogChange: (catalog: ScenarioCatalog) => void;
  onRunBatch: (ids: string[], mode: BatchMode, concurrency: number) => void;
  onGoToComparison: () => void;

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
  marketSimConfig: MarketSimConfig;
  onMarketSimConfigChange: (config: MarketSimConfig) => void;
  mgaConfig: MgaConfig;
  onMgaConfigChange: (config: MgaConfig) => void;
  merchantConfig: MerchantConfig;
  onMerchantConfigChange: (config: MerchantConfig) => void;
  bidStrategyConfig: BidStrategyConfig;
  onBidStrategyConfigChange: (config: BidStrategyConfig) => void;
  assetSwapConfig: AssetSwapConfig;
  onAssetSwapConfigChange: (config: AssetSwapConfig) => void;
  essConfig: EssConfig;
  onEssConfigChange: (config: EssConfig) => void;
  ppaConfig: PpaConfig;
  onPpaConfigChange: (config: PpaConfig) => void;
  demandResponseConfig: DemandResponseConfig;
  onDemandResponseConfigChange: (config: DemandResponseConfig) => void;
  modelCarriers: string[];
  modelBuses: string[];
  merchantOwners: string[];
  ownerColumn: string;
  onOwnerColumnChange: (column: string) => void;
  financeConfig: FinanceConfig;
  onFinanceConfigChange: (config: FinanceConfig) => void;
  contingencyConfig: ContingencyConfig;
  onContingencyConfigChange: (config: ContingencyConfig) => void;
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
  /** Last run's cleared system price series — feeds the Procurement surface. */
  priceSeries?: ValuePoint[] | null;
  /** Last run's total dispatch (≈ load) per snapshot — for a load-shaped procurement profile. */
  loadShape?: number[] | null;

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
  const variant = props.variant ?? 'settings';
  const allowedGroups =
    variant === 'market' ? MARKET_GROUPS :
    variant === 'analysis' ? ANALYSIS_GROUPS :
    TECHNICAL_GROUPS;
  const groups = GROUPS.filter((g) => allowedGroups.includes(g));
  // Default to the first section of the first shown group.
  const firstSection = (SECTIONS.find((s) => s.group === groups[0]) ?? SECTIONS[0]).id;

  const persistKey =
    variant === 'market' ? 'ui:market-section' :
    variant === 'analysis' ? 'ui:analysis-section' :
    'ui:settings-section';
  const [stored, setSection] = usePersistedState<SectionId>(persistKey, firstSection);
  // Guard: if the persisted section belongs to another view, fall back to the
  // first section of this one (so each tab always shows a valid section).
  const section = SECTIONS.some((s) => s.id === stored && allowedGroups.includes(s.group))
    ? stored
    : firstSection;

  // Navigation from the Decisions launcher: if the target lives in this tab,
  // switch section locally; otherwise ask the host (App) to switch tab too.
  const navigate = (target: SectionId) => {
    const meta = SECTIONS.find((s) => s.id === target);
    if (meta && allowedGroups.includes(meta.group)) setSection(target);
    else props.onNavigateExternal?.(target);
  };

  const title =
    variant === 'market' ? 'Market & Policy' :
    variant === 'analysis' ? 'Post-analysis' :
    'Settings';

  return (
    <ResizablePanels id="settings-rail" direction="horizontal" className="settings-view" initialSizes={[20, 80]} minSize={180}>
      <LeftRail
        title={title}
        ariaLabel={`${title} sections`}
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
        {section === 'marketsim'      && <MarketSimulationSection {...props} />}
        {section === 'contingency'    && <ContingencySection {...props} />}
        {section === 'mga'            && <MgaSection {...props} />}
        {section === 'company'        && <CompanySection {...props} />}
        {section === 'merchant'       && <MerchantSection {...props} />}
        {section === 'bidding'        && <BiddingSection {...props} />}
        {section === 'assetSwap'      && <AssetSwapSection {...props} />}
        {section === 'ess'            && <EssSection {...props} />}
        {section === 'ppa'            && <PpaSection {...props} />}
        {section === 'demandResponse' && <DemandResponseSection {...props} />}
        {section === 'decisions'      && <DecisionsSection {...props} onNavigate={(s) => navigate(s as SectionId)} />}
        {section === 'procurement'    && <ProcurementSection priceSeries={props.priceSeries ?? null} loadShape={props.loadShape ?? null} currency={props.currencySymbol} />}
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
