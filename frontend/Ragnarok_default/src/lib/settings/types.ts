/**
 * Settings type definitions — split from `features/settings/useSettings.ts`
 * so lib code (helpers, exporters, etc.) can reference the shape without
 * pulling in the React hook.
 *
 * The actual hook (`useSettings`) lives in `features/settings/useSettings.ts`
 * and re-exports these for back-compatibility.
 */

export type DateFormat = 'auto' | 'dmy' | 'mdy' | 'ymd';
// HiGHS is always the solver; this picks its method. 'auto' lets HiGHS choose.
export type SolverType = 'auto' | 'simplex' | 'ipm' | 'pdlp';

export interface AppSettings {
  dateFormat: DateFormat;
  solverThreads: number; // 0 = let HiGHS decide (all cores)
  solverType: SolverType;
  currencyCode: string; // ISO 4217 code, e.g. "USD"
  currencySymbol: string; // display symbol, e.g. "$"
  enableLoadShedding: boolean;
  loadSheddingCost: number; // VOLL in the currently-selected currency, per MWh
  discountRate: number; // Used to annualise CAPEX for extendable assets
}
