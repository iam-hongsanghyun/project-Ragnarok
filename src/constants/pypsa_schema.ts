import rawSchema from '../config/pypsa_schema.json';
import rawNetworkImportPolicy from '../config/network_import_policy.json';
import { GridRow, Primitive } from '../shared/types';

export type PypsaAttrStatus = 'input' | 'output';
export type PypsaAttrStorage = 'static' | 'series' | 'static_or_series';

export interface PypsaAttribute {
  attribute: string;
  type: string;
  unit: string;
  default: string;
  description: string;
  status: PypsaAttrStatus;
  raw_status: string;
  required: boolean;
  storage: PypsaAttrStorage;
}

export interface PypsaComponentSchema {
  unique_id: string;
  component_name: string;
  list_name: string;
  sheet_name: string;
  label: string;
  category: string;
  source_file: string;
  attributes: PypsaAttribute[];
  input_attributes: string[];
  output_attributes: string[];
  temporal_attributes: string[];
  static_attributes: string[];
  input_temporal_attributes: string[];
  input_static_attributes: string[];
  order: number;
}

interface PypsaSchemaFile {
  meta: {
    repo: string;
    ref: string;
    commit_sha: string;
    generated_at: string;
    generator: string;
    note: string;
    /**
     * Sheet names that are not bulk-added as PyPSA components by the backend.
     * Some of them are still exposed in the frontend table UI and preserved in
     * workbook round-trips (`network`, `shapes`, `sub_networks`).
     */
    non_component_sheets?: string[];
  };
  components: Record<string, PypsaComponentSchema>;
}

export interface NetworkImportPolicyField {
  field: string;
  enabled_for_runtime_import: boolean;
  target: string;
  coercion: string;
  notes?: string;
}

interface NetworkImportPolicyFile {
  fields: NetworkImportPolicyField[];
}

export interface TableGroup {
  uniqueId: string;
  label: string;
  sheet: string;
  temporalSheets: Array<{ sheet: string; attribute: string; label: string }>;
  component: PypsaComponentSchema;
}

export const PYPSA_SCHEMA = rawSchema as PypsaSchemaFile;
export const NETWORK_IMPORT_POLICY = rawNetworkImportPolicy as NetworkImportPolicyFile;
export const PYPSA_SCHEMA_META = PYPSA_SCHEMA.meta;
/** Sheets that the backend does not bulk-add as standard PyPSA components. */
export const NON_COMPONENT_SHEETS: ReadonlySet<string> = new Set(PYPSA_SCHEMA_META.non_component_sheets ?? []);

export const PYPSA_COMPONENTS = Object.values(PYPSA_SCHEMA.components)
  .sort((a, b) => a.order - b.order || a.label.localeCompare(b.label));

export const PYPSA_COMPONENT_BY_SHEET = Object.fromEntries(
  PYPSA_COMPONENTS.map((component) => [component.sheet_name, component]),
) as Record<string, PypsaComponentSchema>;

export const NETWORK_RUNTIME_IMPORT_FIELDS = NETWORK_IMPORT_POLICY.fields.filter(
  (field) => field.enabled_for_runtime_import,
);

export const STATIC_INPUT_COMPONENTS = PYPSA_COMPONENTS.filter((component) => component.sheet_name !== 'snapshots');

export const SHEETS = PYPSA_COMPONENTS.map((component) => component.sheet_name);
export const TS_SHEETS = PYPSA_COMPONENTS.flatMap((component) =>
  component.input_temporal_attributes.map((attribute) => `${component.sheet_name}-${attribute}`),
);
export const ALL_KNOWN_TS_SHEETS = PYPSA_COMPONENTS.flatMap((component) =>
  component.temporal_attributes.map((attribute) => `${component.sheet_name}-${attribute}`),
);
export const ALL_KNOWN_SHEETS = [...SHEETS, ...ALL_KNOWN_TS_SHEETS];

export const TABLE_GROUPS: TableGroup[] = PYPSA_COMPONENTS.map((component) => ({
  uniqueId: component.unique_id,
  label: component.label,
  sheet: component.sheet_name,
  temporalSheets: component.input_temporal_attributes.map((attribute) => ({
    sheet: `${component.sheet_name}-${attribute}`,
    attribute,
    label: attribute,
  })),
  component,
}));

