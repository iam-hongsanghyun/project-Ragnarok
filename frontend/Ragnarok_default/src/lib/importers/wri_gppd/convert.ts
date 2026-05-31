/**
 * WRI Global Power Plant Database — fetch + convert (browser-side).
 *
 * Port of `backend/app/importers/databases/wri_gppd/importer.py`. Self-
 * contained: slug / dedupe / provenance / fuel mapping live in this file.
 *
 * Output generator rows carry **every column** from the upstream CSV
 * alongside the schema-required name / bus / carrier / p_nom / coordinates.
 * Optional PyPSA attributes (`marginal_cost`, `efficiency`, `co2_emissions`,
 * `capital_cost`, `lifetime`, …) are **never fabricated** — empty cells fall
 * through to PyPSA's own component defaults at solve time.
 */
import booleanPointInPolygon from '@turf/boolean-point-in-polygon';
import type { Feature, Polygon, MultiPolygon, Point } from 'geojson';

import type { PreviewSummary, WorkbookFragment } from 'lib/api/databases';
import type { ConvertOptions, DatabaseModule, FetchResult } from '../types';
import { wriGppdMeta } from './meta';
import { loadAllRows } from './fetch';
import carrierMapData from './carrier_map.json';

// ── Carrier map ──────────────────────────────────────────────────────────────

function carrierMapping(): Record<string, string> {
  return { ...(carrierMapData as { fuel_to_carrier?: Record<string, string> })
    .fuel_to_carrier };
}

function mapFuel(fuel: string | undefined, mapping: Record<string, string>): string {
  if (!fuel) return 'Other';
  const key = fuel.trim().toLowerCase();
  for (const [src, target] of Object.entries(mapping)) {
    if (src.trim().toLowerCase() === key) return target;
  }
  return 'Other';
}

// ── Slug + dedupe (per-module) ───────────────────────────────────────────────

const NAME_RE = /[^A-Za-z0-9_]+/g;

function slug(raw: string | null | undefined, fallback: string = 'asset'): string {
  if (!raw) return fallback;
  const s = String(raw).trim().replace(NAME_RE, '_').replace(/^_+|_+$/g, '');
  return s || fallback;
}

function dedupe(name: string, taken: Set<string>): string {
  if (!taken.has(name)) {
    taken.add(name);
    return name;
  }
  let i = 2;
  while (taken.has(`${name}_${i}`)) i++;
  const final = `${name}_${i}`;
  taken.add(final);
  return final;
}

// ── Parsed row shape ─────────────────────────────────────────────────────────

interface Plant {
  name: string;
  capacityMw: number;
  lat: number;
  lon: number;
  primaryFuel: string;
  countryIso: string;
  commissioningYear: number | null;
  owner: string;
  raw: Record<string, string>;
}

