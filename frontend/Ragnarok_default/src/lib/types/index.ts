// ── Sheet name types ──────────────────────────────────────────────────────────

export type SheetName = string;
export type TsSheetName = string;
export type AnySheetName = SheetName | TsSheetName;

// ── Primitives ────────────────────────────────────────────────────────────────

export type Primitive = string | number | boolean | null;
export type GridRow = Record<string, Primitive>;
export type BrowserFileHandle = any;

// ── UI state ──────────────────────────────────────────────────────────────────

export type WorkspaceTab = 'Welcome' | 'Build' | 'Data' | 'Forge' | 'Model' | 'Market' | 'Settings' | 'Analytics' | 'History' | 'Plugins';
export type ModelSubTab = 'Map' | 'Table';
export type AnalyticsSubTab = 'Validation' | 'Result' | 'Analytics' | 'Comparison' | 'Log';
export type ChartMode = 'line' | 'area' | 'bar';
export type ChartSectionType = ChartMode | 'donut';
export type TimeframeOption = 'aggregated' | 'yearly' | 'monthly' | 'weekly' | 'daily' | 'hourly';
export type PlanningMode = 'single_period' | 'pathway';
export type SnapshotMappingMode = 'explicit_period_column' | 'repeat_all_snapshots';
export type PathwayOverridePolicy = 'reuse_base_inputs';
export type RollingStepPolicy = 'derived';

export type ConstraintMetric =
  | 'co2_cap' | 'max_load_shed'
  | 'carrier_max_gen' | 'carrier_min_gen'
  | 'carrier_max_share' | 'carrier_min_share'
  | 'carrier_max_cf' | 'carrier_min_cf';

export type ModuleCapability =
  | 'data-importer'
  | 'data-manipulator'
  | 'analytics-pack'
  | 'constraint-pack';

export type ModulePermission =
  | 'filesystem.read'
  | 'filesystem.write'
  | 'network.access'
  | 'workbook.read'
  | 'workbook.write'
  | 'results.read'
  | 'ui.panel'
  | 'ui.action'
  | 'constraints.register'
  | 'analytics.register';

// ── Domain model ──────────────────────────────────────────────────────────────

/**
 * In-memory workbook: a map from sheet name → rows. The set of valid sheet
 * names is driven by the generated PyPSA schema (`src/config/pypsa_schema.json`)
 * — see `SHEETS` and `TS_SHEETS` in `constants/pypsa_schema.ts`. No named
 * fields are baked into the type so the model stays in sync with the schema
 * even when PyPSA adds new components.
 *
 * `createEmptyWorkbook()` in `shared/utils/workbook.ts` pre-populates every
 * documented sheet with `[]`, so `model.generators` etc. are always defined
 * at runtime for any component the schema knows about.
 */
export type WorkbookModel = Record<string, GridRow[]>;

export interface CustomConstraint {
  id: string;
  enabled: boolean;
  label: string;
  metric: ConstraintMetric;
  carrier: string;
  value: number;
  unit: string;
}

export interface PathwayPeriodConfig {
  period: number;
  objectiveWeight: number;
  yearsWeight: number;
}

export interface PathwayConfig {
  planningMode: PlanningMode;
  enabled: boolean;
  snapshotMappingMode: SnapshotMappingMode;
  overridePolicy: PathwayOverridePolicy;
  periods: PathwayPeriodConfig[];
  selectedPeriod: number | null;
}

export interface RollingWindowSummary {
  index: number;
  solvedStart: string;
  solvedEnd: string;
  acceptedStart: string;
  acceptedEnd: string;
  solvedCount: number;
  acceptedCount: number;
  periods: number[];
}

export interface RollingHorizonConfig {
  enabled: boolean;
  horizonSnapshots: number;
  overlapSnapshots: number;
  stepPolicy: RollingStepPolicy;
  stepSnapshots: number;
  preserveTerminalState: boolean;
  selectedWindow: number | null;
}

/** Sampled snapshot blocks ("test run"): solve a reduced snapshot set,
 *  weighted so totals represent the full window. mode 'count' = N equally
 *  spaced blocks; 'gap' = block + gap repeating; 'average' = ONE synthetic
 *  block holding the positional mean of every period (an "average week" —
 *  exact energy totals, smoothed peaks). */
export interface SamplingConfig {
  enabled: boolean;
  mode: 'count' | 'gap' | 'average';
  blockSize: number;
  blockCount: number;
  gapSnapshots: number;
}

export interface StochasticScenarioOverride {
  id: string;
  sheet: string;
  attribute: string;
  scopeType: 'all' | 'name' | 'carrier';
  scopeValue: string;
  operation: 'multiply' | 'set';
  value: number;
}

export interface StochasticScenarioConfig {
  id: string;
  name: string;
  weight: number;
  overrides: StochasticScenarioOverride[];
}

export interface StochasticConfig {
  enabled: boolean;
  scenarios: StochasticScenarioConfig[];
}

export interface CarbonPriceScheduleEntry {
  year: number;
  price: number;
}

/** A named, reusable carbon-price schedule in the project's carbon library. */
export interface CarbonScheduleProfile {
  id: string;
  name: string;
  schedule: CarbonPriceScheduleEntry[];
}

export interface SecurityConstrainedConfig {
  enabled: boolean;
}

/** Power-flow study mode — solve network physics (pf/lpf) instead of an LP. */
export interface PowerFlowConfig {
  enabled: boolean;
  /** true → linear (DC) lpf(); false → AC Newton-Raphson pf(). */
  linear: boolean;
}

/** Per-bus voltage magnitude (pu) across the modelled snapshots. */
export interface VoltageProfileEntry {
  bus: string;
  min: number;
  mean: number;
  max: number;
}

/** Backend power-flow result block (present only on a pf/lpf run). */
export interface PowerFlowResult {
  linear: boolean;
  method: string;
  converged: boolean;
  iterations: number;
  maxError: number;
  /** Non-null when the flow failed to run (e.g. missing reactance / slack). */
  error: string | null;
  voltageProfile: VoltageProfileEntry[];
  lossesMwh: number;
  peakLossMw: number;
  currency: string;
}

/** One row of PyPSA's statistics() table — a component/carrier slice. */
export interface StatisticsRow {
  component: string;
  carrier: string;
  values: Record<string, number | null>;
}

/** PyPSA statistics() passthrough: the metric columns + per-carrier rows. */
export interface StatisticsResult {
  columns: string[];
  rows: StatisticsRow[];
}

/** One snapshot of the price-formation view (Tier 0). */
export interface PriceFormationRow {
  snapshot: string;
  price: number;
  demand: number;
  residualDemand: number;
  renewableShare: number;
  /** Carrier of the price-setting (most expensive dispatched) generator. */
  marginalCarrier: string;
}

