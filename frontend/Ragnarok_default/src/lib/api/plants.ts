/**
 * Build-plant HTTP client — `/api/build/plant*` (types, preview of add / edit / delete as a change set, results by plant).
 *
 * Stateless from the browser's side: it sends the static sheets it holds and gets a change set back
 * (`lib/build/plants.ts` -> `applyPlantChange` + the fragment merge). Nothing here computes a cost or a share.
 */
import { API_BASE } from 'lib/constants';
import type { GridRow, WorkbookModel } from 'lib/types';
import type { PlantChange } from 'lib/build/plants';
import type { TechEntry, TechParam } from 'lib/api/p2x';

export type PlantFieldKind = 'number' | 'bool' | 'select' | 'text' | 'bus' | 'carrier' | 'json' | 'generators';
/** What a connection port is: the role of the bus, or `generators` (a list of existing generators). */
export type PlantPortRole = 'electricity' | 'gas' | 'h2' | 'product' | 'generators';
export interface PlantField {
  key: string;
  label: string;
  kind: PlantFieldKind;
  default: unknown;
  advanced: boolean;
  unit?: string;
  help?: string;
  options?: string[];
  min?: number;
  /** Set when the field is a connection (bus or generators) rather than a parameter. */
  port?: PlantPortRole;
  /** In words, what leaving a port empty does ("create an H2 bus ..."). */
  blank?: string;
}
export interface PlantType { id: string; label: string; description: string; fields: PlantField[]; defaults: Record<string, unknown>; technology: string | null; portNote?: string | null }

/** Part-load heat-rate line the backend derived (MW_th, MW_el; see `backend/app/plants/partload.py`). */
export interface PlantPartLoad {
  route: 'piecewise-link' | 'stand-by-generator';
  pElMw: number; minLoad: number; etaFull: number; etaMin: number;
  fuelFullMw: number; fuelMinMw: number; noLoadFuelMw: number; incrementalHeatRate: number; incrementalEfficiency: number; minLoadPu: number;
  written?: { stand_by_cost: number; marginal_cost: number };
  formula: string;
}
/** Start cost per start (currency): `hot` is PyPSA's start_up_cost; warm / cold are added by the plants module. */
export interface PlantStartCosts {
  hot: number; hotPerMw: number; nativeStartUpCost: number;
  warm?: number; warmPerMw?: number; warmAfterHours?: number | null;
  cold?: number; coldPerMw?: number; coldAfterHours?: number | null;
  unit: string;
}
/** The registry fields a form shows as derived values (absent when the plant does not use the option). */
export interface PlantDerived { partLoad?: PlantPartLoad; startCosts?: PlantStartCosts }

export interface PlantPreview {
  plantId: string;
  type: string;
  label: string;
  /** Registry row of the plant about to be written: the derived part-load line and start costs are in it. */
  registry?: PlantDerived & Record<string, unknown>;
  summary: Array<Record<string, unknown>>;
  warnings: string[];
  rowCounts: Record<string, number>;
  spec: Record<string, unknown>;
  /** Technology-data keys the build read: `plants` (plant file, `fuels` = the fuel prices) and `p2x` (P2X file). */
  technologies?: { plants: string[]; p2x: string[] };
  change: PlantChange;
  removed?: Record<string, number>;
}
export interface PlantDeletePreview { plantId: string; change: PlantChange; removed: Record<string, number>; kept: PlantChange['kept']; warnings: string[] }

async function readJson<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json())?.detail ?? detail; } catch { /* non-JSON body */ }
    throw new Error(String(detail));
  }
  return resp.json() as Promise<T>;
}

