/**
 * P2X HTTP client — `/api/p2x/*` (technologies, chain preview, RFNBO settings and checks, results).
 *
 * The backend does all the work; nothing here computes a cost. The chain is applied through the
 * ordinary fragment merge (`onApplyFragment`), so this client only previews.
 */
import { API_BASE } from 'lib/constants';
import type { WorkbookModel } from 'lib/types';
import type { WorkbookFragment } from 'lib/api/databases';
import { DEFAULT_SESSION_ID } from 'lib/api/session';

export type P2XProduct = 'H2' | 'NH3' | 'MeOH' | 'eFuel';
export const P2X_PRODUCTS: readonly P2XProduct[] = ['H2', 'NH3', 'MeOH', 'eFuel'];
export type P2XDerivative = Exclude<P2XProduct, 'H2'>;
export const P2X_DERIVATIVES: readonly P2XDerivative[] = ['NH3', 'MeOH', 'eFuel'];

async function readJson<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json())?.detail ?? detail; } catch { /* non-JSON body */ }
    throw new Error(String(detail));
  }
  return resp.json() as Promise<T>;
}

const getJson = async <T,>(path: string): Promise<T> => readJson<T>(await fetch(`${API_BASE}${path}`));
const sendJson = async <T,>(method: 'POST' | 'PUT', path: string, body: unknown): Promise<T> =>
  readJson<T>(await fetch(`${API_BASE}${path}`, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }));

// ── technologies ───────────────────────────────────────────────────────────────

export interface TechParam {
  value: number;
  default: number;
  unit: string;
  source: { document: string; locator: string; year: number };
  costYear: number | null;
  currency: string | null;
  verified: 'file' | 'derived' | 'literature-recalled' | 'assumption';
  note?: string;
}
export interface TechEntry { label: string; notes?: string; parameters: Record<string, TechParam> }
export interface TechCatalogue {
  basis: { currency: string; costYear: number; technologyYear: number };
  sources: Record<string, unknown>;
  technologies: Record<string, TechEntry>;
}
export const fetchTechnologies = () => getJson<TechCatalogue>('/api/p2x/technologies');

// ── chain ──────────────────────────────────────────────────────────────────────

export interface OfftakeSpec { mode: 'none' | 'flat' | 'profile'; tonnesPerYear?: number; mw?: number; profile?: number[] }
export interface ChainSpec {
  chainId: string;
  anchorBus: string | null;
  h2Bus: string | null;
  discountRate: number;
  products: P2XProduct[];
  electrolyser: { tech: 'aec' | 'pem'; extendable: boolean; pNom: number; pNomMax: number | null; applyAvailability: boolean; enforceMinLoad: boolean; buildYear: number };
  storage: { type: 'none' | 'tank' | 'cavern'; compressor: boolean; extendable: boolean; eNom: number; eNomMax: number | null };
  co2: { source: 'dac' | 'point' };
  synthesis: Record<string, { extendable: boolean; pNom: number }>;
  productStorage: Record<string, { enabled: boolean; extendable: boolean; eNom: number }>;
  offtake: Record<string, OfftakeSpec>;
  designatedGenerators: string[];
  params: Record<string, number>;
}
export interface ChainSummaryRow {
  role: string; label: string; sheet: string; name: string;
  bus?: string; bus0?: string; bus1?: string; bus2?: string; bus3?: string;
  efficiency?: number; efficiency2?: number; efficiency3?: number;
  p_nom?: number; p_nom_extendable?: boolean; e_nom?: number; e_nom_extendable?: boolean; p_set?: number;
  overnightCapex?: number; overnightUnit?: string; marginal_cost?: number;
}
export interface ChainPreview {
  fragment: WorkbookFragment;
  summary: ChainSummaryRow[];
  warnings: string[];
  rowCounts: Record<string, number>;
  registry: { chainId: string; components: Record<string, { sheet: string; name: string }> };
  applied: boolean;
}
export const previewChain = (spec: ChainSpec, model: WorkbookModel) =>
  sendJson<ChainPreview>('POST', '/api/p2x/chain', { sessionId: DEFAULT_SESSION_ID, spec, model, apply: false });

// ── RFNBO ──────────────────────────────────────────────────────────────────────

