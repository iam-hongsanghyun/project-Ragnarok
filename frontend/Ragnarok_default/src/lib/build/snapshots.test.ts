import { describe, test, expect } from '@jest/globals';
import {
  buildSnapshots,
  countForHorizon,
  formatDisplay,
  formatNaive,
  MAX_SNAPSHOTS,
  parseNaive,
  summariseSpec,
  validateSpec,
} from './snapshots';

describe('parseNaive', () => {
  test('accepts date-only and date-time forms', () => {
    expect(parseNaive('2030-01-01')).toBe(Date.UTC(2030, 0, 1));
    expect(parseNaive('2030-01-01 06:30')).toBe(Date.UTC(2030, 0, 1, 6, 30));
    expect(parseNaive('2030-01-01T06:30')).toBe(Date.UTC(2030, 0, 1, 6, 30));
    expect(parseNaive('2030-01-01 06:30:15')).toBe(Date.UTC(2030, 0, 1, 6, 30, 15));
  });

  test('rejects malformed input', () => {
    expect(parseNaive('')).toBeNull();
    expect(parseNaive('01/01/2030')).toBeNull();
    expect(parseNaive('2030-1-1')).toBeNull();
    expect(parseNaive('not a date')).toBeNull();
  });

  test('rejects civil dates that would silently roll over', () => {
    // Date.UTC(2030, 1, 30) happily becomes 2 March — a spec built on that
    // would start a day the user never asked for.
    expect(parseNaive('2030-02-30')).toBeNull();
    expect(parseNaive('2030-13-01')).toBeNull();
  });
});

describe('naive round trip', () => {
  test('display format is the inverse of parse', () => {
    for (const s of ['2030-01-01 00:00', '2029-12-31 23:45', '2031-06-15 12:00']) {
      expect(formatDisplay(parseNaive(s) as number)).toBe(s);
    }
  });

  test('date-only input formats with a midnight time', () => {
    expect(formatDisplay(parseNaive('2030-01-01') as number)).toBe('2030-01-01 00:00');
  });

  test('formatNaive emits the workbook canonical form, which round-trips too', () => {
    // Must match CANONICAL_SNAPSHOT_RE in lib/workbook/workbook.ts, otherwise
    // every generated row is re-normalised on load — 8760 times.
    const canonical = formatNaive(parseNaive('2030-01-01 00:00') as number);
    expect(canonical).toBe('2030-01-01T00:00:00');
    expect(canonical).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/);
    expect(parseNaive(canonical)).toBe(Date.UTC(2030, 0, 1));
  });

  test('midnight survives — the first snapshot is 00:00, not 01:00', () => {
    expect(buildSnapshots({ start: '2030-01-01', stepHours: 1, count: 1 })[0])
      .toBe('2030-01-01T00:00:00');
  });
});

describe('buildSnapshots', () => {
  test('hourly steps advance by an hour', () => {
    expect(buildSnapshots({ start: '2030-01-01 00:00', stepHours: 1, count: 3 }))
      .toEqual(['2030-01-01T00:00:00', '2030-01-01T01:00:00', '2030-01-01T02:00:00']);
  });

  test('sub-hourly steps work', () => {
    expect(buildSnapshots({ start: '2030-01-01 00:00', stepHours: 0.25, count: 5 }))
      .toEqual([
        '2030-01-01T00:00:00', '2030-01-01T00:15:00', '2030-01-01T00:30:00',
        '2030-01-01T00:45:00', '2030-01-01T01:00:00',
      ]);
  });

  test('daily steps roll the date, including across a month end', () => {
    expect(buildSnapshots({ start: '2030-01-30 00:00', stepHours: 24, count: 3 }))
      .toEqual(['2030-01-30T00:00:00', '2030-01-31T00:00:00', '2030-02-01T00:00:00']);
  });

  test('a full non-leap year at hourly resolution is 8760 rows that stay inside the year', () => {
    const rows = buildSnapshots({ start: '2030-01-01 00:00', stepHours: 1, count: 8760 });
    expect(rows).toHaveLength(8760);
    expect(rows[0]).toBe('2030-01-01T00:00:00');
    expect(rows[8759]).toBe('2030-12-31T23:00:00');
  });

  test('arithmetic is naive — no DST jump across a spring-forward boundary', () => {
    // 2030-03-31 is the EU DST switch. A timezone-aware add would skip an hour
    // here and misalign every profile indexed against the axis.
    const rows = buildSnapshots({ start: '2030-03-31 00:00', stepHours: 1, count: 5 });
    expect(rows).toEqual([
      '2030-03-31T00:00:00', '2030-03-31T01:00:00', '2030-03-31T02:00:00',
      '2030-03-31T03:00:00', '2030-03-31T04:00:00',
    ]);
  });

  test('an invalid spec yields no rows rather than garbage', () => {
    expect(buildSnapshots({ start: 'nope', stepHours: 1, count: 3 })).toEqual([]);
    expect(buildSnapshots({ start: '2030-01-01', stepHours: 0, count: 3 })).toEqual([]);
  });
});

describe('countForHorizon', () => {
  test('divides the horizon by the resolution', () => {
    expect(countForHorizon(24, 1)).toBe(24);
    expect(countForHorizon(8760, 1)).toBe(8760);
    expect(countForHorizon(168, 3)).toBe(56);
    expect(countForHorizon(24, 0.25)).toBe(96);
  });

  test('never returns zero for a real horizon', () => {
    expect(countForHorizon(1, 24)).toBe(1);
  });

  test('degenerate inputs give zero', () => {
    expect(countForHorizon(0, 1)).toBe(0);
    expect(countForHorizon(24, 0)).toBe(0);
  });
});

describe('validateSpec', () => {
  test('a sound spec has no problem', () => {
    expect(validateSpec({ start: '2030-01-01 00:00', stepHours: 1, count: 24 })).toBeNull();
  });

  test('each failure mode is named', () => {
    expect(validateSpec({ start: 'x', stepHours: 1, count: 1 })?.message).toMatch(/Start/);
    expect(validateSpec({ start: '2030-01-01', stepHours: 0, count: 1 })?.message).toMatch(/Resolution/);
    expect(validateSpec({ start: '2030-01-01', stepHours: 1, count: 0 })?.message).toMatch(/Count/);
    expect(validateSpec({ start: '2030-01-01', stepHours: 1, count: 1.5 })?.message).toMatch(/Count/);
    expect(validateSpec({ start: '2030-01-01', stepHours: 1, count: MAX_SNAPSHOTS + 1 })?.message)
      .toMatch(/limit/);
  });
});

describe('summariseSpec', () => {
  test('reports the span and the weight that matches the resolution', () => {
    expect(summariseSpec({ start: '2030-01-01 00:00', stepHours: 3, count: 8 })).toEqual({
      count: 8,
      first: '2030-01-01 00:00',
      last: '2030-01-01 21:00',
      totalHours: 24,
      matchingWeight: 3,
    });
  });

  test('a single snapshot starts and ends at the same label', () => {
    const s = summariseSpec({ start: '2030-01-01 00:00', stepHours: 1, count: 1 });
    expect(s?.first).toBe(s?.last);
  });

  test('an invalid spec summarises to null', () => {
    expect(summariseSpec({ start: 'nope', stepHours: 1, count: 3 })).toBeNull();
  });
});
