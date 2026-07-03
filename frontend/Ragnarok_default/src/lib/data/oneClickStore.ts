/**
 * Persistent (across tab switches) store for the one-click location→model build.
 *
 * Same problem and fix as `dataImportStore`: the Data tab is rendered as
 * `{tab === 'Data' && <DataView ... />}`, so switching to another view unmounts
 * `DataImportView`. The one-click build used a LOCAL `useState` busy flag, so on
 * remount it reset to `false` — the "Build" button became clickable again while
 * the build was still running in the background (and the in-flight Promise's
 * result was orphaned). Holding the build lifecycle in this module-scoped store
 * makes the busy state — and the eventual result — survive the unmount.
 *
 * Single active build: starting a new one supersedes the previous (its late
 * resolution is ignored via a sequence number). A finished build parks in
 * `ready` until the Data view is present to apply its fragment, then `consume()`
 * returns the store to idle.
 */
import type { StarterPackBuild } from 'lib/api/starterPacks';
import { buildLocationModel } from 'lib/api/starterPacks';

export type OneClickStatus = 'idle' | 'building' | 'ready' | 'error';

export interface OneClickState {
  /** Monotonic id — discards late results from superseded builds. */
  seq: number;
  status: OneClickStatus;
  countryIso: string | null;
  countryName: string | null;
  /** The finished build awaiting apply (status === 'ready'). */
  build: StarterPackBuild | null;
  error: string | null;
}

type Listener = () => void;

const IDLE: OneClickState = {
  seq: 0, status: 'idle', countryIso: null, countryName: null, build: null, error: null,
};

let _state: OneClickState = IDLE;
let _seq = 0;
const _listeners = new Set<Listener>();

function emit(): void {
  _listeners.forEach((l) => l());
}

export const oneClickStore = {
  /** Snapshot for `useSyncExternalStore` (stable reference until state changes). */
  get(): OneClickState {
    return _state;
  },

  subscribe(listener: Listener): () => void {
    _listeners.add(listener);
    return () => {
      _listeners.delete(listener);
    };
  },

  /** Kick off a one-click build for a country. Supersedes any in-flight build. */
  start(countryIso: string, countryName: string): void {
    _seq += 1;
    const seq = _seq;
    _state = { seq, status: 'building', countryIso, countryName, build: null, error: null };
    emit();
    buildLocationModel(countryIso)
      .then((build) => {
        if (_state.seq !== seq) return; // superseded by a newer build / reset
        _state = { ..._state, status: 'ready', build, error: null };
        emit();
      })
      .catch((exc) => {
        if (_state.seq !== seq) return;
        _state = {
          ..._state,
          status: 'error',
          error: exc instanceof Error ? exc.message : 'One-click build failed.',
        };
        emit();
      });
  },

  /** Mark a `ready` build as applied → back to idle. No-op otherwise. */
  consume(): void {
    if (_state.status !== 'ready') return;
    _state = IDLE;
    emit();
  },

  /** Dismiss the current state (e.g. an error, or before starting fresh). */
  reset(): void {
    if (_state.status === 'idle') return;
    _state = IDLE;
    emit();
  },
};
