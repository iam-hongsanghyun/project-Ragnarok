/**
 * PyPSA component schema + the workbook-side network-import policy.
 *
 * Both come from the backend's ``GET /api/config`` bundle at app boot
 * (see ``lib/api/config.ts``). The schema is computed live on the
 * backend from the installed ``pypsa`` package, so frontend and backend
 * always agree on the same definitions for the same deploy.
 *
 * This module exports two flavours of values:
 *
 *   • **Constants** (``let`` exports) — populated by ``applyConfigBundle``
 *     once the boot fetch resolves. Initial values are empty so any
 *     consumer that reads at module-init time gets a safe-but-empty
 *     view; consumers that read at runtime (every React render path)
 *     see the boot-populated data via JS module live-bindings.
 *   • **Helpers** — functions that compute on demand from the current
 *     `PYPSA_*` state. Safe regardless of when they're called.
 *
 * Consumers do not need to change their import statements when this
 * module migrates from the bundled JSON to the boot fetch; the live
 * binding is what makes that possible.
 */
import { GridRow, Primitive } from 'lib/types';

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

export interface PypsaSchemaFile {
  meta: {
    /** Live-build provenance, populated by the backend's
     *  ``pypsa_schema_builder``. */
    source?: string;
    pypsa_version?: string;
    generator?: string;
    note?: string;
    /** Legacy provenance fields (set by the old JS generator that
     *  fetched from GitHub at build time). The live backend builder
     *  doesn't populate them but the workbook still round-trips them
     *  through `RAGNAROK_Provenance` so the columns stay declared as
     *  optional strings. */
    repo?: string;
    ref?: string;
    commit_sha?: string;
    generated_at?: string;
    /** Sheet names that aren't bulk-added via the generic schema-driven
     *  import path (network + snapshots are special-cased at runtime). */
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

export interface NetworkImportPolicyFile {
  fields: NetworkImportPolicyField[];
}

export interface TableGroup {
  uniqueId: string;
  label: string;
  sheet: string;
  temporalSheets: Array<{ sheet: string; attribute: string; label: string }>;
  component: PypsaComponentSchema;
}

// ── State (populated by applyConfigBundle at boot) ──────────────────────────

const EMPTY_SCHEMA: PypsaSchemaFile = { meta: {}, components: {} };
const EMPTY_POLICY: NetworkImportPolicyFile = { fields: [] };

// Each export below starts empty and is reassigned once by
// ``applyConfigBundle``. JS module live-bindings mean consumers
// importing these names see the new value automatically — no need to
// re-export through a function on every read site.
/* eslint-disable import/no-mutable-exports */
export let PYPSA_SCHEMA: PypsaSchemaFile = EMPTY_SCHEMA;
export let NETWORK_IMPORT_POLICY: NetworkImportPolicyFile = EMPTY_POLICY;
export let PYPSA_SCHEMA_META: PypsaSchemaFile['meta'] = EMPTY_SCHEMA.meta;
/** Sheets that the backend does not bulk-add as standard PyPSA components. */
export let NON_COMPONENT_SHEETS: ReadonlySet<string> = new Set();
export let PYPSA_COMPONENTS: PypsaComponentSchema[] = [];
export let PYPSA_COMPONENT_BY_SHEET: Record<string, PypsaComponentSchema> = {};
export let NETWORK_RUNTIME_IMPORT_FIELDS: NetworkImportPolicyField[] = [];
export let STATIC_INPUT_COMPONENTS: PypsaComponentSchema[] = [];
export let SHEETS: string[] = [];
export let TS_SHEETS: string[] = [];
export let ALL_KNOWN_TS_SHEETS: string[] = [];
export let ALL_KNOWN_SHEETS: string[] = [];
export let TABLE_GROUPS: TableGroup[] = [];
/* eslint-enable import/no-mutable-exports */

/**
 * Reassign every cached derivation from a freshly-loaded schema + policy
 * pair. Called once by ``<ConfigBootstrap>`` after ``GET /api/config``
 * resolves, before React renders.
 *
 * Calling it a second time (e.g. after a future "Reload schema"
 * affordance) reassigns everything again — live bindings propagate to
 * any consumer that re-reads on its next render.
 */
export function applyConfigBundle(
  schema: PypsaSchemaFile,
  policy: NetworkImportPolicyFile,
): void {
  PYPSA_SCHEMA = schema;
  NETWORK_IMPORT_POLICY = policy;
  PYPSA_SCHEMA_META = schema.meta;
  NON_COMPONENT_SHEETS = new Set(schema.meta.non_component_sheets ?? []);
  PYPSA_COMPONENTS = Object.values(schema.components).sort(
    (a, b) => a.order - b.order || a.label.localeCompare(b.label),
  );
  PYPSA_COMPONENT_BY_SHEET = Object.fromEntries(
    PYPSA_COMPONENTS.map((component) => [component.sheet_name, component]),
  ) as Record<string, PypsaComponentSchema>;
  NETWORK_RUNTIME_IMPORT_FIELDS = policy.fields.filter(
    (field) => field.enabled_for_runtime_import,
  );
  STATIC_INPUT_COMPONENTS = PYPSA_COMPONENTS.filter(
    (component) => component.sheet_name !== 'snapshots',
  );
  SHEETS = PYPSA_COMPONENTS.map((component) => component.sheet_name);
  TS_SHEETS = PYPSA_COMPONENTS.flatMap((component) =>
    component.input_temporal_attributes.map(
      (attribute) => `${component.sheet_name}-${attribute}`,
    ),
  );
  ALL_KNOWN_TS_SHEETS = PYPSA_COMPONENTS.flatMap((component) =>
    component.temporal_attributes.map(
      (attribute) => `${component.sheet_name}-${attribute}`,
    ),
  );
  ALL_KNOWN_SHEETS = [...SHEETS, ...ALL_KNOWN_TS_SHEETS];
  TABLE_GROUPS = PYPSA_COMPONENTS.map((component) => ({
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
}

// ── Helpers (read from the live state above on every call) ──────────────────

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

/**
 * Defaults for a NEWLY ADDED component row (the "+ Add" action). Richer than
 * {@link getDefaultRowForSheet}: besides the required fields, it pre-fills any
 * non-required input attribute that PyPSA itself defines a concrete default for
 * (e.g. `p_nom=0`, `efficiency=1`), so a fresh generator/load isn't mostly
 * blank. Only schema-backed defaults are written — never guessed values.
 *
 * Kept separate from {@link getDefaultRowForSheet} (which seeds the empty-sheet
 * COLUMN baseline) so adding rich defaults here doesn't balloon the default
 * column set of every sheet.
 */
export function getNewRowDefaults(sheet: string): GridRow {
  const component = getComponentSchema(sheet);
  if (!component) return { name: '' };
  const row: GridRow = getDefaultRowForSheet(sheet);
  for (const attr of component.attributes) {
    if (!isStaticInputAttr(attr) || attr.required || attr.attribute in row) continue;
    const v = defaultCellValue(attr);
    if (v !== '') row[attr.attribute] = v; // only seed real schema defaults
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
