/**
 * KPG193 — MATPOWER + auxiliary CSVs → PyPSA workbook fragment.
 *
 * Mirrors the Python pipeline in simplePyPSA_KR/util/build_kpg193_pypsa.py
 * — including its column-mapping DSL — but performed in the browser. No
 * backend round-trip.
 *
 * Key bits of the conversion:
 *
 *   • baseMVA extracted from the .m header → used for the per-unit /
 *     ohms conversion on branches: z_base = v_nom_0² / baseMVA.
 *   • Buses merged with the bus_location.csv (x = Longitude, y = Latitude).
 *   • Generators = mpc.gen rows concatenated with their gencost + genthermal
 *     siblings (positional join — every block has one row per generator,
 *     same order). carrier filled from the `% <fuel>` row comment.
 *   • Renewable capacities (CSV per carrier) emit additional Generator
 *     rows with `control = PV`, `carrier = solar|wind|hydro`, p_nom from
 *     the CSV's Pmax column.
 *   • Branches split: transformer iff (ratio != 0 || angle != 0); other
 *     wise line. r/x converted from p.u. → ohms; b from p.u. → siemens.
 *   • DC lines (mpc.dcline) → PyPSA Link rows with p_min_pu, efficiency.
 */
import Papa from 'papaparse';

import type { PreviewSummary, WorkbookFragment } from 'lib/api/databases';
import type {
  ConvertOptions,
  DatabaseModule,
  FetchResult,
  Region,
} from '../types';

import { kpg193Meta } from './meta';
import {
  resolvePaths,
  fetchMatpowerText,
  fetchBusLocationCsv,
  fetchRenewableCsv,
  type ResolvedKpg193Paths,
} from './fetch';
import {
  extractScalar,
  extractBlockLines,
  parseMatrix,
  BUS_COLUMNS,
  GEN_COLUMNS,
  BRANCH_COLUMNS,
  DCLINE_COLUMNS,
  GENCOST_COLUMNS,
  GENTHERMAL_COLUMNS,
} from './parse';

// ── Bus location CSV ────────────────────────────────────────────────────────

interface BusLocationRow {
  bus_id: number;
  latitude: number;
  longitude: number;
  name_korean: string;
  name_english: string;
}

function parseBusLocation(csvText: string): Map<number, BusLocationRow> {
  const parsed = Papa.parse<Record<string, string>>(csvText, {
    header: true,
    skipEmptyLines: true,
  });
  const out = new Map<number, BusLocationRow>();
  for (const row of parsed.data) {
    // CSV header sometimes carries a UTF-8 BOM (﻿) on the first key.
    // Strip it and normalise.
    const norm: Record<string, string> = {};
    for (const [k, v] of Object.entries(row)) {
      norm[k.replace(/^﻿/, '').trim()] = (v ?? '').toString().trim();
    }
    const busId = parseInt(norm.bus_id || norm.bus_ID || '', 10);
    if (!Number.isFinite(busId)) continue;
    out.set(busId, {
      bus_id: busId,
      latitude: parseFloat(norm.Latitude || norm.latitude || ''),
      longitude: parseFloat(norm.Longitude || norm.longitude || ''),
      name_korean: norm.name_Korean || norm.name_korean || '',
      name_english: norm.name_English || norm.name_english || '',
    });
  }
  return out;
}

// ── Renewable capacity CSV ──────────────────────────────────────────────────

interface RenewableRow {
  bus: string;
  carrier: 'solar' | 'wind' | 'hydro';
  p_nom: number;
  p_nom_min: number;
}

