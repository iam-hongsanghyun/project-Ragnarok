import { describe, it, expect } from '@jest/globals';
import { fitQuadraticCost, marginalCostAt, CurvePoint } from './costcurve';

describe('fitQuadraticCost', () => {
  it('recovers c₁ and c₂ from points on an exact quadratic-cost marginal line', () => {
    // MC(p) = 20 + 2·0.5·p = 20 + p  → c₁=20, c₂=0.5
    const pts: CurvePoint[] = [0, 25, 50, 75, 100].map((p) => ({ p, mc: 20 + p }));
    const fit = fitQuadraticCost(pts);
    expect(fit.marginalCost).toBeCloseTo(20, 6);
    expect(fit.marginalCostQuadratic).toBeCloseTo(0.5, 6);
    expect(fit.r2).toBeCloseTo(1, 6);
    expect(fit.warning).toBeUndefined();
  });

  it('flat marginal cost → zero quadratic term', () => {
    const pts: CurvePoint[] = [0, 50, 100].map((p) => ({ p, mc: 42 }));
    const fit = fitQuadraticCost(pts);
    expect(fit.marginalCost).toBeCloseTo(42, 6);
    expect(fit.marginalCostQuadratic).toBe(0);
  });

  it('clamps a decreasing (non-convex) marginal cost to flat, with a warning', () => {
    const pts: CurvePoint[] = [
      { p: 0, mc: 80 },
      { p: 50, mc: 50 },
      { p: 100, mc: 20 },
    ];
    const fit = fitQuadraticCost(pts);
    expect(fit.marginalCostQuadratic).toBe(0);
    expect(fit.marginalCost).toBeCloseTo(50, 6); // mean of the mc values
    expect(fit.warning).toMatch(/non-convex/i);
  });

  it('finds the closest line for a curved (non-linear) marginal-cost sketch', () => {
    // A convex-ish upward sketch that is not exactly linear — expect a positive
    // slope, positive quadratic term, and r² < 1 (it is an approximation).
    const pts: CurvePoint[] = [
      { p: 0, mc: 10 },
      { p: 25, mc: 14 },
      { p: 50, mc: 22 },
      { p: 75, mc: 34 },
      { p: 100, mc: 50 },
    ];
    const fit = fitQuadraticCost(pts);
    expect(fit.marginalCostQuadratic).toBeGreaterThan(0);
    expect(fit.slope).toBeGreaterThan(0);
    expect(fit.r2).toBeGreaterThan(0.9);
    expect(fit.r2).toBeLessThan(1);
  });

  it('single point → flat at that marginal cost', () => {
    const fit = fitQuadraticCost([{ p: 30, mc: 55 }]);
    expect(fit.marginalCost).toBeCloseTo(55, 6);
    expect(fit.marginalCostQuadratic).toBe(0);
  });

  it('all points at one output → flat fit with a warning', () => {
    const fit = fitQuadraticCost([{ p: 50, mc: 10 }, { p: 50, mc: 30 }]);
    expect(fit.marginalCostQuadratic).toBe(0);
    expect(fit.marginalCost).toBeCloseTo(20, 6);
    expect(fit.warning).toMatch(/one output/i);
  });

  it('marginalCostAt evaluates c₁ + 2·c₂·p', () => {
    expect(marginalCostAt({ marginalCost: 20, marginalCostQuadratic: 0.5 }, 100)).toBeCloseTo(120, 6);
    expect(marginalCostAt({ marginalCost: 20, marginalCostQuadratic: 0.5 }, 0)).toBeCloseTo(20, 6);
  });
});