export interface RfnboConfig {
  enabled: boolean;
  temporal: 'hourly' | 'monthly' | 'auto';
  hourlyFrom: string;
  enforceAdditionality: boolean;
  additionalityMonths: number;
  unknownBuildYearAs: 'fail' | 'pass';
  enforceGeographic: boolean;
  zoneColumn: string | null;
  designatedGenerators: string[];
  electrolysers: string[];
  chainId: string | null;
  priceRule: { enabled: boolean; thresholdEurPerMwh: number; euaEurPerT: number | null };
}
export interface CheckRow { generator: string; status: 'pass' | 'fail' | 'unknown'; reason: string; buildYear?: number | null; electrolyserYear?: number | null; bus?: string }
export interface RfnboChecks {
  config: RfnboConfig;
  electrolysers: string[];
  designated: string[];
  additionality: CheckRow[];
  geographic: CheckRow[];
  dropped: Array<{ generator: string; rule: string; reason: string }>;
  eligible: string[];
  willBeRefused: boolean;
  attest: Array<{ article: string; rule: string; status: string }>;
  regulation: string;
}
export const fetchRfnboConfig = () =>
  getJson<{ config: RfnboConfig | null; defaults: RfnboConfig }>(`/api/p2x/rfnbo/config?session_id=${encodeURIComponent(DEFAULT_SESSION_ID)}`);
export const saveRfnboConfig = (config: RfnboConfig) =>
  sendJson<{ config: RfnboConfig }>('PUT', '/api/p2x/rfnbo/config', { sessionId: DEFAULT_SESSION_ID, config });
export const fetchRfnboChecks = (config: RfnboConfig, model: WorkbookModel) =>
  sendJson<RfnboChecks>('POST', '/api/p2x/rfnbo/checks', { sessionId: DEFAULT_SESSION_ID, config, model });

// ── results ────────────────────────────────────────────────────────────────────

export interface WaterfallStep { label: string; value: number; cumulative: number }
export interface ProductResult {
  product: string; label: string; producedTonnes: number; producedMwh: number; h2InMwh: number;
  totalCost: number; costPerTonne: number; costPerMwh: number; costPerLitre?: number;
  synthesisCapacityMw: number; synthesisFullLoadHours: number;
  components: Record<string, number>;
  waterfall: { unit: string; steps: WaterfallStep[] };
}
export interface RegimeCompliance {
  periods: number; operatingPeriods: number; compliantOperatingPeriods: number; compliantShareOfOperating: number;
  unmatchedMwh: number; unmatchedShareOfElectrolyserEnergy: number; matchedMwh: number;
}
export interface Compliance {
  hourly: RegimeCompliance; monthly: RegimeCompliance;
  months: Array<{ month: string; electrolyserMwh: number; designatedMwh: number; unmatchedHourlyMwh: number; unmatchedMonthlyMwh: number; operatingHours: number }>;
  art63: { enabled: boolean; thresholdEurPerMwh?: number; operatingPeriodsAtOrBelow?: number };
}
export interface P2XResults {
  chainId: string; chains: string[]; period: number | null; currency: string;
  electricityCost: 'nodal' | 'ppa'; electricityCostRequested: string;
  windowYears: number; snapshots: number;
  lcoh: { perKg: number; totalCost: number; h2Kg: number; perComponent: Record<string, number>; costs: Record<string, number>; waterfall: { unit: string; steps: WaterfallStep[] } };
  electrolyser: { name: string; capacityMw: number; electricityMwh: number; h2Mwh: number; h2Tonnes: number; capacityFactor: number; fullLoadHours: number; fullLoadHoursPerYear: number; efficiencyLhv: number };
  products: Record<string, ProductResult>;
  ppa: { available: boolean; pricePerMwh?: number };
  rfnbo: {
    matchingEnabled: boolean; designated: string[]; electrolysers: string[]; compliance: Compliance | null;
    checks: { additionality: CheckRow[]; geographic: CheckRow[] };
    gridAlternatives: {
      art41: { renewableShare: number; threshold: number; pass: boolean; maxFullLoadHours: number; electrolyserFullLoadHours: number; note: string };
      art42: { emissionIntensityGPerMj: number; threshold: number; pass: boolean | null; note: string };
    };
    regulation: string;
  };
  series: { snapshots: string[]; electrolyserMw: number[]; designatedMw: number[]; matchedMw: number[]; gridMw: number[]; h2SocMwh: number[]; h2SocTonnes: number[]; priceAc: number[] };
  warnings: string[];
  basis: string;
}
export const fetchP2XResults = (run: string, opts: { period?: number | null; electricityCost?: 'nodal' | 'ppa'; chainId?: string | null }) => {
  const q = new URLSearchParams();
  if (opts.period !== null && opts.period !== undefined) q.set('period', String(opts.period));
  q.set('electricity_cost', opts.electricityCost ?? 'nodal');
  if (opts.chainId) q.set('chain_id', opts.chainId);
  return getJson<P2XResults>(`/api/p2x/results/${encodeURIComponent(run)}?${q.toString()}`);
};
