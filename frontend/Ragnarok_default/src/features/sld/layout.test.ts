/** SLD layout: bands by voltage, transformer between bands, composite as one symbol, deterministic coordinates. */
import { describe, expect, it } from '@jest/globals';
import type { WorkbookModel } from 'lib/types';
import { buildSldLayout, DEFAULT_OPTIONS, SLD } from './layout';

const registry = JSON.stringify({ plantId: 'ccgt1', type: 'CCGT cofire', bus: 'N220', capacityMwEl: 400 });
const model = {
  buses: [
    { name: 'N220', v_nom: 220, carrier: 'AC' },
    { name: 'N400', v_nom: 400, carrier: 'AC' },
    { name: 'N400b', v_nom: 400, carrier: 'AC' },
    { name: 'NoV', carrier: 'AC' },
    { name: 'gas', v_nom: 1, carrier: 'gas' },
    { name: 'ccgt1_fuel', carrier: 'gas', plant: 'ccgt1' },
  ],
  carriers: [{ name: 'wind', color: '#123456' }],
  generators: [
    { name: 'w1', bus: 'N400', carrier: 'wind', p_nom: 100 },
    { name: 'ccgt1_gen', bus: 'N220', carrier: 'gas', p_nom: 400, plant: 'ccgt1' },
  ],
  loads: [{ name: 'l1', bus: 'N220', p_set: 50 }],
  lines: [{ name: 'L1', bus0: 'N400', bus1: 'N400b', s_nom: 900, length: 120 }],
  transformers: [{ name: 'T1', bus0: 'N400', bus1: 'N220', s_nom: 500 }],
  links: [
    { name: 'dc', bus0: 'N400b', bus1: 'NoV', p_nom: 200 },
    { name: 'ccgt1_link', bus0: 'ccgt1_fuel', bus1: 'N220', p_nom: 400, plant: 'ccgt1' },
    { name: 'feed', bus0: 'gas', bus1: 'N220', p_nom: 10 },
  ],
  storage_units: [], stores: [],
  RAGNAROK_PLANTS: [{ name: 'ccgt1', json: registry }],
  RAGNAROK_Composites: [{ name: 'ccgt1', type: 'CCGT cofire' }],
} as unknown as WorkbookModel;

describe('buildSldLayout', () => {
  const layout = buildSldLayout(model, DEFAULT_OPTIONS);

  it('orders bands by voltage, highest first, missing voltage last, non-electric hidden by default', () => {
    expect(layout.bands.map((b) => b.label)).toEqual(['400 kV', '220 kV', 'Voltage not set']);
    const y = (n: string) => layout.buses.find((b) => b.name === n)?.y ?? NaN;
    expect(y('N400')).toBeLessThan(y('N220'));
    expect(y('N220')).toBeLessThan(y('NoV'));
    expect(layout.buses.map((b) => b.name)).not.toContain('gas');
    expect(layout.bands[1].dividerY).not.toBeNull();
  });

  it('shows non-electric buses in a bottom band labelled by carrier on request', () => {
    const l = buildSldLayout(model, { ...DEFAULT_OPTIONS, showNonElectric: true });
    expect(l.bands.map((b) => b.label)).toEqual(['400 kV', '220 kV', 'Voltage not set', 'gas']);
    expect(l.buses.map((b) => b.name)).not.toContain('ccgt1_fuel');   // composite internals never drawn
  });

  it('places a transformer symbol on a wire between the two bands', () => {
    const t = layout.edges.find((e) => e.name === 'T1');
    expect(t?.symbol).not.toBeNull();
    const hi = layout.buses.find((b) => b.name === 'N400');
    const lo = layout.buses.find((b) => b.name === 'N220');
    expect(t!.symbol!.y).toBeGreaterThan(hi!.y);
    expect(t!.symbol!.y).toBeLessThan(lo!.y);
    // orthogonal: every segment is horizontal or vertical
    t!.points.slice(1).forEach((p, i) => { const q = t!.points[i]; expect(p[0] === q[0] || p[1] === q[1]).toBe(true); });
  });

  it('draws a link with a direction arrow and a line without symbols', () => {
    expect(layout.edges.find((e) => e.name === 'dc')?.arrow).not.toBeNull();
    const line = layout.edges.find((e) => e.name === 'L1');
    expect(line?.arrow).toBeNull();
    expect(line?.symbol).toBeNull();
  });

  it('collapses a composite to ONE symbol on its electricity bus and drops its internal rows', () => {
    const n220 = layout.buses.find((b) => b.name === 'N220')!;
    const comps = n220.top.filter((i) => i.kind === 'composite');
    expect(comps).toHaveLength(1);
    expect(comps[0]).toMatchObject({ sheet: 'RAGNAROK_Composites', name: 'ccgt1', label: 'CCGT cofire' });
    expect(n220.top.some((i) => i.kind === 'generator')).toBe(false);          // ccgt1_gen is inside the composite
    expect(layout.edges.some((e) => e.name === 'ccgt1_link')).toBe(false);
    expect(n220.loads.map((l) => l.name)).toEqual(['l1']);
  });

  it('uses the carrier colour for generators', () => {
    const w = layout.buses.find((b) => b.name === 'N400')!.top[0];
    expect(w).toMatchObject({ kind: 'generator', name: 'w1', color: '#123456' });
  });

  it('is deterministic', () => {
    expect(JSON.stringify(buildSldLayout(model, DEFAULT_OPTIONS))).toBe(JSON.stringify(layout));
  });

  it('folds many generators into a +N chip', () => {
    const many = { ...model, generators: Array.from({ length: 9 }, (_, i) => ({ name: `g${i}`, bus: 'N400', carrier: 'wind', p_nom: 1 })) } as unknown as WorkbookModel;
    const top = buildSldLayout(many, DEFAULT_OPTIONS).buses.find((b) => b.name === 'N400')!.top;
    expect(top).toHaveLength(SLD.maxTopItems);
    expect(top[top.length - 1]).toMatchObject({ kind: 'more', label: '+6' });
  });

  it('refuses to lay out beyond the bus limit unless asked, and filters by voltage', () => {
    const big = { buses: Array.from({ length: SLD.maxBuses + 5 }, (_, i) => ({ name: `b${i}`, v_nom: i % 2 ? 110 : 220, carrier: 'AC' })) } as unknown as WorkbookModel;
    expect(buildSldLayout(big, DEFAULT_OPTIONS)).toMatchObject({ tooLarge: true, busCount: SLD.maxBuses + 5, buses: [] });
    expect(buildSldLayout(big, { ...DEFAULT_OPTIONS, voltageFilter: 110 }).tooLarge).toBe(false);
    expect(buildSldLayout(big, { ...DEFAULT_OPTIONS, drawLarge: true }).buses).toHaveLength(SLD.maxBuses + 5);
  });

  it('keeps wires of one gap on distinct channels', () => {
    const m = { buses: [{ name: 'a', v_nom: 110 }, { name: 'b', v_nom: 110 }, { name: 'c', v_nom: 110 }],
      lines: [{ name: 'l1', bus0: 'a', bus1: 'b' }, { name: 'l2', bus0: 'a', bus1: 'c' }, { name: 'l3', bus0: 'b', bus1: 'c' }] } as unknown as WorkbookModel;
    const l = buildSldLayout(m, DEFAULT_OPTIONS);
    const channels = l.edges.map((e) => e.points[1][1]);
    expect(new Set(channels).size).toBe(3);
  });
});
