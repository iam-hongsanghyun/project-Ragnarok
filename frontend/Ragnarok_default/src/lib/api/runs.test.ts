import { describe, it, expect } from '@jest/globals';
import { seriesRowsFromWindow } from './runs';

// `seriesRowsFromWindow` normalises a stored-run series window into the row
// shape `deriveAssetDetails` reads: each row keyed by component name plus a
// `snapshot` index. The light "View" bundle strips these series; hydration
// fetches them back, so this reshape is the seam between the two.
describe('seriesRowsFromWindow', () => {
  it('passes rows through untouched when the index column is already `snapshot`', () => {
    const rows = [
      { snapshot: '2038-01-01T00:00:00', GenA: 1.5, GenB: 0 },
      { snapshot: '2038-01-01T01:00:00', GenA: 2.0, GenB: 3.0 },
    ];
    const out = seriesRowsFromWindow({ indexCol: 'snapshot', rows });
    expect(out).toBe(rows); // same reference — no needless copy
    expect(out[0].GenA).toBe(1.5);
  });

  it('remaps a non-`snapshot` index column to `snapshot`, preserving component values', () => {
    const rows = [
      { name: '2038-01-01T00:00:00', GenA: 4.2 },
      { name: '2038-01-01T01:00:00', GenA: 5.1 },
    ];
    const out = seriesRowsFromWindow({ indexCol: 'name', rows });
    expect(out).toEqual([
      { snapshot: '2038-01-01T00:00:00', GenA: 4.2 },
      { snapshot: '2038-01-01T01:00:00', GenA: 5.1 },
    ]);
    expect('name' in out[0]).toBe(false);
  });

  it('returns an empty array when rows are absent', () => {
    expect(seriesRowsFromWindow({ indexCol: 'snapshot', rows: undefined as never })).toEqual([]);
  });
});
