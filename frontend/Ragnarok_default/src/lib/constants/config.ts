import appConfigJson from 'config/app_config.json';
import currenciesJson from 'config/currencies.json';
import type { DateFormat, SolverType } from 'lib/settings/types';

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
  objectiveAutoScale: boolean;
  currencyCode: string;
  currencySymbol: string;
  enableLoadShedding: boolean;
  loadSheddingCost: number;
  discountRate: number;
  queuePollSeconds: number;
}

export const APP_CONFIG: AppConfig = appConfigJson;
export const CURRENCIES: CurrencyConfig[] = currenciesJson as CurrencyConfig[];

export const API_BASE =
  window.location.hostname === 'localhost' ? APP_CONFIG.api.localhostBaseUrl : '';

export const MAX_UNPINNED_HISTORY = APP_CONFIG.runHistory.maxUnpinnedEntries;
export const RUN_POLLING = APP_CONFIG.runPolling;
export const RUN_WINDOW = APP_CONFIG.runWindow;
export const FORGE_CONFIG = APP_CONFIG.forge;
export const VALIDATION_CONFIG = APP_CONFIG.validation;
export const CARBON_CHART_CONFIG = APP_CONFIG.carbonChart;
export const SETTINGS_CONFIG = APP_CONFIG.settings;
export const SETTINGS_DEFAULTS: SettingsDefaultsConfig = APP_CONFIG.settings.defaults as SettingsDefaultsConfig;
export const MODULES_CONFIG = APP_CONFIG.modules;
