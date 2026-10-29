/**
 * Where a composite asset plugs into the network, read from its PyPSA rows (never from its type).
 *
 * Input is a list of component rows (the rows of a plant already in the model, or the rows of a preview fragment) and the model's buses;
 * output is the ports (one per bus the asset touches, with direction and carrier), the loads it owns, and a node / edge graph for the
 * schematic. Because it reads the rows, the table, the schematic and the "Creates" preview can never disagree with what is written.
 *
 * Directions: a Generator delivers to its bus (out); a Load draws from it (in); a StorageUnit / Store both charges and discharges (both);
 * a Link takes at bus0 (in) and delivers at bus1 (out), a further bus_i delivers unless its efficiency_i is negative (then it draws); a
 * Process takes where rate_i is negative. Pure, no React.
 */
import type { GridRow, WorkbookModel } from 'lib/types';
import { numberValue, stringValue } from 'lib/utils/helpers';
import { PLANT_COLUMN } from 'lib/build/plants';

export type Direction = 'in' | 'out' | 'both';
export interface ComponentRow { sheet: string; name: string; row: Record<string, unknown> }
export interface Edge { sheet: string; name: string; column: string; bus: string; direction: Direction }
export interface Port { bus: string; carrier: string; label: string; direction: Direction; created: boolean; loadMw: number | null }
export interface SchematicNode { id: string; kind: 'bus' | 'component'; label: string; sub: string; created: boolean; external: boolean }
export interface Connections {
  ports: Port[];
  /** Buses the asset created that only connect its own parts (a fuel bus between the feeders and the turbine). */
  internalBuses: string[];
  /** Existing generators the asset is matched to (P2X / RFNBO); not a row link. */
  matched: string[];
  edges: Edge[];
  nodes: SchematicNode[];
}

const BUS_COLUMNS = ['bus', 'bus0', 'bus1', 'bus2', 'bus3', 'bus4', 'bus5'];
const FLOW_SHEETS = new Set(['generators', 'links', 'processes', 'storage_units', 'stores', 'loads']);
const ELECTRICITY = /^(ac|dc|electricity|electric|power|el|elec)$/i;

/** True for the carriers an electricity bus has (AC, DC, electricity ...). */
export const isElectricCarrier = (carrier: string): boolean => ELECTRICITY.test(carrier.trim());
/** Gas and hydrogen carriers, as the plant builders look for them. */
export const isGasCarrier = (carrier: string): boolean => /^(gas|natural gas|ch4|methane)$/i.test(carrier.trim());
export const isH2Carrier = (carrier: string): boolean => /^(h2|hydrogen)$/i.test(carrier.trim());

/** Plain word for a bus carrier: any of the electricity names -> "electricity", else the carrier as written. */
export const carrierWord = (carrier: string): string => (ELECTRICITY.test(carrier.trim()) ? 'electricity' : carrier.trim() || 'energy');

function directionOf(sheet: string, column: string, row: Record<string, unknown>): Direction {
  if (sheet === 'generators') return 'out';
  if (sheet === 'loads') return 'in';
  if (sheet === 'storage_units' || sheet === 'stores') return 'both';
  if (column === 'bus0') return 'in';
  const i = column.replace('bus', '');
  if (sheet === 'processes') return numberValue(row[`rate${i}`] as never) < 0 ? 'in' : 'out';
  const key = i === '1' ? 'efficiency' : `efficiency${i}`;
  return numberValue(row[key] as never) < 0 ? 'in' : 'out';
}

/** The rows of plant `plantId` in the model (static component sheets, not the registries). */
export function plantComponentRows(model: WorkbookModel, plantId: string): ComponentRow[] {
  const out: ComponentRow[] = [];
  for (const sheet of Object.keys(model)) {
    if (sheet.includes('-') || sheet === 'snapshots' || sheet === 'network' || sheet.startsWith('RAGNAROK')) continue;
    for (const row of model[sheet] as GridRow[]) {
      if (stringValue(row[PLANT_COLUMN]).trim() === plantId) out.push({ sheet, name: stringValue(row.name), row });
    }
  }
  return out;
}

/** The rows a preview fragment would write (static component sheets only). */
export function fragmentComponentRows(fragment: { sheets: Record<string, Array<Record<string, unknown>>> } | null | undefined): ComponentRow[] {
  const out: ComponentRow[] = [];
  for (const [sheet, rows] of Object.entries(fragment?.sheets ?? {})) {
    if (sheet.includes('-') || sheet.startsWith('RAGNAROK')) continue;
    for (const row of rows) out.push({ sheet, name: stringValue(row.name as never), row });
  }
  return out;
}

const roleOf = (c: ComponentRow): string => stringValue((c.row.carrier ?? '') as never) || c.sheet;

/**
 * Ports and the schematic graph of a set of component rows.
 *
 * @param rows the asset's component rows (the `buses` rows among them are the buses it created).
 * @param buses the model's buses (to tell an existing bus from a created one and to find its carrier).
 * @param matched generator names the asset is matched to (from its spec / chain registry).
 */
