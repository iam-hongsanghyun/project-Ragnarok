/**
 * LogPane — Analytics → Log sub-tab.
 *
 * Event-driven backend log viewer. Fetches the in-process log buffer from
 * /api/log:
 *   1. once when the pane mounts (so opening the tab shows everything up to
 *      now — startup logs, all prior requests, the last solve transcript);
 *   2. when the rest of the app dispatches the `ragnarok:log-refresh`
 *      custom DOM event — fired by App.tsx after a solve completes and
 *      after file imports/exports settle;
 *   3. on user click of the Refresh button.
 *
 * Deliberately no continuous polling. The earlier 2 s loop made the buffer
 * fill with logs about itself polling. Now the log only updates around
 * meaningful backend events, and the user can force a refresh manually.
 *
 * Buffer covers uvicorn HTTP access, uvicorn errors, anything via Python
 * `logging.*`, and exception tracebacks. Solver C-stdout (HiGHS verbose
 * dump) is not captured — would need fd-level redirection.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';

interface LogEntry {
  /** ISO 8601 timestamp string. */
  ts: string;
  /** Logger name (e.g., 'uvicorn.access', 'backend.app.main', 'root'). */
  logger: string;
  /** Log level: DEBUG / INFO / WARNING / ERROR / CRITICAL. */
  level: string;
  /** The formatted log message. May contain newlines for tracebacks. */
  message: string;
}

interface LogResponse {
  entries: LogEntry[];
  /** Monotonic counter of *every* entry ever added to the backend buffer
   *  (not capped by capacity). Lets the client detect drop-on-overflow. */
  cursor: number;
  /** Buffer capacity (oldest entries are dropped past this). */
  capacity: number;
}

/**
 * Custom DOM event name. App.tsx dispatches this whenever a backend event
 * the user would care about has finished — primarily run completion and
 * file imports/exports. The pane re-fetches on every dispatch.
 */
export const LOG_REFRESH_EVENT = 'ragnarok:log-refresh';

const LEVEL_CLASS: Record<string, string> = {
  DEBUG: 'log-line--debug',
  INFO: 'log-line--info',
  WARNING: 'log-line--warn',
  ERROR: 'log-line--error',
  CRITICAL: 'log-line--error',
};

export function LogPane() {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [cursor, setCursor] = useState<number>(0);
  const [capacity, setCapacity] = useState<number>(0);
  const [lastFetchedAt, setLastFetchedAt] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const stickyBottomRef = useRef<boolean>(true);

  const fetchOnce = useCallback(async () => {
    try {
      const r = await fetch('/api/log');
      if (!r.ok) {
        setError(`HTTP ${r.status}`);
        return;
      }
      const data = (await r.json()) as LogResponse;
      setError(null);
      setEntries(data.entries);
      setCursor(data.cursor);
      setCapacity(data.capacity);
      setLastFetchedAt(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  // Initial fetch + subscribe to refresh events. No interval.
  useEffect(() => {
    fetchOnce();
    const handler = () => { fetchOnce(); };
    window.addEventListener(LOG_REFRESH_EVENT, handler);
    return () => window.removeEventListener(LOG_REFRESH_EVENT, handler);
  }, [fetchOnce]);

  // Track whether the user has scrolled away from the bottom — if so,
  // don't snap them back when new lines arrive.
  const onScroll = () => {
    const el = bodyRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 8;
    stickyBottomRef.current = atBottom;
  };

  // After each render with new entries, scroll to bottom only if the
  // user was already at the bottom.
  useEffect(() => {
    if (stickyBottomRef.current && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [cursor]);

  const droppedSinceStart = capacity > 0 && cursor > capacity ? cursor - capacity : 0;

  return (
    <div className="log-pane">
      <div className="log-pane-toolbar">
        <span className="log-pane-status">
          {error
            ? `Error: ${error}`
            : entries.length === 0
              ? 'No log entries.'
              : `${entries.length} entries · cursor ${cursor}${droppedSinceStart > 0 ? ` · ${droppedSinceStart} dropped past buffer (cap ${capacity})` : ''}${lastFetchedAt ? ` · fetched ${lastFetchedAt.toLocaleTimeString()}` : ''}`}
        </span>
        <button type="button" className="tb-btn tb-btn--muted" onClick={fetchOnce}>
          Refresh
        </button>
      </div>
      <div className="log-pane-body" ref={bodyRef} onScroll={onScroll}>
        {entries.length === 0 ? (
          <p className="log-pane-empty">
            No log entries yet. The pane refreshes automatically when a run
            finishes or a file op completes — or click <strong>Refresh</strong>.
          </p>
        ) : (
          entries.map((e, i) => (
            <div key={`${cursor}-${i}`} className={`log-line ${LEVEL_CLASS[e.level] ?? ''}`}>
              <span className="log-line-ts">{e.ts}</span>
              <span className="log-line-level">{e.level}</span>
              <span className="log-line-logger">{e.logger}</span>
              <span className="log-line-msg">{e.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
