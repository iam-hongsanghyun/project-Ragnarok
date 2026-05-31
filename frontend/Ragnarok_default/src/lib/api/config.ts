/**
 * Boot-bundle client.
 *
 * One round-trip to ``GET /api/config`` at app startup. The response
 * contains everything the frontend and backend must agree on:
 *
 *   • schema                — PyPSA component schema (computed live on
 *                             the backend from the installed pypsa
 *                             package)
 *   • standard_types        — built-in line / transformer catalogues
 *                             (same source)
 *   • network_import_policy — curated rule table
 *   • capabilities          — solver-backend capability list
 *   • simulation_defaults   — server-authoritative simulation knobs
 *   • build_id              — deterministic id of the bundle's content;
 *                             changes when the backend's PyPSA version
 *                             changes or when configs are updated. The
 *                             frontend keys its localStorage cache by
 *                             this value.
 *
 * Cache strategy (mirrors index.tsx's existing build-id wipe pattern):
 *
 *   1. On boot, GET /api/config/build-id (cheap).
 *   2. If localStorage has a cached bundle with the same build_id, use
 *      it — no full fetch needed.
 *   3. Otherwise GET /api/config and store the response keyed by the
 *      returned build_id; the next page load will skip the full GET.
 *   4. On hard failure (backend down + no cache), throw — the caller
 *      shows a connection-required error screen.
 */

const CACHE_KEY = 'ragnarok:config:bundle';
const CACHE_BUILD_ID_KEY = 'ragnarok:config:build-id';

export interface PypsaSchemaBundle {
  meta: {
    source?: string;
    pypsa_version?: string;
    generator?: string;
    note?: string;
    non_component_sheets?: string[];
    [k: string]: unknown;
  };
  components: Record<string, unknown>;
}

export interface PypsaStandardTypesBundle {
  meta?: Record<string, unknown>;
  line_types: Array<Record<string, unknown>>;
  transformer_types: Array<Record<string, unknown>>;
}

export interface NetworkImportPolicyBundle {
  fields: Array<{
    field: string;
    enabled_for_runtime_import: boolean;
    target: string;
    coercion: string;
    notes?: string;
  }>;
}

export interface SimulationDefaults {
  maxSnapshots: number;
  defaultSnapshotCount: number;
  defaultSnapshotWeight: number;
}

export interface ConfigBundle {
  schema: PypsaSchemaBundle;
  standard_types: PypsaStandardTypesBundle;
  network_import_policy: NetworkImportPolicyBundle;
  capabilities: Array<Record<string, unknown>>;
  simulation_defaults: SimulationDefaults;
  build_id: string;
  backend_version: string;
}

function readCache(): ConfigBundle | null {
  try {
    const raw = window.localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as ConfigBundle;
  } catch {
    return null;
  }
}

function writeCache(bundle: ConfigBundle): void {
  try {
    window.localStorage.setItem(CACHE_KEY, JSON.stringify(bundle));
    window.localStorage.setItem(CACHE_BUILD_ID_KEY, bundle.build_id);
  } catch {
    // Quota exceeded — silently ignore; the bundle still works for
    // this session, just won't survive a reload.
  }
}

/**
 * Cheap freshness probe — just the (build_id, backend_version) pair.
 * Used to decide whether the cached bundle is current.
 */
async function fetchBuildId(): Promise<{ build_id: string; backend_version: string }> {
  const resp = await fetch('/api/config/build-id');
  if (!resp.ok) {
    throw new Error(`GET /api/config/build-id failed (${resp.status})`);
  }
  return resp.json() as Promise<{ build_id: string; backend_version: string }>;
}

async function fetchFullBundle(): Promise<ConfigBundle> {
  const resp = await fetch('/api/config');
  if (!resp.ok) {
    throw new Error(`GET /api/config failed (${resp.status})`);
  }
  return resp.json() as Promise<ConfigBundle>;
}

/**
 * Load the boot bundle, preferring the localStorage cache when it
 * matches the backend's current build_id.
 *
 * Sequence:
 *   1. Hit /api/config/build-id (small, fast).
 *   2. If we have a cached bundle with that exact build_id → return it.
 *   3. Otherwise fetch the full bundle, cache, return.
 *
 * Throws on any network / parse failure. Caller is expected to render
 * a connection-required error in that case.
 */
export async function loadConfigBundle(): Promise<ConfigBundle> {
  const probe = await fetchBuildId();
  const cached = readCache();
  if (cached && cached.build_id === probe.build_id) {
    return cached;
  }
  const bundle = await fetchFullBundle();
  writeCache(bundle);
  return bundle;
}

/**
 * Hard refresh — fetch full bundle even if cache hits. Useful from a
 * "Reload schema" affordance in the future, or after a manual server
 * restart.
 */
export async function reloadConfigBundle(): Promise<ConfigBundle> {
  const bundle = await fetchFullBundle();
  writeCache(bundle);
  return bundle;
}
