/**
 * OSM transmission importer — Overpass → workbook (browser-side).
 *
 * Port of `backend/app/importers/databases/osm/importer.py`. Self-contained:
 * slug / dedupe / provenance / line-type mapping live in this file.
 *
 * Output rows preserve **every OSM tag** verbatim on each substation-derived
 * bus row and each `power=line/cable` row. Optional PyPSA attributes
 * (`r` / `x` / `b` / `s_nom` / `carrier` / …) are **never fabricated** —
 * empty cells fall through to PyPSA defaults. Lines set `type` to a PyPSA
 * standard-type name (from `line_types.json`) for common voltages so PyPSA's
 * own catalogue supplies the electrical params at solve time.
 */
import type { PreviewSummary, WorkbookFragment } from '../../../../shared/api/databases';
import type {
  ConvertOptions,
  DatabaseModule,
  FetchResult,
  Region,
} from '../types';
import { osmMeta } from './meta';
import { buildQuery, postQuery, type OverpassResponse } from './fetch';
import { parseVoltageKv } from './voltage';
import lineTypesData from './line_types.json';

const SNAP_KM = 5.0;
const EARTH_KM = 6371.0;

// ── Line-type lookup ─────────────────────────────────────────────────────────

function lineTypeMapping(): Record<number, string> {
  const raw = (lineTypesData as { voltage_kv_to_type?: Record<string, string> })
    .voltage_kv_to_type || {};
  const out: Record<number, string> = {};
  for (const [k, v] of Object.entries(raw)) {
    out[parseInt(k, 10)] = String(v);
  }
  return out;
}

function lineTypeFor(voltageKv: number, mapping: Record<number, string>): string {
  return mapping[Math.round(voltageKv)] || '';
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

// ── Parsed Overpass elements ─────────────────────────────────────────────────

interface Substation {
  osmId: number;
  osmType: string;
  lat: number;
  lon: number;
  voltagesKv: number[];
  tags: Record<string, string>;
}

interface Line {
  osmId: number;
  geometry: Array<[number, number]>; // [lat, lon]
  lengthKm: number;
  voltageKv: number;
  frequencyHz: number;
  circuits: number;
  isCable: boolean;
  tags: Record<string, string>;
}

interface Parsed {
  substations: Substation[];
  lines: Line[];
}

// ── Geometry helpers ─────────────────────────────────────────────────────────

function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const lat1r = (lat1 * Math.PI) / 180;
  const lat2r = (lat2 * Math.PI) / 180;
  const dlat = lat2r - lat1r;
  const dlon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dlat / 2) ** 2 +
    Math.cos(lat1r) * Math.cos(lat2r) * Math.sin(dlon / 2) ** 2;
  return 2 * EARTH_KM * Math.asin(Math.sqrt(a));
}

function polylineLengthKm(points: Array<[number, number]>): number {
  let total = 0;
  for (let i = 0; i < points.length - 1; i++) {
    const [lat1, lon1] = points[i];
    const [lat2, lon2] = points[i + 1];
    total += haversineKm(lat1, lon1, lat2, lon2);
  }
  return total;
}

function elementCenter(el: Record<string, unknown>): [number, number] | null {
  if (typeof el.lat === 'number' && typeof el.lon === 'number') {
    return [el.lat as number, el.lon as number];
  }
  const geom = (el.geometry as Array<{ lat: number; lon: number }> | undefined) || [];
  if (geom.length) {
    let lats = 0;
    let lons = 0;
    for (const p of geom) {
      lats += p.lat;
      lons += p.lon;
    }
    return [lats / geom.length, lons / geom.length];
  }
  const center = el.center as { lat: number; lon: number } | undefined;
  if (center) return [center.lat, center.lon];
  return null;
}

function intTag(tags: Record<string, unknown>, key: string, def: number = 1): number {
  const raw = tags[key];
  if (raw === undefined || raw === null || raw === '') return def;
  const head = String(raw).split(';')[0];
  const v = parseInt(head, 10);
  return Number.isFinite(v) && v > 0 ? v : def;
}

