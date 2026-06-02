import { SHEETS, TS_SHEETS } from 'lib/constants/sheets';

// ── Sheet name types ──────────────────────────────────────────────────────────

export type SheetName = string;
export type TsSheetName = string;
export type AnySheetName = SheetName | TsSheetName;

// ── Primitives ────────────────────────────────────────────────────────────────

export type Primitive = string | number | boolean | null;
export type GridRow = Record<string, Primitive>;
export type BrowserFileHandle = any;

// ── UI state ──────────────────────────────────────────────────────────────────

export type WorkspaceTab = 'Welcome' | 'Build' | 'Data' | 'Forge' | 'Model' | 'Settings' | 'Analytics' | 'Plugins';
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

export type PluginFieldFormat = 'number' | 'currency' | 'table' | 'text';

export interface PluginFieldHint {
  label?: string;
  unit?: string;
  format?: PluginFieldFormat;
  section?: string;
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
  generatorDispatchSeries: SeriesPoint[];
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

export type ModuleConfigFieldType = 'number' | 'boolean' | 'string' | 'select' | 'carrier-select' | 'file' | 'table' | 'action' | 'group';

/** Column descriptor for an editable 'table' config field. */
export interface ModuleConfigTableColumn {
  /** Property name on each row object. Required. */
  key: string;
  /** Header label. Defaults to `key`. */
  label?: string;
  /** Cell input type. Defaults to 'string'. */
  type?: 'string' | 'number' | 'select';
  /** Options for 'select'-typed cells. */
  options?: Array<{ value: string; label?: string }>;
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
