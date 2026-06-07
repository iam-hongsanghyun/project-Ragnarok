import { describe, it, expect } from '@jest/globals';
import { matchesQuery } from './HistoryView';
import { RunHistoryEntry } from 'lib/types';

const entry = {
  id: 'r1',
  label: 'Baseline 2030',
  savedAt: '2026-06-07T10:30:00.000Z',
  filename: 'germany.xlsx',
  carbonPrice: 50,
  snapshotStart: 0,
  snapshotEnd: 24,
  snapshotWeight: 1,
  activeConstraints: [],
  componentCounts: {},
  pinned: false,
  inComparison: true,
  results: {} as RunHistoryEntry['results'],
} as RunHistoryEntry;

describe('matchesQuery', () => {
  it('matches everything on an empty query', () => {
    expect(matchesQuery(entry, '')).toBe(true);
  });

  it('matches the label case-insensitively', () => {
    expect(matchesQuery(entry, 'baseline')).toBe(true);
    expect(matchesQuery(entry, 'BASELINE')).toBe(true);
  });

  it('matches the filename', () => {
    expect(matchesQuery(entry, 'germany')).toBe(true);
    expect(matchesQuery(entry, '.xlsx')).toBe(true);
  });

  it('matches a date substring from the ISO savedAt', () => {
    expect(matchesQuery(entry, '2026')).toBe(true);
  });

  it('returns false when nothing matches', () => {
    expect(matchesQuery(entry, 'nuclear')).toBe(false);
  });
});
