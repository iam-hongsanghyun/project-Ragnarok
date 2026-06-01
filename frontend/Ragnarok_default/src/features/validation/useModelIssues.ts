import { useMemo } from 'react';
import type { ModelIssue } from 'lib/validation/issue';
import { Primitive, WorkbookModel } from 'lib/types';
import {
  ALL_KNOWN_TS_SHEETS,
  PYPSA_COMPONENTS,
  getComponentSchema,
  isInputTemporalSheet,
  parseTemporalSheetName,
} from 'lib/constants/pypsa_schema';
import { numberValue, stringValue } from 'lib/utils/helpers';
import {
  PYPSA_STANDARD_LINE_TYPES,
  PYPSA_STANDARD_TRANSFORMER_TYPES,
} from 'lib/constants/pypsa_standard_types';
import { VALIDATION_CONFIG } from 'lib/constants';

export type { ModelIssue } from 'lib/validation/issue';


type Row = Record<string, Primitive>;

const TS_INDEX_KEYS = new Set(['snapshot', 'name', 'datetime', 'timestamp', 'time', 'timestep', 'index', 'period', '']);
const NON_NEGATIVE_ATTRS = new Set([
  'p_nom', 'p_nom_min', 'p_nom_max',
  's_nom', 's_nom_min', 's_nom_max',
  'e_nom', 'e_nom_min', 'e_nom_max',
  'p_set', 'q_set', 'inflow',
  'capital_cost', 'marginal_cost', 'marginal_cost_quadratic',
  'start_up_cost', 'shut_down_cost', 'stand_by_cost',
  'co2_emissions',
]);

function staticInputAttributes(sheet: string): string[] {
  const component = getComponentSchema(sheet);
  if (!component) return [];
  return component.attributes
    .filter((attr) => attr.status === 'input' && attr.storage !== 'series')
    .map((attr) => attr.attribute);
}

function requiredStaticAttributes(sheet: string): string[] {
  const component = getComponentSchema(sheet);
  if (!component) return [];
  return component.attributes
    .filter((attr) => attr.status === 'input' && attr.storage !== 'series' && attr.required)
    .map((attr) => attr.attribute);
}

function busReferenceAttributes(sheet: string): Array<{ attribute: string; required: boolean }> {
  const component = getComponentSchema(sheet);
  if (!component) return [];
  return component.attributes
    .filter((attr) => {
      const name = attr.attribute;
      return attr.status === 'input'
        && attr.storage !== 'series'
        && (name === 'bus' || (name.startsWith('bus') && /^\d+$/.test(name.slice(3))));
    })
    .map((attr) => ({ attribute: attr.attribute, required: attr.required }));
}

function addDuplicateNameIssues(sheet: string, rows: Row[], issues: ModelIssue[]) {
  const seen = new Map<string, number>();
  rows.forEach((row, rowIndex) => {
    const name = stringValue(row.name).trim();
    if (!name) {
      issues.push({ sheet, rowIndex, col: 'name', severity: 'error', message: 'Name is empty' });
      return;
    }
    if (seen.has(name)) {
      issues.push({
        sheet,
        rowIndex,
        col: 'name',
        severity: 'error',
        message: `Duplicate name "${name}" (first at row ${seen.get(name)! + 1})`,
      });
      return;
    }
    seen.set(name, rowIndex);
  });
}

function addStaticValueIssues(sheet: string, rows: Row[], carrierNames: Set<string>, issues: ModelIssue[]) {
  const allowed = new Set(staticInputAttributes(sheet));
  rows.forEach((row, rowIndex) => {
    Object.entries(row).forEach(([col, raw]) => {
      if (!allowed.has(col) || raw === '' || raw === null || raw === undefined) return;
      const value = numberValue(raw);
      if ((NON_NEGATIVE_ATTRS.has(col) || col.endsWith('_nom')) && value < 0) {
        issues.push({ sheet, rowIndex, col, severity: 'error', message: `${col} is negative (${value})` });
      }
      if (col.endsWith('_pu') && (value < 0 || value > 1)) {
        issues.push({ sheet, rowIndex, col, severity: 'warning', message: `${col}=${value} outside [0, 1]` });
      }
      if (col === 'efficiency' && value > 5) {
        issues.push({ sheet, rowIndex, col, severity: 'warning', message: `efficiency ${value} > 5 — check units (use ratio/COP, not %)` });
      }
      if (col === 'co2_emissions' && value > 5) {
        issues.push({ sheet, rowIndex, col, severity: 'warning', message: `co2_emissions ${value} looks too large for tCO₂/MWh — check if this should be divided by 1000` });
      }
      if (col === 'sense') {
        const sense = String(raw).trim();
        if (sense && !['<=', '>=', '==', '<', '>'].includes(sense)) {
          issues.push({ sheet, rowIndex, col, severity: 'warning', message: `Unexpected sense "${sense}"` });
        }
      }
      if (col === 'carrier') {
        const carrier = stringValue(raw).trim();
        if (carrier && carrierNames.size > 0 && !carrierNames.has(carrier)) {
          issues.push({ sheet, rowIndex, col, severity: 'warning', message: `Carrier "${carrier}" not in carriers sheet` });
        }
      }
    });
  });
}

