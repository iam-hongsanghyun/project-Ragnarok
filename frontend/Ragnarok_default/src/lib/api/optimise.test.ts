import { afterEach, describe, expect, jest, test } from '@jest/globals';
import { exportAndDownloadLp, exportedFileName, exportLp } from './optimise';

// Export LP posts the run body, then fetches the written file by the name the server used; a 400 surfaces the server's reason.
describe('export LP client', () => {
  const realFetch = globalThis.fetch;
  afterEach(() => { globalThis.fetch = realFetch; });

  test('the file name is the last path segment of the server path', () => {
    expect(exportedFileName({ path: '/data/exports/lp/base.lp', bytes: 1, variables: 1, constraints: 1, seconds: 0 })).toBe('base.lp');
  });

  test('posts the session, run body and file name; then downloads that file', async () => {
    const calls: Array<[string, RequestInit | undefined]> = [];
    globalThis.fetch = jest.fn(async (url: string, init?: RequestInit) => {
      calls.push([url, init]);
      return url.endsWith('/file?fileName=base.lp')
        ? ({ ok: true, blob: async () => new Blob(['min: 0']) } as unknown as Response)
        : ({ ok: true, json: async () => ({ path: '/d/exports/lp/base.lp', bytes: 6, variables: 3, constraints: 2, seconds: 0.1 }) } as unknown as Response);
    }) as unknown as typeof fetch;
    (URL as unknown as { createObjectURL: () => string }).createObjectURL = () => 'blob:x';
    (URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = () => {};
    const info = await exportAndDownloadLp({ scenario: { carbonPrice: 10 }, options: { forceLp: true } }, 'base.lp');
    expect(info.variables).toBe(3);
    expect(calls[0][0]).toMatch(/\/api\/optimise\/export-lp$/);
    expect(JSON.parse(String(calls[0][1]?.body))).toEqual({ sessionId: 'default', scenario: { carbonPrice: 10 }, options: { forceLp: true }, fileName: 'base.lp' });
    expect(calls[1][0]).toMatch(/\/api\/optimise\/export-lp\/file\?fileName=base\.lp$/);
  });

  test('an error answer throws the server detail', async () => {
    globalThis.fetch = jest.fn(async () => ({ ok: false, statusText: 'Bad Request', json: async () => ({ detail: 'LP export failed: no snapshots' }) }) as unknown as Response) as unknown as typeof fetch;
    await expect(exportLp({ scenario: {}, options: {} }, 'x.lp')).rejects.toThrow('LP export failed: no snapshots');
  });
});
