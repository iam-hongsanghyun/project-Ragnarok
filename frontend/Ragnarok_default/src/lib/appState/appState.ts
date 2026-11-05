/**
 * The project's app state: every setting the browser holds travels with the project.
 *
 * The rule: all app settings — Settings (incl. enabled modules), each module's options,
 * plugin configs, the live run controls and view state — are saved in the project and
 * restored exactly when it is opened. They are the app's `localStorage` key -> string
 * pairs, stored verbatim in the project's `_app_state` table (`docs/project-file.md`).
 *
 * How:
 * - capture: every `localStorage` write is observed; a debounced PUT stores the whole
 *   project set (`PUT /api/session/app-state`). Nothing per module, so a new module's
 *   keys travel without code here.
 * - restore at boot: before React renders, `restoreAtBoot` writes the project's set into
 *   `localStorage`, so every component reads the project's values on first mount.
 * - restore on open: after a different project is loaded, `adoptProjectAppState` applies
 *   its set and reloads once (components read their settings when they mount). A project
 *   with no settings of its own takes the current ones.
 *
 * Out of the project (`isProjectKey`): secrets (API keys), caches and build markers, the
 * installed plugin packages (per machine) and the learner's training / tour progress
 * (opening a tutorial's project must not roll it back).
 */
import { API_BASE } from 'lib/constants';
import { DEFAULT_SESSION_ID } from 'lib/api/session';

export type AppState = Record<string, string>;

/** Sheet name of the app state when it travels inside a model or workbook (the server takes it out). */
export const APP_STATE_SHEET = 'RAGNAROK_AppState';

/** `model` without the app-state sheet: settings are not a sheet of the editor's model. */
export function withoutAppStateSheet<M extends object>(model: M): M {
  if (!(APP_STATE_SHEET in model)) return model;
  const { [APP_STATE_SHEET]: _dropped, ...rest } = model as Record<string, unknown>;
  return rest as M;
}

const INCLUDE_PREFIXES = ['ragnarok:', 'ragnarok.', 'ui:', 'pypsa.', 'project_ragnarok_settings'];
const EXCLUDE_PREFIXES = [
  'ragnarok:build-id',
  'ragnarok:config:',
  'ragnarok:secret:',
  'ragnarok:training:',
  'ragnarok:tour:',
  'ragnarok:fe-plugins:installed',
  'project_ragnarok_settings:migrated_',
];

/** True when `key` is a project setting (travels with the project). */
export function isProjectKey(key: string): boolean {
  if (!INCLUDE_PREFIXES.some((p) => key.startsWith(p))) return false;
  return !EXCLUDE_PREFIXES.some((p) => key.startsWith(p));
}

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** The project settings currently in this browser. */
export function snapshotAppState(): AppState {
  const out: AppState = {};
  const ls = storage();
  if (!ls) return out;
  for (let i = 0; i < ls.length; i += 1) {
    const key = ls.key(i);
    if (key && isProjectKey(key)) {
      const value = ls.getItem(key);
      if (value !== null) out[key] = value;
    }
  }
  return out;
}

export function sameAppState(a: AppState, b: AppState): boolean {
  const ka = Object.keys(a);
  if (ka.length !== Object.keys(b).length) return false;
  return ka.every((k) => b[k] === a[k]);
}

/** Make `state` the browser's project settings exactly (keys it lacks are removed). */
export function applyAppState(state: AppState): void {
  const ls = storage();
  if (!ls) return;
  muted += 1;
  try {
    const current = Object.keys(snapshotAppState());
    for (const key of current) if (!(key in state)) ls.removeItem(key);
    for (const [key, value] of Object.entries(state)) if (isProjectKey(key)) ls.setItem(key, value);
  } finally {
    muted -= 1;
  }
}

// ── server I/O ──────────────────────────────────────────────────────────────────

const url = (sessionId: string) => `${API_BASE}/api/session/app-state?session_id=${encodeURIComponent(sessionId)}`;

/** The project's settings; `null` when no project is loaded. */
export async function fetchAppState(sessionId: string = DEFAULT_SESSION_ID): Promise<AppState | null> {
  const resp = await fetch(url(sessionId));
  if (!resp.ok) throw new Error(`app-state ${resp.status}`);
  const body = (await resp.json()) as { state: AppState | null };
  return body.state;
}

/** Store settings into the project: `replace` the whole set, or merge these keys (`null` removes one).
 *  Resolves false when no project is loaded. */
export async function pushAppState(
  state: Record<string, string | null>,
  replace: boolean,
  sessionId: string = DEFAULT_SESSION_ID,
): Promise<boolean> {
  const resp = await fetch(`${API_BASE}/api/session/app-state`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId, state, replace, source: 'browser' }),
  });
  return resp.ok;
}

