import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';
import { ConfigBootstrap } from './ConfigBootstrap';

/**
 * Wipe stale, build-coupled state when the bundle ID changes.
 *
 * `REACT_APP_BUILD_ID` is baked at compile time (see `package.json`):
 *   • `npm start`  → `dev-<unix-seconds>`   (changes every dev-server boot)
 *   • `npm run build` → `v<pkg.version>-<unix-seconds>` (changes per build)
 *
 * On every page load the client compares the running bundle's ID to the
 * ID it last persisted. A mismatch means the user is on a fresh build —
 * we clear DERIVED / VOLATILE state (grid layout, view selection, the
 * cached config bundle) so the new code starts from clean defaults and
 * lands on the Welcome tab.
 *
 * CRITICAL: we must NOT wipe USER-OWNED CONTENT — things the user
 * explicitly created or installed and expects to persist until they
 * remove them. Installed plugins and BYOK API keys are the prime
 * examples: before this guard, every dev-server restart minted a new
 * build_id and silently uninstalled every plugin and erased every saved
 * API key (`ragnarok:secret:*`), so users had to re-enter keys on each
 * restart. The PRESERVE list below protects both. (API keys live only in
 * this browser's localStorage — a local, never-committed store — and are
 * still wiped by the explicit "Clear cache" button.)
 *
 * `pypsa_gui_settings` is reset on a build change too (see WIPE_KEYS): app
 * settings are derived from the app's *current* defaults, so a new build /
 * restart / deploy must re-sync them — a value cached in one browser must
 * never pin a stale default (e.g. an old solver method) over a changed one.
 * That keeps the tool web-based rather than hostage to one browser's history.
 * `ragnarok_enabled_modules` and installed plugins are user-owned, not
 * settings, and survive.
 */
const BUILD_ID = process.env.REACT_APP_BUILD_ID || 'untagged';
const BUILD_ID_KEY = 'ragnarok:build-id';

// Wiped on a build change (derived / volatile state).
const WIPE_PREFIXES = ['pypsa.', 'ragnarok:', 'ui:'];
// Exact keys also wiped on a build change — app settings re-sync to the
// current defaults instead of persisting a stale cached value.
const WIPE_KEYS = ['pypsa_gui_settings'];
// Never wiped — user-owned content that persists until explicitly removed
// (installed plugins, and BYOK API keys the user typed into Settings).
const PRESERVE_PREFIXES = ['ragnarok:fe-plugins:', 'ragnarok:secret:'];

try {
  const stored = window.localStorage.getItem(BUILD_ID_KEY);
  if (stored !== BUILD_ID) {
    const doomed: string[] = [];
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const key = window.localStorage.key(i);
      if (!key) continue;
      if (key === BUILD_ID_KEY) continue;
      if (PRESERVE_PREFIXES.some((p) => key.startsWith(p))) continue;
      if (WIPE_PREFIXES.some((p) => key.startsWith(p)) || WIPE_KEYS.includes(key)) {
        doomed.push(key);
      }
    }
    for (const key of doomed) window.localStorage.removeItem(key);
    window.localStorage.setItem(BUILD_ID_KEY, BUILD_ID);
  }
} catch {
  /* storage unavailable — first-load defaults apply naturally */
}

const root = ReactDOM.createRoot(
  document.getElementById('root') as HTMLElement
);
root.render(
  <React.StrictMode>
    <ConfigBootstrap>
      <App />
    </ConfigBootstrap>
  </React.StrictMode>
);
