import { afterEach, describe, expect, jest, test } from '@jest/globals';
import { getTimeUnits, previewTimeUnits, TIME_UNITS_SHEET } from './timeUnits';

// The editor reads its vocabulary from the server and asks the server to convert: these pin the requests
// (session id, route, body) and that a 400 surfaces the server's own reason.
describe('time-units client', () => {
  const realFetch = globalThis.fetch;
  afterEach(() => { globalThis.fetch = realFetch; });

  test('the sheet name is the one the backend reads', () => {
    expect(TIME_UNITS_SHEET).toBe('RAGNAROK_TimeUnits');
  });

  test('vocabulary is a GET with the session, the preview a POST with the session and options', async () => {
    const calls: Array<[string, RequestInit | undefined]> = [];
    globalThis.fetch = jest.fn(async (url: string, init?: RequestInit) => {
      calls.push([url, init]);
      return { ok: true, json: async () => ({ table: [], stepHours: null }) } as unknown as Response;
    }) as unknown as typeof fetch;
    await getTimeUnits();
    await previewTimeUnits({ snapshotWeight: 4 });
    expect(calls[0][0]).toMatch(/\/api\/time-units\?session_id=default$/);
    expect(calls[1][0]).toMatch(/\/api\/time-units\/preview$/);
    expect(JSON.parse(String(calls[1][1]?.body))).toEqual({ sessionId: 'default', options: { snapshotWeight: 4 } });
  });

  test('an error answer throws the server detail', async () => {
    globalThis.fetch = jest.fn(async () => ({
      ok: false, statusText: 'Bad Request', json: async () => ({ detail: 'unit \'per_year\' for ramp_limit_up must be one of per_hour' }),
    }) as unknown as Response) as unknown as typeof fetch;
    await expect(previewTimeUnits()).rejects.toThrow(/per_year/);
  });
});
