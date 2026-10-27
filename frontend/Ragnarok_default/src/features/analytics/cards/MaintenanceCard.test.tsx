import { describe, test, expect } from '@jest/globals';
import { maintenanceSpans, segmentTotal } from './MaintenanceCard';
import { phaseShiftPoints } from './PhaseShiftersCard';
import { temporalInputError } from '../../../views/ForgeView.features/TemporalClusterPanel';

describe('maintenance spans', () => {
  test('on-runs keep their start index', () => {
    const segs = [{ on: false, length: 3 }, { on: true, length: 2 }, { on: false, length: 4 }, { on: true, length: 1 }];
    expect(maintenanceSpans(segs)).toEqual([{ start: 3, length: 2 }, { start: 9, length: 1 }]);
    expect(segmentTotal(segs)).toBe(10);
  });
});

describe('phase shift chart', () => {
  test('bounds set the y range (max at top)', () => {
    const row = {
      name: 't', phaseShiftMinDeg: -10, phaseShiftMaxDeg: 10, meanDeg: 0, minDeg: -10, maxDeg: 5, shareAtBound: 0.5,
      series: [{ snapshot: 'a', phaseShiftDeg: -10 }, { snapshot: 'b', phaseShiftDeg: 10 }],
    };
    const { points, yOf } = phaseShiftPoints(row, 100, 50);
    expect(points).toBe('0.0,50.0 100.0,0.0');
    expect(yOf(0)).toBe(25);
  });
});

describe('temporal input', () => {
  test('validates per method', () => {
    expect(temporalInputError({ method: 'resample', offset: ' ' })).toMatch(/offset/i);
    expect(temporalInputError({ method: 'resample', offset: '3h' })).toBeNull();
    expect(temporalInputError({ method: 'downsample', stride: 1 })).toMatch(/stride/i);
    expect(temporalInputError({ method: 'segment', numSegments: 0 })).toMatch(/segments/i);
    expect(temporalInputError({ method: 'segment', numSegments: 8 })).toBeNull();
  });
});
