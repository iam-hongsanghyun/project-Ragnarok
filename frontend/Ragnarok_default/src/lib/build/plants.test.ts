import { describe, expect, it } from '@jest/globals';
import type { GridRow, WorkbookModel } from 'lib/types';
import { applyPlantChange, derivedLines, inPlant, plantCards, plantMarkers, PLANT_SHEET } from './plants';

const reg = (id: string, extra: Record<string, unknown> = {}): GridRow => ({
  name: id, plant: id, json: JSON.stringify({ plantId: id, type: 'ccgt', label: `CCGT ${id}`, bus: 'grid', capacityMwEl: 400, extendable: false, spec: { pNom: 400 }, components: [{ sheet: 'links', name: id, role: 'turbine' }, { sheet: 'generators', name: `${id}_gas_supply`, role: 'gas supply' }], ...extra }),
});

const model = (): WorkbookModel => ({
  buses: [{ name: 'grid', x: 10, y: 50 }, { name: 'c_bus_gas', carrier: 'gas', plant: 'c' }],
  generators: [{ name: 'c_gas_supply', bus: 'c_bus_gas', plant: 'c' }, { name: 'other', bus: 'grid' }],
  links: [{ name: 'c', bus0: 'c_bus_gas', bus1: 'grid', plant: 'c' }],
  carriers: [{ name: 'gas', plant: 'c' }],
  [PLANT_SHEET]: [reg('c')],
  'generators-p_max_pu': [{ snapshot: 't0', other: 1 }],
} as unknown as WorkbookModel);

describe('plantCards', () => {
  it('groups tagged rows by plant id and reads type, bus and capacity from the registry', () => {
    const cards = plantCards(model());
    expect(cards).toHaveLength(1);
    expect(cards[0]).toMatchObject({ plantId: 'c', type: 'ccgt', bus: 'grid', capacityMwEl: 400, editable: true, rowCount: 4 });
    expect(cards[0].components.map((c) => `${c.sheet}:${c.name}`)).toEqual(['links:c', 'generators:c_gas_supply']);
    expect(cards[0].components.every((c) => c.present)).toBe(true);
  });
  it('lists a plant imported without a registry row from its column, not editable', () => {
    const m = model();
    m[PLANT_SHEET] = [];
    const [card] = plantCards(m);
    expect(card).toMatchObject({ plantId: 'c', type: null, editable: false, rowCount: 4 });
    expect(card.components.map((c) => c.name).sort()).toEqual(['c', 'c_bus_gas', 'c_gas_supply', 'gas']);
  });
});

describe('applyPlantChange', () => {
  it('removes the plant rows and releases a shared row, leaving every other row alone', () => {
    const out = applyPlantChange(model(), {
      remove: { links: ['c'], generators: ['c_gas_supply'], [PLANT_SHEET]: ['c'], carriers: [] },
      release: [{ sheet: 'buses', name: 'c_bus_gas' }, { sheet: 'carriers', name: 'gas' }],
    });
    expect(out.links).toEqual([]);
    expect(out.generators.map((g) => g.name)).toEqual(['other']);
    expect(out.buses.find((b) => b.name === 'c_bus_gas')).toEqual({ name: 'c_bus_gas', carrier: 'gas' });   // kept, plant id cleared
    expect(out.carriers).toEqual([{ name: 'gas' }]);
    expect(out[PLANT_SHEET]).toEqual([]);
    expect(out.buses.some(inPlant)).toBe(false);
    expect(out['generators-p_max_pu']).toHaveLength(1);
  });
});

describe('plantMarkers', () => {
  it('draws one marker per plant at its bus, however many components it has', () => {
    const idx = { grid: { name: 'grid', x: 10, y: 50 } } as Record<string, GridRow>;
    const markers = plantMarkers(model(), idx);
    expect(markers).toHaveLength(1);
    expect(markers[0]).toMatchObject({ plantId: 'c', componentCount: 4 });
    expect(markers[0].coords[0]).toBeGreaterThan(50);
  });
  it('draws none when the bus has no coordinates', () => {
    expect(plantMarkers(model(), { grid: { name: 'grid' } } as Record<string, GridRow>)).toEqual([]);
  });
});

describe('derivedLines', () => {
  const partLoad = { route: 'piecewise-link', noLoadFuelMw: 7.692308, incrementalHeatRate: 1.591512, incrementalEfficiency: 0.628333, fuelMinMw: 44.615385, fuelFullMw: 100, etaMin: 0.52, etaFull: 0.58, minLoadPu: 0.446154 };
  it('is empty for a plant that uses neither option', () => {
    expect(derivedLines(null)).toEqual([]);
    expect(derivedLines({})).toEqual([]);
  });
  it('states the heat-rate line, the way it is written and the start costs, with units', () => {
    const lines = derivedLines({ partLoad, startCosts: { hot: 3480, nativeStartUpCost: 3480, warm: 6960, warmAfterHours: 8, cold: 11600, coldAfterHours: 48 } });
    expect(lines[0]).toContain('no-load fuel 7.6923 MW_th');
    expect(lines[0]).toContain('MW_th/MW_el');
    expect(lines[1]).toContain('piecewise efficiency curve');
    expect(lines[1]).toContain('p_min_pu = 0.446154');
    expect(lines[2]).toContain('hot 3,480');
    expect(lines[2]).toContain('warm 6,960 after 8 h offline');
    expect(lines[2]).toContain('cold 11,600 after 48 h offline');
  });
  it('the generator route names stand_by_cost and marginal_cost', () => {
    const lines = derivedLines({ partLoad: { ...partLoad, route: 'stand-by-generator', written: { stand_by_cost: 230.8, marginal_cost: 47.7 } } });
    expect(lines[1]).toContain('stand_by_cost = 230.8 per hour committed');
    expect(lines[1]).toContain('marginal_cost = 47.7 per MWh_el');
  });
  it('plantCards carries the registry values to the card', () => {
    const m = model();
    m[PLANT_SHEET] = [reg('c', { partLoad })];
    expect(plantCards(m)[0].derived?.partLoad?.noLoadFuelMw).toBe(7.692308);
  });
});
