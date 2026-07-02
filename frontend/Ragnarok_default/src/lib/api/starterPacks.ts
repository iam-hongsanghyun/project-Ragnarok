/**
 * Country starter packs (W2) — recipe-assembled runnable workbooks.
 *
 * List the available packs, then build one: the backend runs the recipe's
 * importers for the country and returns a merged workbook fragment ready to
 * apply, so "pick a country + year → runnable model" is one call.
 */
import { API_BASE } from 'lib/constants';
import type { WorkbookFragment } from 'lib/api/databases';

export interface StarterPack {
  iso3: string;
  year: number | string;
  label: string;
  description: string;
  slots: string[];
}

export interface StarterPackBuild {
  iso3: string;
  year: number | string;
  label: string;
  datasetIds: string[];
  countryIso: string;
  fragment: WorkbookFragment;
}

export async function listStarterPacks(): Promise<StarterPack[]> {
  const resp = await fetch(`${API_BASE}/api/import/starter-packs`);
  if (!resp.ok) throw new Error(`Starter packs failed (${resp.status})`);
  return (await resp.json()).packs ?? [];
}

/** One-click (I1): auto-assemble a runnable model for any country from the
 *  keyless global importers (OSM network + plants, WRI fleet, World Bank demand). */
export async function buildLocationModel(iso3: string): Promise<StarterPackBuild> {
  const resp = await fetch(
    `${API_BASE}/api/import/location-model/${encodeURIComponent(iso3)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ secrets: {} }) },
  );
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json())?.detail ?? detail; } catch { /* non-JSON */ }
    throw new Error(`One-click model failed (${resp.status}): ${detail}`);
  }
  const body = await resp.json();
  return {
    iso3: body.iso3, year: 'auto', label: body.label,
    datasetIds: body.dataset_ids ?? [], countryIso: body.country_iso, fragment: body.fragment,
  };
}

export async function buildStarterPack(iso3: string, year: number | string): Promise<StarterPackBuild> {
  const resp = await fetch(
    `${API_BASE}/api/import/starter-packs/${encodeURIComponent(iso3)}/${encodeURIComponent(String(year))}/build`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ secrets: {} }) },
  );
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json())?.detail ?? detail; } catch { /* non-JSON */ }
    throw new Error(`Build failed (${resp.status}): ${detail}`);
  }
  const body = await resp.json();
  return {
    iso3: body.iso3, year: body.year, label: body.label,
    datasetIds: body.dataset_ids ?? [], countryIso: body.country_iso,
    fragment: body.fragment,
  };
}
