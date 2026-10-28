import { describe, expect, it } from '@jest/globals';
import type { GridRow, WorkbookModel } from 'lib/types';
import { applyPlantChange, inPlant, plantCards, plantMarkers, PLANT_SHEET } from './plants';

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
