/**
 * Server-side results (WA7): run comparison, the KPI strip, company comparison
 * and per-asset details are computed by the backend from the stored run
 * (`backend/app/routers/results_derived.py`), so the browser renders them instead
 * of re-deriving them from raw output series.
 *
 *   GET /api/results/compare?runs=a,b&topics=...   -> {items, total, topics}
 *   GET /api/runs/{name}/kpis?currency=            -> {run, kpis}
 *   GET /api/runs/{name}/companies?sort_by=        -> {run, items, total, currency, sortedBy, metrics}
 *   GET /api/runs/{name}/assets?kind=&names=&series=  -> {run, items, total, offset, limit}
 *   GET /api/runs/{name}/metrics?focus=&keys=&groupBy=...  -> {run, focus, items: MetricOption[], total}
 */
import { API_BASE } from 'lib/constants';
import type {
  AnalyticsFocus, BranchDetail, BusDetail, GeneratorDetail, GroupByOption, MetricOption, ProcessDetail,
  ShuntImpedanceDetail, StorageUnitDetail, StoreDetail, SummaryItem,
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

export const fetchRunKpis = (run: string, currency: string): Promise<{ run: string; kpis: RunKpis }> =>
  getJson(`/api/runs/${enc(run)}/kpis?currency=${enc(currency)}`, 'KPIs');

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
  items: CompanyRow[];
  total: number;
  currency: string;
  sortedBy: string;
  metrics: CompanyMetricDef[];
}

export const fetchRunCompanies = (run: string, sortBy?: string): Promise<CompanyComparison> =>
  getJson(`/api/runs/${enc(run)}/companies${sortBy ? `?sort_by=${enc(sortBy)}` : ''}`, 'Company comparison');

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
