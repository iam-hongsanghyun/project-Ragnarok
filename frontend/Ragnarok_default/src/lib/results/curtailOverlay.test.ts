import { test, expect } from '@jest/globals';
import type { MetricOption } from 'lib/types';
import { CURTAIL_PREFIX, curtailmentFor, withCurtailment } from './curtailOverlay';

const dispatch: MetricOption = {
  key: 'dispatch', label: 'Dispatch by carrier', unit: 'MW', reducer: 'mean', allowDonut: true,
  series: [{ key: 'wind', label: 'wind', color: '#9467bd' }, { key: 'gas', label: 'gas', color: '#8c564b' }],
  rows: [
    { label: 'h0', timestamp: 't0', wind: 50, gas: 30 },
    { label: 'h1', timestamp: 't1', wind: 80, gas: 0 },
  ],
};
const curtailment: MetricOption = {
  key: 'curtailment', label: 'Curtailment by carrier', unit: 'MW', reducer: 'mean', allowDonut: true,
  series: [{ key: 'wind', label: 'wind', color: '#9467bd' }],
  rows: [{ label: 'h1', timestamp: 't1', wind: 20 }],
};

test('pairs dispatch with curtailment only when curtailment has data', () => {
  expect(curtailmentFor(dispatch, [dispatch, curtailment])).toBe(curtailment);
  expect(curtailmentFor(dispatch, [dispatch, { ...curtailment, rows: [] }])).toBeUndefined();
  expect(curtailmentFor({ ...dispatch, key: 'system_price' }, [curtailment])).toBeUndefined();
});

test('curtailment stacks after dispatch, joined by snapshot, 0 where none', () => {
  const m = withCurtailment(dispatch, curtailment);
  const key = `${CURTAIL_PREFIX}wind`;
  expect(m.series.map((s) => s.key)).toEqual(['wind', 'gas', key]);
  expect(m.rows.map((r) => r[key])).toEqual([0, 20]);
  // dispatch + curtailment = available wind in h1
  expect((m.rows[1].wind as number) + (m.rows[1][key] as number)).toBe(100);
  // lighter shade of the carrier's own colour
  expect(m.series[2].color).toBe('#9467bd66');
  expect(m.series[2].label).toBe('wind (curtailed)');
});
