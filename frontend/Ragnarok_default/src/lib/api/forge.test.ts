import { describe, test, expect, beforeEach } from '@jest/globals';
import { forgeQueryApply } from './forge';
import type { QueryEditRequest } from 'lib/forge/queryEdit';

describe('forge client targets the editor session', () => {
  let bodies: string[] = [];
  beforeEach(() => {
    bodies = [];
    (global as unknown as { fetch: unknown }).fetch = async (_url: string, init: { body: string }) => {
      bodies.push(init.body);
      return { ok: true, json: async () => ({}) };
    };
  });
  const sent = () => JSON.parse(bodies[0]) as { sessionId?: string };

  test('an explicit session id from the request wins', async () => {
    await forgeQueryApply({ sessionId: 'other' } as QueryEditRequest);
    expect(sent().sessionId).toBe('other');
  });
  test('a request carrying sessionId: undefined still gets the editor session, not the server default', async () => {
    await forgeQueryApply({ sessionId: undefined } as QueryEditRequest);
    expect(sent().sessionId).toBe('default'); // DEFAULT_SESSION_ID under jest
  });
});
