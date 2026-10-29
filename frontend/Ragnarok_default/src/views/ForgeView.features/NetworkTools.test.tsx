/** Forge slice / merge / write-sample panels: payloads, preview before apply, replace only on Apply. */
import React from 'react';
import { afterEach, describe, expect, it, jest } from '@jest/globals';
import { SliceNetworkPanel } from './SliceNetworkPanel';
import { MergeNetworkPanel, parseSkipList } from './MergeNetworkPanel';
import { WriteSamplePanel, sampleInputError } from './WriteSamplePanel';
import { defaultSamplingConfig } from 'lib/results/sampling';
import { button, click, mount, setValue, stubFetch, type Mounted } from '../../shared/testing/dom';

let mounted: Mounted | null = null;
afterEach(async () => { await mounted?.unmount(); mounted = null; });

const counts = (s: number, b: number) => ({ snapshots: s, buses: b, weightedHours: s });
const reduced = { buses: [{ name: 'a' }] };

describe('SliceNetworkPanel', () => {
  const model = { snapshots: [{ snapshot: '2030-01-01T00:00' }, { snapshot: '2030-01-01T23:00' }], buses: [{ name: 'a' }, { name: 'b' }] };

  it('needs a window or buses before it can preview', async () => {
    stubFetch(() => ({ json: {} }));
    mounted = await mount(<SliceNetworkPanel model={model as never} onSessionSync={async () => {}} onReplaceModel={jest.fn()} onStatus={jest.fn()} />);
    expect(button(mounted.container, 'Preview')?.disabled).toBe(true);
  });

  it('posts the window labels, then replaces the model only on Apply', async () => {
    const calls = stubFetch(() => ({ json: { model: reduced, before: counts(24, 3), after: counts(12, 3) } }));
    const onReplace = jest.fn();
    const sync = jest.fn(async () => {});
    mounted = await mount(<SliceNetworkPanel model={model as never} onSessionSync={sync} onReplaceModel={onReplace} onStatus={jest.fn()} />);
    const root = mounted.container;
    await setValue(root.querySelector('#slice-start'), ' 2030-01-01T00:00 ');
    await setValue(root.querySelector('#slice-end'), '2030-01-01T11:00');
    await click(button(root, 'Preview'));
    expect(sync).toHaveBeenCalled();
    expect(calls[0].url).toContain('/api/transform/slice');
    expect(calls[0].body).toEqual({ sessionId: 'default', start: '2030-01-01T00:00', end: '2030-01-01T11:00' });
    expect(root.textContent).toContain('24 to 12 snapshots');
    expect(onReplace).not.toHaveBeenCalled();
    await click(button(root, 'Apply to working model'));
    expect(onReplace).toHaveBeenCalledWith(reduced, expect.stringContaining('Slice'));
  });
});

describe('MergeNetworkPanel', () => {
  const runs = [{ name: 'run_1', label: 'Base case' }] as never;

  it('merges a stored run with the skip list and time flag', async () => {
    const calls = stubFetch(() => ({ json: { model: reduced, before: counts(24, 3), after: counts(24, 5), merged: counts(24, 2) } }));
    const onReplace = jest.fn();
    mounted = await mount(<MergeNetworkPanel runs={runs} onSessionSync={async () => {}} onReplaceModel={onReplace} onStatus={jest.fn()} />);
    const root = mounted.container;
    expect(button(root, 'Preview')?.disabled).toBe(true);
    await setValue(root.querySelector('#merge-run'), 'run_1');
    await setValue(root.querySelector('#merge-skip'), 'Carrier, ');
    await click(button(root, 'Preview'));
    expect(calls[0].url).toContain('/api/transform/merge');
    expect(calls[0].body).toEqual({ sessionId: 'default', otherRun: 'run_1', withTime: true, componentsToSkip: ['Carrier'] });
    expect(root.textContent).toContain('3 to 5 buses');
    await click(button(root, 'Apply to working model'));
    expect(onReplace).toHaveBeenCalledTimes(1);
  });

  it('merges another session and shows the collision message', async () => {
    const calls = stubFetch(() => ({ status: 400, json: { detail: 'merge failed: duplicate names' } }));
    mounted = await mount(<MergeNetworkPanel runs={[]} onSessionSync={async () => {}} onReplaceModel={jest.fn()} onStatus={jest.fn()} />);
    const root = mounted.container;
    await setValue(root.querySelector('#merge-source'), 'session');
    await setValue(root.querySelector('#merge-session'), 'other');
    await click(button(root, 'Preview'));
    expect(calls[0].body).toEqual({ sessionId: 'default', otherSessionId: 'other', withTime: true });
    expect(root.querySelector('[role="alert"]')?.textContent).toContain('duplicate names');
  });

  it('parses the skip list', () => {
    expect(parseSkipList(' Carrier ,, generators ')).toEqual(['Carrier', 'generators']);
  });
});

describe('WriteSamplePanel', () => {
  it('forces sampling on, sends the window and writes the sample on Apply', async () => {
    const calls = stubFetch(() => ({ json: { model: reduced, notes: ['kept 48'], before: { snapshots: 8760 }, after: { snapshots: 48 }, factor: 182.5 } }));
    const onReplace = jest.fn();
    mounted = await mount(<WriteSamplePanel onSessionSync={async () => {}} onReplaceModel={onReplace} onStatus={jest.fn()} />);
    const root = mounted.container;
    await setValue(root.querySelector('#sample-size'), '24');
    await setValue(root.querySelector('#sample-count'), '2');
    await setValue(root.querySelector('#sample-wstart'), '100');
    await click(button(root, 'Preview'));
    expect(calls[0].url).toContain('/api/transform/sample');
    expect(calls[0].body).toEqual({
      sessionId: 'default',
      options: { samplingConfig: { enabled: true, mode: 'count', blockSize: 24, blockCount: 2, gapSnapshots: 672 }, snapshotStart: 100 },
    });
    expect(root.textContent).toContain('8760 to 48 snapshots');
    expect(root.textContent).toContain('kept 48');
    expect(onReplace).not.toHaveBeenCalled();
    await click(button(root, 'Write sample to working model'));
    expect(onReplace).toHaveBeenCalledWith(reduced, expect.stringContaining('factor 182.5'));
  });

  it('validates the inputs', () => {
    const cfg = defaultSamplingConfig();
    expect(sampleInputError(cfg, '', '')).toBeNull();
    expect(sampleInputError({ ...cfg, blockSize: 0 }, '', '')).toMatch(/Block size/);
    expect(sampleInputError(cfg, '-1', '')).toMatch(/Window start/);
    expect(sampleInputError(cfg, '', '0')).toMatch(/Window length/);
  });
});
