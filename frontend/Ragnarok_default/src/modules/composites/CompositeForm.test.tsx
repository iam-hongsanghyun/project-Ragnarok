/**
 * CompositeForm with a mocked backend: the types load, Connections come first and are populated from the model, a chosen port
 * reaches the preview request, the preview says what will be created and draws the schematic, and Add hands the change set to onApply.
 */
import React from 'react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals';
import type { WorkbookModel } from 'lib/types';
import type { PlantChange } from 'lib/build/plants';
import { fetchPlantTypes, previewPlant, type PlantField, type PlantType } from 'lib/api/plants';
import { CompositeForm, specFromValues } from './CompositeForm';
import { button, click, mount, settle, type Mounted } from '../../shared/testing/dom';

jest.mock('lib/api/plants');
jest.mock('lib/api/p2x');
const mockTypes = jest.mocked(fetchPlantTypes);
const mockPreview = jest.mocked(previewPlant);

const fields: PlantField[] = [
  { key: 'plantId', label: 'Plant name', kind: 'text', default: '', advanced: false },
  { key: 'bus', label: 'Electricity bus (power out)', kind: 'bus', default: null, advanced: false, port: 'electricity', blank: 'first electricity bus', help: 'Where power is delivered.' },
  { key: 'gasBus', label: 'Gas bus (fuel in)', kind: 'bus', default: null, advanced: false, port: 'gas', blank: 'create one with a supplier', help: 'Where gas comes from.' },
  { key: 'designatedGenerators', label: 'Matched generators', kind: 'generators', default: [], advanced: false, port: 'generators', blank: 'none' },
  { key: 'extendable', label: 'Let the solver size it', kind: 'bool', default: false, advanced: false },
  { key: 'pNom', label: 'Capacity', kind: 'number', default: 200, advanced: false, unit: 'MW' },
  { key: 'gasPrice', label: 'Gas price', kind: 'number', default: null, advanced: true },
  { key: 'params', label: 'Parameter overrides', kind: 'json', default: {}, advanced: true },
];

describe('specFromValues', () => {
  it('omits blanks (the backend default applies), parses numbers and JSON, keeps booleans and chosen generators', () => {
    const { spec, error } = specFromValues(fields, { plantId: '', bus: 'grid', gasBus: '', designatedGenerators: ['solar'], extendable: false, pNom: '400', gasPrice: '', params: '{"ccgt.min_load": 0.35}' });
    expect(error).toBeNull();
    expect(spec).toEqual({ bus: 'grid', designatedGenerators: ['solar'], extendable: false, pNom: 400, params: { 'ccgt.min_load': 0.35 } });
  });
  it('reports a non-numeric number and invalid JSON instead of sending them', () => {
    expect(specFromValues(fields, { pNom: 'abc' }).error).toMatch(/Capacity must be a number/);
    expect(specFromValues(fields, { pNom: '1', params: '{oops' }).error).toMatch(/not valid JSON/);
  });
  it('an empty JSON object and an empty generator list are no override', () => {
    expect(specFromValues(fields, { pNom: '1', params: '{}', designatedGenerators: [] }).spec).toEqual({ extendable: false, pNom: 1 });
  });
});

const types: PlantType[] = [{ id: 'ccgt', label: 'CCGT (gas turbine)', description: 'Combined-cycle gas plant.', technology: 'technology-data', defaults: {}, fields }];
const change = { remove: {}, release: [], kept: { buses: [], carriers: [] }, fragment: { sheets: { links: [{ name: 'ccgt', bus0: 'ng', bus1: 'KR-1', efficiency: 0.58 }] } } } as unknown as PlantChange;
const model = { buses: [{ name: 'KR-1', carrier: 'AC' }, { name: 'ng', carrier: 'gas' }], generators: [{ name: 'solar', carrier: 'solar', bus: 'KR-1' }] } as unknown as WorkbookModel;

let mounted: Mounted | null = null;
beforeEach(() => { jest.useFakeTimers(); });
afterEach(async () => { await mounted?.unmount(); mounted = null; jest.useRealTimers(); jest.resetAllMocks(); });

describe('CompositeForm', () => {
  it('shows Connections first, previews with the chosen ports, draws the schematic and applies', async () => {
    mockTypes.mockResolvedValue(types);
    mockPreview.mockResolvedValue({ plantId: 'ccgt', type: 'ccgt', label: 'CCGT ccgt', summary: [], warnings: ['Check the gas price.'], rowCounts: { links: 1, RAGNAROK_PLANTS: 1 }, spec: {}, change } as never);
    const onApply = jest.fn<void, [PlantChange, string]>();
    mounted = await mount(<CompositeForm model={model} onApply={onApply} />);
    await settle();
    await act(async () => { jest.advanceTimersByTime(300); });
    await settle();
    const root = mounted.container;
    const text = root.textContent ?? '';
    expect(text.indexOf('Connections')).toBeGreaterThan(-1);
    expect(text.indexOf('Connections')).toBeLessThan(text.indexOf('Size and parameters'));
    expect(text).toContain('Where gas comes from.');
    expect(text).toContain('(create one with a supplier)');
    const gas = root.querySelector('#cmp-gasBus') as HTMLSelectElement;
    expect(Array.from(gas.options).map((o) => o.value)).toEqual(['', 'ng']);               // only gas buses for the gas port
    expect(Array.from((root.querySelector('#cmp-bus') as HTMLSelectElement).options).map((o) => o.value)).toEqual(['', 'KR-1']);
    expect(text).toContain('Show other generators (1');                              // solar has no zero-emission carrier row here: listed under other
    expect(text).toContain('Creates: 1 links.');
    expect(text).toContain('electricity out to bus');
    expect(text).toContain('gas in from bus');
    expect(root.querySelector('[data-testid="connection-schematic"] svg')).not.toBeNull();
    expect(text).toContain('Check the gas price.');
    await click(button(root, 'Add CCGT'));
    expect(onApply).toHaveBeenCalledWith(change, 'Added CCGT ccgt');
  });

  it('says so when the types cannot be loaded', async () => {
    mockTypes.mockRejectedValue(new Error('backend down'));
    mounted = await mount(<CompositeForm model={model} onApply={jest.fn()} />);
    await settle();
    expect(mounted.container.textContent).toContain('backend down');
  });
});
