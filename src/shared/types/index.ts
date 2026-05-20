import { SHEETS, TS_SHEETS } from '../../constants/sheets';

// ── Sheet name types ──────────────────────────────────────────────────────────

export type SheetName = (typeof SHEETS)[number];
export type TsSheetName = (typeof TS_SHEETS)[number];
export type AnySheetName = SheetName | TsSheetName;

// ── Primitives ────────────────────────────────────────────────────────────────

export type Primitive = string | number | boolean | null;
export type GridRow = Record<string, Primitive>;
export type BrowserFileHandle = any;

// ── UI state ──────────────────────────────────────────────────────────────────

export type WorkspaceTab = 'Model' | 'Analytics' | 'Plugins';
export type PluginDisplayMode = 'sidebar' | 'panel';
export type ModelSubTab = 'Map' | 'Table';
export type AnalyticsSubTab = 'Validation' | 'Result' | 'Analytics' | 'Comparison';
export type ChartMode = 'line' | 'area' | 'bar';
export type ChartSectionType = ChartMode | 'donut';
export type TimeframeOption = 'aggregated' | 'yearly' | 'monthly' | 'weekly' | 'daily' | 'hourly';

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

export interface WorkbookModel {
  network: GridRow[];
  snapshots: GridRow[];
  carriers: GridRow[];
  buses: GridRow[];
  generators: GridRow[];
  loads: GridRow[];
  links: GridRow[];
  lines: GridRow[];
  stores: GridRow[];
  storage_units: GridRow[];
  transformers: GridRow[];
  shunt_impedances: GridRow[];
  global_constraints: GridRow[];
  shapes: GridRow[];
  processes: GridRow[];
  'generators-p_max_pu': GridRow[];
  'generators-p_min_pu': GridRow[];
  'loads-p_set': GridRow[];
  'storage_units-inflow': GridRow[];
  'links-p_max_pu': GridRow[];
}

export interface CustomConstraint {
  id: string;
  enabled: boolean;
  label: string;
  metric: ConstraintMetric;
  carrier: string;
  value: number;
  unit: string;
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
}

export interface ValuePoint {
  label: string;
  timestamp?: string;
  value: number;
}

export interface StoragePoint {
  label: string;
  timestamp: string;
  charge: number;
  discharge: number;
  state: number;
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
}

export interface PluginAnalyticsEntry {
  name: string;
  ui: Record<string, PluginFieldHint>;
  data: Record<string, unknown>;
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
  emissionsBreakdown?: EmissionsBreakdown;
  narrative: string[];
  runMeta: {
    snapshotCount: number;
    snapshotWeight: number;
    modeledHours: number;
    storeWeight: number;
  };
  assetDetails: {
    generators: Record<string, GeneratorDetail>;
    buses: Record<string, BusDetail>;
    storageUnits: Record<string, StorageUnitDetail>;
    stores: Record<string, StoreDetail>;
    branches: Record<string, BranchDetail>;
  };
}

// ── Run history ───────────────────────────────────────────────────────────────

export interface RunHistoryEntry {
  id: string;
  label: string;
  savedAt: string;
  filename: string;
  carbonPrice: number;
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  activeConstraints: CustomConstraint[];
  componentCounts: {
    generators: number;
    buses: number;
    lines: number;
    links: number;
    storageUnits: number;
  };
  pinned: boolean;
  inComparison: boolean;   // false = excluded from Comparison tab, still in history
  results: RunResults;
}

export type AnalyticsFocus =
  | { type: 'system' }
  | { type: 'generator'; key: string }
  | { type: 'bus'; key: string }
  | { type: 'storageUnit'; key: string }
  | { type: 'store'; key: string }
  | { type: 'branch'; key: string };

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
  metricKey: string;
  chartType: ChartSectionType;
  timeframe: TimeframeOption;
  startIndex: number;
  endIndex: number;
  stacked: boolean;
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

export type ModuleConfigFieldType = 'number' | 'boolean' | 'string' | 'select' | 'carrier-select';

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
