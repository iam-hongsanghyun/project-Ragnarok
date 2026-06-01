/**
 * Persistent (across tab switches) store for the active OSM/WRI/etc. fetch.
 *
 * Why this exists: in App.tsx the Data tab is rendered as
 *
 *   {tab === 'Data' && <DataView ... />}
 *
 * so switching to Model / Build unmounts `DataImportView`. The browser-side
 * `runImport()` Promise keeps running regardless — `fetch()` is not
 * cancelled by React unmount — but its eventual `setState` calls land on
 * a dead component and the result is silently dropped, forcing the user
 * to re-click Fetch when they come back.
 *
 * Fix: hold the fetch state in a tiny module-scoped store outside React.
 * The store survives view unmounts; `DataImportView` reads it via
 * `useSyncExternalStore` and writes to it via the `start` / `clear` API.
 * Bootstrap data (databases, countries, boundaries) already lives in the
 * registry's module-scope cache, so it survives unmount for free — the
 * only volatile state was the per-fetch progress, which is what this
 * store carries.
 *
 * Single-active-run model: the UI only lets the user kick off one fetch
 * at a time, so the store holds a single `Run` (or null). Starting a new
 * one supersedes the old one — the old Promise's resolution is ignored
 * via a per-run sequence number, so a late return from the old upstream
 * can't overwrite the new run's state.
 */
import type {
  PreviewSummary,
  RunImportResponse,
} from 'lib/api/databases';
import { runImport } from 'lib/api/databases';

export type RunStatus = 'fetching' | 'ready' | 'error';

export interface Run {
  /** Monotonic id — used to discard late results from superseded runs. */
  seq: number;
  sourceId: string;
  sourceLabel: string;
  /** The datasets the user selected (pre dependency-expansion), sorted. */
  datasetIds: string[];
  datasetIdsJson: string;
  countryIso: string;
  countryName: string;
  filtersJson: string;
  status: RunStatus;
  startedAt: number;
  preview: PreviewSummary | null;
  response: RunImportResponse | null;
  error: string | null;
}

type Listener = () => void;

let _run: Run | null = null;
let _seq = 0;
const _listeners = new Set<Listener>();

function emit(): void {
  _listeners.forEach((l) => l());
}

export const dataImportStore = {
  /** Snapshot for `useSyncExternalStore`. Returns the same reference until
   *  state changes, so React skips redundant re-renders. */
  get(): Run | null {
    return _run;
  },

  subscribe(listener: Listener): () => void {
    _listeners.add(listener);
    return () => {
      _listeners.delete(listener);
    };
  },

  /**
   * Kick off a fetch. Any previous run is superseded; its result will be
   * ignored when it eventually resolves.
   */
  start(args: {
    sourceId: string;
    sourceLabel: string;
    /** The datasets the user multi-selected (same source). */
    datasetIds: string[];
    countryIso: string;
    countryName: string;
    filters: Record<string, unknown>;
    /** Union of API-key names the selected datasets declare (BYOK) —
     *  forwarded to runImport so it can collect them from the secret store. */
    requiresSecrets?: string[];
  }): void {
    _seq += 1;
    const seq = _seq;
    const filtersJson = JSON.stringify(args.filters, Object.keys(args.filters).sort());
    const datasetIds = [...args.datasetIds].sort();
    const datasetIdsJson = JSON.stringify(datasetIds);
    _run = {
      seq,
      sourceId: args.sourceId,
      sourceLabel: args.sourceLabel,
      datasetIds,
      datasetIdsJson,
      countryIso: args.countryIso,
      countryName: args.countryName,
      filtersJson,
      status: 'fetching',
      startedAt: Date.now(),
      preview: null,
      response: null,
      error: null,
    };
    emit();

    runImport({
      datasetIds: args.datasetIds,
      countryIso: args.countryIso,
      filters: args.filters,
      requiresSecrets: args.requiresSecrets,
    })
      .then((resp) => {
        // Drop the result if a newer run has started in the meantime.
        if (!_run || _run.seq !== seq) return;
        _run = {
          ..._run,
          status: 'ready',
          preview: resp.preview,
          response: resp,
          error: null,
        };
        emit();
      })
      .catch((exc) => {
        if (!_run || _run.seq !== seq) return;
        _run = {
          ..._run,
          status: 'error',
          error: String(exc),
        };
        emit();
      });
  },

  /** Drop the active run — e.g. user changed country, database, or filters. */
  clear(): void {
    if (_run === null) return;
    _run = null;
    emit();
  },
};
