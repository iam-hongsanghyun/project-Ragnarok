import { ConstraintMetric, CustomConstraint, GridRow, SheetName, TsSheetName } from '../types';
export { SHEETS, TS_SHEETS } from './sheets';

// ── API ───────────────────────────────────────────────────────────────────────

export const API_BASE =
  window.location.hostname === 'localhost' ? 'http://127.0.0.1:8000' : '';

// Maximum number of unpinned run-history entries to retain (pinned entries are unaffected).
export const MAX_UNPINNED_HISTORY = 5;

// ── Default row templates ─────────────────────────────────────────────────────

export const DEFAULT_SHEET_ROWS: Record<SheetName, GridRow> = {
  network: { name: 'Untitled PyPSA Case', _multi_invest: false, pypsa_version: '1.1.2', srid: 4326 },
  snapshots: { snapshot: 'now', objective: 1, stores: 1, generators: 1 },
  carriers: { name: 'AC' },
  buses: {
    name: 'New Bus', x: 126.978, y: 37.5665, v_nom: 154, carrier: 'AC',
    unit: 'kV', control: 'PQ', v_mag_pu_set: 1, v_mag_pu_min: 0.95, v_mag_pu_max: 1.05, sub_network: 0,
  },
  generators: {
    name: 'new_generator', bus: 'New Bus', control: 'PV', carrier: 'LNG',
    p_nom: 100, p_nom_min: 0, p_min_pu: 0.3, p_max_pu: 1, p_set: 70, q_set: 0,
    marginal_cost: 75, capital_cost: 0, committable: true,
    extendable: false, asset_lifetime: 20,
  },
  loads: { name: 'new_load', bus: 'New Bus', carrier: 'load', p_set: 100, q_set: 0, sign: 1 },
  links: {
    name: 'new_link', bus0: 'New Bus', bus1: 'New Bus', carrier: 'HVDC',
    p_nom: 250, p_min_pu: -1, p_max_pu: 1, efficiency: 0.97, marginal_cost: 0,
  },
  lines: {
    name: 'new_line', bus0: 'New Bus', bus1: 'New Bus', type: '',
    x: 0.15, r: 0.03, b: 0, s_nom: 250, length: 20, num_parallel: 1, s_max_pu: 1,
  },
  stores: {
    name: 'new_store', bus: 'New Bus', carrier: 'battery', e_nom: 500,
    e_initial: 100, e_min_pu: 0, e_max_pu: 1, standing_loss: 0.001, marginal_cost: 0,
  },
  storage_units: {
    name: 'new_storage_unit', bus: 'New Bus', carrier: 'battery', p_nom: 200,
    max_hours: 4, efficiency_store: 0.91, efficiency_dispatch: 0.91,
    state_of_charge_initial: 0, cyclic_state_of_charge: true, marginal_cost: 5,
    capital_cost: 0, extendable: false, asset_lifetime: 15,
  },
  transformers: {
    name: 'new_transformer', bus0: 'New Bus', bus1: 'New Bus', type: '', model: 't',
    x: 0.02, r: 0.002, g: 0, b: 0.05, s_nom: 250, tap_ratio: 1, tap_side: 0, phase_shift: 0, s_max_pu: 1,
  },
  shunt_impedances: { name: 'new_shunt', bus: 'New Bus', g: 0, b: 0.01, sign: 1 },
  global_constraints: {
    name: 'co2_cap', type: 'primary_energy', carrier_attribute: 'co2_emissions',
    sense: '<=', constant: 1000000, investment_period: '',
  },
  shapes: {
    name: 'new_shape', component: 'Bus', idx: 'New Bus',
    x1: 126.97, y1: 37.56, x2: 127.02, y2: 37.61,
  },
  processes: {
    name: 'new_process', bus0: 'New Bus', bus1: 'New Bus',
    carrier: '', p_nom: 100, efficiency: 0.75,
    p_min_pu: 0, p_max_pu: 1, marginal_cost: 0, capital_cost: 0,
  },
};

