/**
 * Single-line diagram layout. Pure (no React, no DOM), deterministic: the same model gives the same coordinates.
 *
 * Pipeline
 *  1. Buses are split into bands: electric buses by `v_nom` (highest voltage first; missing `v_nom` shares one band), then
 *     non-electric buses by carrier (gas, H2, heat ...), shown only when asked. Buses owned by a composite (`plant` column) are
 *     never drawn: the composite is one symbol on its electricity bus.
 *  2. Within a band the order is chosen by barycentric sweeps (a bus moves to the mean position of its neighbours), seeded by a
 *     breadth-first order so connected buses start next to each other. This is the classic layered-drawing heuristic; it is cheap
 *     (a few passes over the edges), which is why ~300 buses stay responsive without a worker.
 *  3. A band is cut into rows when it is wider than `MAX_ROW_WIDTH`; every row is a horizontal bus bar line-up.
 *  4. Lines, links and transformers are routed orthogonally: down from the upper bus to a private horizontal channel in the gap
 *     above the lower bus, across, down into it. Edges in one gap get distinct channels (shorter spans nearer the bars), and
 *     every bus orders its connection points by the x of the other end, which keeps wires from crossing near the bars.
 */
import type { GridRow, WorkbookModel } from 'lib/types';
import { numberValue, resolvedColor, stringValue } from 'lib/utils/helpers';
import { PLANT_COLUMN, plantCards } from 'lib/build/plants';

export const COMPOSITES_SHEET = 'RAGNAROK_Composites';

export const SLD = {
  marginLeft: 96,
  marginTop: 24,
  marginRight: 40,
  marginBottom: 32,
  barHeight: 6,
  busGap: 40,
  maxRowWidth: 1800,
  genSlot: 56,
  composite: 132,
  loadSlot: 42,
  moreSlot: 44,
  portPitch: 22,
  charWidth: 6.4,
  labelMaxChars: 14,
  maxTopItems: 4,
  maxLoads: 3,
  topPad: 86,
  topPadEmpty: 26,
  botPad: 48,
  botPadEmpty: 22,
  gapBase: 16,
  channelPitch: 8,
  bandGap: 36,
  maxBuses: 300,
} as const;

export interface SldOptions {
  /** Draw buses of non-electric carriers (gas, H2, heat) as bottom bands. */
  showNonElectric: boolean;
  /** Keep only electric buses of this `v_nom` (null = all). */
  voltageFilter: number | null;
  /** Keep only buses whose `country` equals this (null = all). */
  areaFilter: string | null;
  /** Draw even when the bus count is above `SLD.maxBuses`. */
  drawLarge: boolean;
}

export const DEFAULT_OPTIONS: SldOptions = { showNonElectric: false, voltageFilter: null, areaFilter: null, drawLarge: false };

export type SldItemKind = 'generator' | 'storage_unit' | 'store' | 'load' | 'composite' | 'more';

export interface SldItem {
  id: string;
  kind: SldItemKind;
  sheet: string;
  name: string;
  label: string;
  /** Centre x / width of the symbol's slot. */
  x: number;
  w: number;
  color: string;
  tooltip: string[];
  /** For 'more': the names folded into the "+N" chip. */
  hidden?: string[];
}

export interface SldBus {
  name: string;
  x: number;
  y: number;
  w: number;
  h: number;
  band: number;
  row: number;
  label: string;
  vNom: number | null;
  carrier: string;
  tooltip: string[];
  /** Symbols above the bar (composites, storage, generators), loads below. */
  top: SldItem[];
  loads: SldItem[];
}

export interface SldEdge {
  id: string;
  sheet: 'lines' | 'links' | 'transformers';
  name: string;
  bus0: string;
  bus1: string;
  points: Array<[number, number]>;
  tooltip: string[];
  /** Links: direction arrow (bus0 to bus1) at a point on the wire; angle in degrees. */
  arrow: { x: number; y: number; angle: number } | null;
  /** Transformers: centre of the two-circle symbol. */
  symbol: { x: number; y: number } | null;
}

