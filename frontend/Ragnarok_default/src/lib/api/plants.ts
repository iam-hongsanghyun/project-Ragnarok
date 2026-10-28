/**
 * Build-plant HTTP client — `/api/build/plant*` (types, preview of add / edit / delete as a change set, results by plant).
 *
 * Stateless from the browser's side: it sends the static sheets it holds and gets a change set back
 * (`lib/build/plants.ts` -> `applyPlantChange` + the fragment merge). Nothing here computes a cost or a share.
 */
import { API_BASE } from 'lib/constants';
import type { GridRow, WorkbookModel } from 'lib/types';
import type { PlantChange } from 'lib/build/plants';

export type PlantFieldKind = 'number' | 'bool' | 'select' | 'text' | 'bus' | 'carrier' | 'json';
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
}
export interface PlantType { id: string; label: string; description: string; fields: PlantField[]; defaults: Record<string, unknown>; technology: string | null }

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
const MODEL_SHEETS = ['buses', 'carriers', 'generators', 'loads', 'links', 'processes', 'stores', 'storage_units', 'lines', 'transformers', 'snapshots', 'RAGNAROK_PLANTS', 'RAGNAROK_P2X',
  // module rows keyed by plant component: edit / delete must see them to remove them with the plant
  'RAGNAROK_TimeUnits', 'RAGNAROK_StartCosts', 'links-efficiency-pw'];

export function modelForPlants(model: WorkbookModel): Record<string, GridRow[]> {
  const m = model as Record<string, GridRow[]>;
  return Object.fromEntries(MODEL_SHEETS.map((s) => [s, m[s] ?? []]));
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

export interface PlantResults {
  currency: string;
  windowYears: number;
  plants: Array<Record<string, unknown> & { plantId: string; type: string | null; label: string }>;
  totals: Record<string, number>;
}
export async function fetchPlantResults(run: string, plant?: string, period?: number | null): Promise<PlantResults> {
  const q = new URLSearchParams();
  if (plant) q.set('plant', plant);
  if (period !== undefined && period !== null) q.set('period', String(period));
  return readJson<PlantResults>(await fetch(`${API_BASE}/api/build/plant/results/${encodeURIComponent(run)}?${q.toString()}`));
}
