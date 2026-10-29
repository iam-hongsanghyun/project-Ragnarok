import appConfigJson from 'config/app_config.json';
import currenciesJson from 'config/currencies.json';
import type { DateFormat, SolveAcceptance, SolverType } from 'lib/settings/types';

type AppConfig = typeof appConfigJson;

export interface CurrencyConfig {
  code: string;
  symbol: string;
  name: string;
}

export interface SettingsDefaultsConfig {
  dateFormat: DateFormat;
  solverThreads: number;
  solverType: SolverType;
  solveAcceptance: SolveAcceptance;
  objectiveAutoScale: boolean;
  currencyCode: string;
  currencySymbol: string;
  enableLoadShedding: boolean;
  loadSheddingCost: number;
  discountRate: number;
  queuePollSeconds: number;
  /** Comma-separated TabModuleIds (see src/modules/registry). */
  enabledModules: string;
  seenModules?: string;
}

export const APP_CONFIG: AppConfig = appConfigJson;
export const CURRENCIES: CurrencyConfig[] = currenciesJson as CurrencyConfig[];

/**
 * Base URL of the backend API. The app talks to ITS OWN origin whatever hostname it was opened on
 * (`localhost`, `127.0.0.1`, a LAN name): a same-origin call needs no CORS and no second port. Only an
 * explicit `REACT_APP_API_BASE` (build-time) or `api.baseUrl` in app_config.json overrides that. The dev
 * server (`npm start`) reaches the backend through the CRA `proxy` in package.json, so it needs no base either.
 */
export function resolveApiBase(...explicit: Array<string | undefined | null>): string {
  const chosen = explicit.map((v) => (v ?? '').trim()).find((v) => v !== '') ?? '';
  return chosen.replace(/\/+$/, '');
}

export const API_BASE = resolveApiBase(process.env.REACT_APP_API_BASE, APP_CONFIG.api.baseUrl);

export const MAX_UNPINNED_HISTORY = APP_CONFIG.runHistory.maxUnpinnedEntries;
export const RUN_POLLING = APP_CONFIG.runPolling;
export const RUN_WINDOW = APP_CONFIG.runWindow;

/**
 * Server-authoritative run-window defaults (`GET /api/config` →
 * `simulation_defaults`) win over the values shipped in app_config.json. Called
 * once at boot, before the app reads RUN_WINDOW; non-positive/missing values
 * leave the shipped default in place.
 */
export function applySimulationDefaults(
  defaults: { defaultSnapshotCount?: number; defaultSnapshotWeight?: number } | undefined,
): void {
  const count = defaults?.defaultSnapshotCount;
  const weight = defaults?.defaultSnapshotWeight;
  if (typeof count === 'number' && Number.isFinite(count) && count > 0) {
    RUN_WINDOW.defaultSnapshotEnd = Math.floor(count);
  }
  if (typeof weight === 'number' && Number.isFinite(weight) && weight > 0) {
    RUN_WINDOW.defaultSnapshotWeight = weight;
  }
}
export const FORGE_CONFIG = APP_CONFIG.forge;
export const VALIDATION_CONFIG = APP_CONFIG.validation;
export const CARBON_CHART_CONFIG = APP_CONFIG.carbonChart;
export const SETTINGS_CONFIG = APP_CONFIG.settings;
export const SETTINGS_DEFAULTS: SettingsDefaultsConfig = APP_CONFIG.settings.defaults as SettingsDefaultsConfig;
export const MODULES_CONFIG = APP_CONFIG.modules;
