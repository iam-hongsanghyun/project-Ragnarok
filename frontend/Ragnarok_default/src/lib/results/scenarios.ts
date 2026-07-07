import {
  CarbonPriceScheduleEntry,
  ContingencyConfig,
  AssetSwapConfig,
  BidStrategyConfig,
  CorrelatedSamplingConfig,
  CustomConstraint,
  ElccConfig,
  EssConfig,
  PpaConfig,
  DemandResponseConfig,
  FinanceConfig,
  GridRow,
  MgaConfig,
  MerchantConfig,
  ModelOverride,
  OutageMcConfig,
  PathwayConfig,
  MarketSimConfig,
  PowerFlowConfig,
  Primitive,
  RampConfig,
  ReserveConfig,
  RollingHorizonConfig,
  SamplingConfig,
  ScenarioCatalog,
  ScenarioPreset,
  SecurityConstrainedConfig,
  StochasticConfig,
  WorkbookModel,
} from '../types';
import { defaultPathwayConfig } from 'lib/results/pathway';
import { defaultRollingConfig, normalizeRollingConfig } from 'lib/results/rolling';
import { cloneSamplingConfig, defaultSamplingConfig } from 'lib/results/sampling';

export const SCENARIO_SHEET = 'RAGNAROK_Scenarios';

function primitiveBoolean(value: Primitive, fallback: boolean): boolean {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (normalized === 'true' || normalized === '1' || normalized === 'yes') return true;
    if (normalized === 'false' || normalized === '0' || normalized === 'no') return false;
  }
  return fallback;
}

