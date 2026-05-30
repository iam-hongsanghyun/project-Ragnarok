/**
 * LogPane — Analytics → Log sub-tab.
 *
 * Polls the backend `/api/log` endpoint every 2 seconds and renders every
 * captured log line in a scrollable mono panel. The buffer covers:
 *   - uvicorn HTTP request logs (uvicorn.access)
 *   - application logs (anything emitted via Python `logging.*`)
 *   - unhandled exceptions / tracebacks routed through the root logger
 *
 * Solver C-stdout (HiGHS verbose dump) is not currently captured — it
 * would need fd-level redirection. Listed as a follow-up in TODO.
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
  /** Monotonic counter of entries seen by the buffer (lets the client
   *  detect lost / overwritten lines on the next poll). */
  cursor: number;
  /** Buffer capacity (oldest entries are dropped past this). */
  capacity: number;
}

const POLL_INTERVAL_MS = 2000;

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
  const [error, setError] = useState<string | null>(null);
  const [paused, setPaused] = useState<boolean>(false);
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
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  // Poll loop.
  useEffect(() => {
    if (paused) return;
    fetchOnce();
    const id = window.setInterval(fetchOnce, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [fetchOnce, paused]);

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

  const onClear = () => {
    setEntries([]);
    setCursor(0);
  };

  return (
    <div className="log-pane">
      <div className="log-pane-toolbar">
        <span className="log-pane-status">
          {error ? `Error: ${error}` : `${entries.length} entries · cursor ${cursor}`}
        </span>
        <button
          type="button"
          className="tb-btn tb-btn--muted"
          onClick={() => setPaused((v) => !v)}
        >
          {paused ? 'Resume' : 'Pause'}
        </button>
        <button type="button" className="tb-btn tb-btn--muted" onClick={fetchOnce}>
          Refresh
        </button>
        <button type="button" className="tb-btn tb-btn--muted" onClick={onClear}>
          Clear view
        </button>
      </div>
      <div className="log-pane-body" ref={bodyRef} onScroll={onScroll}>
        {entries.length === 0 ? (
          <p className="log-pane-empty">No log entries yet.</p>
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
