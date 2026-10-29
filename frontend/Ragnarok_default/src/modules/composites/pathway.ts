/** Pathway (multi-period) helpers for the results run picker. Pure (no React). */
import type { ReportRunOption } from 'lib/reporting/types';

/**
 * Whether a stored run is a pathway (multi-period) run and which periods it has, from the run list meta
 * (`isPathway` / `pathwayPeriods`; older sidecars carry only `pathway`). The P2X results picker offers exactly these.
 */
export function pathwayPeriodsOf(run: ReportRunOption | undefined): { isPathway: boolean; periods: number[] } {
  if (!run) return { isPathway: false, periods: [] };
  const enabled = run.isPathway ?? Boolean(run.pathway?.enabled);
  if (!enabled) return { isPathway: false, periods: [] };
  const raw = run.pathwayPeriods ?? (run.pathway?.periods ?? []).map((p) => (typeof p === 'number' ? p : p?.period));
  const periods = raw.map(Number).filter((p) => Number.isFinite(p));
  return { isPathway: true, periods: Array.from(new Set(periods)).sort((a, b) => a - b) };
}
