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
// 'hipo' uses HiGHS's HiPO interior-point solver where the build includes it,
// and falls back to IPM elsewhere (handled server-side) — so it's safe to pick
// on any machine.
export type SolverType = 'auto' | 'simplex' | 'ipm' | 'pdlp' | 'hipo';
// Run-result gate. 'lenient' (default) accepts any solve the toolchain
// validated (linopy status ok) even when HiGHS reports condition='unknown'
// (typical for interior-point runs without crossover). 'strict' requires
// condition='optimal' — vertex-optimal solutions with exact shadow prices.
export type SolveAcceptance = 'lenient' | 'strict';

export interface AppSettings {
  dateFormat: DateFormat;
  solverThreads: number; // 0 = let HiGHS decide (all cores)
  solverType: SolverType;
  solveAcceptance: SolveAcceptance;
  // Pass HiGHS user_objective_scale=-1 — auto-scales a wide-ranging objective
  // (results-neutral) so simplex/PDLP converge faster on badly-scaled LPs.
  objectiveAutoScale: boolean;
  currencyCode: string; // ISO 4217 code, e.g. "USD"
  currencySymbol: string; // display symbol, e.g. "$"
  enableLoadShedding: boolean;
  loadSheddingCost: number; // VOLL in the currently-selected currency, per MWh
  discountRate: number; // Used to annualise CAPEX for extendable assets
  queuePollSeconds: number; // How often the Queue tab polls while a run is active
}