function primitiveNumber(value: Primitive, fallback = 0): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function primitiveString(value: Primitive, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function clonePathwayConfig(config: PathwayConfig): PathwayConfig {
  return {
    ...config,
    periods: config.periods.map((row) => ({ ...row })),
  };
}

function cloneRollingConfig(config: RollingHorizonConfig): RollingHorizonConfig {
  return normalizeRollingConfig({ ...config });
}

function cloneConstraints(constraints: CustomConstraint[]): CustomConstraint[] {
  return constraints.map((row) => ({ ...row }));
}

export function defaultStochasticConfig(): StochasticConfig {
  return { enabled: false, scenarios: [] };
}

export function defaultSclopfConfig(): SecurityConstrainedConfig {
  return { enabled: false };
}

export function defaultReserveConfig(): ReserveConfig {
  return { enabled: false, requirementType: 'fraction', fraction: 0.1, providers: 'all', reserveCost: 0 };
}

export function defaultOutageMcConfig(): OutageMcConfig {
  return {
    enabled: false,
    nMembers: 200,
    seed: 42,
    forcedOutageRate: 0.05,
    mttrHours: 48,
    includeRenewableEnsemble: false,
  };
}

export function defaultCorrelatedSamplingConfig(): CorrelatedSamplingConfig {
  return {
    enabled: false,
    nMembers: 200,
    seed: 42,
    loadSensitivity: 0.15,
    renewableSensitivity: 0.3,
    inflowSensitivity: 0.2,
    loadStd: 0.05,
    renewableStd: 0.1,
    inflowStd: 0.1,
  };
}

export function defaultRampConfig(): RampConfig {
  return { enabled: false, rampLimitUp: 0.5, rampLimitDown: 0.5, appliesTo: 'all' };
}

export function defaultElccConfig(): ElccConfig {
  return {
    enabled: false,
    nMembers: 200,
    seed: 42,
    forcedOutageRate: 0.05,
    mttrHours: 48,
    carriers: [],
  };
}

export function defaultPowerFlowConfig(): PowerFlowConfig {
  return { enabled: false, linear: false };
}

export function defaultMarketSimConfig(): MarketSimConfig {
  return {
    enabled: false, pricing: 'uniform', voll: 3000, chargeQuantile: 0.25, dischargeQuantile: 0.75,
    clearingModel: 'singleSided', demandElasticFraction: 0.2, demandWtp: 120, demandBids: [],
  };
}

export function defaultContingencyConfig(): ContingencyConfig {
  return { enabled: false };
}

export function defaultMgaConfig(): MgaConfig {
  return { enabled: false, slack: 0.05, carriers: [] };
}

export function defaultMerchantConfig(): MerchantConfig {
  return { enabled: false, owner: '', priceSource: 'lmp', flatPrice: 0 };
}

export function defaultBidStrategyConfig(): BidStrategyConfig {
  return { enabled: false, mode: 'fixed', owner: '', markupType: 'percent', markup: 0.2, maxMarkup: 2.0, steps: 8 };
}

export function defaultAssetSwapConfig(): AssetSwapConfig {
  return { enabled: false, removeFilters: [], addCarrier: '', addCapitalCost: 0, addMarginalCost: 0, replaceRatio: 1, addStorageMW: 0, addStorageHours: 4, addStorageCapexPerMW: 20000 };
}

export function defaultEssConfig(): EssConfig {
  return { enabled: false, bus: '', maxHours: 4, capitalCostPerMW: 30000, minSizeMW: 10, maxSizeMW: 100, steps: 6, roundTripEfficiency: 0.9 };
}

export function defaultPpaConfig(): PpaConfig {
  return { enabled: false, owner: '', volumeType: 'generation', flatMW: 0, strikePrice: 0 };
}

export function defaultDemandResponseConfig(): DemandResponseConfig {
  return { enabled: false, loads: [], shiftFraction: 0.2, maxShiftHours: 4, elasticEnabled: false, elasticFraction: 0.2, wtpMax: 200 };
}

export function defaultOwnerColumn(): string {
  return 'owner';
}

export function defaultFinanceConfig(): FinanceConfig {
  return { gearing: 0, interestRate: 0.05, tenorYears: 15 };
}

function cloneStochasticConfig(config: StochasticConfig): StochasticConfig {
  return {
    ...config,
    scenarios: (config.scenarios ?? []).map((s) => ({
      ...s,
      overrides: (s.overrides ?? []).map((o) => ({ ...o })),
    })),
  };
}

function cloneSclopfConfig(config: SecurityConstrainedConfig): SecurityConstrainedConfig {
  return { ...config };
}

function cloneReserveConfig(config: ReserveConfig): ReserveConfig {
  return { ...config };
}

function cloneOutageMcConfig(config: OutageMcConfig): OutageMcConfig {
  return { ...config };
}

function cloneCorrelatedSamplingConfig(config: CorrelatedSamplingConfig): CorrelatedSamplingConfig {
  return { ...config };
}

function cloneRampConfig(config: RampConfig): RampConfig {
  return { ...config };
}

function cloneElccConfig(config: ElccConfig): ElccConfig {
  return { ...config, carriers: [...(config.carriers ?? [])] };
}

function clonePowerFlowConfig(config: PowerFlowConfig): PowerFlowConfig {
  return { ...config };
}

function cloneMarketSimConfig(config: MarketSimConfig): MarketSimConfig {
  // Merge over defaults so scenarios saved before the clearing-model fields
  // existed pick them up rather than carrying undefined.
  return { ...defaultMarketSimConfig(), ...config };
}

function cloneContingencyConfig(config: ContingencyConfig): ContingencyConfig {
  return { ...config };
}

function cloneMgaConfig(config: MgaConfig): MgaConfig {
  return { ...config, carriers: [...(config.carriers ?? [])] };
}

function cloneMerchantConfig(config: MerchantConfig): MerchantConfig {
  return { ...config, priceSeries: config.priceSeries ? [...config.priceSeries] : undefined };
}

function cloneBidStrategyConfig(config: BidStrategyConfig): BidStrategyConfig {
  return { ...config };
}

function cloneAssetSwapConfig(config: AssetSwapConfig): AssetSwapConfig {
  return { ...config, removeFilters: (config.removeFilters ?? []).map((f) => ({ ...f, values: [...(f.values ?? [])] })) };
}

function cloneEssConfig(config: EssConfig): EssConfig {
  return { ...config };
}

function clonePpaConfig(config: PpaConfig): PpaConfig {
  return { ...config };
}

function cloneDemandResponseConfig(config: DemandResponseConfig): DemandResponseConfig {
  return { ...config, loads: [...(config.loads ?? [])] };
}

function cloneFinanceConfig(config: FinanceConfig): FinanceConfig {
  return { ...config };
}

function cloneSchedule(schedule: CarbonPriceScheduleEntry[]): CarbonPriceScheduleEntry[] {
  return (schedule ?? []).map((row) => ({ ...row }));
}

function cloneModelOverrides(overrides: ModelOverride[] | undefined): ModelOverride[] {
  return (overrides ?? [])
    .filter((o): o is ModelOverride => !!o && !!o.sheet && !!o.name && !!o.column)
    .map((o) => ({ sheet: o.sheet, name: o.name, column: o.column, value: o.value }));
}

export function createScenarioId(): string {
  return `scenario-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function buildScenarioPreset(input: {
  id?: string;
  label?: string;
  notes?: string;
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  carbonPrice: number;
  carbonPriceSchedule?: CarbonPriceScheduleEntry[];
  discountRate: number;
  forceLp: boolean;
  enableLoadShedding: boolean;
  loadSheddingCost: number;
  pathwayConfig: PathwayConfig;
  rollingConfig: RollingHorizonConfig;
  // Optional for backward compatibility — presets saved before these modes
  // were captured default to disabled.
  stochasticConfig?: StochasticConfig;
  securityConstrainedConfig?: SecurityConstrainedConfig;
  reserveConfig?: ReserveConfig;
  outageMcConfig?: OutageMcConfig;
  correlatedSamplingConfig?: CorrelatedSamplingConfig;
  rampConfig?: RampConfig;
  elccConfig?: ElccConfig;
  powerFlowConfig?: PowerFlowConfig;
  marketSimConfig?: MarketSimConfig;
  contingencyConfig?: ContingencyConfig;
  mgaConfig?: MgaConfig;
  merchantConfig?: MerchantConfig;
  bidStrategyConfig?: BidStrategyConfig;
  assetSwapConfig?: AssetSwapConfig;
  essConfig?: EssConfig;
  ppaConfig?: PpaConfig;
  demandResponseConfig?: DemandResponseConfig;
  ownerColumn?: string;
  financeConfig?: FinanceConfig;
  samplingConfig?: SamplingConfig;
  constraints: CustomConstraint[];
  modelOverrides?: ModelOverride[];
}): ScenarioPreset {
  return {
    id: input.id ?? createScenarioId(),
    label: input.label?.trim() || 'Scenario',
    notes: input.notes ?? '',
    snapshotStart: input.snapshotStart,
    snapshotEnd: input.snapshotEnd,
    snapshotWeight: input.snapshotWeight,
    carbonPrice: input.carbonPrice,
    carbonPriceSchedule: cloneSchedule(input.carbonPriceSchedule ?? []),
    discountRate: input.discountRate,
    forceLp: input.forceLp,
    enableLoadShedding: input.enableLoadShedding,
    loadSheddingCost: input.loadSheddingCost,
    pathwayConfig: clonePathwayConfig(input.pathwayConfig),
    rollingConfig: cloneRollingConfig(input.rollingConfig),
    stochasticConfig: cloneStochasticConfig(input.stochasticConfig ?? defaultStochasticConfig()),
    securityConstrainedConfig: cloneSclopfConfig(input.securityConstrainedConfig ?? defaultSclopfConfig()),
    reserveConfig: cloneReserveConfig(input.reserveConfig ?? defaultReserveConfig()),
    outageMcConfig: cloneOutageMcConfig(input.outageMcConfig ?? defaultOutageMcConfig()),
    correlatedSamplingConfig: cloneCorrelatedSamplingConfig(input.correlatedSamplingConfig ?? defaultCorrelatedSamplingConfig()),
    rampConfig: cloneRampConfig(input.rampConfig ?? defaultRampConfig()),
    elccConfig: cloneElccConfig(input.elccConfig ?? defaultElccConfig()),
    powerFlowConfig: clonePowerFlowConfig(input.powerFlowConfig ?? defaultPowerFlowConfig()),
    marketSimConfig: cloneMarketSimConfig(input.marketSimConfig ?? defaultMarketSimConfig()),
    contingencyConfig: cloneContingencyConfig(input.contingencyConfig ?? defaultContingencyConfig()),
    mgaConfig: cloneMgaConfig(input.mgaConfig ?? defaultMgaConfig()),
    merchantConfig: cloneMerchantConfig(input.merchantConfig ?? defaultMerchantConfig()),
    bidStrategyConfig: cloneBidStrategyConfig(input.bidStrategyConfig ?? defaultBidStrategyConfig()),
    assetSwapConfig: cloneAssetSwapConfig(input.assetSwapConfig ?? defaultAssetSwapConfig()),
    essConfig: cloneEssConfig(input.essConfig ?? defaultEssConfig()),
    ppaConfig: clonePpaConfig(input.ppaConfig ?? defaultPpaConfig()),
    demandResponseConfig: cloneDemandResponseConfig(input.demandResponseConfig ?? defaultDemandResponseConfig()),
    ownerColumn: (input.ownerColumn ?? defaultOwnerColumn()) || defaultOwnerColumn(),
    financeConfig: cloneFinanceConfig(input.financeConfig ?? defaultFinanceConfig()),
    samplingConfig: cloneSamplingConfig(input.samplingConfig ?? defaultSamplingConfig()),
    constraints: cloneConstraints(input.constraints),
    modelOverrides: cloneModelOverrides(input.modelOverrides),
  };
}

export function defaultScenarioCatalog(
  base: Omit<ScenarioPreset, 'id' | 'label' | 'notes' | 'modelOverrides'> & { modelOverrides?: ModelOverride[] },
): ScenarioCatalog {
  const scenario = buildScenarioPreset({
    ...base,
    id: 'scenario-base',
    label: 'Base case',
    notes: '',
  });
  return {
    activeScenarioId: scenario.id,
    scenarios: [scenario],
  };
}

function normalizeScenarioCatalog(catalog: ScenarioCatalog): ScenarioCatalog {
  if (catalog.scenarios.length === 0) {
    return { activeScenarioId: null, scenarios: [] };
  }
  const activeExists = catalog.activeScenarioId !== null
    && catalog.scenarios.some((scenario) => scenario.id === catalog.activeScenarioId);
  return {
    activeScenarioId: activeExists ? catalog.activeScenarioId : catalog.scenarios[0].id,
    scenarios: catalog.scenarios.map((scenario) => ({
      ...scenario,
      label: scenario.label.trim() || 'Scenario',
      notes: scenario.notes ?? '',
      carbonPriceSchedule: cloneSchedule(scenario.carbonPriceSchedule ?? []),
      pathwayConfig: clonePathwayConfig(scenario.pathwayConfig ?? defaultPathwayConfig()),
      rollingConfig: cloneRollingConfig(scenario.rollingConfig ?? defaultRollingConfig()),
      stochasticConfig: cloneStochasticConfig(scenario.stochasticConfig ?? defaultStochasticConfig()),
      securityConstrainedConfig: cloneSclopfConfig(scenario.securityConstrainedConfig ?? defaultSclopfConfig()),
      reserveConfig: cloneReserveConfig(scenario.reserveConfig ?? defaultReserveConfig()),
      outageMcConfig: cloneOutageMcConfig(scenario.outageMcConfig ?? defaultOutageMcConfig()),
      correlatedSamplingConfig: cloneCorrelatedSamplingConfig(scenario.correlatedSamplingConfig ?? defaultCorrelatedSamplingConfig()),
      rampConfig: cloneRampConfig(scenario.rampConfig ?? defaultRampConfig()),
      elccConfig: cloneElccConfig(scenario.elccConfig ?? defaultElccConfig()),
      powerFlowConfig: clonePowerFlowConfig(scenario.powerFlowConfig ?? defaultPowerFlowConfig()),
      marketSimConfig: cloneMarketSimConfig(scenario.marketSimConfig ?? defaultMarketSimConfig()),
      contingencyConfig: cloneContingencyConfig(scenario.contingencyConfig ?? defaultContingencyConfig()),
      mgaConfig: cloneMgaConfig(scenario.mgaConfig ?? defaultMgaConfig()),
      merchantConfig: cloneMerchantConfig(scenario.merchantConfig ?? defaultMerchantConfig()),
      bidStrategyConfig: cloneBidStrategyConfig(scenario.bidStrategyConfig ?? defaultBidStrategyConfig()),
      assetSwapConfig: cloneAssetSwapConfig(scenario.assetSwapConfig ?? defaultAssetSwapConfig()),
      essConfig: cloneEssConfig(scenario.essConfig ?? defaultEssConfig()),
      ppaConfig: clonePpaConfig(scenario.ppaConfig ?? defaultPpaConfig()),
      demandResponseConfig: cloneDemandResponseConfig(scenario.demandResponseConfig ?? defaultDemandResponseConfig()),
      ownerColumn: (scenario.ownerColumn ?? defaultOwnerColumn()) || defaultOwnerColumn(),
      financeConfig: cloneFinanceConfig(scenario.financeConfig ?? defaultFinanceConfig()),
      samplingConfig: cloneSamplingConfig(scenario.samplingConfig ?? defaultSamplingConfig()),
      constraints: cloneConstraints(scenario.constraints ?? []),
      modelOverrides: cloneModelOverrides(scenario.modelOverrides),
    })),
  };
}

export function readScenarioCatalogFromModel(model: WorkbookModel): ScenarioCatalog {
  const rows = model[SCENARIO_SHEET] ?? [];
  const scenarios = rows.map((row): ScenarioPreset | null => {
    const id = primitiveString(row.id as Primitive).trim();
    if (!id) return null;
    try {
      const payload = typeof row.json === 'string' && row.json.trim()
        ? JSON.parse(row.json)
        : {};
      return buildScenarioPreset({
        id,
        label: primitiveString(row.label as Primitive, payload.label ?? 'Scenario'),
        notes: primitiveString(row.notes as Primitive, payload.notes ?? ''),
        snapshotStart: primitiveNumber(payload.snapshotStart as Primitive, 0),
        snapshotEnd: primitiveNumber(payload.snapshotEnd as Primitive, 24),
        snapshotWeight: primitiveNumber(payload.snapshotWeight as Primitive, 1),
        carbonPrice: primitiveNumber(payload.carbonPrice as Primitive, 0),
        carbonPriceSchedule: Array.isArray(payload.carbonPriceSchedule) ? payload.carbonPriceSchedule : [],
        discountRate: primitiveNumber(payload.discountRate as Primitive, 0),
        forceLp: primitiveBoolean(payload.forceLp as Primitive, false),
        enableLoadShedding: primitiveBoolean(payload.enableLoadShedding as Primitive, false),
        loadSheddingCost: primitiveNumber(payload.loadSheddingCost as Primitive, 1000),
        pathwayConfig: payload.pathwayConfig ?? defaultPathwayConfig(),
        rollingConfig: payload.rollingConfig ?? defaultRollingConfig(),
        stochasticConfig: payload.stochasticConfig ?? defaultStochasticConfig(),
        securityConstrainedConfig: payload.securityConstrainedConfig ?? defaultSclopfConfig(),
        reserveConfig: payload.reserveConfig ?? defaultReserveConfig(),
        outageMcConfig: payload.outageMcConfig ?? defaultOutageMcConfig(),
        correlatedSamplingConfig: payload.correlatedSamplingConfig ?? defaultCorrelatedSamplingConfig(),
        rampConfig: payload.rampConfig ?? defaultRampConfig(),
        elccConfig: payload.elccConfig ?? defaultElccConfig(),
        powerFlowConfig: payload.powerFlowConfig ?? defaultPowerFlowConfig(),
        marketSimConfig: payload.marketSimConfig ?? defaultMarketSimConfig(),
        contingencyConfig: payload.contingencyConfig ?? defaultContingencyConfig(),
        mgaConfig: payload.mgaConfig ?? defaultMgaConfig(),
        merchantConfig: payload.merchantConfig ?? defaultMerchantConfig(),
        bidStrategyConfig: payload.bidStrategyConfig ?? defaultBidStrategyConfig(),
        assetSwapConfig: payload.assetSwapConfig ?? defaultAssetSwapConfig(),
        essConfig: payload.essConfig ?? defaultEssConfig(),
        ppaConfig: payload.ppaConfig ?? defaultPpaConfig(),
        demandResponseConfig: payload.demandResponseConfig ?? defaultDemandResponseConfig(),
        ownerColumn: payload.ownerColumn ?? payload.merchantConfig?.ownerColumn ?? defaultOwnerColumn(),
        financeConfig: payload.financeConfig ?? defaultFinanceConfig(),
        samplingConfig: payload.samplingConfig ?? defaultSamplingConfig(),
        constraints: Array.isArray(payload.constraints) ? payload.constraints : [],
        modelOverrides: Array.isArray(payload.modelOverrides) ? payload.modelOverrides : [],
      });
    } catch {
      return null;
    }
  }).filter((row): row is ScenarioPreset => !!row);

  const activeScenarioId =
    rows.find((row) => primitiveBoolean(row.active as Primitive, false))?.id as string | undefined;

  return normalizeScenarioCatalog({
    activeScenarioId: activeScenarioId ?? null,
    scenarios,
  });
}

export function writeScenarioCatalogToModel(
  model: WorkbookModel,
  catalog: ScenarioCatalog,
): WorkbookModel {
  const normalized = normalizeScenarioCatalog(catalog);
  const rows: GridRow[] = normalized.scenarios.map((scenario) => ({
    id: scenario.id,
    label: scenario.label,
    active: scenario.id === normalized.activeScenarioId,
    notes: scenario.notes,
    json: JSON.stringify({
      snapshotStart: scenario.snapshotStart,
      snapshotEnd: scenario.snapshotEnd,
      snapshotWeight: scenario.snapshotWeight,
      carbonPrice: scenario.carbonPrice,
      carbonPriceSchedule: scenario.carbonPriceSchedule,
      discountRate: scenario.discountRate,
      forceLp: scenario.forceLp,
      enableLoadShedding: scenario.enableLoadShedding,
      loadSheddingCost: scenario.loadSheddingCost,
      pathwayConfig: scenario.pathwayConfig,
      rollingConfig: scenario.rollingConfig,
      stochasticConfig: scenario.stochasticConfig,
      securityConstrainedConfig: scenario.securityConstrainedConfig,
      reserveConfig: scenario.reserveConfig,
      outageMcConfig: scenario.outageMcConfig,
      correlatedSamplingConfig: scenario.correlatedSamplingConfig,
      rampConfig: scenario.rampConfig,
      elccConfig: scenario.elccConfig,
      powerFlowConfig: scenario.powerFlowConfig,
      marketSimConfig: scenario.marketSimConfig,
      contingencyConfig: scenario.contingencyConfig,
      mgaConfig: scenario.mgaConfig,
      merchantConfig: scenario.merchantConfig,
      bidStrategyConfig: scenario.bidStrategyConfig,
      assetSwapConfig: scenario.assetSwapConfig,
      essConfig: scenario.essConfig,
      ppaConfig: scenario.ppaConfig,
      demandResponseConfig: scenario.demandResponseConfig,
      ownerColumn: scenario.ownerColumn,
      financeConfig: scenario.financeConfig,
      samplingConfig: scenario.samplingConfig,
      constraints: scenario.constraints,
      modelOverrides: scenario.modelOverrides,
    }),
  }));
  return {
    ...model,
    [SCENARIO_SHEET]: rows,
  };
}

export function sameScenarioCatalog(left: ScenarioCatalog, right: ScenarioCatalog): boolean {
  return JSON.stringify(normalizeScenarioCatalog(left)) === JSON.stringify(normalizeScenarioCatalog(right));
}
