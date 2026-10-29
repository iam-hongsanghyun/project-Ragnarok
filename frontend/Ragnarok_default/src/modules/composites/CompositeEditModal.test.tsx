/**
 * Editing a composite from the Model tab: the grouped-rows note opens the same Composites form in a popup, Apply hands the change set
 * to onApply and closes it, and "Open in Composites" leaves the popup for the tab.
 */
import React, { useState } from 'react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals';
import type { WorkbookModel } from 'lib/types';
import type { PlantChange } from 'lib/build/plants';
import { fetchPlantTypes, previewPlantEdit, type PlantType } from 'lib/api/plants';
import { OwnedRowsNote } from '../../views/ModelView.features/OwnedRowsNote';
import { CompositeEditModal } from './CompositeEditModal';
import { button, click, mount, settle, type Mounted } from '../../shared/testing/dom';

jest.mock('lib/api/plants');
jest.mock('lib/api/p2x');
const mockTypes = jest.mocked(fetchPlantTypes);
const mockEdit = jest.mocked(previewPlantEdit);

const types: PlantType[] = [{ id: 'ccgt', label: 'CCGT (gas turbine)', description: 'Combined-cycle gas plant.', technology: null, defaults: {},
  fields: [
    { key: 'bus', label: 'Electricity bus (power out)', kind: 'bus', default: null, advanced: false, port: 'electricity', blank: 'first electricity bus', help: 'Where power is delivered.' },
    { key: 'pNom', label: 'Capacity', kind: 'number', default: 200, advanced: false, unit: 'MW' },
  ] }];
const reg = { plantId: 'c', type: 'ccgt', label: 'CCGT c', bus: 'KR-1', capacityMwEl: 100, extendable: false, spec: { bus: 'KR-1', pNom: 100 }, components: [{ sheet: 'links', name: 'c', role: 'turbine' }] };
const model = {
  buses: [{ name: 'KR-1', carrier: 'AC' }, { name: 'KR-2', carrier: 'AC' }],
  links: [{ name: 'c', bus0: 'ng', bus1: 'KR-1', plant: 'c' }],
  RAGNAROK_PLANTS: [{ name: 'c', plant: 'c', json: JSON.stringify(reg) }],
} as unknown as WorkbookModel;
const change = { remove: { links: ['c'] }, release: [], kept: { buses: [], carriers: [] }, fragment: { sheets: { links: [{ name: 'c', bus0: 'ng', bus1: 'KR-2' }] } } } as unknown as PlantChange;

function Harness({ onApply, onOpen }: { onApply: (c: PlantChange, l: string) => void; onOpen: (id: string) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <>
      <OwnedRowsNote sheet="links" rows={model.links as never} onOpenComposite={() => onOpen('tab')} />
      {/* the grid's owner-cell click (TablesPane onOpenOwner) is what opens the popup */}
      <button type="button" onClick={() => setOpen('c')}>Owner cell c</button>
      {open && <CompositeEditModal model={model} plantId={open} onApply={onApply} onClose={() => setOpen(null)} onOpenInComposites={onOpen} />}
    </>
  );
}

let mounted: Mounted | null = null;
beforeEach(() => { jest.useFakeTimers(); mockTypes.mockResolvedValue(types); mockEdit.mockResolvedValue({ plantId: 'c', type: 'ccgt', label: 'CCGT c', summary: [], warnings: [], rowCounts: { links: 1 }, spec: {}, change } as never); });
afterEach(async () => { await mounted?.unmount(); mounted = null; jest.useRealTimers(); jest.resetAllMocks(); });

describe('composite popup from the Model tab', () => {
  it('opens from the owner cell, applies in place and closes', async () => {
    const onApply = jest.fn<void, [PlantChange, string]>();
    mounted = await mount(<Harness onApply={onApply} onOpen={jest.fn()} />);
    expect(mounted.container.textContent).toContain('click a row\'s composite name');
    await click(button(mounted.container, 'Owner cell c'));
    await settle();
    await act(async () => { jest.advanceTimersByTime(300); });
    await settle();
    const modal = document.body.querySelector('[data-testid="composite-modal"]') as HTMLElement;
    expect(modal).not.toBeNull();
    expect(modal.textContent).toContain('Edit composite c');
    expect(modal.textContent).toContain('Electricity bus (power out)');          // the same form: ports first
    expect(mockEdit).toHaveBeenCalledWith('c', expect.anything(), model);
    await click(button(modal, 'Save changes'));
    expect(onApply).toHaveBeenCalledWith(change, 'Updated CCGT c');
    await settle();
    expect(document.body.querySelector('[data-testid="composite-modal"]')).toBeNull();
  });

  it('Open in Composites closes the popup and hands over the composite id', async () => {
    const onOpen = jest.fn<void, [string]>();
    mounted = await mount(<Harness onApply={jest.fn()} onOpen={onOpen} />);
    await click(button(mounted.container, 'Owner cell c'));
    await settle();
    await click(button(document.body.querySelector('[data-testid="composite-modal"]') as HTMLElement, 'Open in Composites'));
    expect(onOpen).toHaveBeenCalledWith('c');
    expect(document.body.querySelector('[data-testid="composite-modal"]')).toBeNull();
  });
});
