import { describe, expect, it } from '@jest/globals';

import { sessionUrl, stopBackendSolves } from './session';
import { stubFetch } from '../../shared/testing/dom';

describe('sessionUrl', () => {
  const here = 'http://localhost:3000/?tab=Settings';

  it('opens another session of the app’s own backend', () => {
    expect(sessionUrl('bifrost', '', here)).toBe('http://localhost:3000/?tab=Settings&session=bifrost');
  });

  it('opens a session of another backend and keeps the rest of the address', () => {
    const url = new URL(sessionUrl('ragnarok-f76c4f09', 'http://127.0.0.1:52185', here));
    expect(url.searchParams.get('session')).toBe('ragnarok-f76c4f09');
    expect(url.searchParams.get('api')).toBe('http://127.0.0.1:52185');
    expect(url.searchParams.get('tab')).toBe('Settings');
  });

  it('back to default on the own backend drops both parameters', () => {
    const from = 'http://localhost:3000/?session=x&api=http%3A%2F%2F127.0.0.1%3A52185';
    expect(sessionUrl('default', '', from)).toBe('http://localhost:3000/');
  });
});

describe('stopBackendSolves', () => {
  it('cancels only the running and queued jobs of the named backend', async () => {
    const calls = stubFetch((url) => (url.endsWith('/api/queue')
      ? { json: { jobs: [{ id: 'a', status: 'running' }, { id: 'b', status: 'queued' }, { id: 'c', status: 'done' }] } }
      : { json: { status: 'cancelled' } }));
    expect(await stopBackendSolves('http://127.0.0.1:52185')).toBe(2);
    expect(calls.map((c) => c.url)).toEqual([
      'http://127.0.0.1:52185/api/queue',
      'http://127.0.0.1:52185/api/queue/a/cancel',
      'http://127.0.0.1:52185/api/queue/b/cancel',
    ]);
  });
});
