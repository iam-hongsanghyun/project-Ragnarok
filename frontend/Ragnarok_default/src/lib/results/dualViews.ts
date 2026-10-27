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
 */
import type { GridRow, RunResults } from 'lib/types';

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

export interface DualRow {
  component: string;
  attribute: DualAttribute;
  asset: string;
  /** Snapshots where |dual| > tolerance. */
  bindingSnapshots: number;
  /** Binding snapshots weighted by the snapshot weighting. */
  bindingHours: number;
  totalSnapshots: number;
  /** Dual (currency/MWh) with the largest magnitude, signed. */
  peakShadowPrice: number;
  peakAt: string;
  /** Mean |dual| over the binding snapshots (currency/MWh). */
  meanShadowPrice: number;
  /** Run-length encoding of the binding pattern, for a strip chart. */
  segments: Array<{ on: boolean; length: number }>;
}

export interface DualSummary {
  /** Assets that bind at least once, strongest peak first. */
  rows: DualRow[];
  /** Assets that carry the dual at all (binding or slack). */
  assetsChecked: number;
}

const INDEX_COLUMNS = new Set(['snapshot', 'period', 'timestep', 'name']);

/** Summarise one `<list>-mu_*` sheet; `tolerance` (currency/MWh) separates binding from slack. */
export function summariseDualSheet(
  sheet: string,
  rows: GridRow[],
  snapshotWeight: number,
  tolerance = 1e-6,
): DualSummary {
  const parsed = parseDualSheet(sheet);
  if (!parsed || rows.length === 0) return { rows: [], assetsChecked: 0 };
  const assets = Array.from(new Set(rows.flatMap((r) => Object.keys(r)))).filter((k) => !INDEX_COLUMNS.has(k));
  const out: DualRow[] = [];
  for (const asset of assets) {
    let binding = 0;
    let peak = 0;
    let peakAt = '';
    let absSum = 0;
    const segments: DualRow['segments'] = [];
    for (const row of rows) {
      const raw = row[asset];
      const v = typeof raw === 'number' ? raw : Number(raw);
      const on = Number.isFinite(v) && Math.abs(v) > tolerance;
      const last = segments[segments.length - 1];
      if (last && last.on === on) last.length += 1;
      else segments.push({ on, length: 1 });
      if (!on) continue;
      binding += 1;
      absSum += Math.abs(v);
      if (Math.abs(v) > Math.abs(peak)) { peak = v; peakAt = String(row.snapshot ?? ''); }
    }
    if (binding === 0) continue;
    out.push({
      component: parsed.component,
      attribute: parsed.attribute,
      asset,
      bindingSnapshots: binding,
      bindingHours: binding * snapshotWeight,
      totalSnapshots: rows.length,
      peakShadowPrice: peak,
      peakAt,
      meanShadowPrice: absSum / binding,
      segments,
    });
  }
  out.sort((a, b) => Math.abs(b.peakShadowPrice) - Math.abs(a.peakShadowPrice));
  return { rows: out, assetsChecked: assets.length };
}
