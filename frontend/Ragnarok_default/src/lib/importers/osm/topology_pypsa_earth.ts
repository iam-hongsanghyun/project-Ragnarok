/**
 * PyPSA-Earth-style OSM topology cleanup.
 *
 * The plain "raw" pipeline in `convert.ts` keeps OSM geometry verbatim:
 * each substation is its own bus, each line stops at the OSM-reported
 * endpoint, and lines that physically cross a substation are *not* split.
 * That preserves data but leaves disconnected components — fine for
 * inspection, bad for an optimisation solve.
 *
 * PyPSA-Earth cleans this up with three operations (see
 * `pypsa-meets-earth/pypsa-earth/scripts/build_osm_network.py`):
 *
 *   1. DBSCAN-cluster substations within 5 km (one station_id per cluster),
 *      then one bus per (station_id, voltage). Two OSM substations that
 *      are really one site collapse to one station with multiple buses.
 *   2. Force every line endpoint to its nearest cluster bus (no distance
 *      cap). Endpoints that fall in the middle of nowhere create a new
 *      synthetic single-bus station at the endpoint coords first.
 *   3. Split lines that pass through an intermediate substation —
 *      `shapely.ops.snap + split` in PyPSA-Earth; here we project each
 *      substation onto each line and break at projected points whose
 *      perpendicular distance falls under a tolerance.
 *
 * Transformer rows between consecutive voltage levels at the same station
 * are still emitted (matches PyPSA-Earth's `get_transformers()`).
 *
 * Every OSM tag is still preserved on each emitted row as `osm_*` —
 * the only thing PyPSA-Earth-style mode rewrites is *topology*, not
 * upstream column data.
 */
import type { WorkbookFragment } from 'lib/api/databases';
import type { Region } from '../types';

import type { Parsed, Substation, Line } from './topology_types';
import {
  slug,
  dedupe,
  haversineKm,
  polylineLengthKm,
  lineTypeFor,
} from './topology_helpers';

// Tuneable thresholds. Match PyPSA-Earth's defaults where they have one.
const CLUSTER_EPS_KM = 5.0;
const SPLIT_TOLERANCE_KM = 0.1; // PyPSA-Earth uses 1 m post-snap; we use
//                                 100 m because OSM line geometry follows
//                                 roads/right-of-way, not substation
//                                 centroids, but anything bigger
//                                 over-splits in dense urban networks
//                                 (Korea, Japan, Netherlands).
const MERGE_COORD_PRECISION = 1e6; // ~10 cm — OSM-shared node coords are
//                                    bit-identical so any precision is
//                                    safe; this absorbs float noise.

// ── Stitch contiguous OSM ways into logical lines (`linemerge`-equivalent) ──
//
// OSM frequently splits a single physical transmission corridor into many
// short `way`s — at administrative boundaries, where the line crosses a
// road, where different editors drew different sections. Each shows up as
// a separate row in the workbook unless we stitch them back.
//
// Two ways are mergeable iff they share an endpoint coordinate AND have
// matching (voltage, circuits, cable/overhead, AC/DC) — i.e. the OSM tags
// say it is the same physical line. Shared endpoints come from referencing
// the same OSM `node`, so their coordinates are bit-identical and rounding
// at 10 cm precision matches reliably.

function coordKey(lat: number, lon: number): string {
  return `${Math.round(lat * MERGE_COORD_PRECISION)}_${Math.round(lon * MERGE_COORD_PRECISION)}`;
}

function groupKey(line: Line): string {
  return [
    Math.round(line.voltageKv),
    line.circuits,
    line.isCable ? 'C' : 'O',
    Math.round(line.frequencyHz),
  ].join('|');
}

