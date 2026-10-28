import { afterEach, beforeEach, describe, expect, jest, test } from '@jest/globals';
import { fetchRunAssetKind, fetchRunCompanies, fetchRunKpis, fetchRunPeriod } from './resultsDerived';

// The pathway period views and the KPI / company strips are server payloads: these tests pin
// the requests the browser makes (the `period` argument reaches every route) and the paging of
// the per-asset details, since nothing in the browser derives those figures any more.
describe('period-aware result requests', () => {
  const realFetch = globalThis.fetch;
  const calls: string[] = [];
  afterEach(() => { globalThis.fetch = realFetch; });
  beforeEach(() => {
    calls.length = 0;
    globalThis.fetch = jest.fn(async (url: string) => {
      calls.push(url);
      const offset = Number(new URL(`http://x${url}`).searchParams.get('offset') ?? 0);
      return {
        ok: true,
        json: async () => ({ items: [{ kind: 'buses', name: `b${offset}` }], total: 3, offset, limit: 2 }),
      } as unknown as Response;
    }) as unknown as typeof fetch;
  });

  test('fetchRunPeriod requests the period route with the currency', async () => {
    await fetchRunPeriod('run 1', 2040, '$');
    expect(calls[0]).toMatch(/\/api\/runs\/run%201\/period\/2040\?currency=%24$/);
  });

  test('kpis and companies carry the period only when one is given', async () => {
    await fetchRunKpis('r', '$', 2030);
    await fetchRunKpis('r', '$');
    await fetchRunCompanies('r', 'npv', 2030);
    await fetchRunCompanies('r');
    expect(calls[0]).toContain('/api/runs/r/kpis?currency=%24&period=2030');
    expect(calls[1]).not.toContain('period');
    expect(calls[2]).toContain('sort_by=npv');
    expect(calls[2]).toContain('period=2030');
    expect(calls[3]).toMatch(/\/companies$/);
  });

  test('fetchRunAssetKind pages until total, windowed by period and end', async () => {
    const items = await fetchRunAssetKind('r', 'buses', '$', { period: 2040, end: 24 });
    expect(items.length).toBe(1); // limit 500 >= total 3 -> one page
    expect(calls[0]).toContain('kind=buses');
    expect(calls[0]).toContain('series=true');
    expect(calls[0]).toContain('period=2040');
    expect(calls[0]).toContain('end=24');
  });
});
