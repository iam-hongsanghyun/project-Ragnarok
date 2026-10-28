/**
 * Server-side results (WA7): run comparison, the KPI strip, company comparison
 * and per-asset details are computed by the backend from the stored run
 * (`backend/app/routers/results_derived.py`), so the browser renders them instead
 * of re-deriving them from raw output series.
 *
 *   GET /api/results/compare?runs=a,b&topics=...   -> {items, total, topics}
 *   GET /api/runs/{name}/kpis?currency=&period=    -> {run, period, kpis}
 *   GET /api/runs/{name}/companies?sort_by=&period= -> {run, period, items, total, currency, sortedBy, metrics}
 *   GET /api/runs/{name}/assets?kind=&names=&series=&period=&end=  -> {run, items, total, offset, limit}
 *   GET /api/runs/{name}/period/{period}?currency= -> {run, period, result}  (one investment period of a pathway run)
 *   GET /api/runs/{name}/derived?period=          -> {run, period, weights, modeledHours, generators, buses, processes}
 *   GET /api/runs/{name}/metrics?focus=&keys=&groupBy=...  -> {run, focus, items: MetricOption[], total}
 *   GET /api/runs/{name}/analysis/{topic}?period=...  -> card analytics (load, carrier performance,
 *       transition risk, duration curve, totals); see `fetchRunAnalysis`
 */
import { API_BASE } from 'lib/constants';
import type {
  AnalyticsFocus, AnnualBudgetEntry, BranchDetail, BusDetail, GeneratorDetail, GroupByOption, MetricOption, ProcessDetail,
  RunResults, ShuntImpedanceDetail, StorageUnitDetail, StoreDetail, SummaryItem,
} from 'lib/types';