function parseRenewableCsv(
  csvText: string,
  carrier: 'solar' | 'wind' | 'hydro',
): RenewableRow[] {
  const parsed = Papa.parse<Record<string, string>>(csvText, {
    header: true,
    skipEmptyLines: true,
  });
  const out: RenewableRow[] = [];
  for (const raw of parsed.data) {
    const row: Record<string, string> = {};
    for (const [k, v] of Object.entries(raw)) {
      row[k.replace(/^﻿/, '').trim()] = (v ?? '').toString().trim();
    }
    const busId = row.bus_ID || row.bus_id || row.bus;
    if (!busId) continue;
    // Header is one of: "Pmax [MW]", "Pmax", or "pmax". Find by prefix.
    const pmaxKey = Object.keys(row).find((k) => k.toLowerCase().startsWith('pmax'));
    const pminKey = Object.keys(row).find((k) => k.toLowerCase().startsWith('pmin'));
    if (!pmaxKey) continue;
    const pmax = parseFloat(row[pmaxKey] || '0');
    if (!Number.isFinite(pmax) || pmax <= 0) continue;
    out.push({
      bus: String(parseInt(busId, 10)),
      carrier,
      p_nom: pmax,
      p_nom_min: pminKey ? parseFloat(row[pminKey] || '0') || 0 : 0,
    });
  }
  return out;
}

// ── PyPSA bus / generator / load / line / transformer / link materialisers ──

type Row = Record<string, unknown>;

function controlFromMatpowerType(t: number): string {
  // MATPOWER bus.type: 1=PQ, 2=PV, 3=Slack/Reference, 4=Isolated.
  switch (Math.round(t)) {
    case 1: return 'PQ';
    case 2: return 'PV';
    case 3: return 'Slack';
    case 4: return 'Isolated';
    default: return 'PQ';
  }
}

function buildBuses(
  busRows: Row[],
  locations: Map<number, BusLocationRow>,
): Row[] {
  return busRows.map((row) => {
    const busId = Number(row.bus_i);
    const loc = locations.get(busId);
    return {
      name: String(busId),
      x: loc?.longitude ?? '',
      y: loc?.latitude ?? '',
      v_nom: Number(row.baseKV) || 0,
      carrier: 'AC',
      unit: 'kV',
      control: controlFromMatpowerType(Number(row.type)),
      v_mag_pu_set: Number(row.Vm) || 0,
      v_mag_pu_min: Number(row.Vmin) || 0,
      v_mag_pu_max: Number(row.Vmax) || 0,
      sub_network: 0,
      kpg193_bus_id: busId,
      kpg193_name_kr: loc?.name_korean ?? '',
      kpg193_name_en: loc?.name_english ?? '',
      source: 'KPG193',
    } as Row;
  });
}

function buildLoads(busRows: Row[]): Row[] {
  // Loads come from per-bus Pd/Qd. The mapping creates one load row per
  // bus, named `load_<bus_i>`, even where Pd = 0 — keeps the indexing
  // straightforward and PyPSA happily ignores zero-load entries.
  return busRows.map((row) => ({
    name: `load_${Number(row.bus_i)}`,
    bus: String(Number(row.bus_i)),
    carrier: 'load',
    p_set: Number(row.Pd) || 0,
    q_set: Number(row.Qd) || 0,
    sign: 1,
    source: 'KPG193',
  }));
}

function buildThermalGenerators(
  genRows: Row[],
  gencostRows: Row[],
  genthermalRows: Row[],
): Row[] {
  // Positional join: each block has the same row count and ordering.
  const n = genRows.length;
  const out: Row[] = [];
  for (let i = 0; i < n; i++) {
    const g = genRows[i];
    const c = gencostRows[i] || {};
    const t = genthermalRows[i] || {};
    const carrier =
      (g.gen_fuel as string) ||
      (c.gencost_fuel as string) ||
      (t.genthermal_fuel as string) ||
      '';
    const pmax = Number(g.Pmax) || 0;
    const pmin = Number(g.Pmin) || 0;
    out.push({
      name: `gen_${i + 1}`,
      bus: String(Number(g.bus)),
      control: 'PV',
      carrier,
      p_nom: pmax,
      p_nom_min: pmin,
      p_min_pu: pmax > 0 ? pmin / pmax : 0,
      p_max_pu: Number(g.status) || 1,
      p_set: Number(g.Pg) || 0,
      q_set: Number(g.Qg) || 0,
      marginal_cost: Number(c.c1) || 0,
      capital_cost: Number(c.startup) || 0,
      committable: true,
      source: 'KPG193',
    });
  }
  return out;
}