/** How often / at what price each carrier set the price. */
export interface PriceFormationMarginalCarrier {
  carrier: string;
  hours: number;
  shareOfHours: number;
  avgPrice: number;
}

/** Price-formation view (Tier 0) — price vs residual demand & marginal carrier. */
export interface PriceFormationResult {
  currency: string;
  series: PriceFormationRow[];
  marginalSummary: PriceFormationMarginalCarrier[];
}

/** Run-length on/off segment of a committable unit's status. */
export interface CommitmentSegment {
  on: boolean;
  length: number;
}

/** One committable generator's commitment summary (Tier 1). */
export interface CommitmentGenerator {
  name: string;
  carrier: string;
  starts: number;
  startUpCost: number;
  startUpCostTotal: number;
  onlineHours: number;
  onlineFraction: number;
  minUpTime: number;
  minDownTime: number;
  segments: CommitmentSegment[];
}

export interface CommitmentCarrier {
  carrier: string;
  starts: number;
  startUpCostTotal: number;
  units: number;
}

/** Unit-commitment view (Tier 1) — starts, start-up costs, on/off patterns. */
export interface CommitmentResult {
  currency: string;
  snapshotCount: number;
  generators: CommitmentGenerator[];
  byCarrier: CommitmentCarrier[];
  totals: { committableCount: number; starts: number; startUpCostTotal: number };
}

/** N-1 contingency study mode — branch loading under each single outage. */
export interface ContingencyConfig {
  enabled: boolean;
}

/** MGA (modelling-to-generate-alternatives) — map the near-optimal capacity
 *  space. Layered on top of a normal optimise run. `carriers` empty = explore
 *  every extendable-generator carrier (backend-capped). */
export interface MgaConfig {
  enabled: boolean;
  /** Cost slack: alternatives stay within `1 + slack` of the optimal cost. */
  slack: number;
  carriers: string[];
}

/** Asset-swap / repowering what-if (DW2) — retire a carrier, add another 1:1. */
export interface AssetSwapConfig {
  enabled: boolean;
  removeCarrier: string;
  addCarrier: string;
  /** Replacement cost when the target carrier isn't already in the model. */
  addCapitalCost: number;
  addMarginalCost: number;
}

/** One side (before / after / delta) of the asset-swap comparison. */
export interface AssetSwapSide {
  systemCost: number;
  operatingCost: number;
  emissionsTonnes: number;
}

/** Asset-swap result (DW2) — before vs after a carrier swap. */
export interface AssetSwapResult {
  removeCarrier: string;
  addCarrier: string;
  currency: string;
  removedCapacityMW: number;
  addedCapacityMW: number;
  replacementCapex: number;
  replacementFirm: boolean;
  before: AssetSwapSide;
  after: AssetSwapSide;
  delta: AssetSwapSide;
  paybackYears: number | null;
}

/** Bid-strategy simulator (Tier 2) + optimal-bid finder (Tier 3a). */
export interface BidStrategyConfig {
  enabled: boolean;
  /** `fixed` = simulate the given markup (Tier 2); `optimal` = sweep for the
   *  profit-maximising markup (Tier 3a). */
  mode: 'fixed' | 'optimal';
  /** Owner value whose offers to mark up (a value found in the owner column). */
  owner: string;
  /** `percent` = offer = cost×(1+markup); `absolute` = offer = cost+markup. */
  markupType: 'percent' | 'absolute';
  /** Fixed-mode markup: fraction for percent (0.5 = +50%), currency/MWh absolute. */
  markup: number;
  /** Optimal-mode: upper bound of the markup sweep. */
  maxMarkup: number;
  /** Optimal-mode: number of sweep steps. */
  steps: number;
}

/** One side (baseline / strategic) of the bid-strategy comparison. */
export interface BidStrategySide {
  profit: number;
  revenue: number;
  energyMWh: number;
  capturePrice: number | null;
}

/** One point on the optimal-bid profit-vs-markup sweep. */
export interface OptimalBidPoint {
  markup: number;
  profit: number;
  energyMWh: number;
  systemAvgPrice: number | null;
}

/** Optimal-bid result (Tier 3a) — the profit-maximising markup + sweep curve. */
export interface OptimalBidResult {
  owner: string;
  markupType: 'percent' | 'absolute';
  currency: string;
  generatorCount: number;
  baselineProfit: number;
  optimalMarkup: number;
  optimalProfit: number;
  deltaProfit: number;
  curve: OptimalBidPoint[];
}

/** Bid-strategy result — owner profit under a markup vs the price-taker baseline. */
export interface BidStrategyResult {
  owner: string;
  markupType: 'percent' | 'absolute';
  markup: number;
  currency: string;
  generatorCount: number;
  baseline: BidStrategySide;
  strategic: BidStrategySide;
  deltaProfit: number;
  systemAvgPrice: { baseline: number; strategic: number | null };
}

/** One MGA alternative — the system at one corner of the near-optimal space. */
export interface MgaAlternative {
  carrier: string;
  sense: 'min' | 'max';
  status: string;
  cost: number;
  /** cost / optimal cost (≈ 1 + slack at the budget boundary). */
  costRatio: number | null;
  capacityByCarrier: Record<string, number>;
}

/** MGA result block — the optimum plus its near-optimal corridor. */
export interface NearOptimalResult {
  slack: number;
  currency: string;
  optimum: { cost: number; capacityByCarrier: Record<string, number> };
  carriers: string[];
  alternatives: MgaAlternative[];
  droppedCarriers: string[];
}

/** Merchant / price-taker analysis (B1) — maximise one owner's profit against a
 *  price signal. Layered on top of a normal optimise run. */
export interface MerchantConfig {
  enabled: boolean;
  /** Owner value whose assets to analyse (a value found in the owner column). */
  owner: string;
  /** `lmp` = stage-1 system marginal price; `series` = exogenous user price. */
  priceSource: 'lmp' | 'series';
  /** Flat price (run currency / MWh) used when priceSource = `series`. */
  flatPrice: number;
  /** Optional hourly price overriding `flatPrice` in series mode. */
  priceSeries?: number[];
}

/** One owner asset's merchant economics. */
export interface MerchantAsset {
  name: string;
  type: 'generator' | 'storage';
  bus: string;
  carrier: string;
  capacityMW: number;
  energyMWh: number;
  revenue: number;
  operatingCost: number;
  capex: number;
  profit: number;
  /** Time-weighted price the asset actually sold at (revenue / energy). */
  capturePrice: number | null;
}

/** One company's KPIs (F1) — its slice of the solved system. */
export interface CompanyKpi {
  company: string;
  capacityMW: number;
  energyMWh: number;
  /** Competitive-benchmark revenue (LMP × dispatch); null if no LMPs. */
  revenue: number | null;
  emissionsTonnes: number;
  generatorCount: number;
  storageCount: number;
}

