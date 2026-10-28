/**
 * Ramp-limit and set-point duals (P30): which assets bind, when, and at what
 * shadow price.
 *
 * PyPSA stores one dual per asset and snapshot for a ramp limit
 * (`mu_ramp_limit_up` / `mu_ramp_limit_down`), a fixed-power set point
 * (`mu_p_set`) and a fixed state of charge (`mu_state_of_charge_set`). All are in
 * currency per MWh: the amount the objective would change per MWh the constraint
 * were relaxed. A zero dual means the constraint is slack. The values arrive as
 * the generic output series sheets `<list>-<attr>` (`outputs.series`).
 *
 * Which assets bind, for how long and at what price is a server summary
 * (`GET /api/runs/{name}/analysis/setpoint-duals`); this module only names the sheets.
 */
import type { RunResults } from 'lib/types';

export const DUAL_ATTRIBUTES = [
  'mu_ramp_limit_up', 'mu_ramp_limit_down', 'mu_p_set', 'mu_state_of_charge_set',
] as const;
export type DualAttribute = (typeof DUAL_ATTRIBUTES)[number];

export const DUAL_LABEL: Record<DualAttribute, string> = {
  mu_ramp_limit_up: 'Ramp-up limit',
  mu_ramp_limit_down: 'Ramp-down limit',
  mu_p_set: 'Power set point',
  mu_state_of_charge_set: 'State-of-charge set point',
};

const SHEET_RE = new RegExp(`^([a-z_]+)-(${DUAL_ATTRIBUTES.join('|')})$`);

/** Output sheet names (`generators-mu_ramp_limit_up`, ...) among `names`. */
export function dualSheetsIn(names: string[]): string[] {
  return names.filter((n) => SHEET_RE.test(n)).sort();
}

/** Dual sheets this result carries: populated `outputs.series` (full bundle) or `outputs.seriesSheets` (light bundle). */
export function dualSheetsOf(results: RunResults): string[] {
  const outputs = results.outputs;
  if (!outputs) return [];
  const full = outputs.series
    ? Object.entries(outputs.series).filter(([, rows]) => Array.isArray(rows) && rows.length > 0).map(([k]) => k)
    : [];
  return dualSheetsIn([...full, ...(outputs.seriesSheets ?? [])]);
}

export function parseDualSheet(sheet: string): { component: string; attribute: DualAttribute } | null {
  const m = SHEET_RE.exec(sheet);
  return m ? { component: m[1], attribute: m[2] as DualAttribute } : null;
}
