import { describe, it, expect } from '@jest/globals';
import { matchesBackendQuery, reorderNames } from './HistoryView';
import { BackendRunMeta } from 'lib/types';

const meta = {
  name: '2026-06-07T10-30-00_baseline',
  savedAt: '2026-06-07T10:30:00.000Z',
  label: 'Baseline 2030',
  filename: 'germany.xlsx',
  snapshotStart: 0,
  snapshotEnd: 24,
  snapshotWeight: 1,
  componentCounts: {},
  kpis: [],
  sizeBytes: 1234,
} as BackendRunMeta;

describe('matchesBackendQuery', () => {
  it('matches everything on an empty query', () => {
    expect(matchesBackendQuery(meta, '')).toBe(true);
  });

  it('matches the label case-insensitively', () => {
    expect(matchesBackendQuery(meta, 'baseline')).toBe(true);
    expect(matchesBackendQuery(meta, 'BASELINE')).toBe(true);
  });

  it('matches the filename', () => {
    expect(matchesBackendQuery(meta, 'germany')).toBe(true);
    expect(matchesBackendQuery(meta, '.xlsx')).toBe(true);
  });

  it('matches the run name', () => {
    expect(matchesBackendQuery(meta, '2026-06-07t10-30-00')).toBe(true);
  });

  it('matches a date substring from the ISO savedAt', () => {
    expect(matchesBackendQuery(meta, '2026')).toBe(true);
  });

  it('returns false when nothing matches', () => {
    expect(matchesBackendQuery(meta, 'nuclear')).toBe(false);
  });
});

describe('reorderNames', () => {
  const names = ['A', 'B', 'C', 'D'];

  it('drops below the target when dragging downward', () => {
    // Drag A (0) onto C (2): A lands just after C.
    expect(reorderNames(names, 0, 2)).toEqual(['B', 'C', 'A', 'D']);
  });

  it('drops above the target when dragging upward', () => {
    // Drag D (3) onto B (1): D lands just before B.
    expect(reorderNames(names, 3, 1)).toEqual(['A', 'D', 'B', 'C']);
  });

  it('swaps adjacent rows', () => {
    expect(reorderNames(names, 0, 1)).toEqual(['B', 'A', 'C', 'D']);
    expect(reorderNames(names, 1, 0)).toEqual(['B', 'A', 'C', 'D']);
  });

  it('moves a row to the very top and bottom', () => {
    expect(reorderNames(names, 2, 0)).toEqual(['C', 'A', 'B', 'D']);
    expect(reorderNames(names, 1, 3)).toEqual(['A', 'C', 'D', 'B']);
  });

  it('is a no-op (copy) when source and target match', () => {
    const out = reorderNames(names, 2, 2);
    expect(out).toEqual(names);
    expect(out).not.toBe(names);
  });

  it('does not mutate the input array', () => {
    const input = [...names];
    reorderNames(input, 0, 3);
    expect(input).toEqual(names);
  });
});