/** Company / owner dimension (F1) — per-company KPIs grouped by owner tag. */
export interface CompanyBreakdownResult {
  ownerColumn: string;
  currency: string;
  companies: CompanyKpi[];
  /** Assets with no owner tag (not attributed to any company). */
  untaggedCount: number;
}

/** Optional debt assumptions (F2) for DSCR. Gearing 0 = all-equity. */
export interface FinanceConfig {
  /** Debt share of overnight capex (0–1). */
  gearing: number;
  /** Debt interest rate (fraction). */
  interestRate: number;
  /** Debt tenor (years). */
  tenorYears: number;
}

/** One company's project-finance metrics (F2). */
export interface CompanyFinanceEntry {
  company: string;
  overnightCapex: number;
  annualMargin: number;
  horizonYears: number;
  npv: number;
  /** Internal rate of return (fraction); null if not bracketable. */
  irr: number | null;
  paybackYears: number | null;
  discountedPaybackYears: number | null;
  /** Debt-service coverage ratio; null when no debt is configured. */
  dscr: number | null;
}

/** Company-level financial model (F2) — NPV/IRR/payback/DSCR per owner. */
export interface CompanyFinanceResult {
  ownerColumn: string;
  currency: string;
  discountRate: number;
  companies: CompanyFinanceEntry[];
}

/** Merchant result block — one owner's profit against the price signal. */
export interface MerchantResult {
  owner: string;
  ownerColumn: string;
  priceSource: 'lmp' | 'series';
  currency: string;
  priceStats: { mean: number | null; min: number | null; max: number | null };
  assets: MerchantAsset[];
  totals: {
    revenue: number;
    operatingCost: number;
    capex: number;
    profit: number;
    energyMWh: number;
  };
}

export interface ContingencyEntry {
  /** Name of the outaged passive branch. */
  outage: string;
  /** Worst post-outage loading (%) on any remaining branch. */
  worstLoadingPct: number;
  /** Which branch hit that worst loading (null if none). */
  worstBranch: string | null;
  overloadCount: number;
}

export interface ContingencyResult {
  snapshot: string;
  secure: boolean;
  baseMaxLoadingPct: number;
  outagesTested: number;
  insecureCount: number;
  contingencies: ContingencyEntry[];
  error: string | null;
  currency: string;
}

export interface StochasticScenarioResult {
  name: string;
  weight: number;
  overrideCount: number;
  totalEnergyMwh: number;
  totalEmissionsTco2: number;
  totalOperatingCost: number;
  totalOperatingCostFormatted: string;
  loadShedEnergyMwh: number;
}

export interface StochasticResult {
  enabled: boolean;
  representativeScenario: string;
  scenarios: StochasticScenarioResult[];
}

export interface ScenarioPreset {
  id: string;
  label: string;
  notes: string;
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  carbonPrice: number;
  carbonPriceSchedule: CarbonPriceScheduleEntry[];
  discountRate: number;
  forceLp: boolean;
  enableLoadShedding: boolean;
  loadSheddingCost: number;
  pathwayConfig: PathwayConfig;
  rollingConfig: RollingHorizonConfig;
  samplingConfig: SamplingConfig;
  // Stochastic + SCLOPF are part of the preset so applying a scenario restores
  // the FULL run configuration (they were silently dropped before). customDsl
  // is deliberately NOT here — it persists in the model workbook sheet
  // RAGNAROK_CustomDSL, not per preset.
  stochasticConfig: StochasticConfig;
  securityConstrainedConfig: SecurityConstrainedConfig;
  powerFlowConfig: PowerFlowConfig;
  contingencyConfig: ContingencyConfig;
  mgaConfig: MgaConfig;
  merchantConfig: MerchantConfig;
  bidStrategyConfig: BidStrategyConfig;
  assetSwapConfig: AssetSwapConfig;
  /** Model column holding the owner/company tag (F1 + B1). Default `owner`. */
  ownerColumn: string;
  /** Optional debt assumptions for company finance DSCR (F2). */
  financeConfig: FinanceConfig;
  constraints: CustomConstraint[];
}

export interface ScenarioCatalog {
  activeScenarioId: string | null;
  scenarios: ScenarioPreset[];
}

export interface ProjectRunState {
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  carbonPrice: number;
  forceLp: boolean;
  activeScenarioId: string | null;
}

export interface ProjectImportProvenance {
  exportedAt: string;
  exportedFilename: string;
  schemaCommitSha: string;
  schemaGeneratedAt: string;
  importedFromFilename: string | null;
  importedAt: string | null;
}

export interface PathwayPeriodSummary {
  period: number;
  snapshotCount: number;
  modeledHours: number;
  totalDispatch: number;
  totalEmissions: number;
  averagePrice: number;
  peakLoad: number;
  objectiveWeight: number;
  yearsWeight: number;
}

// ── Result types ──────────────────────────────────────────────────────────────

export interface SummaryItem {
  label: string;
  value: string;
  detail: string;
}

export interface SeriesPoint {
  label: string;
  timestamp: string;
  values: Record<string, number>;
  total?: number;
  period?: number | null;
}

export interface ValuePoint {
  label: string;
  timestamp?: string;
  value: number;
  period?: number | null;
}

export interface StoragePoint {
  label: string;
  timestamp: string;
  charge: number;
  discharge: number;
  state: number;
  period?: number | null;
}

export interface MixItem {
  label: string;
  value: number;
  color: string;
}

export interface GeneratorDetail {
  name: string;
  carrier: string;
  color?: string;
  bus: string;
  summary: SummaryItem[];
  outputSeries: Array<{ label: string; timestamp: string; output: number }>;
  emissionsSeries: Array<{ label: string; timestamp: string; emissions: number }>;
  availableSeries: Array<{ label: string; timestamp: string; available: number }>;
  curtailmentSeries: Array<{ label: string; timestamp: string; curtailment: number }>;
}

export interface BusDetail {
  name: string;
  summary: SummaryItem[];
  netSeries: Array<{
    label: string;
    timestamp: string;
    load: number;
    generation: number;
    smp: number;
    emissions: number;
    v_mag_pu: number;
    v_ang: number;
  }>;
  hasVoltageMagnitude: boolean;
  hasVoltageAngle: boolean;
  carrierMix: MixItem[];
}

export interface StorageUnitDetail {
  name: string;
  bus: string;
  summary: SummaryItem[];
  dispatchSeries: Array<{ label: string; timestamp: string; dispatch: number }>;
  chargeSeries: Array<{ label: string; timestamp: string; charge: number }>;
  dischargeSeries: Array<{ label: string; timestamp: string; discharge: number }>;
  stateSeries: Array<{ label: string; timestamp: string; state: number }>;
}

