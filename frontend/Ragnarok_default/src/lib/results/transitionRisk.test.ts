import { describe, it, expect } from '@jest/globals';
import { computeTransitionRisk, DEFAULT_TRANSITION_PARAMS } from './transitionRisk';
import { CompanyStatementResult, CompanyStatementEntry } from 'lib/types';

const entry = (over: Partial<CompanyStatementEntry>): CompanyStatementEntry => ({
  company: 'X', revenue: 0, energyMWh: 0, carbonCost: 0, fuelVomCost: 0,
  variableCost: 0, grossMargin: 0, capexAnnual: 0, ebit: 0, interest: 0,
  netMargin: 0, emissionsTonnes: 0, ...over,
});

const statement = (companies: CompanyStatementEntry[]): CompanyStatementResult => ({
  ownerColumn: 'owner', currency: '$', carbonPrice: 0, companies,
  totals: entry({ company: '' }) as unknown as Omit<CompanyStatementEntry, 'company'>,
});

describe('computeTransitionRisk', () => {
  it('builds a compounding carbon-price trajectory over the horizon', () => {
    const r = computeTransitionRisk(statement([entry({})]), {
      baseYear: 2030, years: 10, basePrice: 100, escalationPct: 10, strandedThreshold: 0,
    });
    expect(r.trajectory).toHaveLength(11);
    expect(r.trajectory[0]).toEqual({ year: 2030, price: 100 });
    expect(r.trajectory[10].year).toBe(2040);
    expect(r.trajectory[10].price).toBeCloseTo(100 * 1.1 ** 10, 1); // ≈ 259.37
  });

  it('erodes an emitter\'s margin and flags the stranding year', () => {
    // Margin ex-carbon = revenue − fuel − capex − interest = 1000 − 200 − 0 − 0 = 800.
    // Emissions 10 t; carbon 50 → +5%/yr. Net = 800 − 10·price(year).
    // price(year)=80 → net 0. 50·1.05^k ≥ 80 at k = ceil(ln(1.6)/ln1.05)=10 → year 2040.
    const emitter = entry({ company: 'CoalCo', revenue: 1000, fuelVomCost: 200, emissionsTonnes: 10 });
    const r = computeTransitionRisk(statement([emitter]), {
      baseYear: 2030, years: 20, basePrice: 50, escalationPct: 5, strandedThreshold: 0,
    });
    const co = r.companies[0];
    expect(co.baseNetMargin).toBeCloseTo(800 - 10 * 50, 1); // 300 at base year
    expect(co.strandedYear).not.toBeNull();
    expect(co.strandedYear!).toBeGreaterThan(2030);
    // Net margin is monotonically decreasing as carbon rises.
    const nets = co.byYear.map((p) => p.netMargin);
    for (let i = 1; i < nets.length; i++) expect(nets[i]).toBeLessThan(nets[i - 1]);
    expect(co.marginErosion).toBeGreaterThan(0);
  });

  it('leaves a zero-emissions company untouched (never stranded)', () => {
    const clean = entry({ company: 'WindCo', revenue: 500, fuelVomCost: 0, emissionsTonnes: 0 });
    const r = computeTransitionRisk(statement([clean]), DEFAULT_TRANSITION_PARAMS);
    const co = r.companies[0];
    expect(co.strandedYear).toBeNull();
    expect(co.marginErosion).toBe(0);
    expect(co.byYear.every((p) => p.netMargin === co.baseNetMargin)).toBe(true);
  });

  it('fuel-price escalation erodes even a zero-emissions company', () => {
    // WindCo has no carbon exposure, but a fuel/VOM cost that escalates.
    const co = entry({ company: 'X', revenue: 1000, fuelVomCost: 400, emissionsTonnes: 0 });
    const flat = computeTransitionRisk(statement([co]), { ...DEFAULT_TRANSITION_PARAMS, escalationPct: 0 });
    const shocked = computeTransitionRisk(statement([co]), { ...DEFAULT_TRANSITION_PARAMS, escalationPct: 0, fuelGrowthPct: 10 });
    // No carbon and no fuel escalation → flat margin across the horizon.
    expect(flat.companies[0].marginErosion).toBe(0);
    // Fuel +10%/yr eats the margin over time.
    expect(shocked.companies[0].marginErosion).toBeGreaterThan(0);
    expect(shocked.companies[0].byYear.at(-1)!.netMargin).toBeLessThan(shocked.companies[0].baseNetMargin);
  });

  it('demand growth scales revenue, fuel and emissions together', () => {
    const co = entry({ company: 'X', revenue: 1000, fuelVomCost: 300, emissionsTonnes: 5 });
    // Zero carbon price + zero fuel escalation isolates the demand-scaling effect.
    const r = computeTransitionRisk(statement([co]), {
      ...DEFAULT_TRANSITION_PARAMS, basePrice: 0, escalationPct: 0, demandGrowthPct: 10,
    });
    const y0 = r.companies[0].byYear[0].netMargin;
    const y1 = r.companies[0].byYear[1].netMargin;
    // Year 1: revenue and fuel both ×1.1 (carbon 0) → gross scales 1.1× on the
    // volume-linked lines, capex/interest fixed (both 0 here) → margin ×1.1.
    expect(y1).toBeCloseTo(y0 * 1.1, 4);
  });

  it('ranks the most-at-risk company first', () => {
    const heavy = entry({ company: 'Heavy', revenue: 1000, emissionsTonnes: 20 });
    const light = entry({ company: 'Light', revenue: 1000, emissionsTonnes: 2 });
    const r = computeTransitionRisk(statement([light, heavy]), DEFAULT_TRANSITION_PARAMS);
    expect(r.companies[0].company).toBe('Heavy');
    expect(r.companies[0].marginErosion).toBeGreaterThan(r.companies[1].marginErosion);
  });
});