function floatTag(tags: Record<string, unknown>, key: string, def: number): number {
  const raw = tags[key];
  if (raw === undefined || raw === null || raw === '') return def;
  const head = String(raw).split(';')[0];
  const v = parseFloat(head);
  return Number.isFinite(v) ? v : def;
}

// ── Overpass → parsed model ──────────────────────────────────────────────────

function parseResponse(payload: OverpassResponse, minVoltageKv: number): Parsed {
  const substations: Substation[] = [];
  const lines: Line[] = [];
  for (const el of payload.elements || []) {
    const tags = ((el as { tags?: Record<string, unknown> }).tags || {}) as Record<
      string,
      unknown
    >;
    const power = tags.power as string | undefined;
    const voltages = parseVoltageKv(tags.voltage as string | undefined);
    if (power === 'substation') {
      if (voltages.length && Math.max(...voltages) < minVoltageKv) continue;
      const center = elementCenter(el);
      if (!center) continue;
      const tagsAsStr: Record<string, string> = {};
      for (const [k, v] of Object.entries(tags)) {
        if (v === null || v === undefined) continue;
        tagsAsStr[k] = String(v);
      }
      substations.push({
        osmId: Number((el as { id?: number }).id || 0),
        osmType: String((el as { type?: string }).type || 'node'),
        lat: center[0],
        lon: center[1],
        voltagesKv: voltages,
        tags: tagsAsStr,
      });
      continue;
    }
    if (power === 'line' || power === 'cable') {
      if (!voltages.length) continue;
      const vMax = Math.max(...voltages);
      if (vMax < minVoltageKv) continue;
      const geom = (el.geometry as Array<{ lat: number; lon: number }> | undefined) || [];
      const points = geom.map((p) => [p.lat, p.lon] as [number, number]);
      if (points.length < 2) continue;
      const lengthKm = polylineLengthKm(points);
      if (lengthKm <= 0) continue;
      const tagsAsStr: Record<string, string> = {};
      for (const [k, v] of Object.entries(tags)) {
        if (v === null || v === undefined) continue;
        tagsAsStr[k] = String(v);
      }
      lines.push({
        osmId: Number((el as { id?: number }).id || 0),
        geometry: points,
        lengthKm,
        voltageKv: vMax,
        frequencyHz: floatTag(tags, 'frequency', 50.0),
        circuits: intTag(tags, 'circuits', 1),
        isCable: power === 'cable',
        tags: tagsAsStr,
      });
    }
  }
  return { substations, lines };
}

function nearestSubstation(
  lat: number,
  lon: number,
  subs: Substation[],
): { sub: Substation; distanceKm: number } | null {
  if (!subs.length) return null;
  let best: { sub: Substation; distanceKm: number } | null = null;
  for (const s of subs) {
    const d = haversineKm(lat, lon, s.lat, s.lon);
    if (!best || d < best.distanceKm) best = { sub: s, distanceKm: d };
  }
  return best;
}

// ── Endpoint resolver ────────────────────────────────────────────────────────

interface EndpointCtx {
  substations: Substation[];
  substationBuses: Map<string, string>; // key = `${osm_id}|${kv}`
  busRows: Array<Record<string, unknown>>;
  busNames: Set<string>;
  countryIso: string;
}

function endpointKey(osmId: number, kv: number): string {
  return `${osmId}|${kv}`;
}

function resolveEndpoint(
  lat: number,
  lon: number,
  vNomKv: number,
  ctx: EndpointCtx,
): { busName: string; synthesised: boolean } {
  const nearest = nearestSubstation(lat, lon, ctx.substations);
  if (nearest && nearest.distanceKm <= SNAP_KM) {
    const direct = ctx.substationBuses.get(endpointKey(nearest.sub.osmId, vNomKv));
    if (direct) return { busName: direct, synthesised: false };
    for (const v of [...nearest.sub.voltagesKv].sort((a, b) => a - b)) {
      const alt = ctx.substationBuses.get(endpointKey(nearest.sub.osmId, v));
      if (alt) return { busName: alt, synthesised: false };
    }
  }
  const synth = dedupe(
    `endpoint_${Math.abs(Math.trunc(lat * 1000))}_${Math.abs(Math.trunc(lon * 1000))}`,
    ctx.busNames,
  );
  ctx.busRows.push({
    name: synth,
    v_nom: vNomKv,
    x: lon,
    y: lat,
    country: ctx.countryIso,
    synthesised: true,
    source: 'OSM',
  });
  return { busName: synth, synthesised: true };
}

