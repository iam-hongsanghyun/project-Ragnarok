/**
 * Forge / Build helpers served by the backend (WA8) — the same code the MCP
 * tools run: spatial snap, bulk adjust, and the sector-coupling conversion
 * templates. Stateless from the browser's side: it sends the rows it holds and
 * gets the result back; nothing here writes the session.
 */
import { API_BASE } from 'lib/constants';
import { DEFAULT_SESSION_ID } from 'lib/api/session';
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

/** `anchorBus` is optional: the backend then picks the default electricity bus of `model`.
 *  `discountRate` is written to an extendable row as PyPSA's `discount_rate` (Settings -> Discount rate). */
export interface ConversionOptions { anchorBus?: string; name?: string; pNom: number; extendable: boolean; discountRate?: number }

export interface ConversionBuild { fragment: WorkbookFragment; anchorBus: string }

/** The fragment adding one conversion technology to `model` (only buses, carriers,
 *  generators, links and the snapshots - which give the horizon `fom_cost` is written for - are read,
 *  so only those sheets are sent). */
export async function buildConversion(
  templateId: string,
  options: ConversionOptions,
  model: WorkbookModel,
): Promise<ConversionBuild> {
  const m = model as unknown as Record<string, unknown>;
  const subset = Object.fromEntries(['buses', 'carriers', 'generators', 'links', 'snapshots'].map((s) => [s, m[s] ?? []]));
  return postJson<ConversionBuild>('/api/build/conversion', {
    templateId, anchorBus: options.anchorBus || undefined, name: options.name, pNom: options.pNom,
    extendable: options.extendable, discountRate: options.discountRate, model: subset,
  });
}

/** Result of the Forge "Fill discount rate" action. */
export interface FillDiscountRateResult {
  filled: number;
  overwritten: number;
  skipped: number;
  sheets: Record<string, number>;
  applied: boolean;
}

/** Forge action behind Settings -> Discount rate: write `discount_rate` into every row that carries an
 *  `overnight_cost` (PyPSA annuitises it with the row's own rate). Previews unless `apply`. */
export async function fillDiscountRate(
  discountRate: number,
  opts: { overwrite?: boolean; apply?: boolean } = {},
): Promise<FillDiscountRateResult> {
  return postJson<FillDiscountRateResult>('/api/forge/fill-discount-rate', {
    discountRate, overwrite: opts.overwrite ?? false, apply: opts.apply ?? false,
  });
}

/** Result of the Forge "Clean placeholder bounds" action. */
export interface CleanPlaceholderBoundsResult {
  cleaned: number;
  cells: { sheet: string; name: string; column: string; value: number }[];
  sheets: Record<string, number>;
  applied: boolean;
}

/** Forge action behind the model-check warning: blank every finite 1e9+ bound (`p_nom_max`, `e_sum_max`,
 *  `lifetime` ... 1e12 standing for "no limit") so the row takes PyPSA's `inf` default. The run no longer
 *  snaps them itself. Previews unless `apply`. */
export async function cleanPlaceholderBounds(
  opts: { apply?: boolean } = {},
): Promise<CleanPlaceholderBoundsResult> {
  return postJson<CleanPlaceholderBoundsResult>('/api/forge/clean-placeholder-bounds', { sessionId: DEFAULT_SESSION_ID, apply: opts.apply ?? false });
}
