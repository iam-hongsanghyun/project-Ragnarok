/**
 * CompositeTable: one row per composite with its connections spelled out from the PyPSA rows, the rows behind a Show / Hide
 * toggle, and Delete previewing what the backend would remove before anything is applied.
 */
import React from 'react';
import { renderToStaticMarkup as staticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, jest } from '@jest/globals';
import type { WorkbookModel } from 'lib/types';
import type { PlantChange } from 'lib/build/plants';
import { previewPlantDelete } from 'lib/api/plants';
import { CompositeTable } from './CompositeTable';
import { button, click, mount, type Mounted } from '../../shared/testing/dom';

jest.mock('lib/api/plants');
const mockDelete = jest.mocked(previewPlantDelete);

const reg = { plantId: 'c', type: 'ccgt', label: 'CCGT c', bus: 'KR-1', capacityMwEl: 400, extendable: false, spec: {},
  components: [{ sheet: 'links', name: 'c', role: 'turbine' }, { sheet: 'generators', name: 'c_gas_supply', role: 'gas supply' }] };
const model = {
  buses: [{ name: 'KR-1', carrier: 'AC' }, { name: 'c_bus_gas', carrier: 'gas', plant: 'c' }],
  generators: [{ name: 'c_gas_supply', bus: 'c_bus_gas', plant: 'c' }],
  links: [{ name: 'c', bus0: 'c_bus_gas', bus1: 'KR-1', efficiency: 0.58, plant: 'c' }, { name: 'plain', bus0: 'KR-1', bus1: 'KR-1' }],
  RAGNAROK_PLANTS: [{ name: 'c', plant: 'c', json: JSON.stringify(reg) }],
} as unknown as WorkbookModel;

let mounted: Mounted | null = null;
afterEach(async () => { await mounted?.unmount(); mounted = null; jest.resetAllMocks(); });

describe('CompositeTable', () => {
  it('lists the composite with type, capacity and its connections', () => {
    const html = staticMarkup(<CompositeTable model={model} onEdit={jest.fn()} onApply={jest.fn()} />);
    expect(html).toContain('data-plant="c"');
    expect(html).toContain('ccgt');
    expect(html).toContain('400 MW');
    expect(html).toContain('electricity out to bus <code>KR-1</code>');
    expect(html).toContain('gas in from bus <code>c_bus_gas</code> (created)');
    expect(html).not.toContain('>plain<');
    expect(html).toContain('>Edit<');
    expect(html).toContain('>Delete<');
  });

  it('says so when there is none, and an imported plant (no registry row) cannot be edited', () => {
    expect(staticMarkup(<CompositeTable model={{ buses: [] } as unknown as WorkbookModel} onEdit={jest.fn()} onApply={jest.fn()} />)).toContain('No composite assets');
    const imported = { ...model, RAGNAROK_PLANTS: [] } as unknown as WorkbookModel;
    const html = staticMarkup(<CompositeTable model={imported} onEdit={jest.fn()} onApply={jest.fn()} />);
    expect(html).toContain('imported');
    expect(html).toContain('disabled');
  });

  it('expands the rows with a text toggle', async () => {
    mounted = await mount(<CompositeTable model={model} onEdit={jest.fn()} onApply={jest.fn()} />);
    const root = mounted.container;
    expect(root.textContent).not.toContain('gas supply');
    await click(button(root, 'Show 3 rows'));
    expect(root.textContent).toContain('gas supply');
    expect(root.querySelector('[data-testid="connection-schematic"]')).not.toBeNull();
    await click(button(root, 'Hide 3 rows'));
    expect(root.textContent).not.toContain('gas supply');
  });

  it('Delete asks the backend what it would remove and applies nothing until the dialog confirms', async () => {
    mockDelete.mockResolvedValue({ plantId: 'c', change: {}, removed: { links: 1 }, kept: { buses: [], carriers: [] }, warnings: [] } as never);
    const onApply = jest.fn<void, [PlantChange, string]>();
    mounted = await mount(<CompositeTable model={model} onEdit={jest.fn()} onApply={onApply} />);
    await click(button(mounted.container, 'Delete'));
    expect(mockDelete).toHaveBeenCalledWith('c', model);
    expect(onApply).not.toHaveBeenCalled();
  });
});