function concatLines(
  a: Line,
  b: Line,
  mode: 'append-fwd' | 'append-rev' | 'prepend-fwd' | 'prepend-rev',
): Line {
  let coords: Array<[number, number]>;
  if (mode === 'append-fwd') {
    coords = [...a.geometry, ...b.geometry.slice(1)];
  } else if (mode === 'append-rev') {
    const rev = b.geometry.slice(0, -1).reverse();
    coords = [...a.geometry, ...rev];
  } else if (mode === 'prepend-fwd') {
    coords = [...b.geometry, ...a.geometry.slice(1)];
  } else {
    const rev = b.geometry.slice().reverse();
    coords = [...rev, ...a.geometry.slice(1)];
  }
  // Preserve provenance: the merged line carries every component osm_id.
  const aIds = (a.tags.osm_merged_ids || String(a.osmId)).split(',');
  const bIds = (b.tags.osm_merged_ids || String(b.osmId)).split(',');
  const merged: Line = {
    ...a,
    geometry: coords,
    lengthKm: polylineLengthKm(coords),
    tags: {
      ...a.tags,
      osm_merged_ids: Array.from(new Set([...aIds, ...bIds])).join(','),
    },
  };
  return merged;
}

function mergeContiguousLines(lines: Line[]): Line[] {
  // Bucket by compatibility so we never merge across voltage / cable /
  // circuit mismatches.
  const groups = new Map<string, Line[]>();
  for (const l of lines) {
    const k = groupKey(l);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k)!.push(l);
  }

  const out: Line[] = [];
  Array.from(groups.values()).forEach((group) => {
    // Greedy: take a line, repeatedly absorb any remaining line that
    // shares an endpoint with the current one. Loop until no absorption
    // happens in a full pass.
    const remaining = group.slice();
    while (remaining.length > 0) {
      let current = remaining.shift()!;
      let absorbed = true;
      while (absorbed) {
        absorbed = false;
        for (let i = 0; i < remaining.length; i++) {
          const other = remaining[i];
          const ms = coordKey(current.geometry[0][0], current.geometry[0][1]);
          const me = coordKey(
            current.geometry[current.geometry.length - 1][0],
            current.geometry[current.geometry.length - 1][1],
          );
          const os = coordKey(other.geometry[0][0], other.geometry[0][1]);
          const oe = coordKey(
            other.geometry[other.geometry.length - 1][0],
            other.geometry[other.geometry.length - 1][1],
          );
          if (me === os) current = concatLines(current, other, 'append-fwd');
          else if (me === oe) current = concatLines(current, other, 'append-rev');
          else if (ms === oe) current = concatLines(current, other, 'prepend-fwd');
          else if (ms === os) current = concatLines(current, other, 'prepend-rev');
          else continue;
          remaining.splice(i, 1);
          absorbed = true;
          break;
        }
      }
      out.push(current);
    }
  });
  return out;
}

// ── DBSCAN-equivalent clustering (eps, min_samples=1) ────────────────────────
//
// Naive O(n^2) is fine for typical country-scale n (~500-2000 substations).
// Each substation joins a cluster with anything inside CLUSTER_EPS_KM,
// transitively, via union-find.

function clusterSubstations(subs: Substation[], epsKm: number): number[] {
  const parent: number[] = subs.map((_, i) => i);
  const find = (x: number): number => {
    while (parent[x] !== x) {
      parent[x] = parent[parent[x]];
      x = parent[x];
    }
    return x;
  };
  const union = (a: number, b: number) => {
    const ra = find(a);
    const rb = find(b);
    if (ra !== rb) parent[ra] = rb;
  };
  for (let i = 0; i < subs.length; i++) {
    for (let j = i + 1; j < subs.length; j++) {
      const d = haversineKm(subs[i].lat, subs[i].lon, subs[j].lat, subs[j].lon);
      if (d <= epsKm) union(i, j);
    }
  }
  // Compact root indices to dense 0..k station_ids.
  const roots = new Map<number, number>();
  const stationOf: number[] = new Array(subs.length);
  for (let i = 0; i < subs.length; i++) {
    const r = find(i);
    if (!roots.has(r)) roots.set(r, roots.size);
    stationOf[i] = roots.get(r)!;
  }
  return stationOf;
}

// ── Project point onto segment in lon/lat (small-angle Cartesian) ────────────
//
// For perpendicular-distance and along-segment t-parameter, treating lon/lat
// as a local plane is accurate enough at country scale (< 1 % distance error
// for segments under a few hundred km). We do haversine only for the final
// distance check, where the small error compounds.