async function getJson<T>(path: string, what: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`);
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json())?.detail ?? detail; } catch { /* non-JSON body */ }
    throw new Error(`${what} failed (${resp.status}): ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`);
  }
  return resp.json() as Promise<T>;
}

const enc = encodeURIComponent;

// ── Comparison ────────────────────────────────────────────────────────────────

export type ComparisonTopicId =
  | 'kpi' | 'generation-mix' | 'installed-capacity' | 'cost' | 'emissions' | 'capacity' | 'generation-time';

export interface LabelledValue { label: string; value: number }

/** One scenario column; every field is present only when its topic was requested. */
export interface ComparisonEntry {
  name: string;
  label: string;
  summary?: SummaryItem[];
  carrierMix?: LabelledValue[];
  capacityMix?: LabelledValue[];
  generatorCapacityMw?: number;
  storageCapacityMw?: number;
  costBreakdown?: LabelledValue[];
  emissionsByCarrier?: LabelledValue[];
  expansion?: Array<{ name: string; carrier: string; installedMw: number; optimisedMw: number }>;
  dispatchSeries?: Array<{ label: string; timestamp: string; values: Record<string, number> }>;
  dispatchStride?: number;
}

export interface ComparisonResponse {
  items: ComparisonEntry[];
  total: number;
  topics: ComparisonTopicId[];
}

export const fetchRunComparison = (runs: string[], topics: string[]): Promise<ComparisonResponse> =>
  getJson(`/api/results/compare?runs=${enc(runs.join(','))}&topics=${enc(topics.join(','))}`, 'Run comparison');

// ── KPI strip ─────────────────────────────────────────────────────────────────

/** `null` where the strip shows an em dash. */
export interface RunKpis {
  totalCost: string | null;
  dispatchMwh: number;
  avgPrice: number;
  minPrice: number | null;
  maxPrice: number | null;
  peakLoadMw: number | null;
  loadFactor: number | null;
  renewableSharePct: number;
  emissions: string | null;
  snapshotCount: number | null;
  snapshotWeightHours: number | null;
  currencySymbol: string;
}

export const fetchRunKpis = (
  run: string, currency: string, period?: number | null,
): Promise<{ run: string; period: number | null; kpis: RunKpis }> =>
  getJson(`/api/runs/${enc(run)}/kpis?currency=${enc(currency)}${period != null ? `&period=${period}` : ''}`, 'KPIs');

// ── Annual budgets vs achieved ────────────────────────────────────────────────

/** `GET /api/runs/{name}/annual-budgets`: a budget the run applied, with what the solve achieved. */
export interface AnnualBudgetRow extends AnnualBudgetEntry {
  /** What PyPSA's statistics (e_sum) or the constraint's left-hand side (CO2 cap) came to; null where nothing is read back. */
  achieved: number | null;
  /** `MWh`, `tCO2`, or the reason `achieved` is missing. */
  achievedUnit: string;
  /** `global_constraints.mu` (currency per unit of the budget); null where PyPSA stores none (e_sum). */
  dual: number | null;
  /** True when `achieved` sits on the written bound; null when unknown. */
  binding: boolean | null;
}

export const fetchRunAnnualBudgets = (run: string): Promise<{ run: string; items: AnnualBudgetRow[]; total: number }> =>
  getJson(`/api/runs/${enc(run)}/annual-budgets`, 'Annual budgets');

// ── One investment period of a pathway run ───────────────────────────────────

/** The result payload of one investment period (same shape as the run's analytics `result`,
 *  without `outputs`): every figure in it is `n.statistics` on that period's slice. */
export interface PeriodResponse {
  run: string;
  period: number;
  result: RunResults;
}

export const fetchRunPeriod = (run: string, period: number, currency?: string): Promise<PeriodResponse> =>
  getJson(`/api/runs/${enc(run)}/period/${period}${currency ? `?currency=${enc(currency)}` : ''}`, 'Period results');

// ── Company comparison ────────────────────────────────────────────────────────

export interface CompanyRow {
  company: string;
  capacityMW?: number | null;
  energyMWh?: number | null;
  revenue?: number | null;
  emissionsTonnes?: number | null;
  npv?: number | null;
  irr?: number | null;
  paybackYears?: number | null;
  netMargin?: number | null;
}

export interface CompanyMetricDef { key: string; label: string; higherBetter: boolean }

export interface CompanyComparison {
  run: string;
  period?: number | null;
  items: CompanyRow[];
  total: number;
  currency: string;
  sortedBy: string;
  metrics: CompanyMetricDef[];
}

export const fetchRunCompanies = (run: string, sortBy?: string, period?: number | null): Promise<CompanyComparison> => {
  const params = new URLSearchParams();
  if (sortBy) params.set('sort_by', sortBy);
  if (period != null) params.set('period', String(period));
  const qs = params.toString();
  return getJson(`/api/runs/${enc(run)}/companies${qs ? `?${qs}` : ''}`, 'Company comparison');
};

// ── Per-asset details ─────────────────────────────────────────────────────────

export type AssetKind =
  | 'generators' | 'buses' | 'storageUnits' | 'stores' | 'branches' | 'processes' | 'shuntImpedances';

type WithKind<K extends AssetKind, T> = T & { kind: K };

export type AssetItem =
  | WithKind<'generators', GeneratorDetail>
  | WithKind<'buses', BusDetail>
  | WithKind<'storageUnits', StorageUnitDetail>
  | WithKind<'stores', StoreDetail>
  | WithKind<'branches', BranchDetail>
  | WithKind<'processes', ProcessDetail>
  | WithKind<'shuntImpedances', ShuntImpedanceDetail>;

export interface AssetsResponse {
  run: string;
  items: AssetItem[];
  total: number;
  offset: number;
  limit: number;
}

/** Full detail (with series) of the named assets of one kind. */
export const fetchRunAssets = (
  run: string, kind: AssetKind, names: string[], currency: string, period?: number | null,
): Promise<AssetsResponse> =>
  getJson(
    `/api/runs/${enc(run)}/assets?kind=${kind}&names=${enc(names.join(','))}&currency=${enc(currency)}`
      + (period != null ? `&period=${period}` : ''),
    'Asset details',
  );

/** Details (with series) of EVERY asset of one kind, paged; `end` = first N snapshots of the period. */
export async function fetchRunAssetKind(
  run: string, kind: AssetKind, currency: string, opts: { period?: number | null; end?: number | null } = {},
): Promise<AssetItem[]> {
  const out: AssetItem[] = [];
  const limit = 500;
  for (let offset = 0; ; offset += limit) {
    const page = await getJson<AssetsResponse>(
      `/api/runs/${enc(run)}/assets?kind=${kind}&series=true&currency=${enc(currency)}&offset=${offset}&limit=${limit}`
        + (opts.period != null ? `&period=${opts.period}` : '')
        + (opts.end != null ? `&end=${opts.end}` : ''),
      'Asset details',
    );
    out.push(...page.items);
    if (offset + limit >= page.total) return out;
  }
}

// ── Per-asset chart metrics ───────────────────────────────────────────────────

export interface MetricsQuery {
  focus: Exclude<AnalyticsFocus['type'], 'system'>;
  /** One name = that asset's own metrics; [] = every asset of the type; several = merged. */
  keys: string[];
  groupBy: GroupByOption;
  busFilter: string[];
  carrierFilter: string[];
  /** Pathway investment period; null = every row. */
  period: number | null;
  /** First N snapshots only; null = the whole run. */
  end: number | null;
  currency: string;
}

export interface MetricsResponse {
  run: string;
  focus: string;
  items: MetricOption[];
  total: number;
}

/** Chart-ready metrics (rows, series, colours) of a per-asset focus, derived on the server. */
export const fetchRunMetrics = (run: string, q: MetricsQuery): Promise<MetricsResponse> => {
  const params = new URLSearchParams({ focus: q.focus, groupBy: q.groupBy, currency: q.currency });
  if (q.keys.length) params.set('keys', q.keys.join(','));
  if (q.busFilter.length) params.set('busFilter', q.busFilter.join(','));
  if (q.carrierFilter.length) params.set('carrierFilter', q.carrierFilter.join(','));
  if (q.period != null) params.set('period', String(q.period));
  if (q.end != null) params.set('end', String(q.end));
  return getJson(`/api/runs/${enc(run)}/metrics?${params.toString()}`, 'Chart metrics');
};

// ── Card analytics (load factor, carrier performance, transition risk, duration curve, totals) ──

export interface LoadAnalysisBus {
  name: string;
  peakMw: number;
  energyMwh: number;
  /** mean / peak, null when the bus never draws power. */
  loadFactor: number | null;
  /** Fraction of the system energy (0..1). */
  share: number;
}

export interface LoadAnalysis {
  run: string;
  topic: 'load-analysis';
  period: number | null;
  systemPeakMw: number;
  systemEnergyMwh: number;
  systemLoadFactor: number | null;
  coincidenceFactor: number | null;
  /** Buses with energy, largest first. */
  buses: LoadAnalysisBus[];
  total: number;
}

export interface CarrierPerformanceRow {
  carrier: string;
  color: string;
  generatorCount: number;
  nameplateMw: number;
  capacityShare: number;
  generatedMw: number;
  energyMwh: number;
  generationShare: number;
  capacityFactor: number | null;
  curtailmentMwh: number | null;
}

export interface CarrierPerformance {
  run: string;
  topic: 'carrier-performance';
  period: number | null;
  rows: CarrierPerformanceRow[];
  total: number;
  totals: {
    generatorCount: number;
    nameplateMw: number;
    generatedMw: number;
    energyMwh: number;
    curtailmentMwh: number | null;
  } | null;
}

export interface TransitionRiskQuery {
  baseYear: number;
  years: number;
  basePrice: number;
  escalationPct: number;
  strandedThreshold: number;
  demandGrowthPct: number;
  fuelGrowthPct: number;
}

export interface TransitionYearPoint {
  year: number;
  price: number;
  carbonCost: number;
  netMargin: number;
  stranded: boolean;
}

export interface CompanyRisk {
  company: string;
  baseNetMargin: number;
  emissionsTonnes: number;
  byYear: TransitionYearPoint[];
  strandedYear: number | null;
  marginErosion: number;
}

export interface TransitionRisk {
  run: string;
  topic: 'transition-risk';
  period: number | null;
  baseYear: number;
  strandedThreshold: number;
  currency: string;
  trajectory: Array<{ year: number; price: number }>;
  companies: CompanyRisk[];
  summary: {
    companyCount: number;
    strandedCount: number;
    earliestStrandedYear: number | null;
    totalMarginAtRisk: number;
  };
}

export interface DurationCurve {
  run: string;
  topic: 'duration-curve';
  period: number | null;
  source: 'price' | 'load';
  /** Ranked descending (the load curve omits non-positive snapshots). */
  values: number[];
  total: number;
}

/** Sums over result rows; every block is null when the run has no such section. */
export interface ResultTotals {
  run: string;
  topic: 'totals';
  period: number | null;
  expansion: { newBuildCount: number; totalCapexAnnual: number; totalNewBuildMw: number } | null;
  /** Candidates a siting scan added (`siting_*` expansion assets): MW built per site bus and the annual capex. */
  siting: {
    builtMwBySiteBus: Record<string, number>;
    builtTotalMw: number;
    capexAnnual: number;
    assets: string[];
  } | null;
  emissions: {
    totalTco2: number;
    totalEnergyMwh: number;
    averageIntensityKgPerMwh: number;
    byCarrier: Array<{ carrier: string; sharePct: number }>;
  } | null;
  companies: { ownerEmissionsTonnes: number; systemEmissionsTonnes: number; totalNpv: number } | null;
  /** Company P&L statement: owners' emissions plus the unassigned emissions. */
  statement: { systemEmissionsTonnes: number } | null;
  meritOrder: {
    totalMw: number;
    systemPeakLoadMw: number | null;
    minMarginalCost: number;
    maxMarginalCost: number;
  } | null;
  stochastic: {
    expectedEnergyMwh: number;
    expectedEmissionsTco2: number;
    expectedOperatingCost: number;
    expectedLoadShedMwh: number;
  } | null;
  maintenance: { hoursInMaintenance: number } | null;
}

export interface DualRow {
  component: string;
  attribute: string;
  asset: string;
  /** Snapshots where |dual| exceeds the tolerance. */
  bindingSnapshots: number;
  /** Binding snapshots weighted by the snapshot weighting. */
  bindingHours: number;
  totalSnapshots: number;
  /** Dual (currency/MWh) of largest magnitude, signed. */
  peakShadowPrice: number;
  peakAt: string;
  /** Mean |dual| over the binding snapshots (currency/MWh). */
  meanShadowPrice: number;
  /** Run-length encoding of the binding pattern, for a strip chart. */
  segments: Array<{ on: boolean; length: number }>;
}

/** Ramp-limit / set-point duals: assets that bind at least once, strongest peak first. */
export interface SetpointDuals {
  run: string;
  topic: 'setpoint-duals';
  period: number | null;
  sheets: string[];
  rows: DualRow[];
  total: number;
  /** Assets that carry the dual at all (binding or slack). */
  assetsChecked: number;
  totalSnapshots: number;
  /** Binding hours summed over the listed constraints. */
  bindingHours: number;
}

export interface AnalysisTopics {
  'load-analysis': LoadAnalysis;
  'carrier-performance': CarrierPerformance;
  'transition-risk': TransitionRisk;
  'duration-curve': DurationCurve;
  'setpoint-duals': SetpointDuals;
  totals: ResultTotals;
}

/** One analysis topic of a stored run, evaluated on the server (one pathway period with `period`). */
export function fetchRunAnalysis<T extends keyof AnalysisTopics>(
  run: string, topic: T, query: Record<string, string | number | null | undefined> = {},
): Promise<AnalysisTopics[T]> {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== null && v !== undefined) params.set(k, String(v));
  const qs = params.toString();
  return getJson(`/api/runs/${enc(run)}/analysis/${topic}${qs ? `?${qs}` : ''}`, `Analysis ${topic}`);
}

// ── Weighted totals (core cleanup step 6) ─────────────────────────────────────

/** `GET /api/runs/{name}/derived?period=`: PyPSA's own weighted totals of a stored run (`n.statistics` under the
 *  run's snapshot weightings), plus the per-snapshot weights a browser window sum must use. */
export interface RunDerived {
  run: string;
  period: number | null;
  /** `snapshot_weightings["generators"]` per snapshot (h), in snapshot order of the period. */
  weights: number[];
  modeledHours: number;
  generators: Record<string, {
    energyMwh: number; operatingCost: number; carbonCost: number; emissionsTco2: number; curtailmentMwh: number;
  }>;
  buses: Record<string, {
    loadMwh: number; generationMwh: number; averagePrice: number; carrierMwh: Record<string, number>;
  }>;
  processes: Record<string, { throughputMwh: number; operatingCost: number }>;
}

export const fetchRunDerived = (name: string, period?: number | null): Promise<RunDerived> =>
  getJson(`/api/runs/${enc(name)}/derived${period != null ? `?period=${period}` : ''}`, 'Run derived totals');
