import { describe, it, expect, jest, beforeEach } from '@jest/globals';
import { buildLocationModel } from 'lib/api/starterPacks';
import { oneClickStore } from './oneClickStore';

// Auto-mock the network module so the store's lifecycle is driven deterministically.
jest.mock('lib/api/starterPacks');
const mockBuild = jest.mocked(buildLocationModel);

const FRAG = {
  iso3: 'KOR', year: 'auto' as const, label: 'One-click model',
  datasetIds: ['osm'], countryIso: 'KOR', fragment: { sheets: {} },
} as unknown as Awaited<ReturnType<typeof buildLocationModel>>;

describe('oneClickStore', () => {
  beforeEach(() => {
    mockBuild.mockReset();
    oneClickStore.reset();
  });

  it('goes building → ready and holds the result until consumed', async () => {
    let resolve: (v: typeof FRAG) => void = () => {};
    mockBuild.mockReturnValue(new Promise((r) => { resolve = r; }));

    oneClickStore.start('KOR', 'South Korea');
    expect(oneClickStore.get().status).toBe('building');
    expect(oneClickStore.get().countryName).toBe('South Korea');

    resolve(FRAG);
    await Promise.resolve(); await Promise.resolve();
    expect(oneClickStore.get().status).toBe('ready');
    expect(oneClickStore.get().build).toBe(FRAG);

    // The result survives until the view applies it — this is what makes the
    // build persist across a tab switch instead of vanishing.
    oneClickStore.consume();
    expect(oneClickStore.get().status).toBe('idle');
    expect(oneClickStore.get().build).toBeNull();
  });

  it('stays building across a simulated unmount/remount (subscriber churn)', () => {
    mockBuild.mockReturnValue(new Promise<typeof FRAG>(() => {})); // never resolves
    oneClickStore.start('KOR', 'South Korea');
    // Simulate DataImportView unmounting (unsubscribe) then remounting.
    const unsub = oneClickStore.subscribe(() => {});
    unsub();
    // A freshly-mounted component reads the SAME module state → still building.
    expect(oneClickStore.get().status).toBe('building');
  });

  it('surfaces build errors', async () => {
    mockBuild.mockReturnValue(Promise.reject(new Error('OSM rate-limited')));
    oneClickStore.start('KOR', 'South Korea');
    await Promise.resolve(); await Promise.resolve();
    expect(oneClickStore.get().status).toBe('error');
    expect(oneClickStore.get().error).toContain('OSM rate-limited');
  });

  it('ignores a superseded build resolving late', async () => {
    let resolveFirst: (v: typeof FRAG) => void = () => {};
    mockBuild.mockReturnValueOnce(new Promise((r) => { resolveFirst = r; }));
    oneClickStore.start('KOR', 'South Korea');

    // A second build supersedes the first.
    mockBuild.mockReturnValueOnce(new Promise<typeof FRAG>(() => {}));
    oneClickStore.start('JPN', 'Japan');
    expect(oneClickStore.get().countryName).toBe('Japan');

    // The first (stale) build resolving must NOT clobber the active one.
    resolveFirst(FRAG);
    await Promise.resolve(); await Promise.resolve();
    expect(oneClickStore.get().status).toBe('building');
    expect(oneClickStore.get().countryName).toBe('Japan');
  });
});
