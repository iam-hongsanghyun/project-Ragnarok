import { describe, it, expect } from '@jest/globals';
import { placeAbstractBuses } from './abstractPlacement';
import { getBusIndex } from 'lib/utils/helpers';
import type { WorkbookModel } from 'lib/types';

const el = { name: 'el_bus', x: 127.0, y: 37.0 };

describe('placeAbstractBuses', () => {
  it('places a linked abstract bus at an offset from its anchor', () => {
    const { placed, abstract } = placeAbstractBuses(
      [el, { name: 'h2_bus', carrier: 'H2' }],
      [{ name: 'electrolyser', bus0: 'el_bus', bus1: 'h2_bus' }],
    );
    expect(abstract).toEqual(['h2_bus']);
    expect(placed.h2_bus.x).toBeCloseTo(127.15, 6);
    expect(placed.h2_bus.y).toBeCloseTo(37.15, 6);
  });

  it('stacks several abstract buses on one anchor without overlap', () => {
    const { placed } = placeAbstractBuses(
      [el, { name: 'h2' }, { name: 'co2' }],
      [
        { name: 'l1', bus0: 'el_bus', bus1: 'h2' },
        { name: 'l2', bus0: 'co2', bus1: 'el_bus' },  // reversed direction too
      ],
    );
    expect(placed.h2).toBeDefined();
    expect(placed.co2).toBeDefined();
    expect(placed.h2.x).not.toBeCloseTo(placed.co2.x, 6);  // fanned out
  });

  it('resolves chains: abstract anchored to an abstract anchored to a real bus', () => {
    const { placed } = placeAbstractBuses(
      [el, { name: 'h2' }, { name: 'ch4' }],
      [
        { name: 'l1', bus0: 'el_bus', bus1: 'h2' },
        { name: 'l2', bus0: 'h2', bus1: 'ch4' },      // methanation chain
      ],
    );
    expect(placed.ch4).toBeDefined();
    expect(placed.ch4.x).toBeGreaterThan(placed.h2.x);  // offset from h2
  });

  it('parks unlinked abstract buses in a column east of the bounding box', () => {
    const { placed } = placeAbstractBuses(
      [el, { name: 'lonely1' }, { name: 'lonely2' }],
      [],
    );
    expect(placed.lonely1.x).toBeCloseTo(127.6, 6);      // maxX + 0.6
    expect(placed.lonely2.x).toBeCloseTo(127.6, 6);
    expect(placed.lonely1.y).toBeGreaterThan(placed.lonely2.y);  // column steps down
  });

  it('no coordinate-less buses → nothing placed', () => {
    const { placed, abstract } = placeAbstractBuses([el], []);
    expect(placed).toEqual({});
    expect(abstract).toEqual([]);
  });
});

describe('getBusIndex with abstract buses', () => {
  it('fills synthetic coords on a copy and marks __abstract; model rows untouched', () => {
    const h2 = { name: 'h2_bus', carrier: 'H2' };
    const model = {
      buses: [el, h2],
      links: [{ name: 'elz', bus0: 'el_bus', bus1: 'h2_bus' }],
    } as unknown as WorkbookModel;
    const index = getBusIndex(model);
    expect(index.el_bus).toBe(model.buses[0]);            // positioned: same reference
    expect(index.h2_bus).not.toBe(h2);                    // abstract: a copy
    expect(Number(index.h2_bus.x)).toBeCloseTo(127.15, 6);
    expect(index.h2_bus.__abstract).toBe(true);
    expect(h2).not.toHaveProperty('x');                   // original row untouched
  });
});
