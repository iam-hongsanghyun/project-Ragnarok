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
 * Single-active-run, MULTI-PART model: one user "Fetch" may span several
 * sources (e.g. OSM transmission + WRI power plants ticked together). Each
 * source keeps its OWN filter blob — filter ids collide across sources
 * (`min_capacity_mw`, `date_from`, …) so the blobs must never be merged —
 * and becomes one `RunPart` with its own backend request and its own
 * status / preview / fragment. Starting a new run supersedes the old one;
 * late resolutions are ignored via a per-run sequence number.
 */
import type {
  PreviewSummary,
  RunImportResponse,
} from 'lib/api/databases';
import { runImport } from 'lib/api/databases';

export type RunStatus = 'fetching' | 'ready' | 'error';

/** One source's slice of the run: its datasets, filters, and result. */
export interface RunPart {
  sourceId: string;
  sourceLabel: string;
  /** The datasets the user selected for this source (pre dependency-expansion), sorted. */
  datasetIds: string[];
  datasetIdsJson: string;
  filtersJson: string;
  status: RunStatus;
  preview: PreviewSummary | null;
  response: RunImportResponse | null;
  error: string | null;
}

export interface Run {
  /** Monotonic id — used to discard late results from superseded runs. */
  seq: number;
  countryIso: string;
  countryName: string;
  startedAt: number;
  parts: RunPart[];
}

/** 'fetching' while any part is in flight; 'error' if any failed; else 'ready'. */
export function runStatus(run: Run): RunStatus {
  if (run.parts.some((p) => p.status === 'fetching')) return 'fetching';
  if (run.parts.some((p) => p.status === 'error')) return 'error';
  return 'ready';
}

type Listener = () => void;

let _run: Run | null = null;
let _seq = 0;
const _listeners = new Set<Listener>();

function emit(): void {
  _listeners.forEach((l) => l());
}

export interface StartPart {
  sourceId: string;
  sourceLabel: string;
  /** The datasets the user multi-selected within this source. */
  datasetIds: string[];
  /** This source's own filter blob (never merged across sources). */
  filters: Record<string, unknown>;
  /** Union of API-key names this source's selected datasets declare (BYOK). */
  requiresSecrets?: string[];
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
   * Kick off one fetch covering every selected source — one backend request
   * per part, in parallel. Any previous run is superseded; its results are
   * ignored when they eventually resolve.
   */
  start(args: { countryIso: string; countryName: string; parts: StartPart[] }): void {
    _seq += 1;
    const seq = _seq;
    _run = {
      seq,
      countryIso: args.countryIso,
      countryName: args.countryName,
      startedAt: Date.now(),
      parts: args.parts.map((p) => {
        const datasetIds = [...p.datasetIds].sort();
        return {
          sourceId: p.sourceId,
          sourceLabel: p.sourceLabel,
          datasetIds,
          datasetIdsJson: JSON.stringify(datasetIds),
          filtersJson: JSON.stringify(p.filters, Object.keys(p.filters).sort()),
          status: 'fetching' as RunStatus,
          preview: null,
          response: null,
          error: null,
        };
      }),
    };
    emit();

    args.parts.forEach((p) => {
      runImport({
        datasetIds: p.datasetIds,
        countryIso: args.countryIso,
        filters: p.filters,
        requiresSecrets: p.requiresSecrets,
      })
        .then((resp) => {
          // Drop the result if a newer run has started in the meantime.
          if (!_run || _run.seq !== seq) return;
          _run = {
            ..._run,
            parts: _run.parts.map((part) =>
              part.sourceId === p.sourceId
                ? { ...part, status: 'ready', preview: resp.preview, response: resp, error: null }
                : part,
            ),
          };
          emit();
        })
        .catch((exc) => {
          if (!_run || _run.seq !== seq) return;
          _run = {
            ..._run,
            parts: _run.parts.map((part) =>
              part.sourceId === p.sourceId
                ? { ...part, status: 'error', error: String(exc) }
                : part,
            ),
          };
          emit();
        });
    });
  },

  /** Drop the active run — e.g. user changed country, selection, or filters. */
  clear(): void {
    if (_run === null) return;
    _run = null;
    emit();
  },
};
