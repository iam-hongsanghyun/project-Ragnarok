import { GridRow } from 'lib/types';

/**
 * Map between a snapshot date (YYYY-MM-DD) and the integer snapshot indices the
 * solver window uses (`snapshotStart` inclusive, `snapshotEnd` exclusive).
 *
 * The run axis (the workbook `snapshots` sheet) is monotonic ascending and the
 * timestamps are ISO (`YYYY-MM-DDTHH:MM:SS`), so day comparisons are plain
 * lexicographic string compares on the first 10 chars — no Date parsing, no
 * timezone surprises (mirrors the "Date format is parsing, not display" rule).
 */

/** Ordered ISO timestamps from the workbook `snapshots` rows. */
export function snapshotTimestamps(rows: GridRow[] | undefined | null): string[] {
  if (!rows) return [];
  return rows
    .map((r) => String(r.snapshot ?? r.name ?? r.datetime ?? '').trim())
    .filter(Boolean);
}

/** True when the axis carries real calendar dates (not "now"/index labels). */
export function isDatedAxis(timestamps: string[]): boolean {
  return timestamps.length > 0 && /^\d{4}-\d{2}-\d{2}/.test(timestamps[0]);
}

/** The YYYY-MM-DD of the snapshot at `index`; '' if out of range. */
export function snapshotDateAt(timestamps: string[], index: number): string {
  const ts = timestamps[index];
  return ts ? ts.slice(0, 10) : '';
}

/**
 * First snapshot index whose day is on or after `date`. Returns
 * `timestamps.length` when `date` falls past the last snapshot.
 */
export function startIndexForDate(timestamps: string[], date: string): number {
  for (let i = 0; i < timestamps.length; i += 1) {
    if (timestamps[i].slice(0, 10) >= date) return i;
  }
  return timestamps.length;
}

/**
 * Exclusive end index covering *through the end of* `date`: the count of leading
 * snapshots whose day is on or before `date`. 0 when `date` precedes the first.
 */
export function endIndexForDate(timestamps: string[], date: string): number {
  let count = 0;
  for (let i = 0; i < timestamps.length; i += 1) {
    if (timestamps[i].slice(0, 10) <= date) count = i + 1;
    else break;
  }
  return count;
}
