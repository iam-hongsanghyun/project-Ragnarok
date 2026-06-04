import { describe, it, expect } from '@jest/globals';
import {
  endIndexForDate,
  isDatedAxis,
  snapshotDateAt,
  snapshotTimestamps,
  startIndexForDate,
} from './snapshotWindow';
import { GridRow } from 'lib/types';

// 3 days × 2 hourly snapshots = 6 snapshots, Jan 1–3 2030.
const TS = [
  '2030-01-01T00:00:00', '2030-01-01T12:00:00',
  '2030-01-02T00:00:00', '2030-01-02T12:00:00',
  '2030-01-03T00:00:00', '2030-01-03T12:00:00',
];

describe('snapshotTimestamps', () => {
  it('reads the snapshot column (with name/datetime fallback) and drops blanks', () => {
    const rows: GridRow[] = [
      { snapshot: '2030-01-01T00:00:00' },
      { name: '2030-01-01T12:00:00' } as GridRow,
      { datetime: '2030-01-02T00:00:00' } as GridRow,
      { snapshot: '' } as GridRow,
    ];
    expect(snapshotTimestamps(rows)).toEqual([
      '2030-01-01T00:00:00', '2030-01-01T12:00:00', '2030-01-02T00:00:00',
    ]);
    expect(snapshotTimestamps(null)).toEqual([]);
  });
});

describe('isDatedAxis', () => {
  it('detects calendar dates vs index/now labels', () => {
    expect(isDatedAxis(TS)).toBe(true);
    expect(isDatedAxis(['now'])).toBe(false);
    expect(isDatedAxis([])).toBe(false);
  });
});

describe('snapshotDateAt', () => {
  it('returns the YYYY-MM-DD or empty when out of range', () => {
    expect(snapshotDateAt(TS, 0)).toBe('2030-01-01');
    expect(snapshotDateAt(TS, 5)).toBe('2030-01-03');
    expect(snapshotDateAt(TS, 99)).toBe('');
  });
});

describe('startIndexForDate', () => {
  it('finds the first snapshot on or after the date', () => {
    expect(startIndexForDate(TS, '2030-01-01')).toBe(0);
    expect(startIndexForDate(TS, '2030-01-02')).toBe(2); // first Jan-2 snapshot
    expect(startIndexForDate(TS, '2030-01-03')).toBe(4);
  });
  it('returns length when the date is past the axis', () => {
    expect(startIndexForDate(TS, '2030-02-01')).toBe(6);
  });
});

describe('endIndexForDate', () => {
  it('gives an exclusive end covering through the whole day', () => {
    expect(endIndexForDate(TS, '2030-01-01')).toBe(2); // both Jan-1 snapshots
    expect(endIndexForDate(TS, '2030-01-02')).toBe(4);
    expect(endIndexForDate(TS, '2030-01-03')).toBe(6); // all
  });
  it('returns 0 when the date precedes the first snapshot', () => {
    expect(endIndexForDate(TS, '2029-12-31')).toBe(0);
  });

  it('round-trips: [start, end) selects exactly the chosen day range', () => {
    const start = startIndexForDate(TS, '2030-01-02');
    const end = endIndexForDate(TS, '2030-01-02');
    expect(TS.slice(start, end)).toEqual(['2030-01-02T00:00:00', '2030-01-02T12:00:00']);
  });
});
