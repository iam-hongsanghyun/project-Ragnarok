/** NetworkAnalysisPanel: the exact payloads sent to /api/analysis/*, islands flagged, findings listed. */
import React from 'react';
import { afterEach, describe, expect, it, jest } from '@jest/globals';
import { NetworkAnalysisPanel } from './NetworkAnalysisPanel';
import { button, click, mount, setValue, stubFetch, type Mounted } from '../../shared/testing/dom';

let mounted: Mounted | null = null;
afterEach(async () => { await mounted?.unmount(); mounted = null; });

const sub = (name: string, buses: string[]) => ({
  name, carrier: 'AC', buses, branches: ['Line:a-b'], slackBus: buses[0], slackGenerator: 'g',
});

describe('NetworkAnalysisPanel', () => {
  it('syncs, posts the chosen parts and flags more than one island of the same carrier', async () => {
    const calls = stubFetch(() => ({
      json: {
        parts: ['subnetworks', 'cycles'], cycleBasisMethod: 'paton',
        subNetworks: [sub('0', ['a', 'b']), sub('1', ['c'])],
        cycleMatrix: { rows: ['Line:a-b'], columns: ['0'], data: [[1]] },
      },
    }));
    const sync = jest.fn(async () => {});
    mounted = await mount(<NetworkAnalysisPanel onSessionSync={sync} />);
    const root = mounted.container;
    await setValue(root.querySelector('select[aria-label="Cycle basis method"]'), 'paton');
    await click(button(root, 'Analyse topology'));
    expect(sync).toHaveBeenCalledTimes(1);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toContain('/api/analysis/network');
    expect(calls[0].body).toEqual({ sessionId: 'default', include: ['subnetworks', 'cycles'], cycleBasisMethod: 'paton' });
    expect(root.textContent).toContain('AC: 2 separate islands');
    expect(root.textContent).toContain('Independent loops');
  });

  it('sends strict only when ticked and lists errors and warnings', async () => {
    const calls = stubFetch(() => ({ json: { valid: false, errors: ['bad bus'], warnings: ['w1', 'w2'], strict: ['all'] } }));
    mounted = await mount(<NetworkAnalysisPanel />);
    const root = mounted.container;
    await click(button(root, 'Run consistency check'));
    expect(calls[0].body).toEqual({ sessionId: 'default', strict: null, checkDtypes: false });
    const strict = Array.from(root.querySelectorAll('label.modal-check-row')).find((l) => l.textContent?.includes('Strict'))?.querySelector('input');
    await click(strict ?? null);
    await click(button(root, 'Run consistency check'));
    expect(calls[1].body.strict).toEqual(['all']);
    expect(root.textContent).toContain('1 error, 2 warnings');
    expect(root.textContent).toContain('bad bus');
  });

  it('shows the backend reason on failure', async () => {
    stubFetch(() => ({ status: 400, json: { detail: 'No working model in this session.' } }));
    mounted = await mount(<NetworkAnalysisPanel />);
    await click(button(mounted.container, 'Analyse topology'));
    expect(mounted.container.querySelector('[role="alert"]')?.textContent).toContain('No working model');
  });

  it('does not flag one sub-network per carrier as islands', async () => {
    stubFetch(() => ({
      json: { parts: ['subnetworks'], subNetworks: [sub('0', ['a']), { ...sub('1', ['h']), carrier: 'H2' }] },
    }));
    mounted = await mount(<NetworkAnalysisPanel />);
    const root = mounted.container;
    await click(button(root, 'Analyse topology'));
    expect(root.textContent).not.toContain('separate islands');
    expect(root.textContent).toContain('One sub-network per carrier (AC, H2)');
  });
});
