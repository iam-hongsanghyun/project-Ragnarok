import { describe, it, expect } from '@jest/globals';
import { GridRow } from 'lib/types';
import { seedTemporalRows, snapshotLabel } from './temporalSeed';

const snaps = (labels: string[]): GridRow[] =>
  labels.map((s) => ({ snapshot: s })) as unknown as GridRow[];

describe('snapshotLabel', () => {
  it('reads the label from any of the accepted columns', () => {
    expect(snapshotLabel({ snapshot: '2030-01-01T00:00:00' } as never)).toBe('2030-01-01T00:00:00');
    expect(snapshotLabel({ datetime: '2030-01-01T01:00:00' } as never)).toBe('2030-01-01T01:00:00');
    expect(snapshotLabel({ timestep: 7 } as never)).toBe('7');
  });

  it('prefers `snapshot` when several are present', () => {
    expect(snapshotLabel({ name: 'x', snapshot: 'y' } as never)).toBe('y');
  });

  it('returns empty for a row with no usable label', () => {
    expect(snapshotLabel({} as never)).toBe('');
    expect(snapshotLabel({ snapshot: '   ' } as never)).toBe('');
    expect(snapshotLabel({ snapshot: null } as never)).toBe('');
  });
});

describe('seedTemporalRows', () => {
  it('creates one row per snapshot with a cell per component', () => {
    const rows = seedTemporalRows(snaps(['t0', 't1']), ['L0', 'L1']);
    expect(rows).toEqual([
      { snapshot: 't0', L0: '', L1: '' },
      { snapshot: 't1', L0: '', L1: '' },
    ]);
  });

  it('leaves cells BLANK, never zero', () => {
    // A zero is a real value: a zero-filled p_max_pu pins output to nothing and a
    // zero p_set deletes demand. Blank reads as "not set yet".
    const [row] = seedTemporalRows(snaps(['t0']), ['G']);
    expect(row.G).toBe('');
    expect(row.G).not.toBe(0);
  });

  it('takes the time axis from the model, so a seeded profile lines up', () => {
    const labels = ['2030-01-01T00:00:00', '2030-01-01T01:00:00', '2030-01-01T02:00:00'];
    const rows = seedTemporalRows(snaps(labels), ['G']);
    expect(rows.map((r) => r.snapshot)).toEqual(labels);
  });

  it('dedupes repeated labels so the series stays reindexable', () => {
    // A pathway workbook lists each timestep once per period; a duplicated index
    // cannot be reindexed onto the snapshot axis.
    const rows = seedTemporalRows(snaps(['t0', 't1', 't0']), ['G']);
    expect(rows.map((r) => r.snapshot)).toEqual(['t0', 't1']);
  });

  it('skips rows carrying no label', () => {
    const rows = seedTemporalRows(
      [{ snapshot: 't0' }, {}, { snapshot: '' }, { snapshot: 't1' }] as never,
      ['G'],
    );
    expect(rows.map((r) => r.snapshot)).toEqual(['t0', 't1']);
  });

  it('returns nothing when the model has no time axis', () => {
    // Nothing to seed against — the caller must send the user to the snapshots
    // sheet first rather than invent timestamps that would drop at solve time.
    expect(seedTemporalRows(undefined, ['G'])).toEqual([]);
    expect(seedTemporalRows([], ['G'])).toEqual([]);
  });

  it('still seeds the time axis when the component sheet is empty', () => {
    // Columns arrive with the components; the rows are useful on their own.
    expect(seedTemporalRows(snaps(['t0']), [])).toEqual([{ snapshot: 't0' }]);
  });

  it('ignores blank component names', () => {
    expect(seedTemporalRows(snaps(['t0']), ['G', ''])).toEqual([{ snapshot: 't0', G: '' }]);
  });
});
