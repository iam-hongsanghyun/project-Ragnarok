import { afterEach, beforeEach, describe, expect, jest, test } from '@jest/globals';
import { clearRunOptionFieldCache, getRunOptionFields } from './runOptions';

describe('run-options reference client', () => {
  const realFetch = globalThis.fetch;
  beforeEach(() => clearRunOptionFieldCache());
  afterEach(() => { globalThis.fetch = realFetch; });

  test('keys the fields by path and caches per key', async () => {
    const fetchMock = jest.fn(async () => ({
      ok: true,
      json: async () => ({ key: 'options.riskPreference', fields: [{ path: 'options.riskPreference.alpha', type: 'number', meaning: 'CVaR level', unit: 'probability 0-1' }] }),
    }) as unknown as Response);
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const fields = await getRunOptionFields('options.riskPreference');
    expect(fields['options.riskPreference.alpha'].unit).toBe('probability 0-1');
    await getRunOptionFields('options.riskPreference');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toMatch(/\/api\/run-options\?key=options\.riskPreference$/);
  });

  test('an error answer throws the server detail and is not cached', async () => {
    globalThis.fetch = jest.fn(async () => ({ ok: false, statusText: 'Bad Request', json: async () => ({ detail: 'unknown run-option key' }) }) as unknown as Response) as unknown as typeof fetch;
    await expect(getRunOptionFields('options.nope')).rejects.toThrow('unknown run-option key');
    globalThis.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ fields: [] }) }) as unknown as Response) as unknown as typeof fetch;
    await expect(getRunOptionFields('options.nope')).resolves.toEqual({});
  });
});
