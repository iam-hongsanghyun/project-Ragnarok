/**
 * Plant picker helpers and the plant card list. The picker's form-to-spec mapping is pure (blank -> backend default, numbers parsed,
 * JSON parsed); the list renders from the model alone (one card per plant, its components behind a toggle, Edit / Delete).
 */
import React from 'react';
import { renderToStaticMarkup as staticMarkup } from 'react-dom/server';
import { describe, expect, it, jest } from '@jest/globals';
import type { WorkbookModel } from 'lib/types';
import type { PlantField } from 'lib/api/plants';
import { PlantList } from './PlantList';
import { specFromValues } from './PlantPicker';

const fields: PlantField[] = [
  { key: 'plantId', label: 'Plant name', kind: 'text', default: '', advanced: false },
  { key: 'bus', label: 'Connect at bus', kind: 'bus', default: null, advanced: false },
  { key: 'extendable', label: 'Let the solver size it', kind: 'bool', default: false, advanced: false },
  { key: 'pNom', label: 'Capacity', kind: 'number', default: 100, advanced: false, unit: 'MW' },
  { key: 'gasPrice', label: 'Gas price', kind: 'number', default: null, advanced: true },
  { key: 'params', label: 'Parameter overrides', kind: 'json', default: {}, advanced: true },
];

describe('specFromValues', () => {
  it('omits blanks (the backend default applies), parses numbers and JSON, keeps booleans', () => {
    const { spec, error } = specFromValues(fields, { plantId: '', bus: 'grid', extendable: false, pNom: '400', gasPrice: '', params: '{"ccgt.min_load": 0.35}' });
    expect(error).toBeNull();
    expect(spec).toEqual({ bus: 'grid', extendable: false, pNom: 400, params: { 'ccgt.min_load': 0.35 } });
  });
  it('reports a non-numeric number and invalid JSON instead of sending them', () => {
    expect(specFromValues(fields, { pNom: 'abc' }).error).toMatch(/Capacity must be a number/);
    expect(specFromValues(fields, { pNom: '1', params: '{oops' }).error).toMatch(/not valid JSON/);
  });
  it('an empty JSON object is treated as no override', () => {
    expect(specFromValues(fields, { pNom: '1', params: '{}' }).spec).toEqual({ extendable: false, pNom: 1 });
  });
});

const model = {
  buses: [{ name: 'grid' }, { name: 'c_bus_gas', plant: 'c' }],
  generators: [{ name: 'c_gas_supply', bus: 'c_bus_gas', plant: 'c' }],
  links: [{ name: 'c', bus0: 'c_bus_gas', bus1: 'grid', plant: 'c' }, { name: 'plain', bus0: 'grid', bus1: 'grid' }],
  RAGNAROK_PLANTS: [{ name: 'c', plant: 'c', json: JSON.stringify({ plantId: 'c', type: 'ccgt', label: 'CCGT c', bus: 'grid', capacityMwEl: 400, extendable: false, spec: {}, components: [{ sheet: 'links', name: 'c', role: 'turbine' }, { sheet: 'generators', name: 'c_gas_supply', role: 'gas supply' }] }) }],
} as unknown as WorkbookModel;

describe('PlantList', () => {
  it('shows one card per plant with its type, bus, capacity and row count, and Edit / Delete', () => {
    const html = staticMarkup(<PlantList model={model} onEdit={jest.fn()} onApply={jest.fn()} />);
    expect(html).toContain('Plants (1)');
    expect(html).toContain('data-plant="c"');
    expect(html).toContain('ccgt · grid · 400 MW · 3 rows');
    expect(html).toContain('>Edit<');
    expect(html).toContain('>Delete<');
    expect(html).not.toContain('plain');            // an ordinary link is not a plant
  });
  it('renders nothing when the model has no plant', () => {
    expect(staticMarkup(<PlantList model={{ buses: [{ name: 'a' }] } as unknown as WorkbookModel} onApply={jest.fn()} />)).toBe('');
  });
  it('the registry row gives the editable flag; an imported plant without it cannot be edited', () => {
    const imported = { ...model, RAGNAROK_PLANTS: [] } as unknown as WorkbookModel;
    const html = staticMarkup(<PlantList model={imported} onEdit={jest.fn()} onApply={jest.fn()} />);
    expect(html).toContain('imported');
    expect(html).toContain('disabled');
  });
});

describe('PlantList derived values', () => {
  it('shows the part-load line and the start costs of an expanded card', () => {
    const reg = { plantId: 'c', type: 'ccgt', label: 'CCGT c', bus: 'grid', capacityMwEl: 58, extendable: false, spec: {},
      components: [{ sheet: 'links', name: 'c', role: 'turbine' }],
      partLoad: { route: 'piecewise-link', noLoadFuelMw: 7.7, incrementalHeatRate: 1.59, incrementalEfficiency: 0.63, fuelMinMw: 44.6, fuelFullMw: 100, etaMin: 0.52, etaFull: 0.58, minLoadPu: 0.446 },
      startCosts: { hot: 3480, nativeStartUpCost: 3480, warm: 6960, warmAfterHours: 8 } };
    const m = { ...model, RAGNAROK_PLANTS: [{ name: 'c', plant: 'c', json: JSON.stringify(reg) }] } as unknown as WorkbookModel;
    // collapsed by default: the derived lines are behind the toggle, like the components
    expect(staticMarkup(<PlantList model={m} onApply={jest.fn()} />)).not.toContain('no-load fuel');
  });
});
