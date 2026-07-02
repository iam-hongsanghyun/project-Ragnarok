/**
 * Transition-risk analysis (R2) — reprice carbon over a forward trajectory.
 *
 * Physical dispatch and revenue are held at the solved outcome; only the carbon
 * price rises along a user trajectory. Each company's net margin is
 * recomputed year by year by swapping the carbon line of its P&L statement:
 *
 *     netMargin(year) = (revenue − fuel/VOM − capex − interest) − emissions · P_CO2(year)
 *
 * The bracket is the margin *excluding* carbon (fixed across years); only the
 * emissions × price term moves. A company is "stranded" in the first year its
 * net margin falls to/below the threshold; margin-at-risk is the cumulative
 * margin lost versus the base year over the horizon.
 *
 * Pure over the already-computed statement, so it runs live in the card with no
 * backend round-trip; unit-tested directly.
 */
import { CompanyStatementResult } from 'lib/types';

export interface TransitionParams {
  baseYear: number;
  /** Horizon length in years (trajectory spans baseYear … baseYear+years). */
  years: number;
  /** Carbon price at the base year (currency/tCO₂). */
  basePrice: number;
  /** Annual carbon-price escalation (%/yr, compounded). */
  escalationPct: number;
  /** Net margin at/below this (currency/yr) marks a company stranded. */
  strandedThreshold: number;
  /** Annual demand growth (%/yr) — scales volume-linked revenue, fuel & emissions. */
  demandGrowthPct?: number;
  /** Annual fuel-price change (%/yr) — scales the fuel/VOM cost line. */
  fuelGrowthPct?: number;
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
  /** First year (> base) the company turns stranded; null if never. */
  strandedYear: number | null;
  /** Cumulative margin lost vs the base year over the horizon. */
  marginErosion: number;
}

export interface TransitionRiskResult {
  baseYear: number;
  strandedThreshold: number;
  currency: string;
  trajectory: { year: number; price: number }[];
  companies: CompanyRisk[];
}

export const DEFAULT_TRANSITION_PARAMS: TransitionParams = {
  baseYear: 2030,
  years: 20,
  basePrice: 50,
  escalationPct: 5,
  strandedThreshold: 0,
  demandGrowthPct: 0,
  fuelGrowthPct: 0,
};

export function computeTransitionRisk(
  statement: CompanyStatementResult,
  params: TransitionParams,
): TransitionRiskResult {
  const years = Math.max(1, Math.round(params.years));
  const esc = params.escalationPct / 100;
  const trajectory = Array.from({ length: years + 1 }, (_, i) => ({
    year: params.baseYear + i,
    price: params.basePrice * Math.pow(1 + esc, i),
  }));

  const demandRate = (params.demandGrowthPct ?? 0) / 100;
  const fuelRate = (params.fuelGrowthPct ?? 0) / 100;

  const companies: CompanyRisk[] = statement.companies.map((c) => {
    const emissions = c.emissionsTonnes;
    // Fixed lines (capex / interest) don't scale with volume; revenue, fuel and
    // emissions do. Each year applies the demand and fuel-price trajectories.
    const fixed = c.capexAnnual + c.interest;

    let strandedYear: number | null = null;
    let baseNetMargin = c.revenue - c.fuelVomCost - fixed;
    const byYear: TransitionYearPoint[] = trajectory.map((pt, i) => {
      const d = Math.pow(1 + demandRate, i);
      const f = Math.pow(1 + fuelRate, i);
      const revenue = c.revenue * d;
      const fuelVom = c.fuelVomCost * d * f;
      const carbonCost = emissions * d * pt.price;
      const netMargin = revenue - fuelVom - carbonCost - fixed;
      const stranded = netMargin <= params.strandedThreshold;
      if (pt.year === params.baseYear) baseNetMargin = netMargin;
      if (stranded && strandedYear === null) strandedYear = pt.year;
      return {
        year: pt.year,
        price: Math.round(pt.price * 100) / 100,
        carbonCost: Math.round(carbonCost * 100) / 100,
        netMargin: Math.round(netMargin * 100) / 100,
        stranded,
      };
    });

    const marginErosion = byYear.reduce((s, p) => s + Math.max(0, baseNetMargin - p.netMargin), 0);
    return {
      company: c.company,
      baseNetMargin: Math.round(baseNetMargin * 100) / 100,
      emissionsTonnes: emissions,
      byYear,
      strandedYear,
      marginErosion: Math.round(marginErosion * 100) / 100,
    };
  });

  // Most-at-risk first.
  companies.sort((a, b) => b.marginErosion - a.marginErosion);

  return {
    baseYear: params.baseYear,
    strandedThreshold: params.strandedThreshold,
    currency: statement.currency,
    trajectory: trajectory.map((t) => ({ year: t.year, price: Math.round(t.price * 100) / 100 })),
    companies,
  };
}
