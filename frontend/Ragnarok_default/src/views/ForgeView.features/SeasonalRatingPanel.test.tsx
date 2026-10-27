import { describe, test, expect } from '@jest/globals';
import { parseMonths } from './SeasonalRatingPanel';

describe('parseMonths', () => {
  test('ranges, lists and wrapping ranges', () => {
    expect(parseMonths('4-9')).toEqual([4, 5, 6, 7, 8, 9]);
    expect(parseMonths('10,11,12,1,2,3')).toEqual([1, 2, 3, 10, 11, 12]);
    expect(parseMonths('10-3')).toEqual([1, 2, 3, 10, 11, 12]);
    expect(parseMonths('0, 13, x')).toEqual([]);
  });
});