const post = async <T,>(path: string, body: unknown): Promise<T> =>
  readJson<T>(await fetch(`${API_BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }));

/** The sheets the backend reads to name, place and wire a plant (names, buses, carriers, snapshots, both registries). */
const MODEL_SHEETS = ['buses', 'carriers', 'generators', 'loads', 'links', 'processes', 'stores', 'storage_units', 'lines', 'transformers', 'snapshots', 'RAGNAROK_PLANTS', 'RAGNAROK_P2X', 'RAGNAROK_Composites',
  // module rows keyed by plant component: edit / delete must see them to remove them with the plant
  'RAGNAROK_TimeUnits', 'RAGNAROK_StartCosts', 'links-efficiency-pw'];

export function modelForPlants(model: WorkbookModel): Record<string, GridRow[]> {
  const m = model as Record<string, GridRow[]>;
  return Object.fromEntries(MODEL_SHEETS.map((s) => [s, m[s] ?? []]));
}

/** One plant card of `GET /api/build/plants` (only what a run-option editor needs). */
export interface PlantSummary { plantId: string; type: string | null; label: string }

/** The plants of the session model. */
export async function fetchPlants(sessionId: string): Promise<PlantSummary[]> {
  const body = await readJson<{ plants: PlantSummary[] }>(await fetch(`${API_BASE}/api/build/plants?session_id=${encodeURIComponent(sessionId)}`));
  return body.plants;
}

export async function fetchPlantTypes(): Promise<PlantType[]> {
  return (await readJson<{ types: PlantType[] }>(await fetch(`${API_BASE}/api/build/plant/types`))).types;
}

export const previewPlant = (type: string, spec: Record<string, unknown>, model: WorkbookModel) =>
  post<PlantPreview>('/api/build/plant', { type, spec, model: modelForPlants(model) });

export const previewPlantEdit = (plantId: string, spec: Record<string, unknown>, model: WorkbookModel) =>
  post<PlantPreview>('/api/build/plant/edit', { plantId, spec, model: modelForPlants(model) });

export const previewPlantDelete = (plantId: string, model: WorkbookModel) =>
  post<PlantDeletePreview>('/api/build/plant/delete', { plantId, model: modelForPlants(model) });

/** Per-tier start counts and cost of a committable plant (`backend/app/plants/results.py`). */
export interface PlantStartCostResult {
  starts: Record<string, number>; startCost: number; nativeStartUpCost: number; tierIncrement: number; basis: string;
}
export interface PlantResult {
  plantId: string; type: string | null; label: string; bus?: string | null;
  capacityMwEl?: number; generationMwh?: number; capacityFactor?: number; fullLoadHours?: number; electricityInMwh?: number;
  operatingCost: number; fixedCost: number; fuelCost: number; commitmentCost?: number; totalCost: number; standByCost?: number;
  starts?: number; startCosts?: PlantStartCostResult;
  storage?: { chargeMwh: number; dischargeMwh: number; energyCapacityMwh: number; equivalentCycles: number };
  fuel?: { gasMwhTh: number; h2MwhTh: number; totalMwhTh: number; h2EnergyShare: number; h2VolShare: number };
  emissions?: { actualT: number; gasOnlyBaselineT: number; avoidedT: number; avoidedShare: number };
  cofiring?: { hoursOn: number; maxHourlyEnergyShare: number; minHourlyEnergyShare: number };
  p2x?: { lcohPerKg: number; h2Tonnes: number; electrolyserCapacityFactor: number; products: Record<string, { costPerTonne: number; producedTonnes: number }> };
  warnings: string[];
}
export interface PlantResults {
  currency: string;
  windowYears: number;
  plants: PlantResult[];
  totals: Record<string, number>;
}
export async function fetchPlantResults(run: string, plant?: string, period?: number | null): Promise<PlantResults> {
  const q = new URLSearchParams();
  if (plant) q.set('plant', plant);
  if (period !== undefined && period !== null) q.set('period', String(period));
  return readJson<PlantResults>(await fetch(`${API_BASE}/api/build/plant/results/${encodeURIComponent(run)}?${q.toString()}`));
}

/** `GET /api/build/plant/technologies`: the plant technology data file (value, unit, source, verified flag per parameter). */
export interface PlantTechnologies {
  basis: { currency: string; costYear: number; technologyYear: number };
  fuels: Record<string, TechParam>;
  technologies: Record<string, TechEntry>;
}
export async function fetchPlantTechnologies(): Promise<PlantTechnologies> {
  return readJson<PlantTechnologies>(await fetch(`${API_BASE}/api/build/plant/technologies`));
}

/** `POST /api/build/composite/sync`: the change that re-expands composites whose RAGNAROK_Composites row was edited (null = none). */
export interface CompositeSync { plantIds: string[]; patches: Record<string, Record<string, unknown>>; added: string[]; change: PlantChange | null; warnings: string[]; rowCounts?: Record<string, number> }
export const previewCompositeSync = (model: WorkbookModel) => post<CompositeSync>('/api/build/composite/sync', { model: modelForPlants(model) });

/** `POST /api/build/plant/place`: one composite template on several buses, N independent instances `<prefix>_<bus>`. */
export interface PlacePreview { plantIds: string[]; instances: Array<{ plantId: string; bus: string; rowCounts: Record<string, number> }>; warnings: string[]; change: PlantChange }
export const previewPlace = (type: string, spec: Record<string, unknown>, buses: string[], prefix: string, sharePorts: boolean, model: WorkbookModel) =>
  post<PlacePreview>('/api/build/plant/place', { type, spec, buses, prefix: prefix || null, sharePorts, model: modelForPlants(model) });

/** `POST /api/build/plant/detach`: the composite becomes plain rows (owner tag, registry and sheet rows removed). */
export const previewDetach = (plantId: string, model: WorkbookModel) =>
  post<{ plantId: string; change: PlantChange }>('/api/build/plant/detach', { plantId, model: modelForPlants(model) });