function parseFloatSafe(v: string | undefined | null): number | null {
  if (v === undefined || v === null || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function parseIntSafe(v: string | undefined | null): number | null {
  const f = parseFloatSafe(v);
  return f === null ? null : Math.trunc(f);
}

// ── Module ───────────────────────────────────────────────────────────────────

interface WRIPayload {
  plants: Plant[];
}

export const wriGppdModule: DatabaseModule<WRIPayload> = {
  meta: wriGppdMeta,

  async fetch(region, filters): Promise<FetchResult<WRIPayload>> {
    const mapping = carrierMapping();
    const rows = await loadAllRows();
    const [minLon, minLat, maxLon, maxLat] = region.bbox;
    const polygonFeature: Feature<Polygon | MultiPolygon> = {
      type: 'Feature',
      properties: {},
      geometry: region.polygon,
    };

    const wantedFuels = new Set(
      (Array.isArray(filters.fuels) ? filters.fuels : [])
        .filter((x) => typeof x === 'string')
        .map((x) => (x as string).toLowerCase()),
    );
    const minMw = parseFloatSafe(
      filters.min_capacity_mw === undefined || filters.min_capacity_mw === null
        ? null
        : String(filters.min_capacity_mw),
    );
    const maxMw = parseFloatSafe(
      filters.max_capacity_mw === undefined || filters.max_capacity_mw === null
        ? null
        : String(filters.max_capacity_mw),
    );
    const yearFrom = parseIntSafe(
      filters.commissioned_from === undefined || filters.commissioned_from === null
        ? null
        : String(filters.commissioned_from),
    );
    const yearTo = parseIntSafe(
      filters.commissioned_to === undefined || filters.commissioned_to === null
        ? null
        : String(filters.commissioned_to),
    );
    const ownerQ = String(filters.owner_contains || '').trim().toLowerCase();

    const plants: Plant[] = [];
    for (const row of rows) {
      const lat = parseFloatSafe(row.latitude);
      const lon = parseFloatSafe(row.longitude);
      if (lat === null || lon === null) continue;
      // Cheap bbox prefilter before the point-in-polygon test.
      if (lon < minLon || lon > maxLon || lat < minLat || lat > maxLat) continue;
      const point: Feature<Point> = {
        type: 'Feature',
        properties: {},
        geometry: { type: 'Point', coordinates: [lon, lat] },
      };
      if (!booleanPointInPolygon(point, polygonFeature)) continue;
      const capacity = parseFloatSafe(row.capacity_mw);
      if (capacity === null || capacity <= 0) continue;
      if (minMw !== null && capacity < minMw) continue;
      if (maxMw !== null && capacity > maxMw) continue;
      const year = parseIntSafe(row.commissioning_year);
      if (yearFrom !== null && (year === null || year < yearFrom)) continue;
      if (yearTo !== null && (year === null || year > yearTo)) continue;
      const owner = (row.owner || '').trim();
      if (ownerQ && !owner.toLowerCase().includes(ownerQ)) continue;
      const primaryFuel = (row.primary_fuel || '').trim();
      const carrier = mapFuel(primaryFuel, mapping);
      if (wantedFuels.size && !wantedFuels.has(carrier.toLowerCase())) continue;
      plants.push({
        name: (row.name || '').trim() || row.gppd_idnr || 'plant',
        capacityMw: capacity,
        lat,
        lon,
        primaryFuel,
        countryIso: region.countryIso,
        commissioningYear: year,
        owner,
        raw: { ...row },
      });
    }
    return {
      databaseId: wriGppdMeta.id,
      region,
      filters: { ...filters },
      payload: { plants },
    };
  },

  preview(result): PreviewSummary {
    const mapping = carrierMapping();
    const plants = result.payload.plants;
    const byCarrier: Record<string, number> = {};
    let totalCapacity = 0;
    for (const p of plants) {
      const carrier = mapFuel(p.primaryFuel, mapping);
      byCarrier[carrier] = (byCarrier[carrier] || 0) + 1;
      totalCapacity += p.capacityMw;
    }
    const samples = plants.slice(0, 10).map((p) => ({
      name: p.name,
      carrier: mapFuel(p.primaryFuel, mapping),
      capacity_mw: p.capacityMw,
      lat: p.lat,
      lon: p.lon,
    }));
    const overlay = {
      type: 'FeatureCollection' as const,
      features: plants.map((p) => ({
        type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates: [p.lon, p.lat] },
        properties: {
          name: p.name,
          carrier: mapFuel(p.primaryFuel, mapping),
          capacity_mw: p.capacityMw,
          kind: 'generator',
        },
      })),
    };
    const counts: Record<string, number> = {
      generators: plants.length,
      total_capacity_mw: Math.round(totalCapacity),
    };
    for (const [k, v] of Object.entries(byCarrier)) counts[`carrier:${k}`] = v;
    return {
      counts,
      samples: { generators: samples },
      notes: [`${plants.length} plants matched.`],
      overlay,
    };
  },

  toSheets(
    result: FetchResult<WRIPayload>,
    options: Required<ConvertOptions>,
  ): WorkbookFragment {
    const mapping = carrierMapping();
    const plants = result.payload.plants;
    const genRows: Array<Record<string, unknown>> = [];
    const busRows: Array<Record<string, unknown>> = [];
    const carrierRows: Array<Record<string, unknown>> = [];
    const usedCarriers = new Set<string>();
    const takenNames = new Set<string>();
    const takenBusNames = new Set<string>();

    for (const plant of plants) {
      const baseName = slug(plant.name, 'plant');
      const name = dedupe(baseName, takenNames);
      const carrier = mapFuel(plant.primaryFuel, mapping);
      let busName = '';
      if (options.createBusesForPlants) {
        busName = dedupe(name + options.plantBusSuffix, takenBusNames);
        busRows.push({
          name: busName,
          // Bus.v_nom not provided by WRI; leave empty (PyPSA default 1.0).
          x: plant.lon,
          y: plant.lat,
          country: plant.countryIso,
        });
      }
      // Schema-required identification + every WRI column verbatim.
      // marginal_cost / efficiency / co2_emissions / capital_cost / lifetime /
      // p_nom_extendable / p_min_pu / p_max_pu INTENTIONALLY ABSENT —
      // PyPSA defaults handle unset cells.
      const genRow: Record<string, unknown> = {
        name,
        bus: busName,
        carrier,
        p_nom: plant.capacityMw,
        x: plant.lon,
        y: plant.lat,
      };
      for (const [col, val] of Object.entries(plant.raw)) {
        if (col in genRow) continue;
        if (val === '' || val === null || val === undefined) continue;
        genRow[col] = val;
      }
      genRow.source = 'WRI GPPD';
      genRows.push(genRow);
      if (!usedCarriers.has(carrier)) {
        usedCarriers.add(carrier);
        // No co2_emissions / marginal_cost / capital_cost set — PyPSA
        // defaults apply at solve time.
        carrierRows.push({ name: carrier });
      }
    }

    const sheets: WorkbookFragment['sheets'] = {};
    if (genRows.length) sheets.generators = genRows;
    if (busRows.length) sheets.buses = busRows;
    if (carrierRows.length) sheets.carriers = carrierRows;
    const rowCounts: Record<string, number> = {};
    for (const [k, v] of Object.entries(sheets)) rowCounts[k] = v.length;

    return {
      sheets,
      provenance: {
        database_id: wriGppdMeta.id,
        country_iso: result.region.countryIso,
        country_name: result.region.countryName,
        filters_json: JSON.stringify(result.filters, Object.keys(result.filters).sort()),
        convert_options_json: JSON.stringify({}),
        fetch_timestamp: new Date().toISOString().slice(0, 19),
        row_counts_json: JSON.stringify(rowCounts, Object.keys(rowCounts).sort()),
      },
    };
  },
};
