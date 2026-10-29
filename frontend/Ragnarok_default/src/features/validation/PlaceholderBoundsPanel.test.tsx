/**
 * PlaceholderBoundsPanel: preview first (nothing written), then apply; the server decides which cells.
 */
import React from 'react';
import { afterEach, describe, expect, it, jest } from '@jest/globals';
import { cleanPlaceholderBounds } from 'lib/api/forgeBuild';
import { PlaceholderBoundsPanel } from './PlaceholderBoundsPanel';
import { button, click, mount, type Mounted } from '../../shared/testing/dom';

jest.mock('lib/api/forgeBuild');
const mockClean = jest.mocked(cleanPlaceholderBounds);

let mounted: Mounted | null = null;
afterEach(async () => { await mounted?.unmount(); mounted = null; jest.resetAllMocks(); });

const result = { cleaned: 2, applied: false, sheets: { generators: 2 }, cells: [
  { sheet: 'generators', name: 'coal', column: 'p_nom_max', value: 1e12 },
  { sheet: 'generators', name: 'gas', column: 'p_nom_max', value: 1e9 },
] };

describe('PlaceholderBoundsPanel', () => {
  it('previews the cells, keeps Apply disabled until there is something to clean, then applies and reloads', async () => {
    mockClean.mockResolvedValueOnce(result).mockResolvedValueOnce({ ...result, applied: true });
    const onSessionSync = jest.fn(async () => {});
    const onSessionReload = jest.fn(async () => {});
    const onApplied = jest.fn();
    mounted = await mount(<PlaceholderBoundsPanel onSessionSync={onSessionSync} onSessionReload={onSessionReload} onApplied={onApplied} />);
    const root = mounted.container;
    expect(button(root, 'Apply clean-up')?.disabled).toBe(true);
    await click(button(root, 'Preview clean-up'));
    expect(mockClean).toHaveBeenLastCalledWith({ apply: false });
    expect(root.textContent).toContain('2 cell(s) would be blanked (generators: 2 rows)');
    expect(root.textContent).toContain('1e+12');
    expect(onSessionReload).not.toHaveBeenCalled();
    await click(button(root, 'Apply clean-up'));
    expect(mockClean).toHaveBeenLastCalledWith({ apply: true });
    expect(onSessionReload).toHaveBeenCalled();
    expect(onApplied).toHaveBeenCalled();
    expect(root.textContent).toContain('2 bound cell(s) blanked in generators');
  });

  it('says so when no placeholder bound exists and shows a server error', async () => {
    mockClean.mockResolvedValueOnce({ cleaned: 0, applied: false, sheets: {}, cells: [] }).mockRejectedValueOnce(new Error('no session'));
    mounted = await mount(<PlaceholderBoundsPanel onSessionSync={async () => {}} onSessionReload={async () => {}} />);
    await click(button(mounted.container, 'Preview clean-up'));
    expect(mounted.container.textContent).toContain('No placeholder bounds found.');
    await click(button(mounted.container, 'Preview clean-up'));
    expect(mounted.container.querySelector('[role="alert"]')?.textContent).toBe('no session');
  });
});
