import { describe, it, expect } from '@jest/globals';
import {
  CONVERSION_TEMPLATES,
  buildConversionFragment,
  defaultAnchorBus,
  type ConversionTemplate,
} from './conversions';
import type { WorkbookModel } from 'lib/types';

const tpl = (id: string): ConversionTemplate => {
  const t = CONVERSION_TEMPLATES.find((x) => x.id === id);
  if (!t) throw new Error(`no template ${id}`);
  return t;
};

const baseModel = (): WorkbookModel =>
  ({
    buses: [{ name: 'elec', carrier: 'AC', x: 10, y: 20 }],
    carriers: [{ name: 'AC' }],
    generators: [],
    links: [],
  } as unknown as WorkbookModel);

describe('defaultAnchorBus', () => {
  it('prefers an electricity-carrier bus', () => {
    const model = {
      buses: [{ name: 'h2bus', carrier: 'hydrogen' }, { name: 'grid', carrier: 'AC' }],
    } as unknown as WorkbookModel;
    expect(defaultAnchorBus(model)).toBe('grid');
  });
  it('returns null with no buses', () => {
    expect(defaultAnchorBus({ buses: [] } as unknown as WorkbookModel)).toBeNull();
  });
});

describe('buildConversionFragment — electricity→hydrogen (electrolyser)', () => {
  it('creates the hydrogen bus + carriers + link, no fuel supply', () => {
    const frag = buildConversionFragment(tpl('electrolyser'), { anchorBus: 'elec', pNom: 100, extendable: false }, baseModel());
    // A new hydrogen bus at the anchor's coordinates.
    expect(frag.sheets.buses).toHaveLength(1);
    expect(frag.sheets.buses[0]).toMatchObject({ name: 'H2', carrier: 'hydrogen', x: 10, y: 20 });
    // Carriers: the link tech + the hydrogen vector (electricity comes from AC → not re-added).
    const carrierNames = frag.sheets.carriers.map((c) => c.name);
    expect(carrierNames).toEqual(expect.arrayContaining(['electrolysis', 'hydrogen']));
    expect(carrierNames).not.toContain('AC');
    // The link: power in (anchor) → hydrogen out.
    expect(frag.sheets.links[0]).toMatchObject({
      bus0: 'elec', bus1: 'H2', carrier: 'electrolysis', efficiency: 0.7, p_nom: 100,
    });
    // Electricity input → no fuel-supply generator.
    expect(frag.sheets.generators).toBeUndefined();
  });
});

describe('buildConversionFragment — gas→electricity (CCGT)', () => {
  it('creates a gas bus + gas carrier with co2 + a fuel-supply generator', () => {
    const frag = buildConversionFragment(tpl('ccgt'), { anchorBus: 'elec', pNom: 250, extendable: false }, baseModel());
    expect(frag.sheets.buses[0]).toMatchObject({ name: 'gas', carrier: 'gas' });
    const gas = frag.sheets.carriers.find((c) => c.name === 'gas');
    expect(gas).toMatchObject({ name: 'gas', co2_emissions: 0.2 });
    // Fuel supply: extendable, zero capex, fuel cost as marginal.
    expect(frag.sheets.generators).toHaveLength(1);
    expect(frag.sheets.generators[0]).toMatchObject({
      bus: 'gas', carrier: 'gas', p_nom_extendable: true, capital_cost: 0, marginal_cost: 25,
    });
    // Link: gas in → power out (anchor).
    expect(frag.sheets.links[0]).toMatchObject({ bus0: 'gas', bus1: 'elec', carrier: 'CCGT', efficiency: 0.55, p_nom: 250 });
  });
});

describe('buildConversionFragment — CHP has a heat co-product (bus2)', () => {
  it('emits bus2/efficiency2 and a heat bus', () => {
    const frag = buildConversionFragment(tpl('chp'), { anchorBus: 'elec', pNom: 100, extendable: false }, baseModel());
    const link = frag.sheets.links[0];
    expect(link.bus0).toBe('gas');
    expect(link.bus1).toBe('elec');
    expect(link.bus2).toBe('heat');
    expect(link.efficiency2).toBe(0.45);
    expect(frag.sheets.buses.map((b) => b.name)).toEqual(expect.arrayContaining(['gas', 'heat']));
  });
});

describe('buildConversionFragment — reuses an existing carrier bus', () => {
  it('a second electrolyser attaches to the existing hydrogen bus (no new bus)', () => {
    const model = {
      buses: [
        { name: 'elec', carrier: 'AC', x: 10, y: 20 },
        { name: 'H2', carrier: 'hydrogen' },
      ],
      carriers: [{ name: 'AC' }, { name: 'hydrogen' }, { name: 'electrolysis' }],
      generators: [],
      links: [{ name: 'electrolyser' }],
    } as unknown as WorkbookModel;
    const frag = buildConversionFragment(tpl('electrolyser'), { anchorBus: 'elec', pNom: 50, extendable: false }, model);
    expect(frag.sheets.buses).toBeUndefined(); // reused existing H2
    expect(frag.sheets.carriers).toBeUndefined(); // both already present
    expect(frag.sheets.links[0].bus1).toBe('H2');
    expect(frag.sheets.links[0].name).toBe('electrolyser_2'); // name de-collided
  });
});

describe('buildConversionFragment — extendable', () => {
  it('sets p_nom_extendable + capital_cost and omits fixed p_nom', () => {
    const frag = buildConversionFragment(tpl('heat_pump'), { anchorBus: 'elec', pNom: 100, extendable: true }, baseModel());
    const link = frag.sheets.links[0];
    expect(link.p_nom_extendable).toBe(true);
    expect(link.capital_cost).toBe(60000);
    expect(link.p_nom).toBeUndefined();
    expect(link.efficiency).toBe(3.0); // COP > 1
  });

  it('throws on an unknown anchor bus', () => {
    expect(() => buildConversionFragment(tpl('electrolyser'), { anchorBus: 'nope', pNom: 1, extendable: false }, baseModel())).toThrow();
  });
});