export interface StoreDetail {
  name: string;
  bus: string;
  summary: SummaryItem[];
  energySeries: Array<{ label: string; timestamp: string; energy: number }>;
  powerSeries: Array<{ label: string; timestamp: string; power: number }>;
}

export interface BranchDetail {
  name: string;
  component: string;
  bus0: string;
  bus1: string;
  summary: SummaryItem[];
  flowSeries: Array<{ label: string; timestamp: string; p0: number; p1: number }>;
  loadingSeries: Array<{ label: string; timestamp: string; loading: number }>;
  lossesSeries: Array<{ label: string; timestamp: string; losses: number }>;
}

export interface ProcessDetail {
  name: string;
  carrier: string;
  color?: string;
  bus0: string;
  bus1: string;
  summary: SummaryItem[];
  /** Power drawn from bus0 (MW). Positive = into the process. */
  p0Series: Array<{ label: string; timestamp: string; p0: number }>;
  /** Power delivered to bus1 (MW). Positive = out of the process. */
  p1Series: Array<{ label: string; timestamp: string; p1: number }>;
  /** Net throughput |p0| (MW), used as the primary timeline. */
  throughputSeries: Array<{ label: string; timestamp: string; throughput: number }>;
}

export interface ShuntImpedanceDetail {
  name: string;
  bus: string;
  summary: SummaryItem[];
  /** Active power consumed by the shunt (MW). */
  pSeries: Array<{ label: string; timestamp: string; p: number }>;
  /** Reactive power consumed by the shunt (MVar). */
  qSeries: Array<{ label: string; timestamp: string; q: number }>;
}

// ── Emissions breakdown types ─────────────────────────────────────────────────

export interface GeneratorEmission {
  name: string;
  carrier: string;
  bus: string;
  energy_mwh: number;
  emissions_tco2: number;
  intensity_kg_mwh: number;  // kg CO₂e/MWh
}

export interface CarrierEmission {
  carrier: string;
  energy_mwh: number;
  emissions_tco2: number;
  intensity_kg_mwh: number;  // kg CO₂e/MWh
}

export interface EmissionsBreakdown {
  byGenerator: GeneratorEmission[];
  byCarrier: CarrierEmission[];
}

// ── Market analysis types ─────────────────────────────────────────────────────

export interface MeritOrderEntry {
  name: string;
  carrier: string;
  bus: string;
  marginal_cost: number;
  p_nom: number;
  cumulative_mw: number;
  color: string;
}

export interface Co2Shadow {
  found: boolean;
  constraint_name: string | null;
  shadow_price: number;
  explicit_price: number;
  cap_ktco2: number | null;
  status: 'binding' | 'slack' | 'none';
  note: string;
}

// ── Asset economics (F0 — revenue / margin / capex recovery) ──────────────────
// Competitive-benchmark profit read out of the cost-min solve (no extra solve):
// under the least-cost LP, optimal dispatch is the perfectly-competitive
// profit-max equilibrium. Money columns are on the modeled-horizon basis;
// `recoveryPct` is scale-invariant. Backend-provided (see market.py) and
// preserved through the client deriveRunResults merge; present whenever the
// backend supplied it (solve, stored/light view, pathway, result-import).
// deriveRunResults does not recompute it, so a bundle fully re-derived from bare
// outputs with no backend economics (e.g. a pre-F0 export re-opened) lacks it.

export interface GeneratorEconomicsEntry {
  name: string;
  carrier: string;
  bus: string;
  color: string;
  energyMwh: number;
  capacityMw: number;
  revenue: number;
  variableCost: number;
  grossMargin: number;
  /** Volume-weighted average price captured ($/MWh); null when no energy. */
  capturePrice: number | null;
  fixedCostAnnual: number;
  fixedCostHorizon: number;
  netHorizon: number;
  /** 100·grossMargin / fixedCostHorizon; null when there is no fixed cost. */
  recoveryPct: number | null;
}

export interface StorageEconomicsEntry {
  name: string;
  carrier: string;
  bus: string;
  color: string;
  energyDischargedMwh: number;
  energyChargedMwh: number;
  capacityMw: number;
  revenue: number;
  variableCost: number;
  grossMargin: number;
  fixedCostAnnual: number;
  fixedCostHorizon: number;
  netHorizon: number;
  recoveryPct: number | null;
}

export interface CarrierEconomicsEntry {
  carrier: string;
  color: string;
  energyMwh: number;
  capacityMw: number;
  revenue: number;
  variableCost: number;
  grossMargin: number;
  capturePrice: number | null;
  fixedCostAnnual: number;
  fixedCostHorizon: number;
  netHorizon: number;
  recoveryPct: number | null;
}

export interface GeneratorEconomics {
  currency: string;
  modeledHours: number;
  horizonYears: number;
  generators: GeneratorEconomicsEntry[];
  storage: StorageEconomicsEntry[];
  byCarrier: CarrierEconomicsEntry[];
  system: {
    revenue: number;
    variableCost: number;
    grossMargin: number;
    fixedCostAnnual: number;
    fixedCostHorizon: number;
    netHorizon: number;
    recoveryPct: number | null;
    generatorsModeled: number;
    generatorsRecovered: number;
  };
}

// ── Capacity expansion result ─────────────────────────────────────────────────

export interface ExpansionAsset {
  name: string;
  component: 'Generator' | 'StorageUnit' | 'Store' | 'Link' | 'Line';
  carrier: string;
  bus: string;
  p_nom_mw: number;
  p_nom_opt_mw: number;
  delta_mw: number;
  capital_cost: number;
  capex_annual: number;
  unit?: string;   // 'MW' (default), 'MWh' (Store), 'MVA' (Line)
}

// ── Plugin analytics ─────────────────────────────────────────────────────────

export type PluginFieldFormat = 'number' | 'currency' | 'table' | 'text' | 'chart';

export interface PluginFieldHint {
  label?: string;
  unit?: string;
  format?: PluginFieldFormat;
  section?: string;
}

/** One series in a line/area/bar plugin chart. */
export interface PluginChartSeries {
  /** Property name read from each row in `PluginChartSpec.rows`. */
  key: string;
  /** Legend label. Defaults to `key`. */
  label?: string;
  /** Stroke/fill colour. Defaults to a stable palette colour. */
  color?: string;
}

/** One slice of a donut plugin chart. */
export interface PluginChartSlice {
  label: string;
  value: number;
  /** Slice colour. Defaults to a stable palette colour. */
  color?: string;
}

