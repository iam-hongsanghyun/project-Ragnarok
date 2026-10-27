import { describe, it, expect, afterEach, jest } from '@jest/globals';
import { fetchJournal, revertJournal, undoJournalEntry } from './journal';

const realFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = realFetch; });

function mockFetch(status: number, body: unknown) {
  const fn = jest.fn(async () => ({ ok: status < 400, status, json: async () => body }) as unknown as Response);
  globalThis.fetch = fn as unknown as typeof fetch;
  return fn;
}

describe('journal api', () => {
  it('lists with the session and limit in the query', async () => {
    const fn = mockFetch(200, { version: 3, entries: [] });
    const out = await fetchJournal(10, 's1');
    expect(out.version).toBe(3);
    expect((fn.mock.calls[0] as unknown[])[0]).toContain('/api/session/journal?session_id=s1&limit=10');
  });

  it('surfaces the server detail of a 409 conflict', async () => {
    mockFetch(409, { detail: 'a later change (v5) touches the same sheet(s)' });
    await expect(undoJournalEntry(2, 's1')).rejects.toThrow('later change (v5)');
  });

  it('posts the revert target as toVersion', async () => {
    const fn = mockFetch(200, { version: 7, undone: [6, 5] });
    await revertJournal(4, 's1');
    const [, init] = fn.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ sessionId: 's1', toVersion: 4 });
  });
});
