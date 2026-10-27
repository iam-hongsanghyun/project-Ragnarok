import { describe, test, expect } from '@jest/globals';
import { normSnapshot, sessionSeriesIssues } from './useModelIssues';
import { createEmptyWorkbook } from 'lib/workbook/workbook';

describe('snapshot label comparison is wall-clock text', () => {
  test('the DST hour is neither collapsed nor shifted, whatever the process zone', () => {
    expect(normSnapshot('2024-03-31 02:00:00')).toBe('2024-03-31T02:00:00');
    expect(normSnapshot('2024-03-31T02:00')).toBe('2024-03-31T02:00:00');
    expect(normSnapshot('2024-10-27T02:00:00')).not.toBe(normSnapshot('2024-10-27T03:00:00'));
    expect(normSnapshot('2024-01-01')).toBe('2024-01-01T00:00:00');
    expect(normSnapshot('now')).toBe('now');
    expect(normSnapshot('7')).toBe('7');
  });
});

describe('sessionSeriesIssues (series checks on a loaded model)', () => {
  test('flags unknown columns and a row count off the snapshot axis', () => {
    const model = createEmptyWorkbook();
    model.generators = [{ name: 'g1' }];
    model.snapshots = [{ snapshot: 't0' }, { snapshot: 't1' }, { snapshot: 't2' }];
    const issues = sessionSeriesIssues(model, [
      { name: 'generators-p_max_pu', kind: 'series', rowCount: 2, columns: ['snapshot', 'g1', 'ghost'] },
      { name: 'buses', kind: 'static', rowCount: 4, columns: ['name'] },
    ]);
    expect(issues.map((i) => i.message)).toEqual([
      expect.stringContaining('Row count 2 differs from the snapshot count 3'),
      '"ghost" does not exist in generators',
    ]);
    expect(issues[1].severity).toBe('error');
  });
});
