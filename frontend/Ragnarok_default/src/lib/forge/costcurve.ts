/**
 * Quadratic marginal-cost curve fitting for the Forge cost-curve editor (T4).
 *
 * PyPSA's generation cost is `marginal_cost · p + marginal_cost_quadratic · p²`
 * (convex quadratic), so the **marginal** cost is linear in output:
 *
 *     MC(p) = dC/dp = c₁ + 2·c₂·p      with c₁ = marginal_cost, c₂ = marginal_cost_quadratic
 *
 * The editor lets the user draw marginal-cost-vs-output control points; this
 * module finds the closest PyPSA-representable curve — an ordinary
 * least-squares line MC = a + b·p — and maps it to (c₁, c₂) = (a, b/2). The
 * quadratic term is clamped to ≥ 0 so the fit stays convex (a valid QP); a
 * clamped or degenerate fit is reported via `warning`.
 *
 * Pure and unit-tested; the panel is the thin UI around it.
 */

/** A control point the user placed on the chart: output `p` (MW) vs marginal cost (currency/MWh). */
export interface CurvePoint {
  p: number;
  mc: number;
}

export interface CostFit {
  /** c₁ — the linear `marginal_cost` coefficient (currency/MWh). */
  marginalCost: number;
  /** c₂ — the `marginal_cost_quadratic` coefficient (currency/MWh per MW), ≥ 0. */
  marginalCostQuadratic: number;
  /** Slope of the fitted marginal-cost line (= 2·c₂ before clamping). */
  slope: number;
  /** Coefficient of determination of the (unclamped) line fit, 0–1. */
  r2: number;
  /** Set when the fit was clamped (non-convex) or under-determined. */
  warning?: string;
}

const mean = (xs: number[]): number => (xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : 0);

/**
 * Fit the closest convex quadratic cost to the drawn marginal-cost points.
 *
 * Ordinary least squares on MC = a + b·p, then (c₁, c₂) = (a, b/2). If the
 * slope is negative (decreasing marginal cost → non-convex) the quadratic term
 * is clamped to 0 and the linear term falls back to the best flat fit
 * (mean marginal cost), with a warning. Fewer than two distinct outputs also
 * yields a flat fit.
 */
export function fitQuadraticCost(points: CurvePoint[]): CostFit {
  const pts = points.filter((q) => Number.isFinite(q.p) && Number.isFinite(q.mc));
  const flat = (mc: number, warning?: string): CostFit => ({
    marginalCost: mc,
    marginalCostQuadratic: 0,
    slope: 0,
    r2: 0,
    warning,
  });

  if (pts.length === 0) return flat(0);
  const n = pts.length;
  const ps = pts.map((q) => q.p);
  const mcs = pts.map((q) => q.mc);
  const pBar = mean(ps);
  const mcBar = mean(mcs);

  let sPP = 0; // Σ (p − p̄)²
  let sPM = 0; // Σ (p − p̄)(mc − mc̄)
  let sMM = 0; // Σ (mc − mc̄)²
  for (let i = 0; i < n; i++) {
    const dp = ps[i] - pBar;
    const dm = mcs[i] - mcBar;
    sPP += dp * dp;
    sPM += dp * dm;
    sMM += dm * dm;
  }

  if (n < 2 || sPP === 0) {
    return flat(mcBar, n < 2 ? undefined : 'All points share one output — fitted a flat marginal cost.');
  }

  const b = sPM / sPP; // slope of MC line
  const a = mcBar - b * pBar; // intercept
  const r2 = sMM > 0 ? Math.max(0, Math.min(1, (sPM * sPM) / (sPP * sMM))) : 1;

  if (b < 0) {
    // Decreasing marginal cost is non-convex — PyPSA needs c₂ ≥ 0. Fall back to
    // the best flat marginal cost so the applied curve is still valid.
    return { ...flat(mcBar, 'Marginal cost decreases with output (non-convex) — clamped to a flat cost. Draw an increasing curve for a quadratic term.'), r2 };
  }

  return {
    marginalCost: a,
    marginalCostQuadratic: b / 2,
    slope: b,
    r2,
  };
}

/** Evaluate the fitted marginal cost MC(p) = c₁ + 2·c₂·p. */
export function marginalCostAt(fit: Pick<CostFit, 'marginalCost' | 'marginalCostQuadratic'>, p: number): number {
  return fit.marginalCost + 2 * fit.marginalCostQuadratic * p;
}