// ── Carrier colors ────────────────────────────────────────────────────────────

export const CARRIER_COLORS: Record<string, string> = {
  AC: '#475569', LNG: '#1f4e79', Coal: '#374151', Nuclear: '#7c3aed',
  Solar: '#f59e0b', Wind: '#0f766e', Hydro: '#2563eb', Storage: '#14b8a6',
  battery: '#0ea5e9', Imports: '#dc2626', LoadShedding: '#991b1b',
  load: '#94a3b8', HVDC: '#6366f1', Other: '#94a3b8',
};

// ── Constraint definitions ────────────────────────────────────────────────────

export const METRIC_DEFS: Record<ConstraintMetric, { label: string; description: string; unit: string; needsCarrier: boolean; sense: string }> = {
  co2_cap:          { label: 'CO₂ Intensity Cap',       description: 'Avg emission intensity ≤ value (kg CO₂e/MWh)', unit: 'kg CO₂e/MWh', needsCarrier: false, sense: '≤' },
  re_share:         { label: 'Min Renewable Share',    description: 'Solar+Wind+Hydro share ≥ value',            unit: '%',      needsCarrier: false, sense: '≥' },
  max_load_shed:    { label: 'Max Load Shedding',      description: 'Total unserved energy ≤ value',             unit: 'MWh',    needsCarrier: false, sense: '≤' },
  carrier_max_gen:  { label: 'Max Carrier Generation', description: 'Total output of carrier ≤ value',           unit: 'GWh',    needsCarrier: true,  sense: '≤' },
  carrier_min_gen:  { label: 'Min Carrier Generation', description: 'Total output of carrier ≥ value',           unit: 'GWh',    needsCarrier: true,  sense: '≥' },
  carrier_max_share:{ label: 'Max Carrier Share',      description: 'Carrier dispatch / total dispatch ≤ value', unit: '%',      needsCarrier: true,  sense: '≤' },
  carrier_min_share:{ label: 'Min Carrier Share',      description: 'Carrier dispatch / total dispatch ≥ value', unit: '%',      needsCarrier: true,  sense: '≥' },
  carrier_max_cf:   { label: 'Max Carrier Capacity Factor', description: 'Weighted generation / (carrier capacity × modeled hours) ≤ value', unit: '%', needsCarrier: true, sense: '≤' },
  carrier_min_cf:   { label: 'Min Carrier Capacity Factor', description: 'Weighted generation / (carrier capacity × modeled hours) ≥ value', unit: '%', needsCarrier: true, sense: '≥' },
};

export const DEFAULT_CONSTRAINTS: CustomConstraint[] = [];

export const EMPTY_METRIC_KEY = '__empty__';

// ── Tables pane groups ────────────────────────────────────────────────────────

export const TABLE_GROUPS: Array<{ label: string; sheet: SheetName; tsSheet?: TsSheetName }> = [
  { label: 'Network',            sheet: 'network' },
  { label: 'Snapshots',          sheet: 'snapshots' },
  { label: 'Carriers',           sheet: 'carriers' },
  { label: 'Buses',              sheet: 'buses' },
  { label: 'Generators',         sheet: 'generators',    tsSheet: 'generators-p_max_pu' },
  { label: 'Loads',              sheet: 'loads',         tsSheet: 'loads-p_set' },
  { label: 'Lines',              sheet: 'lines' },
  { label: 'Links',              sheet: 'links',         tsSheet: 'links-p_max_pu' },
  { label: 'Stores',             sheet: 'stores' },
  { label: 'Storage Units',      sheet: 'storage_units', tsSheet: 'storage_units-inflow' },
  { label: 'Transformers',       sheet: 'transformers' },
  { label: 'Shunt Impedances',   sheet: 'shunt_impedances' },
  { label: 'Global Constraints', sheet: 'global_constraints' },
  { label: 'Processes',          sheet: 'processes' },
];
