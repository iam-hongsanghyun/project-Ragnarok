/**
 * Physical Risk — Map / Adaptation sub-tabs: extended types + API helpers not
 * carried by the (Phase-0) shared `types.ts`.
 *
 * Field names mirror `backend/app/physical_risk/entities.py` byte-for-byte
 * (camelCase, as FastAPI serialises the Pydantic models) — do not rename on
 * this side. Same `asJson` convention as `lib/physicalRisk/api.ts` and
 * `lib/physicalRisk/configViews.ts`.
 */
import { API_BASE } from 'lib/constants';
import { Run, Scenario } from './types';

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

// ── cost-benefit run (backend/app/physical_risk/entities.py::MeasureSpec / CostBenefitResult) ──

/** A user-defined adaptation measure — cost-benefit run input. */
export interface MeasureSpec {
  name: string;
  cost: number;
  damageReduction: number;
  hazardFreqCutoff?: number;
  riskTransfAttach?: number;
  riskTransfCover?: number;
}

/** Per-measure cost-benefit outcome (entities.py `MeasureResult`). */
export interface MeasureResult {
  name: string;
  cost: number;
  benefit: number;
  benefitCostRatio: number | null;
}

/** Engine output for an adaptation cost-benefit run (entities.py `CostBenefitResult`). */
export interface CostBenefitResult {
  kind: 'cost-benefit';
  status: string;
  peril: string;
  futureYear: number | null;
  discountRate: number;
  currency: string;
  totClimateRisk: number;
  measures: MeasureResult[];
  detail: string | null;
}

export interface CostBenefitRunRequest {
  perils?: string[];
  scenario?: Scenario;
  measures: MeasureSpec[];
  peril?: string;
  discountRate?: number;
}

/** Submit a cost-benefit adaptation run for the session's portfolio. */
export async function submitCostBenefitRun(
  sessionId: string,
  req: CostBenefitRunRequest,
): Promise<Run> {
  const resp = await fetch(`${API_BASE}/api/physical-risk/session/${encodeURIComponent(sessionId)}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind: 'cost-benefit', ...req }),
  });
  return asJson<Run>(resp);
}

/** Poll a run (shared endpoint — same shape as `lib/physicalRisk/api.ts::getRun`). */
export async function getPhysicalRiskRun(sessionId: string, runId: string): Promise<Run> {
  const resp = await fetch(
    `${API_BASE}/api/physical-risk/session/${encodeURIComponent(sessionId)}/run/${encodeURIComponent(runId)}`,
  );
  return asJson<Run>(resp);
}

// ── per-asset EAI aggregation (Map sub-tab) ───────────────────────────────────

/** One asset's total expected annual impact, summed across a run's perils. */
export interface AssetTotalEai {
  assetId: string;
  total: number;
  byPeril: Record<string, number>;
}

/** Sum each asset's EAI across every peril in a done physical run's result. */
export function totalEaiByAsset(perils: { peril: string; perAsset: { assetId: string; eai: number }[] }[]): Map<string, AssetTotalEai> {
  const out = new Map<string, AssetTotalEai>();
  for (const p of perils) {
    for (const row of p.perAsset) {
      const entry = out.get(row.assetId) ?? { assetId: row.assetId, total: 0, byPeril: {} };
      entry.total += row.eai;
      entry.byPeril[p.peril] = row.eai;
      out.set(row.assetId, entry);
    }
  }
  return out;
}
