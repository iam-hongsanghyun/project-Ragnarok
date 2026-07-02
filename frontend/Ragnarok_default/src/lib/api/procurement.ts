/**
 * Procurement portfolio optimizer (PP2) — API client.
 *
 * Posts a price series + contract volume + instrument menu to the backend,
 * which bootstraps price scenarios and returns the CVaR-constrained optimal
 * hedging mix plus the cost-vs-risk efficient frontier.
 */
import { API_BASE } from 'lib/constants';

export interface ProcurementInstruments {
  ppa: { enabled: boolean; strike: number; maxMw: number };
  forward: { enabled: boolean; price: number; maxMw: number };
  retail: { enabled: boolean; price: number };
}

export interface ProcurementRequest {
  prices: number[];
  /** Contract volume — a flat MW or a per-hour profile aligned to `prices`. */
  loadMw: number | number[];
  ppa: ProcurementInstruments['ppa'];
  forward: ProcurementInstruments['forward'];
  retail: ProcurementInstruments['retail'];
  alpha: number;
  cvarBudget?: number | null;
  bootstrap?: number;
  blockHours?: number;
  stress?: { label: string; multiplier: number }[];
  frontierPoints?: number;
  currency?: string;
}

export interface ProcurementPortfolio {
  mix: Record<string, number>;
  expectedCost: number;
  cvar: number;
  worstCost: number;
  bestCost: number;
  note?: string;
}

export interface ProcurementFrontierPoint extends ProcurementPortfolio {
  budget: number;
}

export interface ProcurementResult {
  alpha: number;
  currency: string;
  instrumentNames: string[];
  baseline: { expectedCost: number; cvar: number; worstCost: number };
  optimal: ProcurementPortfolio | null;
  frontier: ProcurementFrontierPoint[];
  scenarioCosts: number[];
  riskRange: { minCvar: number; maxCvar: number };
  scenarioCount: number;
  horizonHours: number;
  stressLabels: string[];
  error?: string;
}

export async function optimizeProcurement(req: ProcurementRequest): Promise<ProcurementResult> {
  const resp = await fetch(`${API_BASE}/api/procurement/optimize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json())?.detail ?? detail;
    } catch {
      /* non-JSON body */
    }
    throw new Error(`Procurement optimize failed (${resp.status}): ${detail}`);
  }
  return resp.json();
}
