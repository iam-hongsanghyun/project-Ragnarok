/**
 * Letting an embedding host point at a view.
 *
 * Ragnarok runs inside Bifrost's Ragnarok tab as an iframe, and that window was
 * one-way: the agent could change the model and the tab would repaint, but it
 * could not say "the congestion is on THIS corridor — look here". The user had to
 * switch tabs and hunt for whatever was being described, which is the wrong
 * disconnect for a tool whose premise is "ask in words, see the model".
 *
 * A cross-origin iframe is an untrusted channel in both directions, so this is
 * deliberately narrow:
 *
 *   - the message must come from THIS page's parent, and from an allowed origin
 *     (same-origin by default; `RAGNAROK_EMBED_ORIGINS`-style list via the
 *     `data-embed-origins` attribute on <html> for a dev host on another port);
 *   - `tab` is matched against a whitelist of known tab names — never assigned
 *     from arbitrary text, so a hostile frame cannot mount something unexpected;
 *   - `select` is passed through as data for the view to interpret, never
 *     evaluated, and never used to build a selector or a URL.
 *
 * Anything unrecognised is ignored silently: a page that logs loudly about
 * unknown postMessages is noisy in any app that shares the channel.
 */
import type { WorkspaceTab } from './types';

/** Tabs an embedder may navigate to. External module ids are deliberately absent:
 *  a host should not be able to mount a third-party tab. */
const NAVIGABLE: readonly string[] = [
  'Welcome', 'Build', 'Data', 'Forge', 'Model', 'Market', 'PostAnalysis',
  'Analytics', 'PhysicalRisk', 'Siting', 'History', 'Settings',
];

export interface ShowRequest {
  tab: WorkspaceTab;
  /** What to highlight once there — a bus, line or generator name. Data only. */
  select?: string;
  /** Optional sub-view hint, e.g. 'Map' or 'Table' on the Model tab. */
  view?: string;
}

function allowedOrigins(): string[] {
  const attr = document.documentElement.getAttribute('data-embed-origins') || '';
  const extra = attr.split(',').map((s) => s.trim()).filter(Boolean);
  return [window.location.origin, ...extra];
}

/**
 * Listen for `{type:'ragnarok:show', tab, select, view}` from the embedding host.
 * Returns an unsubscribe. `onShow` only ever receives a whitelisted tab.
 */
export function listenForShowRequests(onShow: (req: ShowRequest) => void): () => void {
  const handler = (event: MessageEvent) => {
    // Only the frame that embedded us, and only from an origin we accept.
    if (event.source !== window.parent || event.source === window) return;
    if (!allowedOrigins().includes(event.origin)) return;

    const data = event.data as Record<string, unknown> | null;
    if (!data || data.type !== 'ragnarok:show') return;

    const tab = typeof data.tab === 'string' ? data.tab : '';
    if (!NAVIGABLE.includes(tab)) return;

    onShow({
      tab: tab as WorkspaceTab,
      select: typeof data.select === 'string' ? data.select.slice(0, 200) : undefined,
      view: typeof data.view === 'string' ? data.view.slice(0, 40) : undefined,
    });
  };
  window.addEventListener('message', handler);
  return () => window.removeEventListener('message', handler);
}

/** True when Ragnarok is running inside another page (i.e. Bifrost's tab). */
export function isEmbedded(): boolean {
  return window.parent !== window;
}
