/**
 * The session's change stream, as plain data.
 *
 * Ragnarok holds the static workbook in browser memory and mirrors it to the
 * server session; temporal sheets are read from the server on demand. That was
 * fine while the user was the only author. Once an agent (Bifrost, MCP) writes to
 * the same session the two halves disagree in a way that looks like data loss:
 * the agent builds five buses, the server session HAS five buses, the temporal
 * sheets appear because those are fetched live — and the Bus grid reads 0 rows,
 * because nothing ever told the browser to re-read the static model.
 *
 * The journal publishes `session.version` with the ACTOR that caused it, so the
 * rule is: react when the change was not ours. That avoids the two traps a naive
 * "reload on every bump" would hit — a feedback loop against our own saves, and
 * discarding the user's in-progress edits each time they mirror them.
 *
 * No React here: `src/lib` is the pure-logic layer. The hook lives in
 * `shared/hooks/useSessionSync`.
 */
import { API_BASE } from 'lib/constants';
import { DEFAULT_SESSION_ID } from 'lib/api/session';

export interface SessionVersionEvent {
  sessionId: string;
  version: number;
  actor?: string;
  kind?: string;
  summary?: string;
  sheets?: { name?: string; kind?: string }[];
}

/**
 * Subscribe to changes made by someone OTHER than this browser.
 * Returns an unsubscribe; a no-op when EventSource is unavailable.
 */
export function subscribeForeignSessionChanges(
  onForeignChange: (event: SessionVersionEvent) => void,
  sessionId: string = DEFAULT_SESSION_ID,
): () => void {
  let source: EventSource;
  try {
    source = new EventSource(`${API_BASE}/api/events?session_id=${encodeURIComponent(sessionId)}`);
  } catch {
    return () => { /* no SSE (blocked, or an old browser): the app still works */ };
  }
  const onVersion = (event: MessageEvent) => {
    let data: SessionVersionEvent;
    try {
      data = JSON.parse(event.data) as SessionVersionEvent;
    } catch {
      return;  // a malformed frame must not kill the stream
    }
    // 'user' is this browser mirroring its own edits. Reacting would fight the
    // user's typing and loop against our own writes.
    if (!data || data.actor === 'user') return;
    onForeignChange(data);
  };
  source.addEventListener('session.version', onVersion as EventListener);
  return () => {
    source.removeEventListener('session.version', onVersion as EventListener);
    source.close();
  };
}
