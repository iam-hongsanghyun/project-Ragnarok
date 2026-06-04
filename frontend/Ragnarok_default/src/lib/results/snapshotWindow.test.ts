import { describe, it, expect } from '@jest/globals';
import {
  endIndexForTime,
  isDatedAxis,
  snapshotInputValueAt,
  snapshotLabelAt,
  snapshotTimestamps,
  startIndexForTime,
} from './snapshotWindow';
import { GridRow } from 'lib/types';

// 3 days × 2 snapshots (00:00 and 12:00), Jan 1–3 2030.
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

describe('snapshotInputValueAt / snapshotLabelAt', () => {
  it('returns minute-precision datetime-local value and a human label', () => {
    expect(snapshotInputValueAt(TS, 1)).toBe('2030-01-01T12:00');
    expect(snapshotLabelAt(TS, 1)).toBe('2030-01-01 12:00');
    expect(snapshotInputValueAt(TS, 99)).toBe('');
  });
});

describe('startIndexForTime', () => {
  it('finds the first snapshot at or after the datetime', () => {
    expect(startIndexForTime(TS, '2030-01-01T00:00')).toBe(0);
    expect(startIndexForTime(TS, '2030-01-01T12:00')).toBe(1); // the 12:00 snapshot
    expect(startIndexForTime(TS, '2030-01-01T06:00')).toBe(1); // rounds up to next
    expect(startIndexForTime(TS, '2030-01-02T00:00')).toBe(2);
  });
  it('returns length when the datetime is past the axis', () => {
    expect(startIndexForTime(TS, '2030-02-01T00:00')).toBe(6);
  });
});

describe('endIndexForTime', () => {
  it('gives an exclusive end including the snapshot at the datetime', () => {
    expect(endIndexForTime(TS, '2030-01-01T00:00')).toBe(1); // just 00:00
    expect(endIndexForTime(TS, '2030-01-01T12:00')).toBe(2); // through 12:00
    expect(endIndexForTime(TS, '2030-01-03T12:00')).toBe(6); // all
  });
  it('returns 0 when the datetime precedes the first snapshot', () => {
    expect(endIndexForTime(TS, '2029-12-31T23:00')).toBe(0);
  });

  it('round-trips: [start, end) selects exactly the chosen datetime range', () => {
    const start = startIndexForTime(TS, '2030-01-02T00:00');
    const end = endIndexForTime(TS, '2030-01-02T12:00');
    expect(TS.slice(start, end)).toEqual(['2030-01-02T00:00:00', '2030-01-02T12:00:00']);
  });
});