function projectOntoSegment(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
): { t: number; foot: [number, number] } {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return { t: 0, foot: [ax, ay] };
  const t = ((px - ax) * dx + (py - ay) * dy) / len2;
  const tc = Math.max(0, Math.min(1, t));
  return { t: tc, foot: [ax + tc * dx, ay + tc * dy] };
}

// ── Pre-split lines at intermediate substations ──────────────────────────────
//
// For each line, walk every segment and check every substation. If a
// substation's perpendicular foot lands inside the segment with distance
// under SPLIT_TOLERANCE_KM, record a split.

interface Split {
  segIndex: number;          // which segment of line.geometry to split
  t: number;                 // 0..1 along that segment
  point: [number, number];   // [lat, lon] of split point (= substation coords)
  subIdx: number;            // substation that triggered the split
}

interface SplitLine {
  parts: Line[];             // line broken into N pieces
  splitSubIndices: number[]; // (N-1) substation indices terminating each split
}

function splitLineAtSubstations(line: Line, subs: Substation[]): SplitLine {
  const splits: Split[] = [];
  const lineKv = Math.round(line.voltageKv);
  for (let s = 0; s < line.geometry.length - 1; s++) {
    const [aLat, aLon] = line.geometry[s];
    const [bLat, bLon] = line.geometry[s + 1];
    for (let si = 0; si < subs.length; si++) {
      const sub = subs[si];
      // Only split at substations that actually operate at the line's
      // voltage. A 22 kV city substation that happens to sit under a
      // 154 kV transmission corridor is not an electrical connection
      // for the 154 kV line and must not split it.
      if (!sub.voltagesKv.some((v) => Math.round(v) === lineKv)) continue;
      const { t, foot } = projectOntoSegment(
        sub.lon, sub.lat, aLon, aLat, bLon, bLat,
      );
      // Skip projections at the very ends (those are endpoints, not splits)
      if (t <= 0.001 || t >= 0.999) continue;
      const d = haversineKm(sub.lat, sub.lon, foot[1], foot[0]);
      if (d > SPLIT_TOLERANCE_KM) continue;
      splits.push({ segIndex: s, t, point: [sub.lat, sub.lon], subIdx: si });
    }
  }
  if (splits.length === 0) {
    return { parts: [line], splitSubIndices: [] };
  }
  // Order splits along the line.
  splits.sort((p, q) => (p.segIndex - q.segIndex) || (p.t - q.t));
  // Deduplicate near-identical splits (within ~10 m).
  const uniq: Split[] = [];
  for (const sp of splits) {
    const last = uniq[uniq.length - 1];
    if (
      last &&
      haversineKm(last.point[0], last.point[1], sp.point[0], sp.point[1]) < 0.01
    ) {
      continue;
    }
    uniq.push(sp);
  }

  // Walk geometry, breaking at each split point.
  const parts: Line[] = [];
  const splitSubs: number[] = [];
  let current: Array<[number, number]> = [line.geometry[0]];
  let cursorSeg = 0;
  for (const sp of uniq) {
    // Push the rest of the current segment up to the split.
    while (cursorSeg < sp.segIndex) {
      current.push(line.geometry[cursorSeg + 1]);
      cursorSeg++;
    }
    // Push the split point itself as the segment's terminator.
    current.push(sp.point);
    parts.push({
      ...line,
      geometry: current,
      lengthKm: polylineLengthKm(current),
    });
    splitSubs.push(sp.subIdx);
    // Start the next piece at the split point.
    current = [sp.point];
  }
  // Finish the tail.
  while (cursorSeg < line.geometry.length - 1) {
    current.push(line.geometry[cursorSeg + 1]);
    cursorSeg++;
  }
  if (current.length >= 2) {
    parts.push({
      ...line,
      geometry: current,
      lengthKm: polylineLengthKm(current),
    });
  }
  return { parts, splitSubIndices: splitSubs };
}

// ── Nearest cluster bus for an endpoint (no distance cap) ────────────────────

