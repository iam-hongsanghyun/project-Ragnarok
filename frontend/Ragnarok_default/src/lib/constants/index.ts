import { ConstraintMetric, CustomConstraint } from 'lib/types';
export { API_BASE, MAX_UNPINNED_HISTORY, MODULES_CONFIG, RUN_POLLING, RUN_WINDOW, SETTINGS_CONFIG, SETTINGS_DEFAULTS, CURRENCIES } from './config';
export { SHEETS, TS_SHEETS } from './sheets';
export {
  PYPSA_SCHEMA,
  PYPSA_SCHEMA_META,
  PYPSA_COMPONENTS,
  NETWORK_IMPORT_POLICY,
  NETWORK_RUNTIME_IMPORT_FIELDS,
  TABLE_GROUPS,
  getAddableAttributes,
  getComponentSchema,
  getDefaultRowForSheet,
  getOrderedInputAttributes,
  getProtectedColumns,
  normalizeSheetName,
} from './pypsa_schema';

// ── Carrier colors ────────────────────────────────────────────────────────────

// Only the system-injected "LoadShedding" carrier has a built-in colour.
// All real carrier colours come from the user's workbook (`carriers.color`
// column) or are auto-assigned by hashColor() when the column is blank.
export const CARRIER_COLORS: Record<string, string> = {
  LoadShedding: '#991b1b',
};

// ── Constraint definitions ────────────────────────────────────────────────────

export const METRIC_DEFS: Record<ConstraintMetric, { label: string; description: string; unit: string; needsCarrier: boolean; sense: string }> = {
  co2_cap:          { label: 'CO₂ Intensity Cap',       description: 'Avg emission intensity ≤ value (tCO₂/MWh, matches carriers.co2_emissions)', unit: 'tCO₂/MWh', needsCarrier: false, sense: '≤' },
  max_load_shed:    { label: 'Max Load Shedding',      description: 'Total unserved energy ≤ value',             unit: 'MWh',    needsCarrier: false, sense: '≤' },
  carrier_max_gen:  { label: 'Max Carrier Generation', description: 'Total output of carrier ≤ value (MWh)',     unit: 'MWh',    needsCarrier: true,  sense: '≤' },
  carrier_min_gen:  { label: 'Min Carrier Generation', description: 'Total output of carrier ≥ value (MWh)',     unit: 'MWh',    needsCarrier: true,  sense: '≥' },
  carrier_max_share:{ label: 'Max Carrier Share',      description: 'Carrier dispatch / total dispatch ≤ value', unit: '%',      needsCarrier: true,  sense: '≤' },
  carrier_min_share:{ label: 'Min Carrier Share',      description: 'Carrier dispatch / total dispatch ≥ value', unit: '%',      needsCarrier: true,  sense: '≥' },
  carrier_max_cf:   { label: 'Max Carrier Capacity Factor', description: 'Weighted generation / (carrier capacity × modeled hours) ≤ value', unit: '%', needsCarrier: true, sense: '≤' },
  carrier_min_cf:   { label: 'Min Carrier Capacity Factor', description: 'Weighted generation / (carrier capacity × modeled hours) ≥ value', unit: '%', needsCarrier: true, sense: '≥' },
};

export const DEFAULT_CONSTRAINTS: CustomConstraint[] = [];

export const EMPTY_METRIC_KEY = '__empty__';
