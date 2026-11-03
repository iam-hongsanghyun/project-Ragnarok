/**
 * Fuel-costs module (backend/app/fuel_costs): the marginal-cost series a run would send, previewed. The browser only
 * displays the server's table; it computes nothing.
 */
import { API_BASE } from 'lib/constants';

export interface FuelCostParts { fuel: number | null; vom: number | null; carbon: number | null; other: number | null; total: number | null }

/** One Generator / Link of the module's plan (`POST /api/fuel-costs/preview`, and `result.fuelCosts.units`). */
export interface FuelCostUnit {
  component: 'Generator' | 'Link';
  name: string;
  carrier: string;
  /** generator | supplier | link-supplied | link-direct | vom-only */
  role: string;
  fuelCarrier: string | null;
  suppliers: string[];
  /** applied | unpriced | skipped */
  status: string;
  reason: string;
  efficiencyMean: number | null;
  vom: number | null;
  vomSource: string;
  snapshots: number;
  pricedSnapshots: number;
  unpricedSnapshots: number;
  marginalCost: { oldMean: number | null; newMean: number | null; newMin: number | null; newMax: number | null; basis: string };
  /** MWh_el, or MWh_th for a fuel supplier. */
  basis: string;
  timeMean: FuelCostParts;
  dispatchWeighted?: FuelCostParts;
  generationMwh?: number | null;
  lcoe?: (FuelCostParts & { value: number | null; capex: number | null; fom: number | null }) | null;
}

/** One scenario of a stochastic preview: its own units (fuel price, efficiency and overrides of that scenario). */
export interface FuelCostScenario { name: string; weight: number; units: FuelCostUnit[]; notes?: string[] }

export interface FuelCostsPreview {
  active: boolean;
  carbonPriceActive: boolean;
  units: FuelCostUnit[];
  priceSources: Record<string, string>;
  notes: string[];
  basis: string;
  inputs?: { priceSheet: string; vomSheet: string; flatColumn: string };
  smp: { source: string; note: string };
  /** Present when the request carried an enabled stochastic config. */
  scenarios?: FuelCostScenario[] | null;
}

/** `result.fuelCosts` of a run: the preview rows plus dispatch-weighted components, generation and LCOE. */
export interface FuelCostsResult extends Omit<FuelCostsPreview, 'active' | 'basis' | 'inputs' | 'scenarios'> {
  enabled: boolean;
  /** Stochastic run: `units` are this scenario's; `scenarios` / `expected` carry every scenario and the probability-weighted mean. */
  representativeScenario?: string;
  scenarios?: FuelCostScenario[];
  expected?: { units: FuelCostUnit[]; basis: string };
  currency: string;
  weighting: string;
}

export async function previewFuelCosts(
  carbonPrice: number,
  carbonPriceSchedule: { year: number; price: number }[],
  sessionId = 'default',
  stochasticConfig?: unknown,
): Promise<FuelCostsPreview> {
  const resp = await fetch(`${API_BASE}/api/fuel-costs/preview`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId, carbonPrice, carbonPriceSchedule, ...(stochasticConfig ? { stochasticConfig } : {}) }),
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json())?.detail ?? detail; } catch { /* non-JSON */ }
    throw new Error(`${resp.status}: ${detail}`);
  }
  return resp.json() as Promise<FuelCostsPreview>;
}
