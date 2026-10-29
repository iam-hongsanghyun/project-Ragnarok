/**
 * TimeUnitsPanel: the vocabulary comes from the API (nothing hard-coded), the sheet's rows for the active component are listed
 * and the preview shows the server's converted per-snapshot value.
 */
import React from 'react';
import { afterEach, describe, expect, it, jest } from '@jest/globals';
import type { WorkbookModel } from 'lib/types';
import { getTimeUnits, previewTimeUnits, type TimeUnitsVocabulary } from 'lib/api/timeUnits';
import { TimeUnitsPanel } from './TimeUnitsPanel';
import { button, click, mount, settle, type Mounted } from '../../shared/testing/dom';

jest.mock('lib/api/timeUnits');
const mockVocab = jest.mocked(getTimeUnits);
const mockPreview = jest.mocked(previewTimeUnits);

const vocab: TimeUnitsVocabulary = {
  sheet: 'RAGNAROK_TimeUnits', rows: [], components: ['links'],
  attributes: { ramps: ['ramp_limit_up'], times: ['min_up_time', 'min_down_time'] },
  units: { ramps: ['per_hour', 'per_minute'], times: ['hours', 'minutes'] },
};
const model = {
  links: [{ name: 'cofire' }, { name: 'feed' }],
  RAGNAROK_TimeUnits: [
    { component: 'links', name: 'cofire', attribute: 'min_down_time', value: 4, unit: 'hours' },
    { component: 'generators', name: 'other', attribute: 'min_up_time', value: 2, unit: 'hours' },
  ],
} as unknown as WorkbookModel;

let mounted: Mounted | null = null;
afterEach(async () => { await mounted?.unmount(); mounted = null; jest.resetAllMocks(); });

const props = () => ({ model, sheet: 'links', onUpdateRow: jest.fn(), onDeleteRow: jest.fn(), onBulkPaste: jest.fn(), onSessionSync: jest.fn(async () => {}), onClose: jest.fn() });

describe('TimeUnitsPanel', () => {
  it('lists only the active sheet\'s rows and previews the converted per-snapshot value', async () => {
    mockVocab.mockResolvedValue(vocab);
    mockPreview.mockResolvedValue({ stepHours: 1, table: [{ component: 'links', name: 'cofire', attribute: 'min_down_time', value: 4, unit: 'hours', stepHours: 1, pypsaValue: 4, blank: false, note: '' }] });
    const p = props();
    mounted = await mount(<TimeUnitsPanel {...p} />);
    await settle();
    const root = mounted.container;
    expect(root.textContent).toContain('Time units — ramps and minimum times (links)');
    expect(root.textContent).toContain('min_down_time');
    expect(root.textContent).not.toContain('other');                // a generators row
    await click(button(root, 'Preview per-snapshot values'));
    expect(p.onSessionSync).toHaveBeenCalled();
    expect(root.textContent).toContain('1 h per snapshot');
    const cells = Array.from(root.querySelectorAll('tbody td')).map((c) => c.textContent);
    expect(cells).toContain('4');                                    // PyPSA per snapshot
  });

  it('Remove deletes the row by its sheet index and Close calls back', async () => {
    mockVocab.mockResolvedValue(vocab);
    const p = props();
    mounted = await mount(<TimeUnitsPanel {...p} />);
    await settle();
    await click(button(mounted.container, 'Remove'));
    expect(p.onDeleteRow).toHaveBeenCalledWith('RAGNAROK_TimeUnits', 0);
    await click(button(mounted.container, 'Close'));
    expect(p.onClose).toHaveBeenCalled();
  });

  it('shows the API error when the vocabulary cannot load', async () => {
    mockVocab.mockRejectedValue(new Error('no session'));
    mounted = await mount(<TimeUnitsPanel {...props()} />);
    await settle();
    expect(mounted.container.querySelector('[role="alert"]')?.textContent).toBe('no session');
  });
});
