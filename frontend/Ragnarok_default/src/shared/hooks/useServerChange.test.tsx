import { afterEach, describe, expect, it, jest } from '@jest/globals';
import React from 'react';
import { act } from 'react';

import { SERVER_CHANGED_EVENT } from 'lib/sessionEvents';
import { mount, type Mounted } from '../testing/dom';
import { useServerChange } from './useServerChange';

function Probe({ areas, onChange }: { areas: string[]; onChange: (area: string) => void }) {
  useServerChange(areas, (event) => onChange(event.area), { debounceMs: 50 });
  return null;
}

function fire(area: string) {
  window.dispatchEvent(new CustomEvent(SERVER_CHANGED_EVENT, { detail: { area } }));
}

let mounted: Mounted | null = null;
afterEach(async () => {
  await mounted?.unmount();
  mounted = null;
  jest.useRealTimers();
});

describe('useServerChange', () => {
  it('re-reads once for a burst in its areas and ignores other areas', async () => {
    jest.useFakeTimers();
    const calls: string[] = [];
    const onChange = (area: string) => { calls.push(area); };
    mounted = await mount(<Probe areas={['modules', 'plugins']} onChange={onChange} />);
    act(() => {
      fire('modules');
      fire('modules');
      fire('runs');
      fire('plugins');
    });
    act(() => { jest.advanceTimersByTime(60); });
    expect(calls).toHaveLength(1);
    expect(calls).toEqual(['plugins']);
    act(() => { fire('runs'); jest.advanceTimersByTime(60); });
    expect(calls).toHaveLength(1);
  });
});
