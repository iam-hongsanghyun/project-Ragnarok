/**
 * Carbon-pricing and annual-budgets modules (backend/app/carbon_pricing, backend/app/annual_budgets): what each
 * sends PyPSA, previewed. The browser only displays the server's table; it computes nothing.
 */
import { API_BASE } from 'lib/constants';

async function call<T>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json())?.detail ?? detail; } catch { /* non-JSON */ }
    throw new Error(`${resp.status}: ${detail}`);
  }
  return resp.json() as Promise<T>;
}

export interface CarbonPreviewRow { generator: string; carrier: string; co2PerMWhFuel: number; adderMean: number; adderMax: number }
export interface CarbonPreview { active: boolean; priceMin: number; priceMax: number; generators: CarbonPreviewRow[]; basis: string }

export function previewCarbonPrice(carbonPrice: number, carbonPriceSchedule: { year: number; price: number }[]): Promise<CarbonPreview> {
  return call<CarbonPreview>('/api/carbon-price/preview', { carbonPrice, carbonPriceSchedule });
}

export interface BudgetRow { component: string; name: string; attribute: string; annual: number }
export interface BudgetTableRow extends BudgetRow { horizonYears: number; value: number; scope: string }
export interface BudgetPreview { table: BudgetTableRow[]; notes: string[] }

export function getAnnualBudgets(): Promise<{ sheet: string; rows: BudgetRow[] }> {
  return call('/api/annual-budgets');
}
export function previewAnnualBudgets(): Promise<BudgetPreview> {
  return call<BudgetPreview>('/api/annual-budgets/preview', {});
}
export function setAnnualBudget(row: BudgetRow): Promise<{ rows: BudgetRow[] }> {
  return call('/api/annual-budgets/set', row);
}
export function applyAnnualBudgets(): Promise<BudgetPreview & { sheetsWritten: string[] }> {
  return call('/api/annual-budgets/apply', {});
}
