import { describe, test, expect } from '@jest/globals';
import { boxFromCells, isInBox, resolvePaste } from './range';

describe('range geometry', () => {
  test('boxFromCells normalises anchor/focus regardless of direction', () => {
    expect(boxFromCells({ row: 4, col: 3 }, { row: 1, col: 1 })).toEqual({ r0: 1, r1: 4, c0: 1, c1: 3 });
    expect(boxFromCells({ row: 0, col: 0 }, { row: 0, col: 0 })).toEqual({ r0: 0, r1: 0, c0: 0, c1: 0 });
  });

  test('isInBox is inclusive on all edges and false for null box', () => {
    const box = { r0: 1, r1: 3, c0: 2, c1: 4 };
    expect(isInBox(box, 1, 2)).toBe(true);
    expect(isInBox(box, 3, 4)).toBe(true);
    expect(isInBox(box, 0, 2)).toBe(false);
    expect(isInBox(box, 2, 5)).toBe(false);
    expect(isInBox(null, 2, 3)).toBe(false);
  });
});

describe('resolvePaste', () => {
  const cols = ['name', 'bus', 'p_nom'];

  test('maps a rectangle onto existing rows via displayToOrig', () => {
    // 2 display rows mapped to original indices 5 and 6 (e.g. filtered view).
    const { edits, extraRows } = resolvePaste(
      [['a', 'B1'], ['b', 'B2']],
      0, 0, cols, [5, 6], 7,
    );
    expect(extraRows).toBe(0);
    expect(edits).toEqual([
      { rowIndex: 5, col: 'name', raw: 'a' },
      { rowIndex: 5, col: 'bus', raw: 'B1' },
      { rowIndex: 6, col: 'name', raw: 'b' },
      { rowIndex: 6, col: 'bus', raw: 'B2' },
    ]);
  });

  test('grows the table when the paste extends past the last row', () => {
    // 3 pasted rows starting at the last display row (index 0 → orig 0); table
    // currently has 1 row, so 2 new rows must be appended at orig indices 1, 2.
    const { edits, extraRows } = resolvePaste(
      [['x'], ['y'], ['z']],
      0, 0, ['name'], [0], 1,
    );
    expect(extraRows).toBe(2);
    expect(edits.map((e) => e.rowIndex)).toEqual([0, 1, 2]);
    expect(edits.map((e) => e.raw)).toEqual(['x', 'y', 'z']);
  });

  test('clips columns that overflow the table width', () => {
    const { edits } = resolvePaste([['a', 'b', 'c', 'd']], 0, 1, cols, [0], 1);
    // start col index 1 → can only fill bus, p_nom (2 cols), rest clipped.
    expect(edits.map((e) => e.col)).toEqual(['bus', 'p_nom']);
  });

  test('honours a non-zero start column offset', () => {
    const { edits } = resolvePaste([['B9']], 0, 1, cols, [2], 5);
    expect(edits).toEqual([{ rowIndex: 2, col: 'bus', raw: 'B9' }]);
  });
});
