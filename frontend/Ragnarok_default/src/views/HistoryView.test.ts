import { describe, it, expect } from '@jest/globals';
import { matchesBackendQuery } from './HistoryView';
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
