import { describe, expect, test } from '@jest/globals';
import { mayPushStaticResync, sessionHasModel } from './sessionAdoption';
import type { WorkbookModel } from 'lib/types';

const model = (patch: Record<string, unknown[]>) => ({ ...patch } as unknown as WorkbookModel);

describe('sessionHasModel', () => {
  test('a session with rows is adopted; null and all-empty sheets are not', () => {
    expect(sessionHasModel(null)).toBe(false);
    expect(sessionHasModel(model({ buses: [], generators: [] }))).toBe(false);
    expect(sessionHasModel(model({ buses: [], generators: [{ name: 'g' }] }))).toBe(true);
  });
});

describe('mayPushStaticResync', () => {
  test('nothing is pushed before the boot check finished (the default model must not reach the session)', () => {
    expect(mayPushStaticResync({ tick: 3, bootChecked: false, adoptedAtTick: 0 })).toBe(false);
  });

  test('requests made before adopting the session model are dropped, later ones go through', () => {
    // Three resyncs were requested by the empty default model; the session's model was adopted at tick 3.
    expect(mayPushStaticResync({ tick: 3, bootChecked: true, adoptedAtTick: 3 })).toBe(false);
    expect(mayPushStaticResync({ tick: 4, bootChecked: true, adoptedAtTick: 3 })).toBe(true);
  });

  test('an empty session is seeded with the local model once the check finished', () => {
    expect(mayPushStaticResync({ tick: 2, bootChecked: true, adoptedAtTick: 0 })).toBe(true);
  });

  test('no request, no push', () => {
    expect(mayPushStaticResync({ tick: 0, bootChecked: true, adoptedAtTick: 0 })).toBe(false);
  });
});
