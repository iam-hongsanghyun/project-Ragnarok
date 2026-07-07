/**
 * Physical Risk — Finance / Supply chain / Forecast sub-tabs: extended result
 * types and API helpers not carried by the (Phase-0) `Run`/`PhysicalRunOutput`
 * shapes in `lib/physicalRisk/types`.
 *
 * `POST /session/{sid}/transition` and `POST /session/{sid}/finance` are
 * synchronous REAL-math endpoints (`backend/app/physical_risk/{transition,
 * finance}.py`) whose response models are richer than anything already typed
 * on this side; `POST /session/{sid}/run` also accepts run kinds
 * ('supply-chain', 'forecast') whose result shapes aren't in the checked-in
 * `Run` union either. Rather than touching the shared `types.ts` (out of
 * scope), this module defines the fuller shapes locally, camelCase field for
 * field against the backend Pydantic models — do not rename.
 *
 * Reuses `FinancialProfile` / `ScenarioConfig` / `FullPortfolio` and the
 * `FinanceOutcome` / `FinanceAssessment` primitives already defined in
 * `lib/physicalRisk/configViews` (another Physical Risk sub-tab's extended
 * library module) instead of redefining them — same backend models, one
 * shared TS shape.
 */
import { API_BASE } from 'lib/constants';
import { RunStatus } from './types';
import { FinanceAssessment, FinanceOutcome, FinancialProfile, FullPortfolio } from './configViews';

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

// ── transition (backend/app/physical_risk/transition.py::TransitionResult) ───

export interface AssetCarbon {
  assetId: string;
  name: string;
  emissionsTco2e: number;
  emissionsSource: string;
  annualCostByYear: Record<string, number>;
  npv: number;
}

export interface TransitionResult {
  scenario: string;
  discountRate: number;
  baseYear: number;
  years: number[];
  totalCostByYear: number[];
  totalNpv: number;
  perAsset: AssetCarbon[];
  method: string;
  detail?: string | null;
}

/** Compute the portfolio's transition (carbon-cost) risk — synchronous, real math. */
export async function runTransition(
  sessionId: string,
  overrides: { scenario?: string; discountRate?: number } = {},
): Promise<TransitionResult> {
  const resp = await fetch(`${API_BASE}/api/physical-risk/session/${encodeURIComponent(sessionId)}/transition`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(overrides),
  });
  return asJson<TransitionResult>(resp);
}

// ── finance (backend/app/physical_risk/finance.py::FinanceResult) ────────────

export interface RatingThresholdRow {
  dscrMin: number;
  rating: string;
  source?: string;
}

export interface MethodComparison {
  method: string;
  label: string;
  code: string;
  source: string;
  scenario: FinanceAssessment;
}

export interface AssetFinance {
  assetId: string;
  name: string;
  model?: string | null;
  assessment: FinanceAssessment;
}

export interface FinanceResult {
  currency: string;
  totalPhysicalAai: number;
  transitionAnnualCost: number;
  ratingMethod: string;
  ratingMethodLabel: string;
  ratingMethodSource: string;
  ratingThresholds: RatingThresholdRow[];
  methodsCompared: MethodComparison[];
  financialModel?: string | null;
  portfolioBreakdown: Record<string, unknown>;
  portfolio: FinanceAssessment;
  perAsset: AssetFinance[];
  detail?: string | null;
}

/** Climate Risk Premium for a completed physical run — synchronous, real math. */
export async function runFinance(
  sessionId: string,
  runId: string,
  transitionCost = 0,
): Promise<FinanceResult> {
  const resp = await fetch(`${API_BASE}/api/physical-risk/session/${encodeURIComponent(sessionId)}/finance`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ runId, transitionCost }),
  });
  return asJson<FinanceResult>(resp);
}

// ── portfolio financial-profile edits (Finance sub-tab writes the same ──────
// ── `scenario.financialProfile` field the Assets/Scenarios sections do) ─────

