import { describe, test, expect } from '@jest/globals';
import { buildStatisticsBody, splitList } from './statistics';
import { buildTemporalBody } from './temporal';

describe('statistics query body', () => {
  test('splitList tolerates commas and spaces', () => {
    expect(splitList(' carrier, bus  name ,')).toEqual(['carrier', 'bus', 'name']);
    expect(splitList('')).toEqual([]);
  });
  test('empty lists are omitted; time aggregation passes through', () => {
    expect(buildStatisticsBody({ runName: 'r', metric: 'supply', aggregateTime: false, atPort: false, groupby: [], carrier: [] }))
      .toEqual({ runName: 'r', metric: 'supply', aggregateTime: false, atPort: false });
    expect(buildStatisticsBody({ runName: 'r', metric: 'supply', aggregateTime: 'mean', atPort: true, groupby: ['carrier'], busCarrier: ['AC'], components: ['Generator'], carrier: ['wind'] }))
      .toEqual({ runName: 'r', metric: 'supply', aggregateTime: 'mean', atPort: true, groupby: ['carrier'], busCarrier: ['AC'], components: ['Generator'], carrier: ['wind'] });
  });
});

describe('temporal body', () => {
  test('carries only the chosen method parameters', () => {
    expect(buildTemporalBody({ method: 'resample', offset: '3h', stride: 4, numSegments: 9 }, 's'))
      .toEqual({ sessionId: 's', method: 'resample', offset: '3h', dropLeapDay: false });
    expect(buildTemporalBody({ method: 'downsample', offset: '3h', stride: 4 }, 's'))
      .toEqual({ sessionId: 's', method: 'downsample', stride: 4 });
    expect(buildTemporalBody({ method: 'segment', numSegments: 12, solver: 'highs' }, 's'))
      .toEqual({ sessionId: 's', method: 'segment', numSegments: 12, solver: 'highs' });
  });
});