function buildRenewableGenerators(rows: RenewableRow[]): Row[] {
  return rows.map((r) => ({
    name: `gen_${r.carrier}_${r.bus}`,
    bus: r.bus,
    control: 'PV',
    carrier: r.carrier,
    p_nom: r.p_nom,
    p_nom_min: r.p_nom_min,
    p_min_pu: 0,
    p_max_pu: 1,
    p_set: 0,
    q_set: 0,
    marginal_cost: 0,
    capital_cost: 0,
    committable: false,
    source: 'KPG193 (renewables CSV)',
  }));
}

interface BranchEnriched {
  name: string;
  bus0: string;
  bus1: string;
  v_nom_0: number;
  v_nom_1: number;
  is_transformer: boolean;
  s_nom: number;
  r_ohm: number;
  x_ohm: number;
  b_siemens: number;
  tap_ratio: number;
  phase_shift: number;
  status: number;
}

function enrichBranches(
  branchRows: Row[],
  buses: Row[],
  baseMva: number,
): BranchEnriched[] {
  const vNomByBus = new Map<string, number>();
  for (const b of buses) {
    vNomByBus.set(String(b.name), Number(b.v_nom) || 0);
  }
  return branchRows.map((row, i) => {
    const bus0 = String(Number(row.fbus));
    const bus1 = String(Number(row.tbus));
    const v0 = vNomByBus.get(bus0) || 0;
    const v1 = vNomByBus.get(bus1) || 0;
    const ratio = Number(row.ratio) || 0;
    const angle = Number(row.angle) || 0;
    const isTransformer = ratio !== 0 || angle !== 0;
    const zBase = baseMva > 0 ? (v0 * v0) / baseMva : 0;
    return {
      name: String(i + 1),
      bus0,
      bus1,
      v_nom_0: v0,
      v_nom_1: v1,
      is_transformer: isTransformer,
      s_nom: Number(row.rateA) || 0,
      r_ohm: Number(row.r) * zBase,
      x_ohm: Number(row.x) * zBase,
      b_siemens: zBase > 0 ? Number(row.b) / zBase : 0,
      tap_ratio: ratio || 1.0,
      phase_shift: angle,
      status: Number(row.status) || 0,
    };
  });
}

function buildLines(branches: BranchEnriched[]): Row[] {
  return branches
    .filter((b) => !b.is_transformer)
    .map((b) => ({
      name: b.name,
      bus0: b.bus0,
      bus1: b.bus1,
      type: '',
      x: b.x_ohm,
      r: b.r_ohm,
      b: b.b_siemens,
      s_nom: b.s_nom,
      length: 1,
      num_parallel: 1,
      s_max_pu: 1,
      v_nom: b.v_nom_0,
      source: 'KPG193',
    }));
}

function buildTransformers(branches: BranchEnriched[]): Row[] {
  return branches
    .filter((b) => b.is_transformer)
    .map((b) => ({
      name: b.name,
      bus0: b.bus0,
      bus1: b.bus1,
      type: '',
      model: 't',
      x: b.x_ohm,
      r: b.r_ohm,
      g: 0,
      b: b.b_siemens,
      s_nom: b.s_nom,
      tap_ratio: b.tap_ratio,
      tap_side: 0,
      phase_shift: b.phase_shift,
      s_max_pu: 1,
      source: 'KPG193',
    }));
}

