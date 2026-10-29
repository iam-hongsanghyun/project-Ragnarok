/**
 * ModelCheckPanel: runs the check (debounced) and lists warnings; an action is a button that does nothing until pressed.
 */
import React, { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals';
import { runModelCheck, type ModelCheckResult } from 'lib/api/modelCheck';
import { ModelCheckPanel } from './ModelCheckPanel';
import { button, click, mount, settle, type Mounted } from '../../shared/testing/dom';

jest.mock('lib/api/modelCheck');
jest.mock('lib/api/forgeBuild');
const mockCheck = jest.mocked(runModelCheck);

const result: ModelCheckResult = {
  warnCount: 1, noteCount: 1, verdict: '1 warning, 1 note',
  findings: [
    { level: 'warn', code: 'weighting_spacing', message: 'Weightings say 1 h but the timestamps are 3 h apart.', fix: 'Set the weightings from the spacing.',
      action: { id: 'set_weightings_from_spacing', label: 'Set weightings from spacing', endpoint: 'POST /api/model/set-weightings-from-spacing' } },
    { level: 'note', code: 'some_note', message: 'A note.', fix: '' },
  ],
};

let mounted: Mounted | null = null;
beforeEach(() => { jest.useFakeTimers(); });
afterEach(async () => { await mounted?.unmount(); mounted = null; jest.useRealTimers(); jest.resetAllMocks(); });

const wait = async () => { await act(async () => { jest.advanceTimersByTime(1300); }); await settle(); };

describe('ModelCheckPanel', () => {
  it('lists warnings only by default and runs the action only when its button is pressed', async () => {
    mockCheck.mockResolvedValue(result);
    const onSet = jest.fn(async () => {});
    mounted = await mount(<ModelCheckPanel refreshKey={1} onSessionSync={async () => {}} onSessionReload={async () => {}} onSetWeightingsFromSpacing={onSet} />);
    await wait();
    const root = mounted.container;
    expect(root.textContent).toContain('1 warning, 1 note');
    expect(root.textContent).toContain('Weightings say 1 h but the timestamps are 3 h apart.');
    expect(root.textContent).not.toContain('A note.');
    expect(onSet).not.toHaveBeenCalled();
    await click(button(root, 'Set weightings from spacing'));
    expect(onSet).toHaveBeenCalledTimes(1);
    expect(mockCheck).toHaveBeenCalledTimes(2);                      // re-checked after the action
  });

  it('shows notes with includeNotes and renders nothing when no model is loaded', async () => {
    mockCheck.mockResolvedValue(result);
    mounted = await mount(<ModelCheckPanel refreshKey={1} includeNotes onSessionSync={async () => {}} onSessionReload={async () => {}} />);
    await wait();
    expect(mounted.container.textContent).toContain('A note.');
    await mounted.unmount();
    mockCheck.mockRejectedValue(new Error('No model loaded'));
    mounted = await mount(<ModelCheckPanel refreshKey={2} onSessionSync={async () => {}} onSessionReload={async () => {}} />);
    await wait();
    expect(mounted.container.textContent).toBe('');
  });
});