/** Patch the portfolio's scenario-level financial profile and PUT the full document back. */
export async function saveFinancialProfile(
  portfolio: FullPortfolio,
  patch: Partial<FinancialProfile>,
): Promise<FullPortfolio> {
  const next: FullPortfolio = {
    ...portfolio,
    scenario: { ...portfolio.scenario, financialProfile: { ...portfolio.scenario.financialProfile, ...patch } },
  };
  const resp = await fetch(`${API_BASE}/api/physical-risk/session/${encodeURIComponent(portfolio.sessionId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(next),
  });
  return asJson<FullPortfolio>(resp);
}

// ── worker-gated analysis runs (backend/app/physical_risk/entities.py) ───────
// Supply-chain and forecast share the same queued/poll run lifecycle as the
// Results tab's physical run, but their result shapes aren't in the Phase-0
// `Run` union — a small parallel `AnalysisRun<T>` carries them instead.

export interface SupplyChainSector {
  sector: string;
  indirect: number;
}

export interface SupplyChainResult {
  kind: 'supply-chain';
  status: string;
  mriot: string;
  currency: string;
  totalDirect: number;
  totalIndirect: number;
  amplification: number | null;
  bySector: SupplyChainSector[];
  detail?: string | null;
}

export interface ForecastAssetImpact {
  assetId: string;
  eai: number;
}

export interface ForecastSeriesPoint {
  label: string;
  value: number;
}

export interface ForecastResult {
  kind: 'forecast';
  status: string;
  peril: string;
  nTracks: number;
  totalImpact: number;
  currency: string;
  perAsset: ForecastAssetImpact[];
  series: ForecastSeriesPoint[];
  detail?: string | null;
}

// ── calibration (backend/app/physical_risk/entities.py::CalibrationResult) ───
// The engine (stub and worker) always calibrates TC v_half against an
// observed annual loss it derives itself (stub: 90% of modelled AAI; worker:
// EM-DAT for the portfolio's country) — the run request carries no peril or
// observed-loss override (see `RunRequest` / `run_calibration` /
// `compute_calibration`), so this section submits `{ kind: 'calibration' }`
// only and reads the target back off the result.

export interface CalibrationResult {
  kind: 'calibration';
  status: string;
  peril: string;
  country: string;
  param: string;
  initial: number;
  calibrated: number;
  observedAnnualLoss: number;
  detail?: string | null;
}

export interface AnalysisRun<T> {
  id: string;
  kind: string;
  status: RunStatus;
  result?: T | null;
  error?: string | null;
}

export interface SubmitAnalysisRunRequest {
  kind: 'supply-chain' | 'forecast' | 'calibration';
  perils?: string[];
  scenario?: { rcp: string; horizon: number } | null;
  mriotType?: string;
  mriotYear?: number;
}

/** Submit a worker-gated analysis run ('supply-chain' | 'forecast') for the session's portfolio. */
export async function submitAnalysisRun<T>(
  sessionId: string,
  body: SubmitAnalysisRunRequest,
): Promise<AnalysisRun<T>> {
  const resp = await fetch(`${API_BASE}/api/physical-risk/session/${encodeURIComponent(sessionId)}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return asJson<AnalysisRun<T>>(resp);
}

/** Poll a worker-gated analysis run; the stub engine finalises it on the first poll. */
export async function pollAnalysisRun<T>(sessionId: string, runId: string): Promise<AnalysisRun<T>> {
  const resp = await fetch(
    `${API_BASE}/api/physical-risk/session/${encodeURIComponent(sessionId)}/run/${encodeURIComponent(runId)}`,
  );
  return asJson<AnalysisRun<T>>(resp);
}

/** Fetch the full portfolio (including `scenario.financialProfile`) — Finance needs it to edit. */
export async function getFullPortfolio(sessionId: string): Promise<FullPortfolio> {
  const resp = await fetch(`${API_BASE}/api/physical-risk/session/${encodeURIComponent(sessionId)}`);
  return asJson<FullPortfolio>(resp);
}

/** Money formatter shared by the three sections (mirrors ResultsSection's inline helper). */
export function formatMoney(v: number, currencySymbol: string): string {
  return `${currencySymbol}${Math.round(v).toLocaleString()}`;
}

export type { FinanceAssessment, FinanceOutcome, FinancialProfile, FullPortfolio };