export function connectionsOf(rows: ComponentRow[], buses: GridRow[], matched: string[] = []): Connections {
  const created = new Set(rows.filter((r) => r.sheet === 'buses').map((r) => r.name));
  const carrierOf = new Map<string, string>();
  buses.forEach((b) => carrierOf.set(stringValue(b.name), stringValue(b.carrier)));
  rows.filter((r) => r.sheet === 'buses').forEach((r) => carrierOf.set(r.name, stringValue(r.row.carrier as never)));

  const parts = rows.filter((r) => FLOW_SHEETS.has(r.sheet));
  const edges: Edge[] = [];
  for (const c of parts) {
    for (const column of BUS_COLUMNS) {
      const bus = stringValue(c.row[column] as never).trim();
      if (!bus) continue;
      edges.push({ sheet: c.sheet, name: c.name, column, bus, direction: directionOf(c.sheet, column, c.row) });
    }
  }

  const byBus = new Map<string, Edge[]>();
  edges.forEach((e) => byBus.set(e.bus, [...(byBus.get(e.bus) ?? []), e]));
  const ports: Port[] = [];
  const internalBuses: string[] = [];
  byBus.forEach((list, bus) => {
    const load = list.filter((e) => e.sheet === 'loads');
    const flow = list.filter((e) => e.sheet === 'links' || e.sheet === 'processes' || e.sheet === 'generators');
    const conv = flow.filter((e) => e.sheet !== 'generators');      // a supplier on a created bus does not make it internal: it is the fuel port
    const dirs = new Set(conv.map((e) => e.direction));
    if (created.has(bus) && load.length === 0 && dirs.has('in') && dirs.has('out')) { internalBuses.push(bus); return; }
    const supplied = created.has(bus) && conv.length > 0 && flow.some((e) => e.sheet === 'generators');
    const all = new Set((supplied ? conv : list).map((e) => e.direction));
    const direction: Direction = all.size > 1 || all.has('both') ? 'both' : (Array.from(all)[0] as Direction);
    const carrier = carrierOf.get(bus) ?? '';
    const loadMw = load.length ? load.reduce((s, e) => s + numberValue((parts.find((p) => p.name === e.name && p.sheet === 'loads')?.row.p_set ?? 0) as never), 0) : null;
    // A created bus a load sits on is where the product is delivered: it reads as an output of the asset.
    const shown: Direction = created.has(bus) && load.length > 0 && direction === 'both' ? 'out' : direction;
    ports.push({ bus, carrier, label: `${carrierWord(carrier)} ${shown === 'both' ? 'in/out' : shown}`, direction: shown, created: created.has(bus), loadMw });
  });
  ports.sort((a, b) => Number(!ELECTRICITY.test(a.carrier)) - Number(!ELECTRICITY.test(b.carrier)) || a.bus.localeCompare(b.bus));

  const nodes: SchematicNode[] = [];
  Array.from(byBus.keys()).forEach((bus) => nodes.push({ id: `bus:${bus}`, kind: 'bus', label: bus, sub: carrierWord(carrierOf.get(bus) ?? ''), created: created.has(bus), external: !created.has(bus) }));
  for (const c of parts) nodes.push({ id: `${c.sheet}:${c.name}`, kind: 'component', label: c.name, sub: `${c.sheet === 'storage_units' ? 'storage unit' : c.sheet.replace(/s$/, '')}${roleOf(c) !== c.sheet ? ` (${roleOf(c)})` : ''}`, created: true, external: false });
  return { ports, internalBuses, matched, edges, nodes };
}

/** "electricity out to bus", "gas in from bus", "electricity in/out at bus": the words before the bus name (no arrow glyphs in the UI). */
export function portPhrase(port: Port): string {
  return `${port.label} ${port.direction === 'out' ? 'to' : port.direction === 'in' ? 'from' : 'at'} bus`;
}

/** Existing generators a P2X asset is matched to: the plant spec, else the chain registry row (`RAGNAROK_P2X`) of the same id. */
export function matchedGenerators(model: WorkbookModel, plantId: string, spec: Record<string, unknown> | null): string[] {
  const fromSpec = (spec?.designatedGenerators as unknown) ?? (spec?.chain as { designatedGenerators?: unknown } | undefined)?.designatedGenerators;
  if (Array.isArray(fromSpec) && fromSpec.length) return fromSpec.map(String);
  for (const row of (model.RAGNAROK_P2X ?? []) as GridRow[]) {
    if (stringValue(row.name) !== plantId) continue;
    try {
      const reg = JSON.parse(stringValue(row.json)) as { designatedGenerators?: unknown };
      if (Array.isArray(reg.designatedGenerators)) return reg.designatedGenerators.map(String);
    } catch { /* malformed registry row: nothing matched */ }
  }
  return [];
}