/** A node on a `kind: 'map'` plugin chart (e.g. a region centroid). */
export interface PluginMapNode {
  /** Unique id; `PluginMapEdge.from`/`to` reference it. */
  id: string;
  label?: string;
  /** WGS84 latitude / longitude. */
  lat: number;
  lon: number;
  /** Optional magnitude (e.g. total generation) used to size the marker. */
  value?: number;
  color?: string;
  /**
   * Optional breakdown rendered as a pie at the node (e.g. generation mix by
   * carrier). When present the marker is a pie sized by `value`; otherwise a
   * plain circle.
   */
  mix?: PluginChartSlice[];
}

/** A directed edge on a `kind: 'map'` plugin chart (e.g. inter-region flow). */
export interface PluginMapEdge {
  /** Source / target node id (must match a `PluginMapNode.id`). */
  from: string;
  to: string;
  /** Optional magnitude used to weight the line. */
  value?: number;
  label?: string;
  color?: string;
}

/**
 * Data spec a plugin returns (as a `data` value whose `ui` hint has
 * `format: 'chart'`) for the host to render with the app's own chart
 * components. Plugins emit data, never markup — the host owns rendering.
 */
export interface PluginChartSpec {
  /** 'line' | 'area' | 'bar' | 'donut' | 'map'. */
  kind: ChartSectionType | 'map';
  /** Caption shown above the chart. */
  description?: string;
  /** line/area/bar: rows keyed by series `key`, plus `label`/`x` (category) or `timestamp`. */
  rows?: Array<Record<string, string | number>>;
  /** line/area/bar: series definitions. */
  series?: PluginChartSeries[];
  /** line/area/bar: stack series instead of overlaying. */
  stacked?: boolean;
  xAxisTitle?: string;
  yAxisTitle?: string;
  /** Value unit (e.g. 'MW'). Donut centre/tooltip label; y-axis title fallback. */
  unit?: string;
  showLegend?: boolean;
  /** donut: slice definitions. */
  slices?: PluginChartSlice[];
  /** map: node (e.g. region centroid) definitions. */
  nodes?: PluginMapNode[];
  /** map: directed edge (e.g. inter-region flow) definitions. */
  edges?: PluginMapEdge[];
}

export type PluginPanelLayout = 'single' | '2x1' | '1x2' | '2x2';

export interface ModulePanelTextSection {
  title?: string;
  body: string;
}

export interface ModulePanelConfig {
  descriptionLayout?: PluginPanelLayout;
  inputLayout?: PluginPanelLayout;
  outputLayout?: PluginPanelLayout;
  descriptionSections?: ModulePanelTextSection[];
}

export interface PluginAnalyticsEntry {
  name: string;
  ui: Record<string, PluginFieldHint>;
  data: Record<string, unknown>;
}

/**
 * Manifest-level declaration of a plugin's own (local) build server. Used only
 * to advise the user how to register the server in their local env file +
 * `run.command` — Ragnarok never launches it. A browser cannot discover the
 * absolute install path, so the advisory pairs these with a path placeholder.
 */
export interface PluginServerConfig {
  /** Shell command that starts the server (may activate the plugin's own venv). */
  run: string;
  /** Working directory for the command, relative to the plugin's server directory. */
  cwd?: string;
  /** Port the server listens on. */
  port?: number;
  /** Health-check path (default `/health`). */
  health?: string;
}

export interface AppliedConstraint {
  name: string;
  source: 'custom' | 'dsl' | 'plugin';
  shadowPrice?: number;
}

export type ConstraintTermKind = 'gen' | 'cap' | 'cf' | 'emissions' | 'load_shed' | 'const';

export interface ConstraintTerm {
  coef: number;
  kind: ConstraintTermKind;
  carrier?: string;
}

/** Structured constraint spec — the wire format the frontend sends to the backend. */
export interface ConstraintSpec {
  id?: string;
  lhs: ConstraintTerm[];
  sense: '<=' | '>=' | '==';
  rhs: ConstraintTerm[];
}

