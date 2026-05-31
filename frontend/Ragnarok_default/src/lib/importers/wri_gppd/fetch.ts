/**
 * Browser fetch + CSV parse for the WRI Global Power Plant Database.
 *
 * Ported from `backend/app/importers/databases/wri_gppd/importer.py`. The
 * upstream is a single CSV in the WRI GitHub repo — the portal-side S3 URL
 * is rotated between releases; the raw GitHub copy is stable across the
 * v1.3.0 cohort and CORS-friendly for browser fetch.
 *
 * One process = one fetch: the parsed rows are held in module scope as a
 * read-only array, so subsequent fetches for different countries reuse the
 * same in-memory CSV instead of re-downloading.
 */
import Papa from 'papaparse';

const DEFAULT_URL =
  'https://raw.githubusercontent.com/wri/global-power-plant-database' +
  '/master/output_database/global_power_plant_database.csv';

function csvUrl(): string {
  return process.env.REACT_APP_RAGNAROK_WRI_GPPD_URL || DEFAULT_URL;
}

let _cachedRows: Array<Record<string, string>> | null = null;
let _fetchPromise: Promise<Array<Record<string, string>>> | null = null;

export async function loadAllRows(): Promise<Array<Record<string, string>>> {
  if (_cachedRows) return _cachedRows;
  if (_fetchPromise) return _fetchPromise;
  _fetchPromise = (async () => {
    const resp = await fetch(csvUrl());
    if (!resp.ok) {
      throw new Error(`WRI GPPD fetch failed (${resp.status}): ${resp.statusText}`);
    }
    const text = await resp.text();
    const parsed = Papa.parse<Record<string, string>>(text, {
      header: true,
      skipEmptyLines: true,
    });
    if (parsed.errors.length) {
      // Don't fail outright on cosmetic parse errors — log + carry on.
      // CSV files often have minor field-count quirks on the tail row.
      // eslint-disable-next-line no-console
      console.warn('WRI GPPD CSV parse produced errors', parsed.errors.slice(0, 3));
    }
    _cachedRows = parsed.data;
    return _cachedRows;
  })();
  return _fetchPromise;
}

/** Drop the cached CSV (used by tests). */
export function resetWriGppdCache(): void {
  _cachedRows = null;
  _fetchPromise = null;
}