export interface SldBand {
  key: string;
  label: string;
  kind: 'electric' | 'carrier';
  vNom: number | null;
  y0: number;
  y1: number;
  /** y of the dotted divider above this band (null for the first). */
  dividerY: number | null;
  buses: string[];
}

export interface SldLayout {
  bands: SldBand[];
  buses: SldBus[];
  edges: SldEdge[];
  width: number;
  height: number;
  /** Buses counted before the limit; the caller decides whether to draw. */
  busCount: number;
  /** Set when the bus count is above the limit and nothing was laid out. */
  tooLarge: boolean;
  voltageLevels: number[];
  areas: string[];
  /** Edges dropped because an end is not drawn (hidden bus, composite internals). */
  skippedEdges: number;
}

const ELECTRICITY = /^(ac|dc|electricity|electric|power|el|elec)$/i;
const MAX_LABEL = SLD.labelMaxChars;

const str = (v: unknown): string => stringValue(v as never).trim();
const num = (v: unknown): number => numberValue(v as never);
const rowsOf = (model: WorkbookModel, sheet: string): GridRow[] => (Array.isArray(model[sheet]) ? model[sheet] : []);

export function voltageOf(row: GridRow): number | null {
  const raw = row.v_nom;
  if (raw === undefined || raw === null || raw === '') return null;
  const v = Number(raw);
  return Number.isFinite(v) && v > 0 ? v : null;
}

export const isElectricCarrier = (carrier: string): boolean => carrier === '' || ELECTRICITY.test(carrier);

const fmt = (v: number): string => v.toLocaleString(undefined, { maximumFractionDigits: 3 });
const fmtKv = (v: number | null): string => (v === null ? 'voltage not set' : `${fmt(v)} kV`);
const truncate = (s: string, n: number): string => (s.length > n ? `${s.slice(0, n - 1)}~` : s);

function bandLabel(vNom: number | null, carrier: string | null): string {
  if (carrier !== null) return carrier;
  return vNom === null ? 'Voltage not set' : `${fmt(vNom)} kV`;
}

interface BusNode {
  name: string;
  row: GridRow;
  vNom: number | null;
  carrier: string;
  bandKey: string;
  neighbours: string[];
  degree: number;
  order: number;
}

interface RawEdge {
  sheet: SldEdge['sheet'];
  name: string;
  bus0: string;
  bus1: string;
  tooltip: string[];
}