function addRequiredFieldIssues(sheet: string, rows: Row[], issues: ModelIssue[]) {
  const required = requiredStaticAttributes(sheet).filter((attr) => attr !== 'name');
  rows.forEach((row, rowIndex) => {
    required.forEach((attr) => {
      if (row[attr] === '' || row[attr] === null || row[attr] === undefined) {
        issues.push({ sheet, rowIndex, col: attr, severity: 'error', message: `${attr} is required` });
      }
    });
  });
}

function addTypeReferenceIssues(
  sheet: string,
  rows: Row[],
  catalogue: Set<string>,
  catalogueSheet: string,
  issues: ModelIssue[],
) {
  if (catalogue.size === 0) return;
  rows.forEach((row, rowIndex) => {
    const typeRef = stringValue(row.type).trim();
    if (!typeRef) return;
    if (!catalogue.has(typeRef)) {
      issues.push({
        sheet,
        rowIndex,
        col: 'type',
        severity: 'warning',
        message: `type "${typeRef}" not found in ${catalogueSheet}`,
      });
    }
  });
}

function addBusReferenceIssues(sheet: string, rows: Row[], busNames: Set<string>, issues: ModelIssue[]) {
  const refs = busReferenceAttributes(sheet);
  rows.forEach((row, rowIndex) => {
    refs.forEach(({ attribute, required }) => {
      const ref = stringValue(row[attribute]).trim();
      if (!ref) {
        if (required) issues.push({ sheet, rowIndex, col: attribute, severity: 'error', message: `${attribute}: missing bus reference` });
        return;
      }
      if (!busNames.has(ref)) {
        issues.push({ sheet, rowIndex, col: attribute, severity: 'error', message: `${attribute} "${ref}" not found in buses` });
      }
    });
  });
}

function addTemporalSheetIssues(
  model: WorkbookModel,
  sheet: string,
  rows: Row[],
  issues: ModelIssue[],
) {
  const parsed = parseTemporalSheetName(sheet);
  if (!parsed) return;
  const { componentSheet, attribute } = parsed;
  const componentRows = model[componentSheet] ?? [];
  const knownNames = new Set(componentRows.map((row) => stringValue(row.name).trim()).filter(Boolean));
  if (rows.length === 0) return;

  const snapshotCount = model.snapshots.length;
  if (snapshotCount > 0 && rows.length !== snapshotCount) {
    issues.push({
      sheet,
      rowIndex: 0,
      severity: 'warning',
      message: `Row count ${rows.length} ≠ snapshot count ${snapshotCount}`,
    });
  }

  const labelKey = Object.keys(rows[0]).find((key) => ['snapshot', 'name', 'datetime', 'timestamp', 'time', 'timestep', 'index'].includes(key.toLowerCase()));
  if (!labelKey) {
    issues.push({ sheet, rowIndex: 0, severity: 'error', message: 'Time-series sheet is missing a snapshot label column' });
    return;
  }

  const cols = Object.keys(rows[0]).filter((key) => !TS_INDEX_KEYS.has(key.toLowerCase()));
  if (cols.length === 0) {
    issues.push({ sheet, rowIndex: 0, severity: 'warning', message: 'Time-series sheet has no component columns' });
    return;
  }

  cols.forEach((col) => {
    if (!knownNames.has(col)) {
      issues.push({ sheet, rowIndex: 0, col, severity: 'error', message: `"${col}" does not exist in ${componentSheet}` });
      return;
    }
    let firstBadRow = -1;
    let badCount = 0;
    rows.forEach((row, rowIndex) => {
      const raw = row[col];
      if (raw === '' || raw === null || raw === undefined) return;
      const value = numberValue(raw);
      const outsideNormalizedRange = attribute.endsWith('_pu') && (value < 0 || value > 1);
      const belowZero = ['p_set', 'inflow'].includes(attribute) && value < 0;
      if (outsideNormalizedRange || belowZero) {
        if (firstBadRow === -1) firstBadRow = rowIndex;
        badCount += 1;
      }
    });
    if (firstBadRow !== -1) {
      const range = attribute.endsWith('_pu') ? '[0, 1]' : '≥ 0';
      issues.push({
        sheet,
        rowIndex: firstBadRow,
        col,
        severity: 'warning',
        message: `"${col}": ${badCount} value${badCount > 1 ? 's' : ''} outside ${range}${badCount > 1 ? ` (first at row ${firstBadRow + 1})` : ''}`,
      });
    }
  });
}