/** The keys `next` changed against `base` (`null` = removed). */
export function diffAppState(base: AppState, next: AppState): Record<string, string | null> {
  const out: Record<string, string | null> = {};
  for (const [key, value] of Object.entries(next)) if (base[key] !== value) out[key] = value;
  for (const key of Object.keys(base)) if (!(key in next)) out[key] = null;
  return out;
}

// ── capture (every localStorage write -> debounced PUT) ─────────────────────────

const PUSH_DEBOUNCE_MS = 600;
let armed = false;
let muted = 0;
let timer: number | undefined;
let lastPushed: AppState | null = null;

function schedulePush(): void {
  if (!armed || muted > 0) return;
  if (timer !== undefined) window.clearTimeout(timer);
  timer = window.setTimeout(() => {
    timer = undefined;
    if (!armed) return;
    const state = snapshotAppState();
    // Only what THIS browser changed is sent (merged), so a setting another writer (an agent) changed in
    // the meantime is never overwritten by this browser's older copy. The first write of a project that
    // holds no settings yet stores the whole set.
    const base = lastPushed;
    const changes = base ? diffAppState(base, state) : state;
    if (base && Object.keys(changes).length === 0) return;
    void pushAppState(changes, base === null).then((ok) => { if (ok) lastPushed = state; }).catch(() => undefined);
  }, PUSH_DEBOUNCE_MS);
}

let installed = false;
/** Observe `localStorage` writes (idempotent). */
export function installAppStateCapture(): void {
  if (installed) return;
  const ls = storage();
  if (!ls) return;
  installed = true;
  const proto = Object.getPrototypeOf(ls) as Storage;
  const setItem = proto.setItem;
  const removeItem = proto.removeItem;
  proto.setItem = function patchedSetItem(this: Storage, key: string, value: string) {
    setItem.call(this, key, value);
    if (this === ls && isProjectKey(key)) schedulePush();
  };
  proto.removeItem = function patchedRemoveItem(this: Storage, key: string) {
    removeItem.call(this, key);
    if (this === ls && isProjectKey(key)) schedulePush();
  };
}

/** Start writing settings into the project (after it is known which project's they are). */
export function armAppStateCapture(knownState: AppState | null): void {
  lastPushed = knownState;
  armed = true;
  schedulePush();
}

/** Stop writing: a different project is being loaded and its settings are not adopted yet. */
export function disarmAppStateCapture(): void {
  armed = false;
  if (timer !== undefined) window.clearTimeout(timer);
  timer = undefined;
}

// ── restore ─────────────────────────────────────────────────────────────────────

/** Before the first render: make the project's settings the browser's. Never throws. */
export async function restoreAtBoot(
  tooLate: () => boolean = () => false,
  sessionId: string = DEFAULT_SESSION_ID,
): Promise<void> {
  installAppStateCapture();
  let state: AppState | null = null;
  try {
    state = await fetchAppState(sessionId);
  } catch {
    return; // backend unreachable: the app boots on the browser's own values and does not write
  }
  // The app already rendered without waiting: leave it; the boot rehydrate's adoptProjectAppState applies them.
  if (tooLate()) return;
  if (state && Object.keys(state).length > 0 && !sameAppState(state, snapshotAppState())) applyAppState(state);
  // A project with no settings yet (state {}) takes the browser's; with no project (null) nothing is written
  // until one is loaded (adoptProjectAppState arms it then).
  if (state !== null) armAppStateCapture(Object.keys(state).length > 0 ? state : null);
}

/**
 * After a project was loaded into the session (or an agent changed its settings): adopt them. Returns true
 * when the page is reloading to apply them (callers stop there).
 *
 * The project's settings are compared with the set this browser last synced with the project, NOT with
 * `localStorage`: the app itself writes view state while it mounts, and comparing with that would reload
 * every time (a loop). Only a different project, or a change made elsewhere, reloads.
 */
export async function adoptProjectAppState(sessionId: string = DEFAULT_SESSION_ID): Promise<boolean> {
  disarmAppStateCapture();
  let state: AppState | null;
  try {
    state = await fetchAppState(sessionId);
  } catch {
    if (lastPushed) armAppStateCapture(lastPushed);
    return false;
  }
  if (state === null) return false; // no project: nothing to write into
  if (Object.keys(state).length === 0) {
    armAppStateCapture(null); // the project carries no settings: it takes the current ones
    return false;
  }
  const baseline = lastPushed ?? snapshotAppState();
  if (sameAppState(state, baseline)) {
    armAppStateCapture(baseline); // the same project as this browser's: keep syncing local changes into it
    return false;
  }
  applyAppState(state);
  lastPushed = state;
  window.location.reload();
  return true;
}
