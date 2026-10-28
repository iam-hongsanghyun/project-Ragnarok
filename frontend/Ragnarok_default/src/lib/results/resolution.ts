/**
 * Resolution of the working workbook — what the Run dialog and the Window section show, and the visible
 * transforms behind the "resolution" choice.
 *
 * Core no longer strides the snapshots at run time (the old `snapshotWeight` run option point-sampled every k-th
 * row). The resolution is a property of the WORKBOOK: its snapshots and their weightings. Changing it is the
 * Forge → Temporal transform (`POST /api/transform/temporal`, resample takes block means), which writes the reduced
 * snapshots, the weightings and the aggregated series into the workbook. Setting the weightings from the timestamp
 * spacing is the other visible action (`POST /api/model/set-weightings-from-spacing`).
 */
import type { GridRow } from '../types';

/** Resolutions offered as one-click resamples (hours). */
export const RESOLUTION_CHOICES_HOURS = [1, 2, 3, 4, 6, 12];

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Median snapshot weighting in hours (generators → objective → stores column), or null when the sheet carries none. */
export function medianWeightingHours(snapshots: GridRow[] | undefined): number | null {
  const rows = snapshots ?? [];
  for (const column of ['generators', 'objective', 'stores']) {
    const values = rows.map((r) => Number(r[column])).filter((v) => Number.isFinite(v) && v > 0);
    if (values.length > 0) return median(values);
  }
  return null;
}

/** Median gap between consecutive timestamps in hours, or null when the labels are not dates. */
export function medianSpacingHours(snapshots: GridRow[] | undefined): number | null {
  const stamps = (snapshots ?? [])
    .map((r) => Date.parse(String(r.snapshot ?? '').replace(' ', 'T')))
    .filter((t) => Number.isFinite(t));
  if (stamps.length < 2) return null;
  const gaps: number[] = [];
  for (let i = 1; i < stamps.length; i++) {
    const gap = (stamps[i] - stamps[i - 1]) / 3_600_000;
    if (gap > 0) gaps.push(gap);
  }
  return median(gaps);
}

export interface WorkbookResolution {
  /** Hours each snapshot represents in the solve (the weighting; 1 when the sheet carries none). */
  weightingHours: number;
  /** Hours between timestamps, or null. */
  spacingHours: number | null;
  /** True when the timestamps and the weighting disagree by more than 1 % (the model-check `weighting_spacing` case). */
  mismatch: boolean;
}

export function workbookResolution(snapshots: GridRow[] | undefined): WorkbookResolution {
  const weighting = medianWeightingHours(snapshots) ?? 1;
  const spacing = medianSpacingHours(snapshots);
  return { weightingHours: weighting, spacingHours: spacing, mismatch: spacing !== null && Math.abs(spacing - weighting) > 0.01 * spacing };
}

/** The pandas offset the temporal transform takes for a whole number of hours. */
export function resampleOffset(hours: number): string {
  return `${hours}h`;
}

/** A preset saved before core cleanup step 4 may carry a run-time stride; it is not applied any more. */
export function strideNotice(snapshotWeight: number | null | undefined): string | null {
  const w = Number(snapshotWeight);
  if (!Number.isFinite(w) || w <= 1) return null;
  return `This preset asked for every ${w}th snapshot. A run-time stride no longer exists: use Resample ${w}h (Run → Resolution, or Forge → Temporal) to write that resolution into the workbook.`;
}
