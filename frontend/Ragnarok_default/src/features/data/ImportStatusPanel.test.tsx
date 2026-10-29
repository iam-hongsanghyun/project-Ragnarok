/** ImportStatusPanel: loads the registry and log when opened, probes sources on request. */
import React, { act } from 'react';
import { afterEach, describe, expect, it } from '@jest/globals';
import { ImportStatusPanel, formatRowCounts } from './ImportStatusPanel';
import { button, click, mount, settle, stubFetch, type Mounted } from '../../shared/testing/dom';

let mounted: Mounted | null = null;
afterEach(async () => { await mounted?.unmount(); mounted = null; });

const db = { id: 'osm', name: 'OpenStreetMap', short_name: 'Grid topology', source_id: 'osm', source_label: 'OSM', category: 'transmission', license: 'ODbL', version_hint: 'live', available: true };
const entry = { version: 3, recordedAt: '2026-10-29T06:00:00+00:00', sourceId: 'osm', datasetIds: ['osm'], databaseId: 'osm', countryIso: 'KOR', countryName: 'Korea', filters: '{}', fetchedAt: '', rowCounts: '{"buses": 12, "lines": 30}' };

describe('ImportStatusPanel', () => {
  it('loads nothing until opened, then lists databases and the provenance log', async () => {
    const calls = stubFetch((url) => ({
      json: url.includes('/databases') ? { databases: [db] } : url.includes('/provenance') ? { imports: [entry] } : { sources: {} },
    }));
    mounted = await mount(<ImportStatusPanel />);
    expect(calls).toHaveLength(0);
    const details = mounted.container.querySelector('details') as HTMLDetailsElement;
    await act(async () => { details.open = true; details.dispatchEvent(new Event('toggle')); });
    await settle();
    expect(calls.map((c) => c.url.replace(/^.*\/api/, '/api')).sort()).toEqual(['/api/import/databases', '/api/import/provenance?limit=50']);
    expect(mounted.container.textContent).toContain('Grid topology');
    expect(mounted.container.textContent).toContain('buses 12, lines 30');
    expect(mounted.container.textContent).toContain('not checked');
  });

  it('shows reachability per source after Check source health', async () => {
    stubFetch((url) => ({
      json: url.includes('/health')
        ? { sources: { osm: { ok: false, status: null, latencyMs: 6000, checkedAt: 'x', error: 'ReadTimeout' } } }
        : url.includes('/databases') ? { databases: [db] } : { imports: [] },
    }));
    mounted = await mount(<ImportStatusPanel />);
    const details = mounted.container.querySelector('details') as HTMLDetailsElement;
    await act(async () => { details.open = true; details.dispatchEvent(new Event('toggle')); });
    await settle();
    await click(button(mounted.container, 'Check source health'));
    expect(mounted.container.textContent).toContain('unreachable (ReadTimeout)');
    expect(mounted.container.textContent).toContain('No imports recorded yet.');
  });

  it('formats row counts and tolerates plain text', () => {
    expect(formatRowCounts('{"a": 1}')).toBe('a 1');
    expect(formatRowCounts('n/a')).toBe('n/a');
    expect(formatRowCounts('')).toBe('');
  });
});