export interface RunResults {
  pluginAnalytics?: Record<string, PluginAnalyticsEntry>;
  summary: SummaryItem[];
  dispatchSeries: SeriesPoint[];
  /** Per-carrier curtailed power (MW) per snapshot — renewables (time-varying
   *  p_max_pu) only; thermal part-load is not curtailment. Backend aggregate,
   *  kept in the light analytics bundle (like dispatchSeries). */
  curtailmentSeries?: SeriesPoint[];
  /** Per-carrier storage state of charge (MWh) per snapshot. Backend
   *  aggregate, kept in the light analytics bundle. */
  storageSocSeries?: SeriesPoint[];
  generatorDispatchSeries: SeriesPoint[];
  /** Compact per-generator dispatched energy (MWh) — backend aggregate that
   *  powers the "Dispatch by unit" donut without shipping the per-snapshot
   *  series. Present on light (View) loads; the full series is fetched windowed. */
  generatorEnergy?: Array<{ name: string; value: number; carrier?: string; color?: string; curtailmentMwh?: number | null }>;
  systemPriceSeries: ValuePoint[];
  systemEmissionsSeries: ValuePoint[];
  storageSeries: StoragePoint[];
  nodalPriceSeries?: SeriesPoint[];   // per-bus LMP time series
  carrierMix: MixItem[];
  costBreakdown: Array<{ label: string; value: number }>;
  nodalBalance: Array<{ label: string; load: number; generation: number }>;
  lineLoading: Array<{ label: string; value: number }>;
  expansionResults?: ExpansionAsset[];
  meritOrder?: MeritOrderEntry[];
  co2Shadow?: Co2Shadow;
  /** Per-asset competitive-benchmark economics (F0). Backend-provided and
   *  preserved through the deriveRunResults merge; see the GeneratorEconomics
   *  doc comment for when it is present. */
  generatorEconomics?: GeneratorEconomics;
  /** Present only when the run was a power-flow study (pf/lpf), not an LP. */
  powerFlow?: PowerFlowResult;
  /** Present only when the run was an N-1 contingency analysis. */
  contingency?: ContingencyResult;
  /** PyPSA statistics() table (per-carrier capacity/CF/curtailment/revenue/…). */
  statistics?: StatisticsResult;
  /** MGA near-optimal capacity corridor (present only when MGA was enabled). */
  nearOptimal?: NearOptimalResult;
  /** Merchant / price-taker owner economics (present only when enabled). */
  merchant?: MerchantResult;
  /** Per-company KPIs (present only when assets carry an owner tag). */
  companies?: CompanyBreakdownResult;
  /** Per-company project finance (NPV/IRR/payback/DSCR); needs an LP run. */
  companyFinance?: CompanyFinanceResult;
  /** Price-formation view (price vs residual demand, marginal carrier). */
  priceFormation?: PriceFormationResult;
  /** Unit-commitment view (starts, start-up costs, on/off patterns). */
  commitment?: CommitmentResult;
  /** Bid-strategy simulation (markup vs price-taker baseline). */
  bidStrategy?: BidStrategyResult;
  /** Optimal-bid finder (profit-maximising markup + sweep curve). */
  optimalBid?: OptimalBidResult;
  /** Asset-swap / repowering what-if (before vs after a carrier swap). */
  assetSwap?: AssetSwapResult;
  appliedConstraints?: AppliedConstraint[];
  emissionsBreakdown?: EmissionsBreakdown;
  narrative: string[];
  runMeta: {
    snapshotCount: number;
    snapshotWeight: number;
    modeledHours: number;
    storeWeight: number;
    planningMode?: PlanningMode;
    investmentPeriods?: number[];
    rolling?: {
      enabled: boolean;
      horizonSnapshots: number;
      overlapSnapshots: number;
      stepSnapshots: number;
      windowCount: number;
    };
    /** Sampled-blocks test run: snapshotWeight carries the full-window
     *  scaling (W/M); null/absent for contiguous runs. For mode 'average',
     *  blockCount is the number of periods folded into the profile. */
    sampling?: {
      enabled: boolean;
      mode: 'count' | 'gap' | 'average';
      blockSize: number;
      blockCount: number;
      gapSnapshots: number;
      sampledSnapshots: number;
      representedSnapshots: number;
      scale: number;
    } | null;
  };
  pathway?: {
    enabled: boolean;
    periods: number[];
    selectedPeriod: number | null;
    snapshotMappingMode: SnapshotMappingMode;
    summaries: PathwayPeriodSummary[];
  };
  rolling?: {
    enabled: boolean;
    horizonSnapshots: number;
    overlapSnapshots: number;
    stepSnapshots: number;
    windowCount: number;
    windows: RollingWindowSummary[];
  };
  stochastic?: StochasticResult | null;
  securityConstrained?: { enabled: boolean; branchCount: number } | null;
  assetDetails: {
    generators: Record<string, GeneratorDetail>;
    buses: Record<string, BusDetail>;
    storageUnits: Record<string, StorageUnitDetail>;
    stores: Record<string, StoreDetail>;
    branches: Record<string, BranchDetail>;
    processes: Record<string, ProcessDetail>;
    shuntImpedances: Record<string, ShuntImpedanceDetail>;
  };
  /**
   * Full PyPSA-native output dataset built directly from the solved network.
   * Used by Export Project (and round-tripped by Import Project) so the
   * full input + output workbook can be assembled entirely on the frontend
   * — the backend keeps no xlsx artifact.
   *
   * - `static[list_name][component_name][attr]` — solved scalar output
   *   attributes (e.g. `p_nom_opt`, `mu_*`).
   * - `series[<list_name>-<attr>]` — solved time-series sheets keyed by
   *   PyPSA's native `<list>-<attr>` convention (e.g. `generators-p`,
   *   `buses-marginal_price`). Each row has a `name` column (ISO
   *   timestamp) and one numeric column per component.
   */
  outputs?: {
    static: Record<string, Record<string, Record<string, Primitive>>>;
    series: Record<string, GridRow[]>;
    /** Light analytics view only: the names of the output series sheets that
     *  were stripped (`series` is null there). Lets a viewer detect it must
     *  refetch the full bundle to client-derive analytics. Absent on a full
     *  bundle, where `series` itself is populated. */
    seriesSheets?: string[];
  };
}

// ── Run history ───────────────────────────────────────────────────────────────

export interface RunHistoryEntry {
  id: string;
  label: string;
  scenarioLabel?: string | null;
  savedAt: string;
  filename: string;
  carbonPrice: number;
  /**
   * Discount rate this run was derived with. Optional for backward
   * compatibility: entries persisted before it was captured fall back to the
   * current setting when re-deriving pathway KPIs.
   */
  discountRate?: number;
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  activeConstraints: CustomConstraint[];
  /**
   * Row count per workbook sheet at the time of this run. Keyed by the
   * canonical sheet name from the PyPSA schema (e.g. `generators`, `buses`,
   * `storage_units`). New PyPSA components flow in automatically when the
   * schema is regenerated — no UI changes required.
   */
  componentCounts: Record<string, number>;
  pinned: boolean;
  inComparison: boolean;   // false = excluded from Comparison tab, still in history
  results: RunResults;
  /**
   * Full workbook topology submitted for this run. Analytics (map geometry,
   * per-asset derivation) bind to this snapshot so a restored run shows its
   * own buses/lines/generators rather than the live model the user may have
   * edited since. Optional for backward compatibility: entries persisted
   * before per-run snapshots were captured fall back to the live model.
   */
  model?: WorkbookModel;
}

/**
 * Lightweight metadata for a run persisted server-side. Every successful solve
 * is stored automatically (the backend is the single source of truth for run
 * history). Mirrors the meta sidecar written by `backend/app/run_store.py`
 * (`<name>.meta.json`). The heavy bundle (full model + results) is fetched on
 * demand via `GET /api/runs/{name}`.
 *
 * The light fields (`summary`, `carrierMix`, `pathway`, `rolling`,
 * `scenarioLabel`) carry exactly what Analytics → Comparison needs, so the
 * Comparison tab renders straight from `GET /api/runs` without a heavy fetch.
 */
export interface BackendRunMeta {
  name: string;
  savedAt: string;
  label: string;
  filename: string;
  snapshotStart: number | null;
  snapshotEnd: number | null;
  snapshotWeight: number | null;
  componentCounts: Record<string, number>;
  /** First ~4 entries of the run summary (label/value KPI cards). */
  kpis: Array<{ label: string; value: string | number }>;
  sizeBytes: number;
  /** Full run summary (KPI rows). Powers the Comparison table's Results section. */
  summary?: SummaryItem[];
  /** Carrier generation mix (label/value/color). Powers Comparison dispatch totals. */
  carrierMix?: MixItem[];
  /** Light pathway projection (no time-series) for Comparison. */
  pathway?: {
    enabled?: boolean;
    periods?: number[];
    selectedPeriod?: number | null;
    summaries?: PathwayPeriodSummary[];
  } | null;
  /** Light rolling-horizon projection (no time-series) for Comparison. */
  rolling?: {
    enabled?: boolean;
    horizonSnapshots?: number;
    overlapSnapshots?: number;
    windowCount?: number;
  } | null;
  /** Scenario label this run was solved under, for cross-scenario pivots. */
  scenarioLabel?: string | null;
  /** True once the server has finished pre-building the run's xlsx, so the
   *  export package can be downloaded. Until then the UI shows "Preparing…". */
  xlsxReady?: boolean;
  // ── History-card display fields ──
  /** Calendar year of the run's first snapshot. */
  scenarioYear?: number | null;
  /** Effective resolution = hours per snapshot (snapshotWeight). */
  resolutionHours?: number | null;
  /** Rolling-horizon batch (window) count, if rolling was used. */
  windowCount?: number | null;
  /** Total annual energy demand (MWh) — sum of the load profile. */
  totalDemandMwh?: number | null;
  /** Short chips for non-standard / notable settings (carbon price, force-LP,
   *  load-shed, custom solver, pathway, stochastic, N-1, constraint count). */
  tags?: string[];
  /** How this entry entered History: a normal solve (`'solve'`) or an imported
   *  external results file (`'xlsx_import'`). Absent on legacy entries → treat
   *  as `'solve'`. Drives the History "imported" chip. */
  origin?: string;
}

