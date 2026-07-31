/**
 * Snapshot axis generation.
 *
 * The `snapshots` sheet is the one time axis every temporal sheet is indexed
 * by, and it is the only sheet whose row count is routinely in the thousands —
 * a year at hourly resolution is 8760 rows. Adding those by hand is not a
 * workflow, so the axis is specified rather than typed: a start instant, a
 * resolution, and a horizon.
 *
 * Two quantities are easy to conflate and are kept separate here:
 *
 *   RESOLUTION — the spacing between consecutive snapshots. Decides how many
 *   rows the sheet gets.
 *
 *   WEIGHT — how many real hours each snapshot stands for, used to scale
 *   energy and cost totals. Usually equal to the resolution, but not always:
 *   12 snapshots weighted 730 h each represent a year in monthly blocks. Weight
 *   is global app state (Settings → Simulation window), not a sheet column, so
 *   this module only reports the weight that would match a spec.
 *
 * Date arithmetic is naive — no timezone, no DST. Snapshots are labels on a
 * model's time axis, not instants in a civil calendar; introducing a DST jump
 * would silently misalign every profile indexed against them.
 */

export interface Resolution {
  id: string;
  label: string;
  /** Spacing in hours. Fractional for sub-hourly. */
  hours: number;
}

export interface Horizon {
  id: string;
  label: string;
  /** Total span in hours, or null when the user supplies a count directly. */
  hours: number | null;
}

export const RESOLUTIONS: Resolution[] = [
  { id: '15min', label: '15 minutes', hours: 0.25 },
  { id: '30min', label: '30 minutes', hours: 0.5 },
  { id: '1h', label: '1 hour', hours: 1 },
  { id: '2h', label: '2 hours', hours: 2 },
  { id: '3h', label: '3 hours', hours: 3 },
  { id: '6h', label: '6 hours', hours: 6 },
  { id: '1d', label: '1 day', hours: 24 },
];

export const HORIZONS: Horizon[] = [
  { id: '1d', label: '1 day', hours: 24 },
  { id: '3d', label: '3 days', hours: 72 },
  { id: '1w', label: '1 week', hours: 168 },
  { id: '4w', label: '4 weeks', hours: 672 },
  { id: '1y', label: '1 year (8760 h)', hours: 8760 },
  { id: 'custom', label: 'Custom count', hours: null },
];

/** Refuse to generate beyond this — a typo should not lock up the browser. */
export const MAX_SNAPSHOTS = 100_000;
/**
 * At or above this, generation still works but the UI warns about solve time.
 * Set to a full hourly year deliberately: 8760 is both the commonest real
 * configuration and the first one slow enough to surprise someone.
 */
export const LARGE_SNAPSHOTS = 8_760;

export interface SnapshotSpec {
  /** Naive local start, `YYYY-MM-DD HH:mm` or `YYYY-MM-DDTHH:mm`. */
  start: string;
  /** Spacing between snapshots, in hours. */
  stepHours: number;
  /** How many snapshots to generate. */
  count: number;
}

const pad = (n: number, width = 2): string => String(n).padStart(width, '0');

/**
 * Parse a naive `YYYY-MM-DD[ T]HH:mm[:ss]` into epoch ms, interpreted as UTC.
 *
 * UTC deliberately: it makes the arithmetic below a pure millisecond add with
 * no DST discontinuity, and the value is only ever formatted back through the
 * matching UTC getters — so the timezone never surfaces.
 */
export function parseNaive(value: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$/.exec(value.trim());
  if (!m) return null;
  const [, y, mo, d, h, mi, s] = m;
  const ms = Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h ?? 0), Number(mi ?? 0), Number(s ?? 0));
  if (Number.isNaN(ms)) return null;
  // Reject impossible civil dates that Date.UTC silently rolls over (2030-02-30).
  const back = new Date(ms);
  if (back.getUTCFullYear() !== Number(y) || back.getUTCMonth() !== Number(mo) - 1 || back.getUTCDate() !== Number(d)) {
    return null;
  }
  return ms;
}

/**
 * Format epoch ms (read as UTC) as `YYYY-MM-DDTHH:MM:SS`.
 *
 * This is the canonical snapshot form the workbook layer stores
 * (`CANONICAL_SNAPSHOT_RE` in `lib/workbook/workbook.ts`). Emitting it directly
 * means generated rows short-circuit re-normalisation on every load — which
 * matters at 8760 rows — and are byte-identical to what a re-import produces.
 */
export function formatNaive(ms: number): string {
  const d = new Date(ms);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`
    + `T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
}

/** The same instant as a compact `YYYY-MM-DD HH:mm` for display in the UI. */
export function formatDisplay(ms: number): string {
  const d = new Date(ms);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} `
    + `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

/** How many snapshots a horizon holds at a given resolution, at least 1. */
export function countForHorizon(horizonHours: number, stepHours: number): number {
  if (!(stepHours > 0) || !(horizonHours > 0)) return 0;
  return Math.max(1, Math.round(horizonHours / stepHours));
}

export interface SpecProblem {
  /** Human-readable reason the spec cannot be generated. */
  message: string;
}

/** Why a spec cannot be generated, or null when it is fine. */
export function validateSpec(spec: SnapshotSpec): SpecProblem | null {
  if (parseNaive(spec.start) === null) {
    return { message: 'Start must be a date like 2030-01-01 or 2030-01-01 00:00.' };
  }
  if (!Number.isFinite(spec.stepHours) || spec.stepHours <= 0) {
    return { message: 'Resolution must be greater than zero.' };
  }
  if (!Number.isInteger(spec.count) || spec.count < 1) {
    return { message: 'Count must be a whole number of at least 1.' };
  }
  if (spec.count > MAX_SNAPSHOTS) {
    return { message: `That is ${spec.count.toLocaleString()} snapshots. The limit is ${MAX_SNAPSHOTS.toLocaleString()}.` };
  }
  return null;
}

/** The snapshot labels a spec produces. Empty when the spec is invalid. */
export function buildSnapshots(spec: SnapshotSpec): string[] {
  if (validateSpec(spec)) return [];
  const start = parseNaive(spec.start) as number;
  const stepMs = spec.stepHours * 3_600_000;
  const out: string[] = new Array(spec.count);
  for (let i = 0; i < spec.count; i += 1) out[i] = formatNaive(start + i * stepMs);
  return out;
}

export interface SpecSummary {
  count: number;
  first: string;
  last: string;
  /** Span covered if each snapshot stands for `stepHours`. */
  totalHours: number;
  /** The weight that matches this resolution — what to set in Settings. */
  matchingWeight: number;
}

/** Headline numbers for a spec, without materialising every row. */
export function summariseSpec(spec: SnapshotSpec): SpecSummary | null {
  if (validateSpec(spec)) return null;
  const start = parseNaive(spec.start) as number;
  const stepMs = spec.stepHours * 3_600_000;
  return {
    count: spec.count,
    first: formatDisplay(start),
    last: formatDisplay(start + (spec.count - 1) * stepMs),
    totalHours: spec.count * spec.stepHours,
    matchingWeight: spec.stepHours,
  };
}