function defaultCellValue(attr: PypsaAttribute): Primitive {
  const raw = String(attr.default ?? '').trim();
  if (!raw || raw.toLowerCase() === 'n/a' || raw.toLowerCase() === 'none' || raw.toLowerCase() === 'nan') return '';
  const loweredType = attr.type.toLowerCase();
  if (loweredType.includes('bool')) return raw.toLowerCase() === 'true';
  if (loweredType.includes('int') || loweredType.includes('float') || loweredType.includes('number')) {
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : '';
  }
  return raw;
}

export function getComponentSchema(sheet: string): PypsaComponentSchema | null {
  return PYPSA_COMPONENT_BY_SHEET[sheet] ?? null;
}

export function getAttributeSchema(sheet: string, attribute: string): PypsaAttribute | null {
  const component = getComponentSchema(sheet);
  return component?.attributes.find((attr) => attr.attribute === attribute) ?? null;
}

// `static_or_series` attributes (e.g. marginal_cost, efficiency) can be entered
// as a scalar in the static sheet OR as a column in the time-series sheet.
// Treat them as valid static-sheet attributes for UI editing and defaults.
const isStaticInputAttr = (attr: PypsaAttribute): boolean =>
  attr.status === 'input' && attr.storage !== 'series';

export function getDefaultRowForSheet(sheet: string): GridRow {
  const component = getComponentSchema(sheet);
  if (!component) return { name: '' };
  const row: GridRow = {};
  const attrs = component.attributes.filter((attr) => isStaticInputAttr(attr) && attr.required);
  attrs.forEach((attr) => {
    row[attr.attribute] = defaultCellValue(attr);
  });
  if (component.sheet_name === 'snapshots' && !('snapshot' in row)) row.snapshot = '';
  if (attrs.length === 0) {
    const fallback = component.input_static_attributes[0] ?? 'name';
    row[fallback] = '';
  }
  return row;
}

export function getOrderedInputAttributes(sheet: string): PypsaAttribute[] {
  const component = getComponentSchema(sheet);
  if (!component) return [];
  return component.attributes.filter(isStaticInputAttr);
}

export function getAddableAttributes(sheet: string): PypsaAttribute[] {
  return getOrderedInputAttributes(sheet).filter((attr) => !attr.required);
}

export function getProtectedColumns(sheet: string): string[] {
  const component = getComponentSchema(sheet);
  if (!component) return ['name'];
  return component.attributes
    .filter((attr) => attr.required && isStaticInputAttr(attr))
    .map((attr) => attr.attribute);
}

export function isInputSheet(sheet: string): boolean {
  return SHEETS.includes(sheet) || TS_SHEETS.includes(sheet);
}

export function isTemporalSheet(sheet: string): boolean {
  return ALL_KNOWN_TS_SHEETS.includes(sheet);
}

export function normalizeSheetName(sheet: string): string {
  if (ALL_KNOWN_SHEETS.includes(sheet)) return sheet;
  const hyphenated = sheet.replace(/_/g, '-');
  if (ALL_KNOWN_SHEETS.includes(hyphenated)) return hyphenated;
  return sheet;
}

export function parseTemporalSheetName(sheet: string): { componentSheet: string; attribute: string } | null {
  const normalized = normalizeSheetName(sheet);
  const index = normalized.indexOf('-');
  if (index === -1) return null;
  const componentSheet = normalized.slice(0, index);
  const attribute = normalized.slice(index + 1);
  const component = getComponentSchema(componentSheet);
  if (!component || !component.temporal_attributes.includes(attribute)) return null;
  return { componentSheet, attribute };
}

export function isInputTemporalSheet(sheet: string): boolean {
  const parsed = parseTemporalSheetName(sheet);
  if (!parsed) return false;
  const component = getComponentSchema(parsed.componentSheet);
  return !!component?.input_temporal_attributes.includes(parsed.attribute);
}

export function isOutputTemporalSheet(sheet: string): boolean {
  const parsed = parseTemporalSheetName(sheet);
  if (!parsed) return false;
  const component = getComponentSchema(parsed.componentSheet);
  return !!component?.output_attributes.includes(parsed.attribute) && !!component?.temporal_attributes.includes(parsed.attribute);
}

export function stripOutputStaticAttributes(sheet: string, row: GridRow): GridRow {
  const component = getComponentSchema(sheet);
  if (!component) return row;
  const output = new Set(component.output_attributes.filter((attribute) => !component.temporal_attributes.includes(attribute)));
  return Object.fromEntries(Object.entries(row).filter(([key]) => !output.has(key))) as GridRow;
}
