import { describe, expect, it } from '@jest/globals';
import type { WorkbookModel } from 'lib/types';
import { connectionsOf, fragmentComponentRows, matchedGenerators, plantComponentRows, portPhrase } from './connections';

const buses = [{ name: 'KR-1', carrier: 'AC' }, { name: 'ng', carrier: 'gas' }, { name: 'hyd', carrier: 'H2' }];

describe('connectionsOf', () => {
  it('a CCGT takes gas from the chosen bus and delivers electricity to the chosen bus', () => {
    const rows = [{ sheet: 'links', name: 'c', row: { name: 'c', bus0: 'ng', bus1: 'KR-1', efficiency: 0.58 } }];
    const c = connectionsOf(rows, buses);
    expect(c.ports.map((p) => `${portPhrase(p)} ${p.bus}`)).toEqual(['electricity out to bus KR-1', 'gas in from bus ng']);
    expect(c.internalBuses).toEqual([]);
    expect(c.edges.map((e) => [e.column, e.direction])).toEqual([['bus0', 'in'], ['bus1', 'out']]);
  });

  it('a created fuel bus between feeders and turbine is internal, a created gas bus is a created port', () => {
    const rows = [
      { sheet: 'buses', name: 'p_fuel', row: { name: 'p_fuel', carrier: 'fuel' } },
      { sheet: 'buses', name: 'p_gas', row: { name: 'p_gas', carrier: 'gas' } },
      { sheet: 'links', name: 'p_gas_feed', row: { bus0: 'p_gas', bus1: 'p_fuel', efficiency: 1 } },
      { sheet: 'links', name: 'p_h2_feed', row: { bus0: 'hyd', bus1: 'p_fuel', efficiency: 1 } },
      { sheet: 'links', name: 'p', row: { bus0: 'p_fuel', bus1: 'KR-1', efficiency: 0.58 } },
    ];
    const c = connectionsOf(rows, buses);
    expect(c.internalBuses).toEqual(['p_fuel']);
    expect(c.ports.map((p) => [p.bus, p.direction, p.created])).toEqual([['KR-1', 'out', false], ['hyd', 'in', false], ['p_gas', 'in', true]]);
  });

  it('a created product bus with a load is an output with its offtake; a negative efficiency_2 draws electricity', () => {
    const rows = [
      { sheet: 'buses', name: 'h', row: { name: 'h', carrier: 'H2' } },
      { sheet: 'links', name: 'ely', row: { bus0: 'KR-1', bus1: 'h', efficiency: 0.62 } },
      { sheet: 'loads', name: 'ld', row: { bus: 'h', p_set: 30 } },
      { sheet: 'links', name: 'comp', row: { bus0: 'h', bus1: 'h', bus2: 'KR-1', efficiency2: -0.05 } },
    ];
    const c = connectionsOf(rows, buses);
    const h = c.ports.find((p) => p.bus === 'h');
    expect(h).toMatchObject({ direction: 'out', created: true, loadMw: 30, label: 'H2 out' });
    expect(c.ports.find((p) => p.bus === 'KR-1')?.direction).toBe('in');
  });

  it('a storage unit connects both ways and a generator delivers', () => {
    const c = connectionsOf([{ sheet: 'storage_units', name: 'b', row: { bus: 'KR-1' } }, { sheet: 'generators', name: 'g', row: { bus: 'KR-1' } }], buses);
    expect(c.ports[0]).toMatchObject({ bus: 'KR-1', direction: 'both', label: 'electricity in/out' });
  });
});

describe('row sources', () => {
  it('reads the plant rows of a model and of a fragment, skipping series and registry sheets', () => {
    const model = { generators: [{ name: 'a', bus: 'KR-1', plant: 'x' }, { name: 'b', bus: 'KR-1' }], RAGNAROK_PLANTS: [{ name: 'x', plant: 'x', json: '{}' }] } as unknown as WorkbookModel;
    expect(plantComponentRows(model, 'x').map((r) => r.name)).toEqual(['a']);
    expect(fragmentComponentRows({ sheets: { links: [{ name: 'l' }], 'loads-p_set': [{ snapshot: 's' }], RAGNAROK_PLANTS: [{ name: 'x' }] } }).map((r) => r.name)).toEqual(['l']);
  });

  it('finds the matched generators in the spec, then in the chain registry', () => {
    const model = { RAGNAROK_P2X: [{ name: 'p2x', json: JSON.stringify({ designatedGenerators: ['solar'] }) }] } as unknown as WorkbookModel;
    expect(matchedGenerators(model, 'p2x', { designatedGenerators: ['wind'] })).toEqual(['wind']);
    expect(matchedGenerators(model, 'p2x', { chain: { designatedGenerators: ['wind2'] } })).toEqual(['wind2']);
    expect(matchedGenerators(model, 'p2x', null)).toEqual(['solar']);
  });
});