function nearestBusForVoltage(
  lat: number,
  lon: number,
  voltageKv: number,
  subs: Substation[],
  stationOf: number[],
  stationBuses: Map<string, string>,
): string | null {
  let bestBus: string | null = null;
  let bestD = Infinity;
  // First pass: prefer a bus at this voltage in any nearby cluster.
  for (let i = 0; i < subs.length; i++) {
    const s = subs[i];
    const bus = stationBuses.get(stationKey(stationOf[i], voltageKv));
    if (!bus) continue;
    const d = haversineKm(lat, lon, s.lat, s.lon);
    if (d < bestD) {
      bestD = d;
      bestBus = bus;
    }
  }
  if (bestBus) return bestBus;
  // Fallback: any bus in any cluster (different voltage).
  for (let i = 0; i < subs.length; i++) {
    const s = subs[i];
    const d = haversineKm(lat, lon, s.lat, s.lon);
    if (d >= bestD) continue;
    // Find any bus at this station (lowest voltage).
    for (const [k, v] of Array.from(stationBuses.entries())) {
      if (k.startsWith(`${stationOf[i]}|`)) {
        bestBus = v;
        bestD = d;
        break;
      }
    }
  }
  return bestBus;
}

function stationKey(stationId: number, voltageKv: number): string {
  return `${stationId}|${Math.round(voltageKv)}`;
}

// ── Public: build a PyPSA-Earth-style WorkbookFragment ───────────────────────

