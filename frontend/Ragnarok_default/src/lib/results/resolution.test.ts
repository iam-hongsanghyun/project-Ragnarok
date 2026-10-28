import { describe, test, expect } from '@jest/globals';
import { medianSpacingHours, medianWeightingHours, resampleOffset, strideNotice, workbookResolution } from './resolution';

const hourly = (n: number, extra: Record<string, number> = {}) =>
  Array.from({ length: n }, (_, i) => ({ snapshot: `2030-01-01 ${String(i).padStart(2, '0')}:00:00`, ...extra }));

describe('workbook resolution', () => {
  test('spacing and weighting are read separately', () => {
    expect(medianSpacingHours(hourly(5))).toBe(1);
    expect(medianWeightingHours(hourly(5))).toBeNull();
    expect(medianWeightingHours(hourly(5, { objective: 4 }))).toBe(4);
  });

  test('a weighting that disagrees with the spacing is a mismatch (the model-check warning case)', () => {
    expect(workbookResolution(hourly(5)).mismatch).toBe(false);
    const fourHourly = Array.from({ length: 4 }, (_, i) => ({ snapshot: `2030-01-01 ${String(i * 4).padStart(2, '0')}:00:00` }));
    const r = workbookResolution(fourHourly);
    expect(r).toEqual({ weightingHours: 1, spacingHours: 4, mismatch: true });
    expect(workbookResolution(fourHourly.map((s) => ({ ...s, generators: 4 }))).mismatch).toBe(false);
  });

  test('the resample offset and the notice for an old stride', () => {
    expect(resampleOffset(4)).toBe('4h');
    expect(strideNotice(1)).toBeNull();
    expect(strideNotice(4)).toContain('Resample 4h');
  });
});