/** A run on the backend's serial queue (GET /api/queue). */
export interface QueueJob {
  id: string;
  label: string;
  status: 'queued' | 'staged' | 'running' | 'done' | 'error' | 'cancelled';
  submittedAt: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  error?: string | null;
  payloadAvailable?: boolean;
  /** Cores assigned to this solve — actual once running, projected while queued. */
  cores?: number | null;
  // Display-only run settings.
  snapshots?: number | null;
  snapshotWeight?: number | null;
  scenarioLabel?: string | null;
  solver?: string | null;
  solverThreads?: number | null;
  carbonPrice?: number | null;
  rolling?: boolean;
  pathway?: boolean;
  backend?: string | null;
  filename?: string | null;
}

/** Response of GET /api/queue: the jobs plus the server's concurrency budget. */
export interface QueueResponse {
  jobs: QueueJob[];
  concurrency: number;
  maxConcurrency: number;
  cpuCount: number;
}

export type AnalyticsFocus =
  | { type: 'system' }
  | { type: 'generator'; key: string }
  | { type: 'bus'; key: string }
  | { type: 'storageUnit'; key: string }
  | { type: 'store'; key: string }
  | { type: 'branch'; key: string }
  | { type: 'process'; key: string }
  | { type: 'shuntImpedance'; key: string };

// ── Analytics / chart types ───────────────────────────────────────────────────

export interface TimeSeriesSeries {
  key: string;
  label: string;
  color: string;
}

export interface TimeSeriesRow {
  label: string;
  timestamp?: string;
  [key: string]: string | number | undefined;
}

export interface MetricOption {
  key: string;
  label: string;
  unit: string;
  rows: TimeSeriesRow[];
  series: TimeSeriesSeries[];
  reducer: 'sum' | 'mean' | 'last';
  allowDonut: boolean;
}

export type GroupByOption = 'carrier' | 'asset';

export interface ChartSectionConfig {
  id: number;
  focusType: AnalyticsFocus['type'];  // per-card component selection
  focusKeys: string[];                // [] = all assets of that type; ['x'] = single
  groupBy: GroupByOption;             // how multi-asset series are combined
  busFilter: string[];                // secondary filter: keep only assets on these buses ([] = all)
  carrierFilter: string[];            // secondary filter: keep only generators with these carriers ([] = all)
  metricKey: string;
  chartType: ChartSectionType;
  timeframe: TimeframeOption;
  startIndex: number;
  endIndex: number;
  stacked: boolean;
  // ── Appearance (all optional; undefined = sensible default) ──
  xAxisTitle?: string;       // custom x-axis caption ('' / undefined = none)
  yAxisTitle?: string;       // custom y-axis caption ('' / undefined = none)
  showLegend?: boolean;      // default true
  showAxisLabels?: boolean;  // default true — tick labels on both axes
  xLabelAngle?: number;      // rotation (deg) of x-axis tick labels; 0 = horizontal
  // The per-asset temporal window is the slider range itself: `endIndex` (full-
  // run index) is how much stripped per-component series gets hydrated. A
  // preset's "unbounded" endIndex resolves to a 1-week default for per-asset
  // charts (DEFAULT_CHART_WINDOW_HOURS); see effectiveEndIndex in lib/api/runs.
}

// ── Tables pane ───────────────────────────────────────────────────────────────

export type TableSelKind = 'static' | 'ts';
export interface TableSel { kind: TableSelKind; sheet: AnySheetName }

// ── Module host types ────────────────────────────────────────────────────────

export interface ModuleHostRoot {
  label: string;
  path: string;
  configuredPath: string;
  exists: boolean;
  isDirectory: boolean;
  managed: boolean;
}

export type ModuleConfigFieldType = 'number' | 'boolean' | 'string' | 'select' | 'multi-select' | 'carrier-select' | 'file' | 'table' | 'action' | 'group';

/**
 * Dynamic option source for a `select` / `multi-select` field or a `select`
 * table column. Resolved at render time to a list of `{ value, label }`.
 * When present it takes precedence over a static `options` array; if it
 * resolves to nothing (e.g. no model loaded yet) the static `options` are
 * used as a fallback.
 */
export interface ModuleConfigOptionsFrom {
  /**
   * - `'model'`  — distinct values from a workbook sheet (e.g. bus names).
   * - `'config'` — distinct values from a sibling `table` field's current rows
   *   (e.g. a `province_mapping` table the user is editing).
   * - `'server'` — rows fetched from the plugin's own HTTP server (POST
   *   `endpoint` with `{config}`, response `{rows: [...]}`), e.g. the full
   *   imported generator fleet. Filtered/labelled client-side like the others.
   *   Used by FRONTEND plugins (which run their own server).
   * - `'plugin'` — rows fetched from a BACKEND plugin's `options(name, …)` hook
   *   via Ragnarok (`POST /api/plugins/{id}/options`, response `{rows: [...]}`).
   *   No external server; the backend plugin owns the logic. Filtered/labelled
   *   client-side like the others.
   */
  source: 'model' | 'config' | 'server' | 'plugin';
  /** For `source: 'model'`: the workbook sheet name (e.g. `'buses'`). */
  sheet?: string;
  /** For `source: 'config'`: the sibling config field key whose rows to read. */
  field?: string;
  /** For `source: 'server'`: the POST path (e.g. `'/generators'`). */
  endpoint?: string;
  /**
   * For `source: 'plugin'`: the option-set id passed to the plugin's
   * `options(name, …)` hook (e.g. `'/demand_values'`).
   */
  name?: string;
  /**
   * For `source: 'server'`: config field holding the server base URL
   * (defaults to `http://127.0.0.1:8765`).
   */
  baseUrlField?: string;
  /** Row property used as the option value. Defaults to `'name'`. */
  column?: string;
  /** Row property used as the option label. Defaults to `column`. */
  labelColumn?: string;
  /**
   * Append `" (row[labelSuffixColumn])"` to each option label — e.g. show a
   * generator's `build_year` next to its name.
   */
  labelSuffixColumn?: string;
  /**
   * Keep only rows that satisfy the condition(s). One condition or an array
   * (all must pass / AND). Each compares `column` to a threshold (`value`
   * literal, or `valueFrom` a sibling config field). Numeric ops
   * (`>=` `<=` `>` `<`) coerce both sides to numbers; equality (`==` `!=`)
   * compares numerically when the threshold is a number, else as strings
   * (e.g. carrier). A blank threshold makes that condition a no-op.
   */
  filter?: ModuleConfigOptionsFilter | ModuleConfigOptionsFilter[];
}

