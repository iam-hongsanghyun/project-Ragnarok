/**
 * RelaxMaintenancePanel: preview first (apply false, nothing written), then apply; the server decides which rows.
 */
import React from 'react';
import { afterEach, describe, expect, it, jest } from '@jest/globals';
import { relaxMaintenance } from 'lib/api/operationsModules';
import { RelaxMaintenancePanel } from './RelaxMaintenancePanel';
import { button, click, mount, type Mounted } from '../../shared/testing/dom';

jest.mock('lib/api/operationsModules');
const mockRelax = jest.mocked(relaxMaintenance);

let mounted: Mounted | null = null;
afterEach(async () => { await mounted?.unmount(); mounted = null; jest.resetAllMocks(); });

const preview = { changed: [{ sheet: 'generators', name: 'coal' }, { sheet: 'links', name: 'hvdc' }], sheetsWritten: [], applied: false };

describe('RelaxMaintenancePanel', () => {
  it('previews the rows, keeps Apply disabled until there is something to change, then applies and reloads', async () => {
    mockRelax.mockResolvedValueOnce(preview).mockResolvedValueOnce({ ...preview, sheetsWritten: ['generators', 'links'], applied: true });
    const onSessionSync = jest.fn(async () => {});
    const onSessionReload = jest.fn(async () => {});
    const onApplied = jest.fn();
    mounted = await mount(<RelaxMaintenancePanel onSessionSync={onSessionSync} onSessionReload={onSessionReload} onApplied={onApplied} />);
    const root = mounted.container;
    expect(button(root, 'Relax maintenance')?.disabled).toBe(true);
    await click(button(root, 'Preview relax maintenance'));
    expect(mockRelax).toHaveBeenLastCalledWith(false);
    expect(onSessionSync).toHaveBeenCalled();
    expect(root.textContent).toContain('2 row(s) would get maintainable = false');
    expect(root.textContent).toContain('hvdc');
    expect(onSessionReload).not.toHaveBeenCalled();
    await click(button(root, 'Relax maintenance'));
    expect(mockRelax).toHaveBeenLastCalledWith(true);
    expect(onSessionReload).toHaveBeenCalled();
    expect(onApplied).toHaveBeenCalled();
    expect(root.textContent).toContain('maintainable set to false on 2 row(s) in generators, links');
  });

  it('says so when no unit is maintainable and shows a server error', async () => {
    mockRelax.mockResolvedValueOnce({ changed: [], sheetsWritten: [], applied: false }).mockRejectedValueOnce(new Error('no session'));
    mounted = await mount(<RelaxMaintenancePanel onSessionSync={async () => {}} onSessionReload={async () => {}} />);
    await click(button(mounted.container, 'Preview relax maintenance'));
    expect(mounted.container.textContent).toContain('No maintainable units in the model');
    expect(button(mounted.container, 'Relax maintenance')?.disabled).toBe(true);
    await click(button(mounted.container, 'Preview relax maintenance'));
    expect(mounted.container.querySelector('[role="alert"]')?.textContent).toBe('no session');
  });
});
