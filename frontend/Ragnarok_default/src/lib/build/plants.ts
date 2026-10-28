/**
 * Build plants on the client: group a model's rows into plants, apply a backend change set, place one map marker per plant.
 *
 * A plant is the set of rows whose `plant` column equals its id, plus one row in the `RAGNAROK_PLANTS` registry sheet (type,
 * spec, components). The backend (`/api/build/plant*`) derives every component and returns a *change set*; this module only
 * groups and applies it (`applyPlantChange`), so the browser model and the session end up the same. Pure — no React.
 */
import type { GridRow, WorkbookModel } from 'lib/types';
import { numberValue, stringValue } from 'lib/utils/helpers';

export const PLANT_SHEET = 'RAGNAROK_PLANTS';
export const PLANT_COLUMN = 'plant';
const BUS_COLUMNS = ['bus', 'bus0', 'bus1', 'bus2', 'bus3', 'bus4', 'bus5'];
const NOT_COMPONENTS = new Set(['snapshots', 'network']);
/** Registry sheets: tagged with the plant id too, but they are bookkeeping, not components. */
const REGISTRY_SHEETS = new Set(['RAGNAROK_PLANTS', 'RAGNAROK_P2X']);

export interface PlantComponent { sheet: string; name: string; role: string; present: boolean }

/** Derived values stored in a plant's registry row (part-load line, start costs); same shape as `PlantDerived` in `lib/api/plants.ts`. */
export interface PlantDerivedValues {
  partLoad?: { route: string; noLoadFuelMw: number; incrementalHeatRate: number; incrementalEfficiency: number; fuelMinMw: number; fuelFullMw: number; etaMin: number; etaFull: number; minLoadPu: number; written?: { stand_by_cost: number; marginal_cost: number } };
  startCosts?: { hot: number; nativeStartUpCost: number; warm?: number; warmAfterHours?: number | null; cold?: number; coldAfterHours?: number | null };
}

const num = (v: number, digits = 4): string => v.toLocaleString(undefined, { maximumFractionDigits: digits });

/** Plain-language lines for the derived values of a plant (preview and card); empty when the plant uses neither option. Units are stated. */
export function derivedLines(d: PlantDerivedValues | null | undefined): string[] {
  const out: string[] = [];
  const pl = d?.partLoad;
  if (pl) {
    out.push(`Part-load: fuel ${num(pl.fuelMinMw)} MW_th at minimum load (efficiency ${num(pl.etaMin)}), ${num(pl.fuelFullMw)} MW_th at full load (${num(pl.etaFull)}); no-load fuel ${num(pl.noLoadFuelMw)} MW_th, incremental heat rate ${num(pl.incrementalHeatRate)} MW_th/MW_el (incremental efficiency ${num(pl.incrementalEfficiency)}).`);
    out.push(pl.route === 'piecewise-link'
      ? `Written as PyPSA's piecewise efficiency curve on the Link (sheet links-efficiency-pw), with p_min_pu = ${num(pl.minLoadPu, 6)}.`
      : `Written as stand_by_cost = ${num(pl.written?.stand_by_cost ?? 0)} per hour committed and marginal_cost = ${num(pl.written?.marginal_cost ?? 0)} per MWh_el.`);
  }
  const sc = d?.startCosts;
  if (sc) {
    const tiers = [`hot ${num(sc.hot, 2)}`];
    if (sc.warm !== undefined) tiers.push(`warm ${num(sc.warm, 2)} after ${num(sc.warmAfterHours ?? 0)} h offline`);
    if (sc.cold !== undefined) tiers.push(`cold ${num(sc.cold, 2)} after ${num(sc.coldAfterHours ?? 0)} h offline`);
    out.push(`Start costs per start: ${tiers.join(', ')}. PyPSA's start_up_cost is the hot cost (${num(sc.nativeStartUpCost, 2)}); warm and cold add the difference at solve time.`);
  }
  return out;
}
export interface PlantCard {
  plantId: string;
  type: string | null;
  label: string;
  bus: string | null;
  capacityMwEl: number | null;
  extendable: boolean | null;
  editable: boolean;
  spec: Record<string, unknown> | null;
  components: PlantComponent[];
  rowCount: number;
  derived: PlantDerivedValues | null;
}

/** What the backend returns for add / edit / delete (`change` in the response). */
export interface PlantChange {
  remove: Record<string, string[]>;
  release: Array<{ sheet: string; name: string }>;
  fragment: { sheets: Record<string, Array<Record<string, unknown>>>; snapshots?: string[] } | null;
  kept: { buses: string[]; carriers: string[] };
}

const isStaticSheet = (model: WorkbookModel, sheet: string): boolean => Array.isArray(model[sheet]) && !sheet.includes('-') && !NOT_COMPONENTS.has(sheet);

/** True for a component row that belongs to a plant (it carries a plant id). */
export const inPlant = (row: GridRow): boolean => stringValue(row[PLANT_COLUMN]).trim() !== '';

function registry(model: WorkbookModel): Map<string, Record<string, unknown>> {
  const out = new Map<string, Record<string, unknown>>();
  for (const row of model[PLANT_SHEET] ?? []) {
    try {
      const reg = JSON.parse(stringValue(row.json)) as Record<string, unknown>;
      if (reg && typeof reg.plantId === 'string') out.set(reg.plantId, reg);
    } catch { /* a malformed registry row is skipped, its components still group by column */ }
  }
  return out;
}