/** One condition for `ModuleConfigOptionsFrom.filter`. */
export interface ModuleConfigOptionsFilter {
  column: string;
  /**
   * Numeric (`>=` `<=` `>` `<`) or equality (`==` `!=`, numeric or string), or
   * set membership (`in` / `not-in`) when the threshold is an array (e.g. a
   * multi-select field value). An empty/blank threshold is a no-op.
   */
  op?: '>=' | '<=' | '>' | '<' | '==' | '!=' | 'in' | 'not-in';
  value?: string | number;
  valueFrom?: string;
}

/** Column descriptor for an editable 'table' config field. */
export interface ModuleConfigTableColumn {
  /** Property name on each row object. Required. */
  key: string;
  /** Header label. Defaults to `key`. */
  label?: string;
  /** Cell input type. Defaults to 'string'. `'display'` is a read-only text
   * cell whose value is looked up per row via `lookup` (not editable, not
   * stored on the row). */
  type?: 'string' | 'number' | 'select' | 'display';
  /** Options for 'select'-typed cells. */
  options?: Array<{ value: string; label?: string }>;
  /** Dynamic option source for 'select'-typed cells. Overrides `options`. */
  optionsFrom?: ModuleConfigOptionsFrom;
  /**
   * Per-row dependent options for 'select'-typed cells: the option source is
   * chosen by the value of another column in the SAME row. Read
   * `row[switchColumn]`, look it up in `cases`, and resolve that
   * `ModuleConfigOptionsFrom` (config/model/server) for this row. Falls back to
   * `options` when the switch value is blank or has no matching case. Overrides
   * `optionsFrom`. Lets e.g. a "value" column show bus names when its row's
   * "resolution" is `bus` and region labels when it is `group2`.
   */
  optionsFromByColumn?: {
    switchColumn: string;
    cases: Record<string, ModuleConfigOptionsFrom>;
  };
  /**
   * For `'display'` cells: look up the text from a server dataset keyed by
   * another column in the same row. The host POSTs `{config}` to `endpoint`,
   * expects `{rows:[...]}`, then shows the `valueColumn` of the row whose
   * `keyColumn` equals this row's `matchColumn` value.
   */
  lookup?: {
    source: 'server' | 'plugin';
    /** For `source: 'server'`: the POST path. */
    endpoint?: string;
    /** For `source: 'plugin'`: the backend-plugin `options(name, …)` id. */
    name?: string;
    baseUrlField?: string;
    /** This row's column to match on (e.g. `'generator'`). */
    matchColumn: string;
    /** Fetched-row column matched against `matchColumn` (defaults to it). */
    keyColumn?: string;
    /** Fetched-row column whose value is displayed. */
    valueColumn: string;
  };
  /** Optional CSS width (px or rem string, or number-as-px). */
  width?: string | number;
}

/** Condition under which a config field is visible. */
export interface ModuleConfigVisibleWhen {
  /** Sibling field key whose current value drives visibility. */
  field: string;
  /** Field is visible iff sibling value strictly equals this. */
  equals: string | number | boolean;
}

export interface ModuleConfigField {
  type: ModuleConfigFieldType;
  label?: string;
  description?: string;
  default?: unknown;
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  options?: Array<{ value: unknown; label: string }>;
  /** For 'select' / 'multi-select' fields: dynamic option source. Overrides `options`. */
  optionsFrom?: ModuleConfigOptionsFrom;
  /**
   * For 'select' fields: prepend an empty `''` option so the user can clear the
   * selection back to unset. Label defaults to "— none —" (override with
   * `emptyLabel`). Use for optional selects whose blank value is meaningful.
   */
  clearable?: boolean;
  emptyLabel?: string;
  /** For 'file' fields: MIME types / extension filter passed to <input accept>. */
  accept?: string;
  /**
   * For 'file' fields: when true, the picker reads the file as a base64 data
   * URL (readAsDataURL) instead of text (readAsText). Use for binary formats
   * like xlsx, png, parquet where UTF-8 decoding would corrupt the bytes.
   * The plugin receives `content` as `data:<mime>;base64,<payload>`.
   */
  binary?: boolean;
  /** For 'table' fields: column schema. Required when type === 'table'. */
  columns?: ModuleConfigTableColumn[];
  /** For 'table' fields: max visible height in px before the body scrolls. Defaults to 260. */
  maxHeight?: number;
  /**
   * For 'group' fields in a two-column input layout: which column this group's
   * box belongs to. When any group declares a column, the host renders the
   * input as two stacked columns (with a draggable divider) instead of a grid,
   * so e.g. control boxes stay left and reference tables stay right.
   */
  column?: 'left' | 'right';
  /** Field is hidden unless this gate is satisfied. */
  visibleWhen?: ModuleConfigVisibleWhen;
  /**
   * For 'action' fields: the name of the plugin hook to invoke when the
   * button is clicked. `"transform"` runs the plugin's transform/contribute
   * and merges the result into the workbook (no solve). Any other name (e.g.
   * `"connect"`) invokes the same-named exported function on the plugin
   * module; its returned `{ ok, message }` drives a success/error toast.
   */
  hook?: string;
  /** For 'action' fields: button style. Defaults to 'primary'. */
  variant?: 'primary' | 'secondary';
  /** For 'action' fields: toast text on success. */
  successMessage?: string;
}

export interface PluginFileValue {
  name: string;
  content: string;
  mime: string;
}

export type ModuleConfigSchema = Record<string, ModuleConfigField>;

export interface ModuleDescriptor {
  id: string;
  name: string;
  version: string;
  sdkVersion: string;
  entry: string;
  entryPath: string;
  entryExists: boolean;
  description: string;
  capabilities: ModuleCapability[];
  permissions: ModulePermission[];
  compatible: boolean;
  valid: boolean;
  status: 'ready' | 'invalid' | 'incompatible';
  diagnostics: string[];
  manifestPath: string;
  modulePath: string;
  isManaged: boolean;
  config?: ModuleConfigSchema;
  panel?: ModulePanelConfig;
}

export interface ModuleHostInventory {
  host: {
    sdkVersion: string;
    supportedCapabilities: ModuleCapability[];
    supportedPermissions: ModulePermission[];
    managedRoot: ModuleHostRoot;
  };
  modules: ModuleDescriptor[];
  summary: {
    discovered: number;
    ready: number;
    invalid: number;
    incompatible: number;
  };
}
