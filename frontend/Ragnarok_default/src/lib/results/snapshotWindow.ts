import { GridRow } from 'lib/types';

/**
 * Map between a snapshot datetime and the integer snapshot indices the solver
 * window uses (`snapshotStart` inclusive, `snapshotEnd` exclusive).
 *
 * Snapshots are sub-daily (hourly etc.), so the window picker works at minute
 * precision to match an `<input type="datetime-local">` value
 * (`YYYY-MM-DDTHH:MM`). The run axis is monotonic ascending and ISO, so
 * comparisons are plain lexicographic string compares on the first 16 chars —
 * no Date parsing, no timezone surprises ("date format is parsing, not display").
 */

const MINUTE_LEN = 16; // "YYYY-MM-DDTHH:MM"
const minute = (s: string): string => s.slice(0, MINUTE_LEN);

/** Ordered ISO timestamps from the workbook `snapshots` rows. */
export function snapshotTimestamps(rows: GridRow[] | undefined | null): string[] {
  if (!rows) return [];
  return rows
    .map((r) => String(r.snapshot ?? r.name ?? r.datetime ?? '').trim())
    .filter(Boolean);
}

/** True when the axis carries real calendar datetimes (not "now"/index labels). */
export function isDatedAxis(timestamps: string[]): boolean {
  return timestamps.length > 0 && /^\d{4}-\d{2}-\d{2}/.test(timestamps[0]);
}

/** Value for an `<input type="datetime-local">` at `index`: `YYYY-MM-DDTHH:MM`. */
export function snapshotInputValueAt(timestamps: string[], index: number): string {
  const ts = timestamps[index];
  return ts ? minute(ts) : '';
}

/** Human label `YYYY-MM-DD HH:MM` at `index`; '' if out of range. */
export function snapshotLabelAt(timestamps: string[], index: number): string {
  const ts = timestamps[index];
  return ts ? minute(ts).replace('T', ' ') : '';
}

/**
 * First snapshot index whose datetime is on or after `value`. Returns
 * `timestamps.length` when `value` falls past the last snapshot.
 */
export function startIndexForTime(timestamps: string[], value: string): number {
  const v = minute(value);
  for (let i = 0; i < timestamps.length; i += 1) {
    if (minute(timestamps[i]) >= v) return i;
  }
  return timestamps.length;
}

/**
 * Exclusive end index *including* the snapshot at `value`: the count of leading
 * snapshots at or before `value`. 0 when `value` precedes the first snapshot.
 */
export function endIndexForTime(timestamps: string[], value: string): number {
  const v = minute(value);
  let count = 0;
  for (let i = 0; i < timestamps.length; i += 1) {
    if (minute(timestamps[i]) <= v) count = i + 1;
    else break;
  }
  return count;
}
