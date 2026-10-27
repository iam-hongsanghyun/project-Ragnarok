/**
 * Schema-aware lookups for piecewise curves (which components accept which curve).
 *
 * Reads the live schema bundle (`piecewise_attributes` per component, built by the
 * backend from PyPSA's own `piecewise.csv`), so nothing about PyPSA's curve table is
 * hardcoded in the frontend. The pure curve maths lives in `./piecewise`.
 */
import { PYPSA_COMPONENT_BY_SHEET } from 'lib/constants/pypsa_schema';
import { baseAttribute, parsePiecewiseSheetName, PiecewiseSpec } from './piecewise';

/** Curves the component sheet accepts (empty when it has none or the bundle predates P10). */
export function piecewiseSpecsFor(listSheet: string): PiecewiseSpec[] {
  return (PYPSA_COMPONENT_BY_SHEET[listSheet]?.piecewise_attributes ?? []) as PiecewiseSpec[];
}

/** The spec behind `attribute` (`efficiency2` resolves to the `efficiency` spec). */
export function piecewiseSpecFor(listSheet: string, attribute: string): PiecewiseSpec | null {
  const base = baseAttribute(attribute);
  return piecewiseSpecsFor(listSheet).find((s) => s.attribute === base) ?? null;
}

/** x-axis attribute of a `<list>-<attr>-pw` sheet, or null when the sheet is not a valid curve sheet. */
export function xAttributeOfSheet(sheet: string): string | null {
  const parsed = parsePiecewiseSheetName(sheet);
  if (!parsed) return null;
  return piecewiseSpecFor(parsed.listSheet, parsed.attribute)?.x ?? null;
}

/** Component sheets that accept at least one curve. */
export function piecewiseCapableSheets(): string[] {
  return Object.values(PYPSA_COMPONENT_BY_SHEET)
    .filter((c) => (c.piecewise_attributes ?? []).length > 0)
    .map((c) => c.sheet_name);
}