export function buildPyPSAEarthStyleSheets(
  parsed: Parsed,
  region: Region,
  typeMap: Record<number, string>,
): WorkbookFragment {
  const subs = parsed.substations.slice();

  // Step 1: stitch contiguous OSM ways into logical lines. OSM frequently
  // fragments one physical line into many ways; without this step the
  // workbook ends up with thousands of short lines instead of a few hundred
  // logical connections, which is what the user sees when they import a
  // dense country like Korea.
  const mergedLines = mergeContiguousLines(parsed.lines);

  // Synthesise a substation at every line endpoint not within
  // CLUSTER_EPS_KM of a real one. PyPSA-Earth's add_line_endings_tosubstations.
  for (const line of mergedLines) {
    for (const endpoint of [line.geometry[0], line.geometry[line.geometry.length - 1]]) {
      const [lat, lon] = endpoint;
      let near = false;
      for (const s of subs) {
        if (haversineKm(lat, lon, s.lat, s.lon) <= CLUSTER_EPS_KM) {
          near = true;
          break;
        }
      }
      if (!near) {
        subs.push({
          osmId: 0,
          osmType: 'synthetic_endpoint',
          lat,
          lon,
          voltagesKv: [line.voltageKv],
          tags: { name: '', power: 'substation_synthetic' },
        });
      }
    }
  }

  const stationOf = clusterSubstations(subs, CLUSTER_EPS_KM);
  const nStations = Math.max(...stationOf, -1) + 1;

  // For each station_id, the union of voltages present at all member substations.
  const stationVoltages: Set<number>[] = Array.from({ length: nStations }, () => new Set());
  const stationCentroid: Array<[number, number, number]> = Array.from(
    { length: nStations },
    () => [0, 0, 0],
  ); // [latSum, lonSum, count]
  const stationTags: Array<Record<string, string>> = Array.from(
    { length: nStations },
    () => ({}),
  );
  const stationOsmIds: Array<number[]> = Array.from({ length: nStations }, () => []);
  for (let i = 0; i < subs.length; i++) {
    const st = stationOf[i];
    for (const v of subs[i].voltagesKv) stationVoltages[st].add(Math.round(v));
    stationCentroid[st][0] += subs[i].lat;
    stationCentroid[st][1] += subs[i].lon;
    stationCentroid[st][2]++;
    // Keep tags from the first real substation we find in the cluster
    // (synthetic endpoints carry empty tag dicts).
    if (Object.keys(stationTags[st]).length === 0 && subs[i].osmId !== 0) {
      for (const [k, v] of Object.entries(subs[i].tags)) {
        if (v) stationTags[st][k] = v;
      }
    }
    if (subs[i].osmId !== 0) stationOsmIds[st].push(subs[i].osmId);
  }

  // Emit one bus per (station_id, voltage).
  const busRows: Array<Record<string, unknown>> = [];
  const busNames = new Set<string>();
  const stationBuses = new Map<string, string>();
  const transformerRows: Array<Record<string, unknown>> = [];
  const transformerNames = new Set<string>();

  for (let st = 0; st < nStations; st++) {
    if (stationCentroid[st][2] === 0) continue;
    const latC = stationCentroid[st][0] / stationCentroid[st][2];
    const lonC = stationCentroid[st][1] / stationCentroid[st][2];
    const voltages = Array.from(stationVoltages[st]).sort((a, b) => a - b);
    if (voltages.length === 0) continue;
    const base = slug(stationTags[st].name || `station_${st}`, 'station');
    for (const v of voltages) {
      const name = dedupe(`${base}_${v}kv`, busNames);
      stationBuses.set(stationKey(st, v), name);
      const row: Record<string, unknown> = {
        name,
        v_nom: v,
        x: lonC,
        y: latC,
        country: region.countryIso,
        station_id: st,
        osm_substation_ids: stationOsmIds[st].join(';'),
      };
      for (const [tk, tv] of Object.entries(stationTags[st])) {
        const key = `osm_${tk}`;
        if (key in row) continue;
        row[key] = tv;
      }
      row.source = 'OSM (PyPSA-Earth style)';
      busRows.push(row);
    }
    // Transformers between consecutive voltage levels.
    for (let i = 0; i < voltages.length - 1; i++) {
      const vLow = voltages[i];
      const vHigh = voltages[i + 1];
      const tName = dedupe(`${base}_tx_${vLow}_${vHigh}`, transformerNames);
      transformerRows.push({
        name: tName,
        bus0: stationBuses.get(stationKey(st, vLow))!,
        bus1: stationBuses.get(stationKey(st, vHigh))!,
        station_id: st,
        source: 'OSM (PyPSA-Earth style)',
      });
    }
  }

  // Split each line at intermediate substations, then snap endpoints.
  const lineRows: Array<Record<string, unknown>> = [];
  const lineNames = new Set<string>();
  for (const line of mergedLines) {
    const split = splitLineAtSubstations(line, subs);
    for (let pi = 0; pi < split.parts.length; pi++) {
      const part = split.parts[pi];
      const [startLat, startLon] = part.geometry[0];
      const [endLat, endLon] = part.geometry[part.geometry.length - 1];
      const bus0 = nearestBusForVoltage(
        startLat, startLon, part.voltageKv,
        subs, stationOf, stationBuses,
      );
      const bus1 = nearestBusForVoltage(
        endLat, endLon, part.voltageKv,
        subs, stationOf, stationBuses,
      );
      if (!bus0 || !bus1 || bus0 === bus1) continue; // drop self-loops
      const lineName = dedupe(
        slug(
          part.tags.name
            ? (split.parts.length > 1 ? `${part.tags.name}_p${pi}` : part.tags.name)
            : `osm_line_${part.osmId}_p${pi}`,
          'line',
        ),
        lineNames,
      );
      const typeRef = lineTypeFor(part.voltageKv, typeMap);
      const row: Record<string, unknown> = {
        name: lineName,
        bus0,
        bus1,
        length: part.lengthKm,
        v_nom: part.voltageKv,
        num_parallel: part.circuits,
        osm_id: part.osmId,
        is_cable: part.isCable,
      };
      if (typeRef) row.type = typeRef;
      if (split.parts.length > 1) row.osm_split_part = pi;
      for (const [tk, tv] of Object.entries(part.tags)) {
        if (!tv) continue;
        const key = `osm_${tk}`;
        if (key in row) continue;
        row[key] = tv;
      }
      row.source = 'OSM (PyPSA-Earth style)';
      lineRows.push(row);
    }
  }

  const sheets: WorkbookFragment['sheets'] = {};
  if (busRows.length) sheets.buses = busRows;
  if (lineRows.length) sheets.lines = lineRows;
  if (transformerRows.length) sheets.transformers = transformerRows;
  return { sheets };
}
