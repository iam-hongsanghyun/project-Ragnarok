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

// Per-step toggles + numeric knobs, resolved from the user's filters by
// `resolveTopologyOptions` in convert.ts. PyPSA-Earth-style default is to
// turn every flag ON; "Raw" turns them all off; users can mix-and-match.
export interface TopologyOptions {
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
// ── Stitch contiguous OSM ways into logical lines (`linemerge`-equivalent) ──
//
// OSM frequently splits a single physical transmission corridor into many
// short `way`s — at administrative boundaries, where the line crosses a
// road, where different editors drew different sections. Each shows up as
// a separate row in the workbook unless we stitch them back.
//
// **Merge key = OSM node IDs.** Overpass returns each way's `nodes: number[]`
// alongside the resolved `geometry`. Two ways meeting at the same OSM node
// reference the *same* node ID, so endpoint comparison is bit-identical and
// independent of any rounding / precision tricks on coordinates. This is
// far more robust than coordinate matching for OSM data, which has plenty
// of editor-history quirks that leave near-but-not-bit-equal coordinates.
//
// Tag-level constraint: only voltage must match. OSM's `circuits` and
// `cable/overhead` tagging is inconsistent across editors and along the
// length of a single physical line, so requiring them to match prevents
// legitimate merges. After concatenation we keep the MAX `circuits`
// (taking sum would over-count parallel circuits each tagged with the
// full multiplicity, see the bus-pair collapse below).

function groupKey(line: Line): string {
  // Same voltage band, same AC/DC frequency split. Within that, anything
  // sharing a node is fair game.
  const dcMark = Math.abs(line.frequencyHz) <= 0.1 ? 'DC' : 'AC';
  return `${Math.round(line.voltageKv)}|${dcMark}`;
}

function concatLines(
  a: Line,
  b: Line,
  mode: 'append-fwd' | 'append-rev' | 'prepend-fwd' | 'prepend-rev',
): Line {
  let coords: Array<[number, number]>;
  let nodes: number[];
  if (mode === 'append-fwd') {
    coords = [...a.geometry, ...b.geometry.slice(1)];
    nodes = [...a.nodes, ...b.nodes.slice(1)];
  } else if (mode === 'append-rev') {
    coords = [...a.geometry, ...b.geometry.slice(0, -1).reverse()];
    nodes = [...a.nodes, ...b.nodes.slice(0, -1).reverse()];
  } else if (mode === 'prepend-fwd') {
    coords = [...b.geometry, ...a.geometry.slice(1)];
    nodes = [...b.nodes, ...a.nodes.slice(1)];
  } else {
    coords = [...b.geometry.slice().reverse(), ...a.geometry.slice(1)];
    nodes = [...b.nodes.slice().reverse(), ...a.nodes.slice(1)];
  }
  // Preserve provenance: the merged line carries every component osm_id.
  const aIds = (a.tags.osm_merged_ids || String(a.osmId)).split(',');
  const bIds = (b.tags.osm_merged_ids || String(b.osmId)).split(',');
  return {
    ...a,
    geometry: coords,
    nodes,
    lengthKm: polylineLengthKm(coords),
    circuits: Math.max(a.circuits, b.circuits),
    isCable: a.isCable && b.isCable, // overhead wins if either is overhead
    tags: {
      ...a.tags,
      osm_merged_ids: Array.from(new Set([...aIds, ...bIds])).join(','),
    },
  };
}

function mergeContiguousLines(lines: Line[]): Line[] {
  const groups = new Map<string, Line[]>();
  for (const l of lines) {
    const k = groupKey(l);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k)!.push(l);
  }