function compare(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** Order of the buses inside each band: BFS seed, then barycentric sweeps against the other bands. */
function orderBuses(bands: string[][], nodes: Map<string, BusNode>, bandOf: Map<string, number>): void {
  // seed: BFS from the best-connected bus of each component, neighbours by name, so linked buses start adjacent
  const seen = new Set<string>();
  const bfs: string[] = [];
  const all = Array.from(nodes.values()).sort((a, b) => b.degree - a.degree || compare(a.name, b.name));
  for (const start of all) {
    if (seen.has(start.name)) continue;
    const queue = [start.name];
    seen.add(start.name);
    while (queue.length) {
      const cur = queue.shift() as string;
      bfs.push(cur);
      for (const nb of Array.from(new Set(nodes.get(cur)?.neighbours ?? [])).sort(compare)) {
        if (!seen.has(nb) && nodes.has(nb)) { seen.add(nb); queue.push(nb); }
      }
    }
  }
  const seed = new Map(bfs.map((n, i) => [n, i]));
  bands.forEach((band) => band.sort((a, b) => (seed.get(a) ?? 0) - (seed.get(b) ?? 0)));

  const pos = new Map<string, number>();
  const refresh = () => bands.forEach((band) => band.forEach((n, i) => pos.set(n, band.length <= 1 ? 0.5 : i / (band.length - 1))));
  refresh();
  for (let sweep = 0; sweep < 8; sweep += 1) {
    const order = sweep % 2 === 0 ? bands.map((_, i) => i) : bands.map((_, i) => bands.length - 1 - i);
    for (const bi of order) {
      const band = bands[bi];
      const bary = new Map<string, number>();
      for (const n of band) {
        const nb = nodes.get(n)?.neighbours ?? [];
        let sum = 0;
        let w = 0;
        for (const o of nb) {
          if (o === n || !nodes.has(o)) continue;
          const weight = bandOf.get(o) === bi ? 0.5 : 1;
          sum += (pos.get(o) ?? 0.5) * weight;
          w += weight;
        }
        bary.set(n, w > 0 ? sum / w : pos.get(n) ?? 0.5);
      }
      const prev = new Map(band.map((n, i) => [n, i]));
      band.sort((a, b) => (bary.get(a) ?? 0) - (bary.get(b) ?? 0) || (prev.get(a) ?? 0) - (prev.get(b) ?? 0) || compare(a, b));
      band.forEach((n, i) => pos.set(n, band.length <= 1 ? 0.5 : i / (band.length - 1)));
    }
  }
}

interface Pending {
  edge: RawEdge;
  a: SldBus;
  b: SldBus;
  sideB: 'top' | 'bottom';
  ax: number;
  bx: number;
  index: number;
}

export function buildSldLayout(model: WorkbookModel, options: SldOptions = DEFAULT_OPTIONS): SldLayout {
  const empty = (extra: Partial<SldLayout>): SldLayout => ({ bands: [], buses: [], edges: [], width: 0, height: 0, busCount: 0, tooLarge: false, voltageLevels: [], areas: [], skippedEdges: 0, ...extra });

  // ---- candidate buses ---------------------------------------------------------------------------------------------
  const allBuses = rowsOf(model, 'buses').filter((b) => str(b.name) !== '' && str(b[PLANT_COLUMN]) === '');
  const voltageLevels = Array.from(new Set(allBuses.filter((b) => isElectricCarrier(str(b.carrier))).map(voltageOf).filter((v): v is number => v !== null))).sort((a, b) => b - a);
  const areas = Array.from(new Set(allBuses.map((b) => str(b.country)).filter(Boolean))).sort(compare);

  const nodes = new Map<string, BusNode>();
  for (const row of allBuses) {
    const name = str(row.name);
    const carrier = str(row.carrier);
    const electric = isElectricCarrier(carrier);
    if (!electric && !options.showNonElectric) continue;
    const vNom = electric ? voltageOf(row) : null;
    if (electric && options.voltageFilter !== null && vNom !== options.voltageFilter) continue;
    if (options.areaFilter !== null && str(row.country) !== options.areaFilter) continue;
    nodes.set(name, { name, row, vNom, carrier, bandKey: electric ? `e:${vNom ?? 'none'}` : `c:${carrier}`, neighbours: [], degree: 0, order: nodes.size });
  }
  const busCount = nodes.size;
  if (busCount > SLD.maxBuses && !options.drawLarge) return empty({ busCount, tooLarge: true, voltageLevels, areas });
  if (busCount === 0) return empty({ voltageLevels, areas });

  // ---- edges between drawn buses ----------------------------------------------------------------------------------
  const rawEdges: RawEdge[] = [];
  let skippedEdges = 0;
  const addEdges = (sheet: SldEdge['sheet'], describe: (r: GridRow) => string[]) => {
    for (const r of rowsOf(model, sheet)) {
      if (str(r[PLANT_COLUMN]) !== '') continue;
      const bus0 = str(r.bus0);
      const bus1 = str(r.bus1);
      if (!nodes.has(bus0) || !nodes.has(bus1) || bus0 === bus1) { skippedEdges += 1; continue; }
      rawEdges.push({ sheet, name: str(r.name), bus0, bus1, tooltip: [`${sheet === 'lines' ? 'Line' : sheet === 'links' ? 'Link' : 'Transformer'} ${str(r.name)}`, `${bus0} to ${bus1}`, ...describe(r)] });
    }
  };
  addEdges('lines', (r) => [`s_nom: ${fmt(num(r.s_nom))} MVA`, ...(str(r.length) !== '' ? [`length: ${fmt(num(r.length))} km`] : [])]);
  addEdges('transformers', (r) => [`s_nom: ${fmt(num(r.s_nom))} MVA`]);
  addEdges('links', (r) => [`p_nom: ${fmt(num(r.p_nom))} MW`, ...(str(r.carrier) ? [`carrier: ${str(r.carrier)}`] : [])]);
  for (const e of rawEdges) {
    const a = nodes.get(e.bus0) as BusNode;
    const b = nodes.get(e.bus1) as BusNode;
    a.neighbours.push(e.bus1); a.degree += 1;
    b.neighbours.push(e.bus0); b.degree += 1;
  }

  // ---- bands --------------------------------------------------------------------------------------------------------
  const keyInfo = new Map<string, { vNom: number | null; carrier: string | null }>();
  nodes.forEach((n) => keyInfo.set(n.bandKey, n.bandKey.startsWith('e:') ? { vNom: n.vNom, carrier: null } : { vNom: null, carrier: n.carrier }));
  const keys = Array.from(keyInfo.keys()).sort((ka, kb) => {
    const a = keyInfo.get(ka) as { vNom: number | null; carrier: string | null };
    const b = keyInfo.get(kb) as { vNom: number | null; carrier: string | null };
    const ea = a.carrier === null;
    const eb = b.carrier === null;
    if (ea !== eb) return ea ? -1 : 1;
    if (ea) return a.vNom === null ? 1 : b.vNom === null ? -1 : b.vNom - a.vNom;
    return compare(a.carrier as string, b.carrier as string);
  });
  const bandOf = new Map<string, number>();
  const bandBuses: string[][] = keys.map(() => []);
  nodes.forEach((n) => { const i = keys.indexOf(n.bandKey); bandOf.set(n.name, i); bandBuses[i].push(n.name); });
  bandBuses.forEach((b) => b.sort(compare));
  orderBuses(bandBuses, nodes, bandOf);

  // ---- per-bus symbols ---------------------------------------------------------------------------------------------
  const carrierColors = new Map<string, string>();
  for (const c of rowsOf(model, 'carriers')) carrierColors.set(str(c.name), str(c.color));
  const colorOf = (row: GridRow): string => resolvedColor((row.color as never) || carrierColors.get(str(row.carrier)) || undefined, str(row.carrier) as never);

  type RawItem = Omit<SldItem, 'x' | 'w'> & { w: number };
  const topRaw = new Map<string, RawItem[]>();
  const loadRaw = new Map<string, RawItem[]>();
  const push = (m: Map<string, RawItem[]>, bus: string, item: RawItem) => {
    if (!nodes.has(bus)) return;
    const list = m.get(bus) ?? [];
    list.push(item);
    m.set(bus, list);
  };

  const cards = plantCards(model);
  const rowsByPlant = new Map<string, GridRow[]>();
  for (const sheet of ['generators', 'links', 'storage_units', 'stores', 'loads']) {
    for (const r of rowsOf(model, sheet)) {
      const id = str(r[PLANT_COLUMN]);
      if (id) rowsByPlant.set(id, [...(rowsByPlant.get(id) ?? []), r]);
    }
  }
  for (const card of cards) {
    const members = rowsByPlant.get(card.plantId) ?? [];
    let bus = card.bus && nodes.has(card.bus) ? card.bus : '';
    if (!bus) {
      outer: for (const r of members) {
        for (const col of ['bus', 'bus0', 'bus1', 'bus2', 'bus3']) {
          const candidate = str(r[col]);
          if (candidate && nodes.has(candidate) && isElectricCarrier(nodes.get(candidate)?.carrier ?? '')) { bus = candidate; break outer; }
        }
      }
    }
    if (!bus) continue;
    const typeLabel = (card.type ?? 'composite').replace(/_/g, ' ');
    push(topRaw, bus, {
      id: `composite:${card.plantId}`, kind: 'composite', sheet: COMPOSITES_SHEET, name: card.plantId,
      label: typeLabel, w: SLD.composite, color: '#7c3aed',
      tooltip: [`Composite ${card.plantId}`, `type: ${typeLabel}`, ...(card.capacityMwEl !== null ? [`capacity: ${fmt(card.capacityMwEl)} MW`] : []), `${card.rowCount} components`],
    });
  }
  for (const r of rowsOf(model, 'storage_units')) {
    if (str(r[PLANT_COLUMN])) continue;
    push(topRaw, str(r.bus), { id: `storage_units:${str(r.name)}`, kind: 'storage_unit', sheet: 'storage_units', name: str(r.name), label: str(r.name), w: SLD.genSlot, color: colorOf(r), tooltip: [`Storage unit ${str(r.name)}`, `carrier: ${str(r.carrier) || 'none'}`, `p_nom: ${fmt(num(r.p_nom))} MW`, `max_hours: ${fmt(num(r.max_hours))} h`] });
  }
  for (const r of rowsOf(model, 'stores')) {
    if (str(r[PLANT_COLUMN])) continue;
    push(topRaw, str(r.bus), { id: `stores:${str(r.name)}`, kind: 'store', sheet: 'stores', name: str(r.name), label: str(r.name), w: SLD.genSlot, color: colorOf(r), tooltip: [`Store ${str(r.name)}`, `carrier: ${str(r.carrier) || 'none'}`, `e_nom: ${fmt(num(r.e_nom))} MWh`] });
  }
  for (const r of rowsOf(model, 'generators')) {
    if (str(r[PLANT_COLUMN])) continue;
    push(topRaw, str(r.bus), { id: `generators:${str(r.name)}`, kind: 'generator', sheet: 'generators', name: str(r.name), label: str(r.name), w: SLD.genSlot, color: colorOf(r), tooltip: [`Generator ${str(r.name)}`, `carrier: ${str(r.carrier) || 'none'}`, `p_nom: ${fmt(num(r.p_nom))} MW`] });
  }
  for (const r of rowsOf(model, 'loads')) {
    if (str(r[PLANT_COLUMN])) continue;
    push(loadRaw, str(r.bus), { id: `loads:${str(r.name)}`, kind: 'load', sheet: 'loads', name: str(r.name), label: str(r.name), w: SLD.loadSlot, color: '#334155', tooltip: [`Load ${str(r.name)}`, ...(str(r.p_set) !== '' ? [`p_set: ${fmt(num(r.p_set))} MW`] : [])] });
  }

  const limitItems = (items: RawItem[], max: number, bus: string, sheetWord: string) => {
    if (items.length <= max) return items;
    const shown = items.slice(0, max - 1);
    const hidden = items.slice(max - 1);
    shown.push({ id: `more:${bus}:${sheetWord}`, kind: 'more', sheet: '', name: '', label: `+${hidden.length}`, w: SLD.moreSlot, color: '#64748b', tooltip: [`${hidden.length} more on ${bus}`, ...hidden.slice(0, 12).map((h) => h.name), ...(hidden.length > 12 ? ['...'] : [])], hidden: hidden.map((h) => h.name) });
    return shown;
  };

  // ---- horizontal placement ---------------------------------------------------------------------------------------
  const sldBuses = new Map<string, SldBus>();
  const widthOf = (n: BusNode, top: Array<{ w: number }>, loads: Array<{ w: number }>): number => {
    const label = Math.min(n.name.length, MAX_LABEL) * SLD.charWidth + 10;
    const ports = n.degree * SLD.portPitch;
    const topW = label + top.reduce((s, t) => s + t.w, 0) + ports;
    const botW = loads.reduce((s, t) => s + t.w, 0) + ports;
    return Math.max(84, topW, botW) + 16;
  };
  const rowOfBus: Array<{ band: number; buses: string[]; width: number }> = [];
  const placed = new Map<string, { top: RawItem[]; loads: RawItem[]; w: number }>();
  bandBuses.forEach((band, bi) => {
    let cur = { band: bi, buses: [] as string[], width: 0 };
    for (const name of band) {
      const n = nodes.get(name) as BusNode;
      const top = limitItems(topRaw.get(name) ?? [], SLD.maxTopItems, name, 'top');
      const loads = limitItems(loadRaw.get(name) ?? [], SLD.maxLoads, name, 'load');
      const w = widthOf(n, top, loads);
      placed.set(name, { top, loads, w });
      if (cur.buses.length > 0 && cur.width + SLD.busGap + w > SLD.maxRowWidth) { rowOfBus.push(cur); cur = { band: bi, buses: [], width: 0 }; }
      cur.width += (cur.buses.length > 0 ? SLD.busGap : 0) + w;
      cur.buses.push(name);
    }
    if (cur.buses.length > 0) rowOfBus.push(cur);
  });
  const widest = Math.max(...rowOfBus.map((r) => r.width));
  rowOfBus.forEach((row, ri) => {
    let x = SLD.marginLeft + (widest - row.width) / 2;       // rows are centred on the widest one
    for (const name of row.buses) {
      const n = nodes.get(name) as BusNode;
      const p = placed.get(name) as NonNullable<ReturnType<typeof placed.get>>;
      const label = truncate(name, MAX_LABEL);
      const labelW = Math.min(name.length, MAX_LABEL) * SLD.charWidth + 10;
      let tx = x + labelW;
      const top: SldItem[] = p.top.map((t) => { const it = { ...t, x: tx + t.w / 2 }; tx += t.w; return it; });
      let lx = x + 8;
      const loads: SldItem[] = p.loads.map((t) => { const it = { ...t, x: lx + t.w / 2 }; lx += t.w; return it; });
      sldBuses.set(name, {
        name, x, y: 0, w: p.w, h: SLD.barHeight, band: row.band, row: ri, label, vNom: n.vNom, carrier: n.carrier,
        tooltip: [`Bus ${name}`, n.carrier !== '' && !isElectricCarrier(n.carrier) ? `carrier: ${n.carrier}` : `v_nom: ${fmtKv(n.vNom)}`, ...(str(n.row.country) ? [`area: ${str(n.row.country)}`] : [])],
        top, loads,
      });
      x += p.w + SLD.busGap;
    }
  });

  // ---- edges: sides, ports, channels ------------------------------------------------------------------------------
  const pending: Pending[] = rawEdges.map((edge, index) => {
    let a = sldBuses.get(edge.bus0) as SldBus;
    let b = sldBuses.get(edge.bus1) as SldBus;
    if (a.row > b.row || (a.row === b.row && a.x > b.x)) [a, b] = [b, a];
    return { edge, a, b, sideB: b.row > a.row ? 'top' : 'bottom', ax: 0, bx: 0, index };
  });
  type Port = { p: Pending; end: 'a' | 'b'; otherX: number };
  const portLists = new Map<string, Port[]>();
  for (const p of pending) {
    const ka = `${p.a.name}|bottom`;
    const kb = `${p.b.name}|${p.sideB}`;
    portLists.set(ka, [...(portLists.get(ka) ?? []), { p, end: 'a', otherX: p.b.x + p.b.w / 2 }]);
    portLists.set(kb, [...(portLists.get(kb) ?? []), { p, end: 'b', otherX: p.a.x + p.a.w / 2 }]);
  }
  portLists.forEach((list, key) => {
    const bus = sldBuses.get(key.split('|')[0]) as SldBus;
    list.sort((u, v) => u.otherX - v.otherX || u.p.index - v.p.index);
    const right = bus.x + bus.w - 10;
    list.forEach((port, i) => {
      const x = right - (list.length - 1 - i) * SLD.portPitch;
      if (port.end === 'a') port.p.ax = x; else port.p.bx = x;
    });
  });
  // gap g sits below row g; an edge into a lower row uses the gap right above that row, a same-row edge the gap below its row
  const gapOf = (p: Pending): number => (p.b.row > p.a.row ? p.b.row - 1 : p.a.row);
  const gapEdges = new Map<number, Pending[]>();
  for (const p of pending) gapEdges.set(gapOf(p), [...(gapEdges.get(gapOf(p)) ?? []), p]);
  const channelIndex = new Map<number, number>();
  gapEdges.forEach((list) => {
    list.sort((u, v) => Math.abs(u.bx - u.ax) - Math.abs(v.bx - v.ax) || u.index - v.index);
    list.forEach((p, k) => channelIndex.set(p.index, k));
  });

  // ---- vertical placement -------------------------------------------------------------------------------------------
  const rowTall = new Set<number>();
  sldBuses.forEach((b) => { if (b.loads.length > 0) rowTall.add(b.row); });
  for (const p of pending) if (p.edge.sheet === 'transformers') rowTall.add(p.a.row);
  const rowHasTop = rowOfBus.map((r) => r.buses.some((n) => (sldBuses.get(n)?.top.length ?? 0) > 0));
  const rowBottom: number[] = [];
  const bands: SldBand[] = keys.map((key, i) => {
    const info = keyInfo.get(key) as { vNom: number | null; carrier: string | null };
    return { key, label: bandLabel(info.vNom, info.carrier), kind: info.carrier === null ? 'electric' : 'carrier', vNom: info.vNom, y0: 0, y1: 0, dividerY: null, buses: bandBuses[i] };
  });
  let y: number = SLD.marginTop;
  let prevBand = -1;
  rowOfBus.forEach((row, ri) => {
    if (ri > 0) {
      const gapHeight = SLD.gapBase + (gapEdges.get(ri - 1)?.length ?? 0) * SLD.channelPitch;
      y += gapHeight;
      if (row.band !== prevBand) {
        y += SLD.bandGap;
        bands[row.band].dividerY = y - SLD.bandGap / 2;
      }
    }
    if (row.band !== prevBand) bands[row.band].y0 = y;
    const barY = y + (rowHasTop[ri] ? SLD.topPad : SLD.topPadEmpty);
    for (const n of row.buses) (sldBuses.get(n) as SldBus).y = barY;
    y = barY + SLD.barHeight + (rowTall.has(ri) ? SLD.botPad : SLD.botPadEmpty);
    rowBottom.push(y);
    bands[row.band].y1 = y;
    prevBand = row.band;
  });
  const height = y + SLD.marginBottom;
  const width = SLD.marginLeft + widest + SLD.marginRight;

  // ---- edge geometry ------------------------------------------------------------------------------------------------
  const edges: SldEdge[] = pending.map((p) => {
    const g = gapOf(p);
    const k = channelIndex.get(p.index) ?? 0;
    const chY = rowBottom[g] + 10 + k * SLD.channelPitch;
    const ya = p.a.y + p.a.h;
    const yb = p.sideB === 'top' ? p.b.y : p.b.y + p.b.h;
    const points: Array<[number, number]> = [[p.ax, ya], [p.ax, chY], [p.bx, chY], [p.bx, yb]];
    const forward = p.a.name === p.edge.bus0;
    let arrow: SldEdge['arrow'] = null;
    if (p.edge.sheet === 'links') {
      const horizontal = Math.abs(p.bx - p.ax) >= 24;
      const [from, to]: Array<[number, number]> = horizontal ? [points[1], points[2]] : [points[0], points[1]];
      const dx = to[0] - from[0];
      const dy = to[1] - from[1];
      const angle = (Math.atan2(dy, dx) * 180) / Math.PI + (forward ? 0 : 180);
      arrow = { x: (from[0] + to[0]) / 2, y: (from[1] + to[1]) / 2, angle };
    }
    const symbol = p.edge.sheet === 'transformers' ? { x: p.ax, y: ya + 22 } : null;
    return { id: `${p.edge.sheet}:${p.edge.name}`, sheet: p.edge.sheet, name: p.edge.name, bus0: p.edge.bus0, bus1: p.edge.bus1, points, tooltip: p.edge.tooltip, arrow, symbol };
  });

  return { bands, buses: Array.from(sldBuses.values()), edges, width, height, busCount, tooLarge: false, voltageLevels, areas, skippedEdges };
}
