import { beforeEach, describe, expect, jest, test } from '@jest/globals';
import {
  APP_STATE_SHEET,
  diffAppState,
  adoptProjectAppState,
  applyAppState,
  isProjectKey,
  restoreAtBoot,
  sameAppState,
  snapshotAppState,
  withoutAppStateSheet,
} from './appState';

const jsonResponse = (body: unknown, ok = true) => ({ ok, status: ok ? 200 : 500, json: async () => body }) as unknown as Response;

describe('app state (every setting travels with the project)', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  test('project keys: settings, module and view state in; secrets, caches, learner progress out', () => {
    expect(isProjectKey('project_ragnarok_settings')).toBe(true);
    expect(isProjectKey('ragnarok:session:controls')).toBe(true);
    expect(isProjectKey('ragnarok:fe-plugins:configs')).toBe(true);
    expect(isProjectKey('ui:be-plugin-cfg:fuel')).toBe(true);
    expect(isProjectKey('ragnarok.screening.level')).toBe(true);
    expect(isProjectKey('pypsa.panelSizes.main')).toBe(true);
    expect(isProjectKey('ragnarok:secret:OPENAI')).toBe(false);
    expect(isProjectKey('ragnarok:config:bundle')).toBe(false);
    expect(isProjectKey('ragnarok:build-id')).toBe(false);
    expect(isProjectKey('ragnarok:training:progress')).toBe(false);
    expect(isProjectKey('ragnarok:tour:v1')).toBe(false);
    expect(isProjectKey('ragnarok:fe-plugins:installed')).toBe(false);
    expect(isProjectKey('project_ragnarok_settings:migrated_solver_auto')).toBe(false);
    expect(isProjectKey('some-other-app')).toBe(false);
  });

  test('apply makes the project set exact and leaves non-project keys alone', () => {
    window.localStorage.setItem('ui:old', 'x');
    window.localStorage.setItem('ragnarok:secret:KEY', 'sk');
    applyAppState({ 'project_ragnarok_settings': '{"currencyCode":"KRW"}', 'ui:new': '1' });
    expect(snapshotAppState()).toEqual({ 'project_ragnarok_settings': '{"currencyCode":"KRW"}', 'ui:new': '1' });
    expect(window.localStorage.getItem('ragnarok:secret:KEY')).toBe('sk');
    expect(sameAppState({ a: '1' }, { a: '1' })).toBe(true);
    expect(sameAppState({ a: '1' }, { a: '2' })).toBe(false);
  });

  test('a browser sends only the keys it changed (never clobbers another writer)', () => {
    expect(diffAppState({ a: '1', b: '2', c: '3' }, { a: '1', b: '20', d: '4' })).toEqual({ b: '20', c: null, d: '4' });
    expect(diffAppState({ a: '1' }, { a: '1' })).toEqual({});
  });

  test('the app-state sheet is not part of the editor model', () => {
    const model = { buses: [], [APP_STATE_SHEET]: [{ key: 'k', part: 0, value: 'v' }] };
    expect(withoutAppStateSheet(model)).toEqual({ buses: [] });
  });

  test('boot restores the project settings before render; a project without settings takes the browser ones', async () => {
    const fetchMock = jest.fn<Promise<Response>, []>().mockResolvedValue(jsonResponse({ state: { 'ui:x': 'project' } }));
    (global as any).fetch = fetchMock;
    window.localStorage.setItem('ui:x', 'browser');
    await restoreAtBoot();
    expect(window.localStorage.getItem('ui:x')).toBe('project');

    // too late: rendered already -> leave the browser alone
    window.localStorage.setItem('ui:x', 'browser');
    await restoreAtBoot(() => true);
    expect(window.localStorage.getItem('ui:x')).toBe('browser');
  });

  test('adopting a project with other settings applies them and reloads; equal settings do nothing', async () => {
    const reload = jest.fn();
    Object.defineProperty(window, 'location', { value: { ...window.location, reload }, writable: true });
    (global as any).fetch = jest.fn<Promise<Response>, []>().mockResolvedValue(jsonResponse({ state: { 'ui:x': 'other' } }));
    window.localStorage.setItem('ui:x', 'mine');
    expect(await adoptProjectAppState()).toBe(true);
    expect(window.localStorage.getItem('ui:x')).toBe('other');
    expect(reload).toHaveBeenCalledTimes(1);
    expect(await adoptProjectAppState()).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);
    // The app writes view state while it mounts: that is not a different project, so no reload (no loop).
    window.localStorage.setItem('ui:mount-written', 'x');
    expect(await adoptProjectAppState()).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);
    // An agent changes the project's settings: reload once.
    (global as any).fetch = jest.fn<Promise<Response>, []>().mockResolvedValue(jsonResponse({ state: { 'ui:x': 'agent' } }));
    expect(await adoptProjectAppState()).toBe(true);
    expect(reload).toHaveBeenCalledTimes(2);
  });
});
