/**
 * Re-read the workbook when someone else changes the session.
 *
 * The React half of `lib/sessionEvents` — see there for why this exists (an
 * agent's edits landing in the session while the browser's static grids showed
 * stale, empty sheets).
 */
import { useEffect, useRef } from 'react';

import { SessionVersionEvent, subscribeForeignSessionChanges } from 'lib/sessionEvents';

export function useSessionSync(
  onForeignChange: (event: SessionVersionEvent) => void,
  { sessionId, enabled = true }: { sessionId?: string; enabled?: boolean } = {},
): void {
  // Held in a ref so re-renders do not tear down and rebuild the EventSource —
  // reconnecting on every keystroke would miss the events this exists for.
  const handler = useRef(onForeignChange);
  handler.current = onForeignChange;

  useEffect(() => {
    if (!enabled) return undefined;
    return subscribeForeignSessionChanges((event) => handler.current(event), sessionId);
  }, [sessionId, enabled]);
}