  const out: Line[] = [];
  Array.from(groups.values()).forEach((group) => {
    // Greedy: take a line, repeatedly absorb any remaining line that
    // shares an endpoint NODE ID with the current one. Loop until no
    // absorption happens in a full pass.
    const remaining = group.slice();
    while (remaining.length > 0) {
      let current = remaining.shift()!;
      let absorbed = true;
      while (absorbed) {
        absorbed = false;
        for (let i = 0; i < remaining.length; i++) {
          const other = remaining[i];
          // Skip degenerate lines that somehow lost their node array
          // (e.g. very old OSM imports). Coord-based fallback isn't worth
          // the risk; degenerate cases stay as-is and the bus-pair
          // collapse downstream catches them.
          if (current.nodes.length < 2 || other.nodes.length < 2) continue;
          const ms = current.nodes[0];
          const me = current.nodes[current.nodes.length - 1];
          const os = other.nodes[0];
          const oe = other.nodes[other.nodes.length - 1];
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

function splitLineAtSubstations(
  line: Line,
  subs: Substation[],
  toleranceKm: number,
): SplitLine {
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
      if (d > toleranceKm) continue;
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
  maxDistanceKm: number = Infinity,
): string | null {
  let bestBus: string | null = null;
  let bestD = Infinity;
  // First pass: prefer a bus at this voltage in any nearby cluster.
  for (let i = 0; i < subs.length; i++) {
    const s = subs[i];
    const bus = stationBuses.get(stationKey(stationOf[i], voltageKv));
    if (!bus) continue;
    const d = haversineKm(lat, lon, s.lat, s.lon);
    if (d > maxDistanceKm) continue;
    if (d < bestD) {
      bestD = d;
      bestBus = bus;
    }
  }
  if (bestBus) return bestBus;
  // Fallback: any bus in any cluster (different voltage), still within
  // maxDistanceKm so the "snap with cap" mode doesn't reach across the map.
  for (let i = 0; i < subs.length; i++) {
    const s = subs[i];
    const d = haversineKm(lat, lon, s.lat, s.lon);
    if (d > maxDistanceKm) continue;
    if (d >= bestD) continue;
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
  opts: TopologyOptions,
): WorkbookFragment {
  const subs = parsed.substations.slice();

  // Step 1: stitch contiguous OSM ways into logical lines (optional).
  // OSM frequently fragments one physical line into many ways; without
  // this step the workbook ends up with thousands of short lines
  // instead of a few hundred logical connections (Korea example).
  const mergedLines = opts.mergeFragments
    ? mergeContiguousLines(parsed.lines)
    : parsed.lines.slice();

  // Step 2: synthesise a substation at every line endpoint not within
  // the cluster radius of a real one (optional — PyPSA-Earth's
  // `add_line_endings_tosubstations`).
  if (opts.addLineEndings) {
    for (const line of mergedLines) {
      for (const endpoint of [line.geometry[0], line.geometry[line.geometry.length - 1]]) {
        const [lat, lon] = endpoint;
        let near = false;
        for (const s of subs) {
          if (haversineKm(lat, lon, s.lat, s.lon) <= opts.clusterEpsKm) {
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
  }

  // Step 3: DBSCAN cluster (optional). When off, each substation is its
  // own "cluster" (station_id = its index).
  const stationOf = opts.clusterSubstations
    ? clusterSubstations(subs, opts.clusterEpsKm)
    : subs.map((_, i) => i);
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
    // Step 4: transformers between consecutive voltage levels (optional).
    if (opts.emitTransformers) {
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
  }

  // Step 5: split each line at intermediate substations (optional), then
  // snap endpoints. When `snapEndpoints` is on, the snap has NO distance
  // cap (forces every endpoint to its nearest cluster bus, PyPSA-Earth's
  // behaviour). When off, a 5 km cap limits the snap to nearby buses;
  // endpoints with nothing within 5 km drop their lines.
  const snapMaxKm = opts.snapEndpoints ? Infinity : 5.0;
  const lineRows: Array<Record<string, unknown>> = [];
  const lineNames = new Set<string>();
  for (const line of mergedLines) {
    const split = opts.splitAtSubstations
      ? splitLineAtSubstations(line, subs, opts.splitToleranceKm)
      : { parts: [line], splitSubIndices: [] as number[] };
    for (let pi = 0; pi < split.parts.length; pi++) {
      const part = split.parts[pi];
      const [startLat, startLon] = part.geometry[0];
      const [endLat, endLon] = part.geometry[part.geometry.length - 1];
      const bus0 = nearestBusForVoltage(
        startLat, startLon, part.voltageKv,
        subs, stationOf, stationBuses, snapMaxKm,
      );
      const bus1 = nearestBusForVoltage(
        endLat, endLon, part.voltageKv,
        subs, stationOf, stationBuses, snapMaxKm,
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

  // ── Step 4: collapse parallel & redundant connections ─────────────────────
  //
  // After merging, splitting, and endpoint snap, multiple line rows may end
  // up connecting the same (bus0, bus1) at the same voltage:
  //   • genuine parallel circuits (two physical towers between A and B),
  //   • OSM way fragments that didn't merge because of inconsistent
  //     `circuits` tagging or non-shared endpoints,
  //   • split-and-rejoin artefacts.
  //
  // For PyPSA the network only needs ONE row per pair-of-buses; the
  // `num_parallel` column carries the multiplicity. We collapse by
  // (min(bus0,bus1), max(bus0,bus1), v_nom) and take MAX (not SUM) of
  // num_parallel — taking the sum would over-count fragments-of-the-same-
  // line that all carry circuits=2, claiming 10× the real capacity.
  // Length is the max (all parallel candidates connect the same two buses,
  // so their lengths are within rounding of each other).
  //
  // The collapsed row carries every contributing osm_id as
  // `osm_merged_ids`, so the provenance trail is preserved.
  let collapsedLineRows: Array<Record<string, unknown>>;
  if (opts.collapseParallels) {
    const pairKey = (a: string, b: string, v: number) => {
      const lo = a < b ? a : b;
      const hi = a < b ? b : a;
      return `${lo}|${hi}|${Math.round(v)}`;
    };
    const byPair = new Map<string, Array<Record<string, unknown>>>();
    for (const row of lineRows) {
      const key = pairKey(
        String(row.bus0),
        String(row.bus1),
        Number(row.v_nom),
      );
      if (!byPair.has(key)) byPair.set(key, []);
      byPair.get(key)!.push(row);
    }
    collapsedLineRows = [];
    byPair.forEach((group) => {
      if (group.length === 1) {
        collapsedLineRows.push(group[0]);
        return;
      }
      const head = group[0];
      // Take max num_parallel + max length (see comment block above).
      let np = 0;
      let len = 0;
      const osmIds = new Set<string>();
      for (const r of group) {
        const npv = Number(r.num_parallel) || 1;
        if (npv > np) np = npv;
        const lv = Number(r.length) || 0;
        if (lv > len) len = lv;
        if (r.osm_id !== undefined && r.osm_id !== null) osmIds.add(String(r.osm_id));
        const merged = r.osm_merged_ids;
        if (typeof merged === 'string' && merged) {
          merged.split(',').forEach((id) => osmIds.add(id));
        }
      }
      const collapsed: Record<string, unknown> = { ...head };
      collapsed.num_parallel = np;
      collapsed.length = len;
      collapsed.osm_merged_ids = Array.from(osmIds).join(',');
      collapsed.osm_collapsed_count = group.length;
      delete collapsed.osm_split_part;
      collapsedLineRows.push(collapsed);
    });
  } else {
    collapsedLineRows = lineRows;
  }

  const sheets: WorkbookFragment['sheets'] = {};
  if (busRows.length) sheets.buses = busRows;
  if (collapsedLineRows.length) sheets.lines = collapsedLineRows;
  if (transformerRows.length) sheets.transformers = transformerRows;
  return { sheets };
}