function buildLinks(dclineRows: Row[]): Row[] {
  return dclineRows.map((row, i) => {
    const pmax = Number(row.Pmax) || 0;
    const pmin = Number(row.Pmin) || 0;
    const loss1 = Number(row.loss1) || 0;
    const pMinPu = pmax !== 0 ? Math.max(-1, Math.min(0, pmin / pmax)) : 0;
    return {
      name: `dcline_${i + 1}`,
      bus0: String(Number(row.f_bus)),
      bus1: String(Number(row.t_bus)),
      p_nom: pmax,
      p_min_pu: pMinPu,
      efficiency: Math.max(0, Math.min(1, 1 - loss1)),
      carrier: 'DC',
      source: 'KPG193',
    };
  });
}

// ── Module ───────────────────────────────────────────────────────────────────

interface KPG193Payload {
  paths: ResolvedKpg193Paths;
  sheets: WorkbookFragment['sheets'];
  counts: {
    buses: number;
    loads: number;
    thermal_generators: number;
    renewable_generators: number;
    lines: number;
    transformers: number;
    links: number;
    base_mva: number;
  };
}

export const kpg193Module: DatabaseModule<KPG193Payload> = {
  meta: kpg193Meta,

  async fetch(region, filters): Promise<FetchResult<KPG193Payload>> {
    const paths = await resolvePaths({
      version: filters.version as string | undefined,
      renewable_year: filters.renewable_year as string | undefined,
    });
    const includeRenewables = filters.include_renewables !== false;
    const includeDcLinks = filters.include_dc_links !== false;

    // Pull everything in parallel — independent files, all CORS-friendly.
    const [matText, locText, solarText, windText, hydroText] = await Promise.all([
      fetchMatpowerText(paths.matpowerPath),
      fetchBusLocationCsv(paths.busLocationPath),
      includeRenewables ? fetchRenewableCsv(paths.solarPath) : Promise.resolve(null),
      includeRenewables ? fetchRenewableCsv(paths.windPath) : Promise.resolve(null),
      includeRenewables ? fetchRenewableCsv(paths.hydroPath) : Promise.resolve(null),
    ]);

    const baseMva = parseFloat(extractScalar(matText, 'baseMVA'));
    const busRows = parseMatrix(extractBlockLines(matText, 'bus'), BUS_COLUMNS, 'bus_comment');
    const genRows = parseMatrix(extractBlockLines(matText, 'gen'), GEN_COLUMNS, 'gen_fuel');
    const branchRows = parseMatrix(
      extractBlockLines(matText, 'branch'), BRANCH_COLUMNS, 'branch_comment',
    );
    const gencostRows = parseMatrix(
      extractBlockLines(matText, 'gencost'), GENCOST_COLUMNS, 'gencost_fuel',
    );
    const genthermalRows = parseMatrix(
      extractBlockLines(matText, 'genthermal'), GENTHERMAL_COLUMNS, 'genthermal_fuel',
    );
    const dclineRows = includeDcLinks
      ? parseMatrix(extractBlockLines(matText, 'dcline'), DCLINE_COLUMNS, 'dcline_comment')
      : [];

    const locations = parseBusLocation(locText);
    const renewables: RenewableRow[] = [];
    if (solarText) renewables.push(...parseRenewableCsv(solarText, 'solar'));
    if (windText) renewables.push(...parseRenewableCsv(windText, 'wind'));
    if (hydroText) renewables.push(...parseRenewableCsv(hydroText, 'hydro'));

    const buses = buildBuses(busRows as Row[], locations);
    const loads = buildLoads(busRows as Row[]);
    const thermalGens = buildThermalGenerators(
      genRows as Row[], gencostRows as Row[], genthermalRows as Row[],
    );
    const renewableGens = buildRenewableGenerators(renewables);
    const generators = [...thermalGens, ...renewableGens];

    const branches = enrichBranches(branchRows as Row[], buses, baseMva);
    const lines = buildLines(branches);
    const transformers = buildTransformers(branches);
    const links = buildLinks(dclineRows as Row[]);

    // Union of carriers actually present. MATPOWER + KPG193's convention.
    const carriersSet = new Set<string>(['AC', 'load']);
    for (const g of generators) {
      const c = g.carrier;
      if (typeof c === 'string' && c) carriersSet.add(c);
    }
    if (links.length) carriersSet.add('DC');
    const carriers: Row[] = Array.from(carriersSet)
      .sort()
      .map((name) => ({ name }));

    const sheets: WorkbookFragment['sheets'] = {
      carriers,
      buses,
      loads,
      generators,
      lines,
    };
    if (transformers.length) sheets.transformers = transformers;
    if (links.length) sheets.links = links;

    const payload: KPG193Payload = {
      paths,
      sheets,
      counts: {
        buses: buses.length,
        loads: loads.length,
        thermal_generators: thermalGens.length,
        renewable_generators: renewableGens.length,
        lines: lines.length,
        transformers: transformers.length,
        links: links.length,
        base_mva: baseMva,
      },
    };
    return {
      databaseId: kpg193Meta.id,
      region,
      filters: { ...filters },
      payload,
    };
  },

  preview(result): PreviewSummary {
    const { paths, counts, sheets } = result.payload;
    const summary = `KPG193 ${paths.versionTag}, renewables ${paths.renewableYear}: ${counts.buses} buses, ${counts.lines} lines, ${counts.transformers} transformers, ${counts.thermal_generators} thermal + ${counts.renewable_generators} renewable generators${counts.links ? `, ${counts.links} HVDC links` : ''}.`;
    // Drop a per-bus point overlay on the map so the user can see the
    // network footprint immediately. KPG193's bus_location.csv covers
    // every bus, so this should always populate.
    const overlay = {
      type: 'FeatureCollection' as const,
      features: (sheets.buses || [])
        .filter((b) => typeof b.x === 'number' && typeof b.y === 'number')
        .map((b) => ({
          type: 'Feature' as const,
          geometry: {
            type: 'Point' as const,
            coordinates: [Number(b.x), Number(b.y)],
          },
          properties: {
            kind: 'substation',
            name: String(b.kpg193_name_en || b.kpg193_name_kr || b.name),
            voltages_kv: [Number(b.v_nom) || 0],
          },
        })),
    };
    return {
      counts: {
        buses: counts.buses,
        loads: counts.loads,
        generators: counts.thermal_generators + counts.renewable_generators,
        lines: counts.lines,
        transformers: counts.transformers,
        links: counts.links,
      },
      samples: {
        buses: (sheets.buses || []).slice(0, 10).map((b) => ({
          name: b.name,
          v_nom: b.v_nom,
          name_en: b.kpg193_name_en,
        })),
        generators: (sheets.generators || []).slice(0, 10).map((g) => ({
          name: g.name,
          bus: g.bus,
          carrier: g.carrier,
          p_nom: g.p_nom,
        })),
      },
      notes: [summary, `baseMVA = ${counts.base_mva}`],
      overlay,
    };
  },

  toSheets(
    result: FetchResult<KPG193Payload>,
    _options: Required<ConvertOptions>,
  ): WorkbookFragment {
    const { paths, sheets, counts } = result.payload;
    const region: Region = result.region;
    const rowCounts: Record<string, number> = {};
    for (const [k, v] of Object.entries(sheets)) rowCounts[k] = v.length;
    rowCounts.base_mva = counts.base_mva;
    return {
      sheets,
      provenance: {
        database_id: kpg193Meta.id,
        country_iso: region.countryIso,
        country_name: region.countryName,
        filters_json: JSON.stringify(result.filters, Object.keys(result.filters).sort()),
        convert_options_json: JSON.stringify({
          version: paths.versionTag,
          renewable_year: paths.renewableYear,
        }),
        fetch_timestamp: new Date().toISOString().slice(0, 19),
        row_counts_json: JSON.stringify(rowCounts, Object.keys(rowCounts).sort()),
      },
    };
  },
};
