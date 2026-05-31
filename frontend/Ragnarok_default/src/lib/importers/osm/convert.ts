/**
 * OSM transmission importer — Overpass → workbook (browser-side).
 *
 * Two topology pipelines, switched by the right-rail filter
 * `topology_style` (`raw` | `pypsa_earth`):
 *
 *   raw         — current behaviour. One bus per (OSM substation, voltage).
 *                 Line endpoints snap to a substation within 5 km, otherwise
 *                 a synthetic endpoint bus is created. Through-lines are
 *                 NOT split at intermediate substations. Maximum geometry
 *                 fidelity, but the resulting network is often disconnected.
 *
 *   pypsa_earth — DBSCAN-clusters nearby substations (~5 km) into stations,
 *                 one bus per (station, voltage), endpoint snap with no
 *                 distance cap, and lines split at any intermediate
 *                 substation. See `topology_pypsa_earth.ts`.
 *
 * Output rows in both modes preserve **every OSM tag** verbatim as
 * `osm_*` columns. Optional PyPSA attributes (`r` / `x` / `b` / `s_nom` /
 * `carrier` / …) are **never fabricated** — empty cells fall through to
 * PyPSA defaults. Lines set `type` to a PyPSA standard-type name (from
 * `line_types.json`) for common voltages.
 */
import type { PreviewSummary, WorkbookFragment } from 'lib/api/databases';
import type {
  ConvertOptions,
  DatabaseModule,
  FetchResult,
  Region,
} from '../types';
import { osmMeta } from './meta';
import { buildQuery, postQuery, type OverpassResponse } from './fetch';
import { parseVoltageKv } from './voltage';
import type { Parsed, Substation, Line } from './topology_types';
import {
  slug,
  dedupe,
  haversineKm,
  polylineLengthKm,
  lineTypeMapping,
  lineTypeFor,
  endpointKey,
} from './topology_helpers';
import { buildPyPSAEarthStyleSheets } from './topology_pypsa_earth';

const SNAP_KM = 5.0;

