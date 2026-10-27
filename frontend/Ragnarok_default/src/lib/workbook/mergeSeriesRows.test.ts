import { describe, test, expect } from '@jest/globals';
import { mergeSeriesRows } from './mergeSeriesRows';
import type { GridRow } from 'lib/types';

describe('mergeSeriesRows', () => {
  test('keeps columns the import does not carry and overwrites the ones it does', () => {
    const existing = [
      { snapshot: 't0', a: 1, b: 2 },
      { snapshot: 't1', a: 3, b: 4 },
    ];
    const imported: GridRow[] = [{ snapshot: 't0', b: 9, c: 7 }, { snapshot: 't2', c: 5 }];
    expect(mergeSeriesRows(existing, imported, 'snapshot')).toEqual([
      { snapshot: 't0', a: 1, b: 9, c: 7 },
      { snapshot: 't1', a: 3, b: 4 },
      { snapshot: 't2', c: 5 },
    ]);
    expect(existing[0]).toEqual({ snapshot: 't0', a: 1, b: 2 }); // inputs not mutated
  });
  test('an empty sheet just takes the import', () => {
    expect(mergeSeriesRows([], [{ snapshot: 't0', a: 1 }], 'snapshot')).toEqual([{ snapshot: 't0', a: 1 }]);
  });
});
