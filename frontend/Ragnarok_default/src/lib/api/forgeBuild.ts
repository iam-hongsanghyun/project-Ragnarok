/**
 * Forge / Build helpers served by the backend (WA8) — the same code the MCP
 * tools run: spatial snap, bulk adjust, and the sector-coupling conversion
 * templates. Stateless from the browser's side: it sends the rows it holds and
 * gets the result back; nothing here writes the session.
 */
import { API_BASE } from 'lib/constants';
import type { GridRow, WorkbookModel } from 'lib/types';
import type { WorkbookFragment } from 'lib/api/databases';
import type { SnapResult } from 'lib/forge/snap';
import type { Adjustment } from 'lib/forge/adjust';

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return readJson<T>(resp);
}

async function readJson<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json())?.detail ?? detail; } catch { /* non-JSON */ }
    throw new Error(`${resp.status}: ${detail}`);
  }
  return resp.json() as Promise<T>;
}

export type SnapResponse = SnapResult;

/** Snap `rows` to the nearest of `busRows` within `bufferKm` (x = lon, y = lat). */
export const snapRows = (rows: GridRow[], busRows: GridRow[], bufferKm: number) =>
  postJson<SnapResponse>('/api/forge/snap', { rows, targetRows: busRows, bufferKm });

export interface AdjustResponse {
  sheets: Record<string, GridRow[]>;
  changed: number;
  perAdjustment: number[];
  baseline: Record<string, unknown>;
}

/** Apply adjustments to the given sheets of the model the UI holds. */
export const adjustSheets = (model: Record<string, GridRow[]>, adjustments: Adjustment[]) =>
  postJson<AdjustResponse>('/api/forge/adjust', {
    model,
    adjustments: adjustments.map(({ sheet, attribute, action, amount, filters }) => ({ sheet, attribute, action, amount, filters })),
  });

/** One endpoint of a conversion template (`role: 'power'` binds to the anchor bus). */
export interface ConversionEndpoint { role: 'power' | 'carrier'; carrier?: string; fuel?: boolean }

export interface ConversionTemplate {
  id: string;
  label: string;
  description: string;
  linkCarrier: string;
  input: ConversionEndpoint;
  output: ConversionEndpoint;
  output2?: ConversionEndpoint;
  efficiency: number;
  efficiency2?: number;
  capitalCost: number;
  lifetime?: number;
  fuelCost?: number;
  co2?: number;
}

export interface ConversionList {
  items: ConversionTemplate[];
  total: number;
}

export async function fetchConversionTemplates(): Promise<ConversionList> {
  return readJson<ConversionList>(await fetch(`${API_BASE}/api/build/conversions`));
}

/** `anchorBus` is optional: the backend then picks the default electricity bus of `model`. */
export interface ConversionOptions { anchorBus?: string; name?: string; pNom: number; extendable: boolean }

export interface ConversionBuild { fragment: WorkbookFragment; anchorBus: string }

/** The fragment adding one conversion technology to `model` (only buses, carriers,
 *  generators and links are read, so only those sheets are sent). */
export async function buildConversion(
  templateId: string,
  options: ConversionOptions,
  model: WorkbookModel,
): Promise<ConversionBuild> {
  const m = model as unknown as Record<string, unknown>;
  const subset = Object.fromEntries(['buses', 'carriers', 'generators', 'links'].map((s) => [s, m[s] ?? []]));
  return postJson<ConversionBuild>('/api/build/conversion', {
    templateId, anchorBus: options.anchorBus || undefined, name: options.name, pNom: options.pNom,
    extendable: options.extendable, model: subset,
  });
}
