/**
 * HacOptions: feature columns are the numeric bus columns; metric and linkage are chosen; ward needs euclidean.
 */
import React from 'react';
import { afterEach, describe, expect, it, jest } from '@jest/globals';
import { DEFAULT_HAC, HacOptions, numericBusColumns, type HacOptionsValue } from './HacOptions';
import { mount, setValue, type Mounted } from '../../shared/testing/dom';

let mounted: Mounted | null = null;
afterEach(async () => { await mounted?.unmount(); mounted = null; });

const buses = [
  { name: 'a', x: 1, y: 2, v_nom: 110, province: 'north' },
  { name: 'b', x: 3, y: 4, v_nom: '220', province: 'south' },
];

describe('HacOptions', () => {
  it('offers only columns that are numeric on every bus', () => {
    expect(numericBusColumns(buses)).toEqual(['v_nom', 'x', 'y']);
    expect(numericBusColumns([...buses, { name: 'c', x: 5, y: '', v_nom: 66 }])).toEqual(['v_nom', 'x']);
    expect(numericBusColumns([])).toEqual([]);
  });

  it('changes linkage and metric and flags ward with a non-euclidean metric', async () => {
    const onChange = jest.fn<void, [HacOptionsValue]>();
    mounted = await mount(<HacOptions busRows={buses} value={DEFAULT_HAC} onChange={onChange} />);
    await setValue(mounted.container.querySelector('#forge-hac-linkage'), 'average');
    expect(onChange).toHaveBeenLastCalledWith({ features: ['x', 'y'], affinity: 'euclidean', linkage: 'average' });
    expect(mounted.container.querySelector('[role="alert"]')).toBeNull();
    await mounted.unmount();
    mounted = await mount(<HacOptions busRows={buses} value={{ ...DEFAULT_HAC, affinity: 'cosine' }} onChange={onChange} />);
    expect(mounted.container.querySelector('[role="alert"]')?.textContent).toContain('Ward linkage requires the euclidean (or l2) metric');
  });
});