// ── Public module ────────────────────────────────────────────────────────────

interface OSMPayload {
  parsed: Parsed;
  rawCount: number;
}

export const osmModule: DatabaseModule<OSMPayload> = {
  meta: osmMeta,

  async fetch(region, filters): Promise<FetchResult<OSMPayload>> {
    const minKv = Number(filters.min_voltage_kv || 0);
    const includeCables = filters.include_cables !== false;
    const includeDc = filters.include_dc !== false;
    const query = buildQuery(region.polygon, {
      includeCables,
      includeDc,
      minVoltageV: Math.round(minKv * 1000),
    });
    const payload = await postQuery(query);
    const parsed = parseResponse(payload, minKv);
    return {
      databaseId: osmMeta.id,
      region,
      filters: { ...filters },
      payload: { parsed, rawCount: (payload.elements || []).length },
    };
  },

  preview(result): PreviewSummary {
    const parsed = result.payload.parsed;
    const voltages: Record<string, number> = {};
    for (const line of parsed.lines) {
      const key = `${Math.round(line.voltageKv)} kV`;
      voltages[key] = (voltages[key] || 0) + 1;
    }
    const totalLength = parsed.lines.reduce((s, l) => s + l.lengthKm, 0);
    const overlay = {
      type: 'FeatureCollection' as const,
      features: [
        ...parsed.lines.map((line) => ({
          type: 'Feature' as const,
          geometry: {
            type: 'LineString' as const,
            coordinates: line.geometry.map(([lat, lon]) => [lon, lat]),
          },
          properties: {
            kind: 'line',
            voltage_kv: line.voltageKv,
            length_km: line.lengthKm,
          },
        })),
        ...parsed.substations.map((s) => ({
          type: 'Feature' as const,
          geometry: { type: 'Point' as const, coordinates: [s.lon, s.lat] },
          properties: {
            kind: 'substation',
            voltages_kv: s.voltagesKv,
            name: (s.tags.name || '').trim() || `substation_${s.osmId}`,
          },
        })),
      ],
    };
    const counts: Record<string, number> = {
      substations: parsed.substations.length,
      lines: parsed.lines.length,
      total_length_km: Math.round(totalLength),
    };
    for (const [k, v] of Object.entries(voltages).sort(([a], [b]) => a.localeCompare(b))) {
      counts[`voltage:${k}`] = v;
    }
    return {
      counts,
      samples: {
        lines: parsed.lines.slice(0, 10).map((line) => ({
          osm_id: line.osmId,
          voltage_kv: line.voltageKv,
          length_km: Math.round(line.lengthKm * 100) / 100,
          circuits: line.circuits,
        })),
        substations: parsed.substations.slice(0, 10).map((s) => ({
          osm_id: s.osmId,
          voltages_kv: s.voltagesKv,
          name: (s.tags.name || '').trim(),
        })),
      },
      notes: [
        `${parsed.substations.length} substations, ${parsed.lines.length} lines.`,
      ],
      overlay,
    };
  },

  toSheets(
    result: FetchResult<OSMPayload>,
    _options: Required<ConvertOptions>,
  ): WorkbookFragment {
    const parsed = result.payload.parsed;
    const region: Region = result.region;
    const typeMap = lineTypeMapping();
    const busRows: Array<Record<string, unknown>> = [];
    const lineRows: Array<Record<string, unknown>> = [];
    const transformerRows: Array<Record<string, unknown>> = [];
    const busNames = new Set<string>();
    const lineNames = new Set<string>();
    const transformerNames = new Set<string>();

    // Substations → buses (one per voltage level) + transformers between
    // consecutive voltage levels at the same site.
    const substationBuses = new Map<string, string>();
    for (const s of parsed.substations) {
      const sorted = Array.from(new Set(s.voltagesKv)).sort((a, b) => a - b);
      const voltages = sorted.length ? sorted : [380.0];
      const base = slug(s.tags.name || `sub_${s.osmId}`, 'sub');
      for (const v of voltages) {
        const keyName = `${base}_${Math.round(v)}kv`;
        const busName = dedupe(keyName, busNames);
        substationBuses.set(endpointKey(s.osmId, v), busName);
        const row: Record<string, unknown> = {
          name: busName,
          v_nom: v,
          x: s.lon,
          y: s.lat,
          country: region.countryIso,
          osm_id: s.osmId,
          osm_type: s.osmType,
        };
        for (const [tk, tv] of Object.entries(s.tags)) {
          if (tv === '' || tv === undefined || tv === null) continue;
          const key = `osm_${tk}`;
          if (key in row) continue;
          row[key] = tv;
        }
        row.source = 'OSM';
        busRows.push(row);
      }
      for (let i = 0; i < voltages.length - 1; i++) {
        const vLower = voltages[i];
        const vUpper = voltages[i + 1];
        const tName = dedupe(
          `${base}_tx_${Math.round(vLower)}_${Math.round(vUpper)}`,
          transformerNames,
        );
        transformerRows.push({
          name: tName,
          bus0: substationBuses.get(endpointKey(s.osmId, vLower))!,
          bus1: substationBuses.get(endpointKey(s.osmId, vUpper))!,
          osm_substation_id: s.osmId,
          source: 'OSM',
        });
      }
    }

    // Lines → match endpoints to substations (or synthesise buses).
    const ctx: EndpointCtx = {
      substations: parsed.substations,
      substationBuses,
      busRows,
      busNames,
      countryIso: region.countryIso,
    };
    let synthesisedBusCount = 0;
    for (const line of parsed.lines) {
      const [startLat, startLon] = line.geometry[0];
      const [endLat, endLon] = line.geometry[line.geometry.length - 1];
      const a = resolveEndpoint(startLat, startLon, line.voltageKv, ctx);
      const b = resolveEndpoint(endLat, endLon, line.voltageKv, ctx);
      if (a.synthesised) synthesisedBusCount++;
      if (b.synthesised) synthesisedBusCount++;
      const lineName = dedupe(
        slug(line.tags.name || `osm_line_${line.osmId}`, 'line'),
        lineNames,
      );
      const typeRef = lineTypeFor(line.voltageKv, typeMap);
      const row: Record<string, unknown> = {
        name: lineName,
        bus0: a.busName,
        bus1: b.busName,
        length: line.lengthKm,
        v_nom: line.voltageKv,
        num_parallel: line.circuits,
        osm_id: line.osmId,
        is_cable: line.isCable,
      };
      if (typeRef) row.type = typeRef;
      for (const [tk, tv] of Object.entries(line.tags)) {
        if (tv === '' || tv === undefined || tv === null) continue;
        const key = `osm_${tk}`;
        if (key in row) continue;
        row[key] = tv;
      }
      row.source = 'OSM';
      lineRows.push(row);
    }

    const sheets: WorkbookFragment['sheets'] = {};
    if (busRows.length) sheets.buses = busRows;
    if (lineRows.length) sheets.lines = lineRows;
    if (transformerRows.length) sheets.transformers = transformerRows;

    const rowCounts: Record<string, number> = {};
    for (const [k, v] of Object.entries(sheets)) rowCounts[k] = v.length;
    rowCounts.synthesised_buses = synthesisedBusCount;

    return {
      sheets,
      provenance: {
        database_id: osmMeta.id,
        country_iso: region.countryIso,
        country_name: region.countryName,
        filters_json: JSON.stringify(result.filters, Object.keys(result.filters).sort()),
        convert_options_json: JSON.stringify({}),
        fetch_timestamp: new Date().toISOString().slice(0, 19),
        row_counts_json: JSON.stringify(rowCounts, Object.keys(rowCounts).sort()),
      },
    };
  },
};
