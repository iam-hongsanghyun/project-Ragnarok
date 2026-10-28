/**
 * Curtailment overlay for dispatch charts.
 *
 * Stacks each carrier's (or asset's) curtailed MW on top of its dispatch as a
 * lighter band, so the top of the stack reads as available output. The numbers
 * are the server's curtailment metric (n.statistics.curtailment, restricted to
 * time-varying p_max_pu); this only lines the two metrics up for drawing.
 */
import type { MetricOption, TimeSeriesRow, TimeSeriesSeries } from 'lib/types';

/** Dispatch metric key → the curtailment metric that overlays it, per focus. */
const PAIRS: Record<string, string> = {
  dispatch: 'curtailment', // system: dispatch by carrier ↔ curtailment by carrier
  output: 'curtailment',   // generator focus: output ↔ curtailment (same grouping)
};

export const CURTAIL_PREFIX = 'curtailed:';

/** The curtailment metric that can overlay `metric`, if this focus offers one with data. */
export function curtailmentFor(metric: MetricOption | undefined, options: MetricOption[]): MetricOption | undefined {
  if (!metric) return undefined;
  const pair = PAIRS[metric.key];
  const curt = pair ? options.find((o) => o.key === pair) : undefined;
  if (!curt || curt.rows.length === 0 || curt.series.length === 0) return undefined;
  return curt;
}

/** `#rrggbb` → the same colour at ~40% opacity (`#rrggbb66`); other formats pass through. */
function lighter(color: string): string {
  return /^#[0-9a-f]{6}$/i.test(color) ? `${color}66` : color;
}

const rowKey = (r: TimeSeriesRow) => `${r.timestamp ?? ''}|${r.label}`;

/**
 * One metric whose rows carry both dispatch and curtailment columns.
 *
 * Curtailment columns are prefixed so a carrier's dispatch and curtailment never
 * collide, and appended after the dispatch series so they stack on top. Rows are
 * joined on timestamp+label; a snapshot with no curtailment row gets 0.
 */
export function withCurtailment(metric: MetricOption, curt: MetricOption): MetricOption {
  const byKey = new Map(curt.rows.map((r) => [rowKey(r), r]));
  const rows = metric.rows.map((r) => {
    const c = byKey.get(rowKey(r));
    const out: TimeSeriesRow = { ...r };
    for (const s of curt.series) {
      const v = c?.[s.key];
      out[CURTAIL_PREFIX + s.key] = typeof v === 'number' ? v : 0;
    }
    return out;
  });
  const colourOf = new Map(metric.series.map((s) => [s.key, s.color]));
  const extra: TimeSeriesSeries[] = curt.series.map((s) => ({
    key: CURTAIL_PREFIX + s.key,
    // A single-asset curtailment series is already labelled "Curtailment MW".
    label: /curtail/i.test(s.label) ? s.label : `${s.label} (curtailed)`,
    color: lighter(colourOf.get(s.key) ?? s.color),
  }));
  return { ...metric, label: `${metric.label} + curtailment`, rows, series: [...metric.series, ...extra] };
}