// ── Tag helpers ──────────────────────────────────────────────────────────────

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
      // Require a parseable voltage on every substation and require its
      // max voltage to clear the user's threshold. Substations without a
      // voltage tag are almost always LV distribution noise.
      if (!voltages.length) continue;
      if (Math.max(...voltages) < minVoltageKv) continue;
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
      // OSM node IDs along the way. Endpoint node IDs are the gold-
      // standard merge key — two ways meeting at the same OSM node are
      // bit-identical at that endpoint and definitively belong to the
      // same physical line.
      const nodes = ((el as { nodes?: number[] }).nodes || []).map((n) => Number(n));
      const tagsAsStr: Record<string, string> = {};
      for (const [k, v] of Object.entries(tags)) {
        if (v === null || v === undefined) continue;
        tagsAsStr[k] = String(v);
      }
      lines.push({
        osmId: Number((el as { id?: number }).id || 0),
        geometry: points,
        nodes,
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

// ── Raw-topology endpoint resolver ───────────────────────────────────────────

interface EndpointCtx {
  substations: Substation[];
  substationBuses: Map<string, string>;
  busRows: Array<Record<string, unknown>>;
  busNames: Set<string>;
  countryIso: string;
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

// ── Raw-topology builder ─────────────────────────────────────────────────────

function buildRawSheets(
  parsed: Parsed,
  region: Region,
  typeMap: Record<number, string>,
): { fragment: WorkbookFragment; synthesisedBusCount: number } {
  const busRows: Array<Record<string, unknown>> = [];
  const lineRows: Array<Record<string, unknown>> = [];
  const transformerRows: Array<Record<string, unknown>> = [];
  const busNames = new Set<string>();
  const lineNames = new Set<string>();
  const transformerNames = new Set<string>();

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
  return { fragment: { sheets }, synthesisedBusCount };
}

// ── Public module ────────────────────────────────────────────────────────────

/**
 * The fetch step now PRE-BUILDS the workbook sheets (raw or cleaned-up
 * depending on the user's filters), and stores them in the payload alongside
 * the raw parsed OSM. preview() reports counts from the BUILT sheets so the
 * user sees the actual numbers the workbook will receive — not the raw
 * pre-cleanup counts that confused users when they didn't match the rows
 * landing in the workbook after PyPSA-Earth cleanup.
 */
interface OSMPayload {
  parsed: Parsed;
  rawCount: number;
  sheets: WorkbookFragment['sheets'];
  /** Resolved options that produced these sheets — surfaced in provenance. */
  resolvedOptions: ResolvedTopologyOptions;
}

type TopologyStyle = 'raw' | 'pypsa_earth';

export interface ResolvedTopologyOptions {
  style: TopologyStyle;
  mergeFragments: boolean;
  clusterSubstations: boolean;
  clusterEpsKm: number;
  addLineEndings: boolean;
  snapEndpoints: boolean;
  splitAtSubstations: boolean;
  splitToleranceKm: number;
  emitTransformers: boolean;
  collapseParallels: boolean;
}

function asBool(v: unknown, def: boolean): boolean {
  if (v === undefined || v === null) return def;
  if (typeof v === 'boolean') return v;
  return def;
}

function asNumber(v: unknown, def: number): number {
  if (v === undefined || v === null || v === '') return def;
  const n = Number(v);
  return Number.isFinite(n) ? n : def;
}

function resolveStyle(filters: Record<string, unknown>): TopologyStyle {
  const raw = String(filters.topology_style || 'raw').toLowerCase();
  return raw === 'pypsa_earth' ? 'pypsa_earth' : 'raw';
}

/**
 * Resolve the cleanup options from the user's filter blob.
 *
 *   • `topology_style = 'raw'` → all cleanup steps off regardless of toggles.
 *   • `topology_style = 'pypsa_earth'` → each step on by default, but the
 *     individual checkboxes can opt out (e.g. PyPSA-Earth WITHOUT splitting).
 */
export function resolveTopologyOptions(
  filters: Record<string, unknown>,
): ResolvedTopologyOptions {
  const style = resolveStyle(filters);
  if (style === 'raw') {
    return {
      style,
      mergeFragments: false,
      clusterSubstations: false,
      clusterEpsKm: 5,
      addLineEndings: false,
      snapEndpoints: false,
      splitAtSubstations: false,
      splitToleranceKm: 0.1,
      emitTransformers: false,
      collapseParallels: false,
    };
  }
  // PyPSA-Earth preset: defaults are ON, individual toggles can disable.
  return {
    style,
    mergeFragments: asBool(filters.merge_fragments, true),
    clusterSubstations: asBool(filters.cluster_substations, true),
    clusterEpsKm: asNumber(filters.cluster_eps_km, 5),
    addLineEndings: asBool(filters.add_line_endings, true),
    snapEndpoints: asBool(filters.snap_endpoints, true),
    splitAtSubstations: asBool(filters.split_at_substations, true),
    splitToleranceKm: asNumber(filters.split_tolerance_m, 100) / 1000,
    emitTransformers: asBool(filters.emit_transformers, true),
    collapseParallels: asBool(filters.collapse_parallels, true),
  };
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

    // Build the sheets ONCE here so preview and toSheets agree on counts.
    // The cleanup respects the user's per-step toggles (see meta.ts).
    const opts = resolveTopologyOptions(filters);
    const typeMap = lineTypeMapping();
    let sheets: WorkbookFragment['sheets'];
    if (opts.style === 'pypsa_earth') {
      sheets = buildPyPSAEarthStyleSheets(parsed, region, typeMap, opts).sheets;
    } else {
      sheets = buildRawSheets(parsed, region, typeMap).fragment.sheets;
    }

    return {
      databaseId: osmMeta.id,
      region,
      filters: { ...filters },
      payload: {
        parsed,
        rawCount: (payload.elements || []).length,
        sheets,
        resolvedOptions: opts,
      },
    };
  },

  preview(result): PreviewSummary {
    const { parsed, sheets } = result.payload;
    const lineRows = sheets.lines || [];
    const busRows = sheets.buses || [];
    const transformerRows = sheets.transformers || [];

    // Voltage histogram on the FINAL line rows (post-cleanup), not on the
    // raw OSM. That's what the user will actually see in the workbook.
    const voltages: Record<string, number> = {};
    let totalLength = 0;
    for (const row of lineRows) {
      const v = Math.round(Number(row.v_nom) || 0);
      const key = `${v} kV`;
      voltages[key] = (voltages[key] || 0) + 1;
      totalLength += Number(row.length) || 0;
    }

    // Map overlay still draws raw OSM geometry — that's the only place we
    // *want* to see the raw shapes (so the user can compare to OSM on the
    // tile basemap underneath).
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

    // Headline counts are deliberately bus/line/transformer (workbook-row
    // terminology) — not "substations", which previously confused users
    // because synthesized endpoint buses inflated that number above the
    // raw OSM substation count.
    const counts: Record<string, number> = {
      buses: busRows.length,
      lines: lineRows.length,
      transformers: transformerRows.length,
      length_km: Math.round(totalLength),
    };
    for (const [k, v] of Object.entries(voltages).sort(([a], [b]) => a.localeCompare(b))) {
      counts[`voltage:${k}`] = v;
    }

    // Single-line provenance note: how many rows we started with from
    // OSM vs how many landed in the workbook after the chosen cleanup.
    // Keeps the preview lean — the preset selector itself already tells
    // the user which mode they picked.
    const rawSubs = parsed.substations.length;
    const rawLines = parsed.lines.length;
    const finalSubs = busRows.length;
    const finalLines = lineRows.length;
    const subDelta = finalSubs !== rawSubs ? ` → ${finalSubs}` : '';
    const lineDelta = finalLines !== rawLines ? ` → ${finalLines}` : '';
    const rawSummary = `OSM input: ${rawSubs}${subDelta} substations · ${rawLines}${lineDelta} lines`;

    return {
      counts,
      samples: {
        lines: lineRows.slice(0, 10).map((row) => ({
          name: row.name,
          bus0: row.bus0,
          bus1: row.bus1,
          v_nom: row.v_nom,
          length_km: Math.round((Number(row.length) || 0) * 100) / 100,
          num_parallel: row.num_parallel,
        })),
        substations: busRows.slice(0, 10).map((row) => ({
          name: row.name,
          v_nom: row.v_nom,
          country: row.country,
        })),
      },
      notes: [rawSummary],
      overlay,
    };
  },

  toSheets(
    result: FetchResult<OSMPayload>,
    _options: Required<ConvertOptions>,
  ): WorkbookFragment {
    // Sheets were already built in fetch() — just package them with
    // provenance now. Keeps preview's reported counts identical to what
    // lands in the workbook.
    const { sheets, resolvedOptions } = result.payload;
    const region: Region = result.region;
    const rowCounts: Record<string, number> = {};
    for (const [k, v] of Object.entries(sheets)) rowCounts[k] = v.length;
    rowCounts.raw_osm_lines = result.payload.parsed.lines.length;
    rowCounts.raw_osm_substations = result.payload.parsed.substations.length;

    return {
      sheets,
      provenance: {
        database_id: osmMeta.id,
        country_iso: region.countryIso,
        country_name: region.countryName,
        filters_json: JSON.stringify(result.filters, Object.keys(result.filters).sort()),
        convert_options_json: JSON.stringify(resolvedOptions),
        fetch_timestamp: new Date().toISOString().slice(0, 19),
        row_counts_json: JSON.stringify(rowCounts, Object.keys(rowCounts).sort()),
      },
    };
  },
};
