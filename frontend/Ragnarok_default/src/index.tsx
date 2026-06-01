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
 * remove them. Installed plugins are the prime example: before this
 * guard, every dev-server restart minted a new build_id and silently
 * uninstalled every plugin. The PRESERVE list below protects them.
 *
 * Note: `pypsa_gui_settings` and `ragnarok_enabled_modules` use `_`
 * separators (not `.`/`:`) so they already fall outside the wiped
 * prefixes and survive untouched.
 */
const BUILD_ID = process.env.REACT_APP_BUILD_ID || 'untagged';
const BUILD_ID_KEY = 'ragnarok:build-id';

// Wiped on a build change (derived / volatile state).
const WIPE_PREFIXES = ['pypsa.', 'ragnarok:', 'ui:'];
// Never wiped — user-owned content that persists until explicitly removed.
const PRESERVE_PREFIXES = ['ragnarok:fe-plugins:'];

try {
  const stored = window.localStorage.getItem(BUILD_ID_KEY);
  if (stored !== BUILD_ID) {
    const doomed: string[] = [];
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const key = window.localStorage.key(i);
      if (!key) continue;
      if (key === BUILD_ID_KEY) continue;
      if (PRESERVE_PREFIXES.some((p) => key.startsWith(p))) continue;
      if (WIPE_PREFIXES.some((p) => key.startsWith(p))) {
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
