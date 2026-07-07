/**
 * Physical Risk — Scenarios / Vulnerability / Method sub-tabs: extended library
 * types and API helpers not carried by the (Phase-0) `Libraries` type in
 * `lib/physicalRisk/types`.
 *
 * `GET /api/physical-risk/libraries` actually returns a much richer payload
 * than that type declares (see `backend/app/physical_risk/libraries/__init__.py
 * ::libraries_payload`) — perils, scenarios, sectors, vulnerabilityClasses,
 * impactFunctions, ngfsScenarios, financeChannels, dataSources. Rather than
 * touching the shared `types.ts` (out of scope / owned by another agent), this
 * module defines the fuller shape locally and fetches it directly. Field names
 * mirror the backend's camelCase payload byte-for-byte — do not rename.
 *
 * Also carries the `ScenarioConfig` / `VulnerabilityOverride` portfolio-scenario
 * shapes from `backend/app/physical_risk/entities.py` (the checked-in
 * `Portfolio` type only has `sessionId` + `assets`; the live Portfolio also
 * carries a `scenario` field) and the `/report` bundle shape.
 */
import { API_BASE } from 'lib/constants';
import { Portfolio } from './types';

// ── scenario config (backend/app/physical_risk/entities.py::ScenarioConfig) ──

export interface VulnerabilityOverride {
  tcVHalf?: number | null;
  wfMaxMdd?: number | null;
  floodMdr?: number[] | null;
  eqMdr?: number[] | null;
}

export interface FinancialProfile {
  capex?: number | null;
  annualEbitda?: number | null;
  horizonYears?: number | null;
  debtFraction?: number | null;
  debtTenorYears?: number | null;
  riskFreeRate?: number | null;
  baselineSpreadBps?: number | null;
  baselineEquityRate?: number | null;
  ratingMethod?: string | null;
  ratingMethods?: string[] | null;
  financialModel?: string | null;
  capacityMw?: number | null;
  powerPrice?: number | null;
  capacityFactor?: number | null;
  plantFuel?: string | null;
  fixedOpex?: number | null;
  opexPerMwh?: number | null;
  dispatchPenalty?: number | null;
  outageRate?: number | null;
  capacityDerate?: number | null;
  efficiencyLoss?: number | null;
}

export interface ScenarioConfig {
  perils: string[];
  climate: string;
  transition: string;
  horizonYear: number;
  anchorYears: number[];
  discountRate: number;
  sector: string;
  vulnerabilityOverrides: Record<string, VulnerabilityOverride>;
  financialProfile?: FinancialProfile | null;
}

/** The live Portfolio document — a superset of the checked-in `Portfolio` type. */
export interface FullPortfolio extends Portfolio {
  scenario: ScenarioConfig;
}

// ── libraries payload (backend/app/physical_risk/libraries/__init__.py) ──────

export interface PerilLibraryEntry {
  id: string;
  label: string;
  engineHazardType: string;
  futureSource?: string;
  supportedMvp?: boolean;
  historicalOnly?: boolean;
  coverage?: string;
  reason?: string;
  requiresIngest?: boolean;
  requiresDem?: boolean;
  resultKind?: string;
  workerGated?: boolean;
}

export interface ClimateScenarioEntry {
  id: string;
  label: string;
  warmingC?: number;
}

export interface TransitionScenarioEntry {
  id: string;
  label: string;
  ngfsFamily?: string;
  peakWarmingC?: number;
}

export interface ScenariosLibrary {
  climate: ClimateScenarioEntry[];
  transition: TransitionScenarioEntry[];
  anchorYears: number[];
}

export interface SectorEntry {
  id: string;
  label: string;
  defaultVulnerabilityClass: string;
  emissionIntensityTco2ePerMusd: number;
}

export interface VulnerabilityClassEntry {
  id: string;
  label: string;
  group: 'building' | 'energy';
  tcVHalf: number;
  wfMaxMdd: number;
  floodMdr: number[];
  eqMdr: number[];
}

export interface ImpfPresetEntry {
  id: string;
  peril: 'tc' | 'flood' | 'eq';
  label: string;
  tcVHalf?: number;
  floodMdr?: number[];
  eqMdr?: number[];
  provenance?: string;
}

