/**
 * Re-read server data when it changes elsewhere (an agent over MCP, another tab).
 *
 * App subscribes to the backend's `server.changed` stream once and re-broadcasts each event as a
 * window event; a view passes the API areas it shows (`'screening'`, `'plugins'`, ...) and a reload
 * function. Bursts are coalesced so a batch of agent writes triggers one re-read.
 */
import { useEffect, useRef } from 'react';

import { SERVER_CHANGED_EVENT, type ServerChangedEvent } from 'lib/sessionEvents';

export function useServerChange(
  areas: readonly string[],
  onChange: (event: ServerChangedEvent) => void,
  { debounceMs = 250 }: { debounceMs?: number } = {},
): void {
  const handler = useRef(onChange);
  handler.current = onChange;
  const key = areas.join('|');

  useEffect(() => {
    const wanted = new Set(key.split('|').filter(Boolean));
    let timer: ReturnType<typeof setTimeout> | null = null;
    const listener = (event: Event) => {
      const detail = (event as CustomEvent<ServerChangedEvent>).detail;
      if (!detail || !wanted.has(detail.area)) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        timer = null;
        handler.current(detail);
      }, debounceMs);
    };
    window.addEventListener(SERVER_CHANGED_EVENT, listener);
    return () => {
      window.removeEventListener(SERVER_CHANGED_EVENT, listener);
      if (timer) clearTimeout(timer);
    };
  }, [key, debounceMs]);
}
