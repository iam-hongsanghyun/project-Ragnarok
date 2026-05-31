/**
 * Dynamic discovery + raw-file fetch for the KPG193 dataset.
 *
 * Everything that points at a specific path in the upstream repo lives
 * here, and every path is computed from a GitHub Contents API listing at
 * fetch time — never hard-coded — so newer dataset versions and newer
 * renewable-year snapshots appear automatically.
 *
 * Two GitHub URL forms in use:
 *
 *   • Contents API (JSON listing, CORS-enabled):
 *       https://api.github.com/repos/agm-center/kpg-testgrid/contents/<path>
 *   • Raw file (HTTP 302 → raw.githubusercontent.com, also CORS-enabled):
 *       https://github.com/agm-center/kpg-testgrid/raw/main/<path>
 *
 * Both are GitHub-hosted; the redirect through raw.githubusercontent.com
 * is GitHub's own CDN, not a third party.
 */

const REPO_OWNER = 'agm-center';
const REPO_NAME = 'kpg-testgrid';
const REPO_BRANCH = 'main';

interface ContentEntry {
  name: string;
  path: string;
  type: 'file' | 'dir' | 'symlink' | 'submodule';
  download_url: string | null;
}

function contentsUrl(path: string = ''): string {
  const base = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents`;
  return path ? `${base}/${path}` : base;
}

function rawUrl(path: string): string {
  return `https://github.com/${REPO_OWNER}/${REPO_NAME}/raw/${REPO_BRANCH}/${path}`;
}

async function listContents(path: string = ''): Promise<ContentEntry[]> {
  const resp = await fetch(contentsUrl(path));
  if (!resp.ok) {
    throw new Error(
      `KPG193 listing failed (${resp.status}) for ${path || '<root>'}: ${resp.statusText}`,
    );
  }
  const body = (await resp.json()) as ContentEntry[] | { message?: string };
  if (!Array.isArray(body)) {
    throw new Error(
      `KPG193 listing returned non-array for ${path || '<root>'}: ${(body as { message?: string }).message || 'unknown'}`,
    );
  }
  return body;
}

async function fetchText(path: string): Promise<string> {
  const resp = await fetch(rawUrl(path));
  if (!resp.ok) {
    throw new Error(`KPG193 raw fetch failed (${resp.status}) for ${path}: ${resp.statusText}`);
  }
  return resp.text();
}

// ── Discovery ────────────────────────────────────────────────────────────────

/** Compare semver-ish version strings like "v1_5" / "v2_0" / "1.5". */
function compareVersionTag(a: string, b: string): number {
  const norm = (s: string) =>
    s
      .replace(/^v/i, '')
      .replace(/_/g, '.')
      .split('.')
      .map((p) => parseInt(p, 10) || 0);
  const av = norm(a);
  const bv = norm(b);
  const n = Math.max(av.length, bv.length);
  for (let i = 0; i < n; i++) {
    const diff = (av[i] || 0) - (bv[i] || 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

/** Return the kpg193_v* directory names sorted ascending by version. */
export async function discoverVersions(): Promise<string[]> {
  const root = await listContents();
  const versions = root
    .filter((e) => e.type === 'dir' && /^kpg193_v/i.test(e.name))
    .map((e) => e.name);
  versions.sort((a, b) => compareVersionTag(a.replace(/^kpg193_/, ''), b.replace(/^kpg193_/, '')));
  return versions;
}

/** Return the available renewable-year integers inside a version dir. */
export async function discoverRenewableYears(versionDir: string): Promise<number[]> {
  const entries = await listContents(`${versionDir}/renewables_capacity`);
  const years = new Set<number>();
  for (const e of entries) {
    const m = e.name.match(/_generators_(\d{4})\.csv$/);
    if (m) years.add(parseInt(m[1], 10));
  }
  return Array.from(years).sort((a, b) => a - b);
}

// ── Resolved paths ───────────────────────────────────────────────────────────

export interface ResolvedKpg193Paths {
  versionDir: string;     // e.g. "kpg193_v1_5"
  versionTag: string;     // e.g. "v1_5"
  renewableYear: number;  // e.g. 2022
  matpowerPath: string;
  busLocationPath: string;
  solarPath: string;
  windPath: string;
  hydroPath: string;
}

/**
 * Resolve user filter values to actual repo paths, using discovery for
 * any value the user left at `latest`. Throws if the repo is empty / the
 * pinned version doesn't exist / the pinned year doesn't exist.
 */
export async function resolvePaths(
  filters: { version?: string; renewable_year?: string | number },
): Promise<ResolvedKpg193Paths> {
  const versions = await discoverVersions();
  if (versions.length === 0) {
    throw new Error('KPG193: no kpg193_v* directories found in the upstream repo');
  }

  const requestedVersion = String(filters.version || 'latest').trim();
  let versionDir: string;
  if (requestedVersion === 'latest' || requestedVersion === '') {
    versionDir = versions[versions.length - 1];
  } else {
    // Accept either "v1_5" or "kpg193_v1_5".
    const wanted = requestedVersion.startsWith('kpg193_')
      ? requestedVersion
      : `kpg193_${requestedVersion}`;
    const match = versions.find(
      (v) => v.toLowerCase() === wanted.toLowerCase(),
    );
    if (!match) {
      throw new Error(
        `KPG193: version "${requestedVersion}" not found. Available: ${versions.join(', ')}`,
      );
    }
    versionDir = match;
  }

  const years = await discoverRenewableYears(versionDir);
  const requestedYear = String(filters.renewable_year || 'latest').trim();
  let renewableYear: number;
  if (requestedYear === 'latest' || requestedYear === '') {
    renewableYear = years.length ? years[years.length - 1] : 0;
  } else {
    const wantedYear = parseInt(requestedYear, 10);
    if (!years.includes(wantedYear)) {
      throw new Error(
        `KPG193: renewable year "${requestedYear}" not found in ${versionDir}. Available: ${years.join(', ')}`,
      );
    }
    renewableYear = wantedYear;
  }

  const versionTag = versionDir.replace(/^kpg193_/, '');
  // Build the file paths the same way the Python build_kpg193_pypsa.py
  // expects them. The MATPOWER .m file is named KPG193_ver<tag>.m using
  // the tag form (e.g. "KPG193_ver1_5.m") — we derive that from the
  // directory name to stay generic.
  const matFileTag = versionTag.replace(/^v/i, ''); // "1_5"
  return {
    versionDir,
    versionTag,
    renewableYear,
    matpowerPath: `${versionDir}/network/m/KPG193_ver${matFileTag}.m`,
    busLocationPath: `${versionDir}/network/location/bus_location.csv`,
    solarPath: `${versionDir}/renewables_capacity/solar_generators_${renewableYear}.csv`,
    windPath: `${versionDir}/renewables_capacity/wind_generators_${renewableYear}.csv`,
    hydroPath: `${versionDir}/renewables_capacity/hydro_generators_${renewableYear}.csv`,
  };
}

// ── Raw-file fetchers ────────────────────────────────────────────────────────

export async function fetchMatpowerText(path: string): Promise<string> {
  return fetchText(path);
}

export async function fetchBusLocationCsv(path: string): Promise<string> {
  return fetchText(path);
}

export async function fetchRenewableCsv(path: string): Promise<string | null> {
  try {
    return await fetchText(path);
  } catch {
    // Renewable year CSV may not exist for every (version, carrier) tuple.
    return null;
  }
}