/** One card per plant: tagged rows grouped by plant id, enriched from the registry row when there is one. */
export function plantCards(model: WorkbookModel): PlantCard[] {
  const members = new Map<string, Map<string, Set<string>>>();
  for (const sheet of Object.keys(model)) {
    if (!isStaticSheet(model, sheet) || REGISTRY_SHEETS.has(sheet)) continue;
    for (const row of model[sheet]) {
      const id = stringValue(row[PLANT_COLUMN]).trim();
      if (!id) continue;
      const bySheet = members.get(id) ?? new Map<string, Set<string>>();
      const names = bySheet.get(sheet) ?? new Set<string>();
      names.add(stringValue(row.name));
      bySheet.set(sheet, names);
      members.set(id, bySheet);
    }
  }
  const regs = registry(model);
  regs.forEach((_reg, id) => { if (!members.has(id)) members.set(id, new Map()); });
  return Array.from(members.entries()).map(([plantId, bySheet]) => {
    const reg = regs.get(plantId);
    const live = new Set<string>();
    bySheet.forEach((names, sheet) => names.forEach((n) => live.add(`${sheet}\u0000${n}`)));
    const regComps = (reg?.components as Array<{ sheet: string; name: string; role?: string }> | undefined)
      ?? Array.from(bySheet.entries()).flatMap(([sheet, names]) => Array.from(names).map((name) => ({ sheet, name, role: '' })));
    return {
      plantId,
      type: (reg?.type as string | undefined) ?? null,
      label: (reg?.label as string | undefined) ?? plantId,
      bus: (reg?.bus as string | undefined) ?? null,
      capacityMwEl: typeof reg?.capacityMwEl === 'number' ? reg.capacityMwEl : null,
      extendable: typeof reg?.extendable === 'boolean' ? reg.extendable : null,
      editable: reg !== undefined,
      spec: (reg?.spec as Record<string, unknown> | undefined) ?? null,
      components: regComps.filter((c) => c.sheet !== PLANT_SHEET).map((c) => ({ sheet: c.sheet, name: c.name, role: c.role ?? '', present: live.has(`${c.sheet}\u0000${c.name}`) })),
      rowCount: Array.from(bySheet.values()).reduce((n, s) => n + s.size, 0),
      derived: reg && (reg.partLoad || reg.startCosts) ? { partLoad: reg.partLoad as PlantDerivedValues['partLoad'], startCosts: reg.startCosts as PlantDerivedValues['startCosts'] } : null,
    };
  });
}

/** The model with a change set's `remove` and `release` applied (rows gone, shared rows lose their plant id). The fragment is merged by the caller. */
export function applyPlantChange(model: WorkbookModel, change: Pick<PlantChange, 'remove' | 'release'>): WorkbookModel {
  const out: WorkbookModel = { ...model };
  for (const [sheet, names] of Object.entries(change.remove ?? {})) {
    if (!out[sheet]) continue;
    const gone = new Set(names);
    out[sheet] = out[sheet].filter((r) => !gone.has(stringValue(r.name)));
  }
  for (const rel of change.release ?? []) {
    if (!out[rel.sheet]) continue;
    out[rel.sheet] = out[rel.sheet].map((r) => {
      if (stringValue(r.name) !== rel.name) return r;
      const { [PLANT_COLUMN]: _drop, ...rest } = r;
      return rest;
    });
  }
  return out;
}

export interface PlantMarker { plantId: string; label: string; type: string | null; coords: [number, number]; capacityMwEl: number | null; componentCount: number }

function coordsOf(row: GridRow | undefined): [number, number] | null {
  if (!row) return null;
  const x = row.x;
  const y = row.y;
  if (x === undefined || x === null || x === '' || y === undefined || y === null || y === '') return null;
  return [numberValue(y), numberValue(x)];
}

/** One map marker per plant, at its connection bus (a small offset keeps it off the bus marker). Plants whose bus has no coordinates draw none. */
export function plantMarkers(model: WorkbookModel, busIndex: Record<string, GridRow>): PlantMarker[] {
  const out: PlantMarker[] = [];
  const cards = plantCards(model);
  cards.forEach((card, i) => {
    const busName = card.bus ?? stringValue(((model.generators ?? []).concat(model.links ?? [], model.storage_units ?? []).find((r) => stringValue(r[PLANT_COLUMN]) === card.plantId) ?? {}).bus);
    const c = coordsOf(busIndex[busName]);
    if (!c) return;
    const k = cards.slice(0, i).filter((o) => o.bus === card.bus).length;           // several plants on one bus fan out
    out.push({ plantId: card.plantId, label: card.label, type: card.type, coords: [c[0] + 0.05 + 0.03 * k, c[1] - 0.05 - 0.03 * k], capacityMwEl: card.capacityMwEl, componentCount: card.rowCount });
  });
  return out;
}

/** Whether any remaining row references bus `name` (used to explain what a deletion keeps). */
export function busReferenced(model: WorkbookModel, name: string): boolean {
  return Object.keys(model).some((sheet) => isStaticSheet(model, sheet) && sheet !== 'buses' && model[sheet].some((r) => BUS_COLUMNS.some((c) => stringValue(r[c]) === name)));
}