/** Numeric cell value, or null when empty / non-numeric. */
function cellNumber(raw: Primitive): number | null {
  if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null;
  if (typeof raw === 'string' && raw.trim() !== '') {
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/**
 * Flag attribute values whose magnitude is excessively large or small — the
 * same conditioning problem HiGHS warns about ("excessively large costs",
 * "excessively small row bounds"), which slows and can destabilise the solver.
 * Reported per (sheet, attribute) with the first offending row + a count, so a
 * badly-scaled column produces one warning, not thousands. Bus references and
 * the name column are skipped; only finite, non-zero numbers are considered.
 */
function addMagnitudeIssues(
  sheet: string,
  rows: Row[],
  issues: ModelIssue[],
  max: number,
  min: number,
) {
  const attrs = staticInputAttributes(sheet).filter(
    (attr) => attr !== 'name' && !(attr === 'bus' || (attr.startsWith('bus') && /^\d+$/.test(attr.slice(3)))),
  );
  for (const col of attrs) {
    let firstBig = -1;
    let bigCount = 0;
    let firstSmall = -1;
    let smallCount = 0;
    rows.forEach((row, rowIndex) => {
      const n = cellNumber(row[col]);
      if (n === null || n === 0) return;
      const mag = Math.abs(n);
      if (mag > max) {
        if (firstBig === -1) firstBig = rowIndex;
        bigCount += 1;
      } else if (mag < min) {
        if (firstSmall === -1) firstSmall = rowIndex;
        smallCount += 1;
      }
    });
    if (firstBig !== -1) {
      issues.push({
        sheet,
        rowIndex: firstBig,
        col,
        severity: 'warning',
        message: `"${col}": ${bigCount} value${bigCount > 1 ? 's' : ''} exceed ${max.toExponential(0)} — very large magnitudes can slow or destabilise the solver (consider scaling units)`,
      });
    }
    if (firstSmall !== -1) {
      issues.push({
        sheet,
        rowIndex: firstSmall,
        col,
        severity: 'warning',
        message: `"${col}": ${smallCount} non-zero value${smallCount > 1 ? 's' : ''} below ${min.toExponential(0)} — very small magnitudes can cause numerical issues`,
      });
    }
  }
}

export function useModelIssues(model: WorkbookModel): ModelIssue[] {
  return useMemo(() => {
    const issues: ModelIssue[] = [];
    const busNames = new Set((model.buses ?? []).map((row) => stringValue(row.name).trim()).filter(Boolean));
    const carrierNames = new Set((model.carriers ?? []).map((row) => stringValue(row.name).trim()).filter(Boolean));
    // Combine workbook-defined types with PyPSA's built-in catalogues — PyPSA
    // pre-populates `network.line_types` / `.transformer_types` on every fresh
    // network, so a `lines.type = "149-AL1/24-ST1A 110.0"` resolves at solve
    // time even without a matching row in the workbook sheet.
    const lineTypeNames = new Set([
      ...(model.line_types ?? []).map((row) => stringValue(row.name).trim()),
      ...PYPSA_STANDARD_LINE_TYPES.map((row) => stringValue(row.name).trim()),
    ].filter(Boolean));
    const transformerTypeNames = new Set([
      ...(model.transformer_types ?? []).map((row) => stringValue(row.name).trim()),
      ...PYPSA_STANDARD_TRANSFORMER_TYPES.map((row) => stringValue(row.name).trim()),
    ].filter(Boolean));

    for (const component of PYPSA_COMPONENTS) {
      const sheet = component.sheet_name;
      if (sheet === 'snapshots' || sheet === 'network') continue;
      const rows = (model[sheet] ?? []) as Row[];
      if (!rows.length) continue;

      if (requiredStaticAttributes(sheet).includes('name')) {
        addDuplicateNameIssues(sheet, rows, issues);
      }
      addRequiredFieldIssues(sheet, rows, issues);
      addBusReferenceIssues(sheet, rows, busNames, issues);
      addStaticValueIssues(sheet, rows, carrierNames, issues);
      addMagnitudeIssues(sheet, rows, issues, VALIDATION_CONFIG.magnitudeMax, VALIDATION_CONFIG.magnitudeMin);
      if (sheet === 'lines') {
        addTypeReferenceIssues(sheet, rows, lineTypeNames, 'line_types', issues);
      } else if (sheet === 'transformers') {
        addTypeReferenceIssues(sheet, rows, transformerTypeNames, 'transformer_types', issues);
      }
    }

    for (const sheet of ALL_KNOWN_TS_SHEETS) {
      const rows = model[sheet] as Row[] | undefined;
      if (!rows || !rows.length || !isInputTemporalSheet(sheet)) continue;
      addTemporalSheetIssues(model, sheet, rows, issues);
    }

    return issues;
  }, [model]);
}
