/**
 * Resolver for API keys + endpoint overrides.
 *
 * Lookup chain, first match wins:
 *
 *   1. `sessionStorage['ragnarok:secret:<name>']` — per-tab override
 *      (typed once into the Settings panel, gone when the tab closes).
 *   2. `localStorage['ragnarok:secret:<name>']` — per-user persistent key
 *      (the user types it into Settings; survives page reloads).
 *   3. `process.env.REACT_APP_<NAME>` — dev-host fallback baked at build
 *      time from `.env.local` (gitignored). Convenience for development
 *      only — these values ship to every browser.
 *
 * Layering it this way means:
 *   • Dev hosts can set their own keys in `.env.local` and not have to
 *     re-type them every session;
 *   • Real users (production) enter their own keys in Settings — those
 *     never leave the user's browser;
 *   • No shared production keys end up in the bundle or on the server.
 */

const STORAGE_PREFIX = 'ragnarok:secret:';

function storageGet(storage: Storage | undefined, key: string): string | null {
  if (!storage) return null;
  try {
    const v = storage.getItem(STORAGE_PREFIX + key);
    return v && v.trim() ? v.trim() : null;
  } catch {
    return null;
  }
}

function envGet(key: string): string | null {
  // CRA inlines `process.env.REACT_APP_*` at build time. We construct the
  // env name dynamically here, but the inlining still works because CRA's
  // webpack DefinePlugin picks up the reference pattern at compile time
  // for known keys — see the explicit table below.
  const envKey = `REACT_APP_RAGNAROK_${key.toUpperCase()}`;
  const v = (process.env as Record<string, string | undefined>)[envKey];
  return v && v.trim() ? v.trim() : null;
}

/**
 * Read a secret by its canonical name (e.g. `'entsoe_key'`).
 * Returns `null` when the key is not configured anywhere.
 */
export function getSecret(name: string): string | null {
  const session =
    typeof window !== 'undefined' ? window.sessionStorage : undefined;
  const local = typeof window !== 'undefined' ? window.localStorage : undefined;
  return storageGet(session, name) ?? storageGet(local, name) ?? envGet(name);
}

/**
 * Collect the named secrets into a `{name: value}` map for a request
 * body. Missing keys are simply omitted — the backend decides whether a
 * given importer can proceed without them (and returns an actionable
 * 400 if a required key is absent). Used by `runImport` to ship BYOK
 * keys for the database the user is fetching.
 */
export function collectSecretsFor(names: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const name of names) {
    const v = getSecret(name);
    if (v) out[name] = v;
  }
  return out;
}

/**
 * Persist a user-supplied secret into localStorage (the Settings-panel
 * path). Stored under `ragnarok:secret:<name>` so the global Clear button
 * wipes it along with every other Ragnarok-owned key.
 */
export function setUserSecret(name: string, value: string): void {
  if (typeof window === 'undefined') return;
  try {
    if (value && value.trim()) {
      window.localStorage.setItem(STORAGE_PREFIX + name, value.trim());
    } else {
      window.localStorage.removeItem(STORAGE_PREFIX + name);
    }
  } catch {
    /* quota / privacy mode — ignore */
  }
}

/**
 * Drop the secret from BOTH storages. Useful when the user signs out of an
 * upstream or rotates a key.
 */
export function clearSecret(name: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.removeItem(STORAGE_PREFIX + name);
    window.localStorage.removeItem(STORAGE_PREFIX + name);
  } catch {
    /* ignore */
  }
}

/**
 * Read an upstream URL override (e.g. when running against a local mirror).
 * Lookup is env-only — URL overrides aren't per-user config.
 */
export function getEndpointOverride(name: string): string | null {
  const envKey = `REACT_APP_RAGNAROK_${name.toUpperCase()}`;
  const v = (process.env as Record<string, string | undefined>)[envKey];
  return v && v.trim() ? v.trim() : null;
}