export interface ImpactFunctionsLibrary {
  floodDepthM: number[];
  eqMmi: number[];
  presets: ImpfPresetEntry[];
}

export interface NgfsScenarioEntry {
  id: string;
  label: string;
  prices: Record<string, number>;
}

export interface NgfsScenariosLibrary {
  units: string;
  model: string;
  source: string;
  scenarios: NgfsScenarioEntry[];
}

export interface DataSourceEntry {
  id: string;
  category: string;
  name: string;
  url: string;
  access: string;
  license: string;
  for: string;
}

export interface DataSourcesLibrary {
  categories: { id: string; label: string; note?: string }[];
  sources: DataSourceEntry[];
}

/** The full `GET /api/physical-risk/libraries` payload (superset of `Libraries`). */
export interface FullLibraries {
  perils: PerilLibraryEntry[];
  scenarios: ScenariosLibrary;
  sectors: SectorEntry[];
  vulnerabilityClasses: VulnerabilityClassEntry[];
  impactFunctions: ImpactFunctionsLibrary;
  ngfsScenarios: NgfsScenariosLibrary;
  financeChannels: Record<string, unknown>;
  dataSources: DataSourcesLibrary;
}

async function asJson<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      detail = (body && (body.detail as string)) || detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

/** The full methodology libraries payload (perils, scenarios, sectors, impact functions, ...). */
export async function getFullLibraries(): Promise<FullLibraries> {
  const resp = await fetch(`${API_BASE}/api/physical-risk/libraries`);
  return asJson<FullLibraries>(resp);
}

/** Fetch the full portfolio (including `scenario`) for a physical-risk session. */
export async function getFullSession(sessionId: string): Promise<FullPortfolio> {
  const resp = await fetch(`${API_BASE}/api/physical-risk/session/${encodeURIComponent(sessionId)}`);
  return asJson<FullPortfolio>(resp);
}

/** Replace the stored portfolio for a session (full-document sync, same as `saveSession`). */
export async function saveFullSession(
  sessionId: string,
  portfolio: FullPortfolio,
): Promise<FullPortfolio> {
  const resp = await fetch(`${API_BASE}/api/physical-risk/session/${encodeURIComponent(sessionId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(portfolio),
  });
  return asJson<FullPortfolio>(resp);
}

// ── report bundle (GET /api/physical-risk/session/{sid}/report) ──────────────

export interface ReportSummary {
  assetCount: number;
  totalValue: number;
  currency: string;
}

export interface TransitionAssetCarbon {
  assetId: string;
  name: string;
  emissionsTco2e: number;
  emissionsSource: string;
  annualCostByYear: Record<string, number>;
  npv: number;
}

export interface TransitionReport {
  scenario: string;
  discountRate: number;
  baseYear: number;
  years: number[];
  totalCostByYear: number[];
  totalNpv: number;
  perAsset: TransitionAssetCarbon[];
  method: string;
  detail?: string | null;
}

export interface FinanceOutcome {
  npv: number;
  irr: number | null;
  minDscr: number;
  rating: string;
  spreadBps: number;
  wacc: number;
}

export interface FinanceAssessment {
  baseline: FinanceOutcome;
  stressed: FinanceOutcome;
  annualClimateLoss: number;
  npvLoss: number;
  npvLossPctCapex: number;
  crpBps: number;
  downgrade: boolean;
}

export interface FinanceReport {
  currency: string;
  totalPhysicalAai: number;
  transitionAnnualCost: number;
  ratingMethod: string;
  ratingMethodLabel: string;
  financialModel?: string | null;
  portfolio: FinanceAssessment;
  detail?: string | null;
}

export interface ReportBundle {
  sessionId: string;
  generatedAt: string;
  portfolio: FullPortfolio;
  summary: ReportSummary;
  results: Record<string, unknown>;
  transition: TransitionReport;
  finance: FinanceReport | null;
}

/** The compact session report: portfolio + latest results per run kind + transition/finance. */
export async function getReport(sessionId: string): Promise<ReportBundle> {
  const resp = await fetch(
    `${API_BASE}/api/physical-risk/session/${encodeURIComponent(sessionId)}/report`,
  );
  return asJson<ReportBundle>(resp);
}
