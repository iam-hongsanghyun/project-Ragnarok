import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';
import { ConfigBootstrap } from './ConfigBootstrap';

/**
 * Wipe persisted Ragnarok state when the bundle ID changes.
 *
 * `REACT_APP_BUILD_ID` is baked at compile time (see `package.json`):
 *   • `npm start`  → `dev-<unix-seconds>`   (changes every dev-server boot)
 *   • `npm run build` → `v<pkg.version>-<unix-seconds>` (changes per build)
 *
 * On every page load the client compares the running bundle's ID to the
 * ID it last persisted. A mismatch means the user is on a fresh build —
 * we wipe every Ragnarok-owned localStorage key so the new code starts
 * from a clean state and React's `usePersistedState` falls back to its
 * declared defaults (which routes the user to the Welcome tab).
 *
 * Prefixes wiped: `pypsa.*` (layout/grid), `ragnarok:*` (feature state),
 * `ui:*` (view state). Anything else stays — we never touch third-party
 * origin storage.
 */
const BUILD_ID = process.env.REACT_APP_BUILD_ID || 'untagged';
const BUILD_ID_KEY = 'ragnarok:build-id';
try {
  const stored = window.localStorage.getItem(BUILD_ID_KEY);
  if (stored !== BUILD_ID) {
    const doomed: string[] = [];
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const key = window.localStorage.key(i);
      if (!key) continue;
      if (
        key.startsWith('pypsa.') ||
        key.startsWith('ragnarok:') ||
        key.startsWith('ui:')
      ) {
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
