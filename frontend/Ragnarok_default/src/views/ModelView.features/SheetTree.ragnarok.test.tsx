/** The Model tree lists the Ragnarok module sheets (composites, templates, time units, start costs) as selectable tables once they hold rows. */
import React from 'react';
import { afterEach, describe, expect, it, jest } from '@jest/globals';
import type { TableSel, WorkbookModel } from 'lib/types';
import { SheetTree } from './SheetTree';
import { click, mount, type Mounted } from '../../shared/testing/dom';

let mounted: Mounted | null = null;
afterEach(async () => { await mounted?.unmount(); mounted = null; });

describe('SheetTree Ragnarok sheets', () => {
  it('shows the group only for sheets with rows and selects the sheet on click', async () => {
    const onSel = jest.fn<void, [TableSel]>();
    const model = { buses: [{ name: 'a' }], RAGNAROK_Composites: [{ name: 'c', type: 'ccgt' }], RAGNAROK_TimeUnits: [], RAGNAROK_StartCosts: [{ component: 'links', name: 'c' }] } as unknown as WorkbookModel;
    mounted = await mount(<SheetTree model={model} issues={[]} sel={{ kind: 'static', sheet: 'buses' }} onSelChange={onSel} />);
    const group = mounted.container.querySelector('[data-testid="ragnarok-sheets"]') as HTMLElement;
    expect(group.textContent).toContain('Ragnarok sheets');
    expect(group.textContent).toContain('Composites');
    expect(group.textContent).toContain('Start costs');
    expect(group.textContent).not.toContain('Time units');
    await click(Array.from(group.querySelectorAll('button')).find((b) => b.textContent?.includes('Composites')) as HTMLElement);
    expect(onSel).toHaveBeenCalledWith({ kind: 'static', sheet: 'RAGNAROK_Composites' });
  });
  it('shows no group when none of them has rows', async () => {
    mounted = await mount(<SheetTree model={{ buses: [{ name: 'a' }] } as unknown as WorkbookModel} issues={[]} sel={{ kind: 'static', sheet: 'buses' }} onSelChange={jest.fn()} />);
    expect(mounted.container.querySelector('[data-testid="ragnarok-sheets"]')).toBeNull();
  });
});
