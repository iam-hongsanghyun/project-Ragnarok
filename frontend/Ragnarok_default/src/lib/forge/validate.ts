/**
 * Forge — context-aware "what needs handling" scans for the active tool.
 *
 * These power the Validate button in the Forge rail: they look at the current
 * model and report, per sheet/attribute, what the selected tool would address.
 * Pure functions over the model so they are unit-testable.
 */
import type { GridRow, WorkbookModel } from 'lib/types';
import { stringValue } from 'lib/utils/helpers';
import { applyRounding, numericColumns } from './transforms';
import { SNAP_ANCHORS, anchorCoord } from './snap';

export interface ForgeFinding {
  sheet: string;
  message: string;
}

/** Every data sheet that currently holds at least one row (any naming).
 *  Internal `RAGNAROK_*` metadata sheets (scenarios, carbon library, settings…)
 *  are excluded — they aren't model data the Forge tools should touch. */
export function nonEmptySheets(model: WorkbookModel): string[] {
  return Object.keys(model).filter(
    (key) => !key.startsWith('RAGNAROK_') && Array.isArray(model[key]) && (model[key] as GridRow[]).length > 0,
  );
}

function cellNumber(raw: unknown): number | null {
  if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null;
  if (typeof raw === 'string' && raw.trim() !== '') {
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/**
 * Round tool: per (sheet, numeric attribute), how many values are not already
 * at `decimals` decimal places (would change if rounded) and how many exceed
 * the magnitude limits. One finding per affected attribute.
 */
export function roundFindings(
  model: WorkbookModel,
  decimals: number,
  magnitudeMax: number,
  magnitudeMin: number,
): ForgeFinding[] {
  const out: ForgeFinding[] = [];
  for (const sheet of nonEmptySheets(model)) {
    const rows = model[sheet] as GridRow[];
    for (const col of numericColumns(rows)) {
      const changed = applyRounding(rows, [col], 'round', decimals).changed;
      let big = 0;
      let small = 0;
      for (const row of rows) {
        const n = cellNumber(row[col]);
        if (n === null || n === 0) continue;
        const mag = Math.abs(n);
        if (mag > magnitudeMax) big += 1;
        else if (mag < magnitudeMin) small += 1;
      }
      const parts: string[] = [];
      if (changed > 0) parts.push(`${changed} not at ${decimals} dp`);
      if (big > 0) parts.push(`${big} very large`);
      if (small > 0) parts.push(`${small} very small`);
      if (parts.length) out.push({ sheet, message: `${col}: ${parts.join(', ')}` });
    }
  }
  return out;
}

/**
 * Snap tool: per overlay sheet, how many coordinate-bearing components have a
 * missing or unknown bus reference — i.e., what snapping would resolve.
 */
export function snapFindings(model: WorkbookModel): ForgeFinding[] {
  const busNames = new Set(
    (model.buses ?? []).map((r) => stringValue(r.name).trim()).filter(Boolean),
  );
  const out: ForgeFinding[] = [];
  for (const sheet of nonEmptySheets(model)) {
    if (sheet === 'buses') continue;
    const rows = model[sheet] as GridRow[];
    let missing = 0;
    let unknown = 0;
    for (const row of rows) {
      for (const anchor of SNAP_ANCHORS) {
        if (!anchorCoord(row, anchor.x, anchor.y)) continue;
        const bus = stringValue(row[anchor.bus]).trim();
        if (!bus) missing += 1;
        else if (!busNames.has(bus)) unknown += 1;
      }
    }
    if (missing || unknown) {
      const parts: string[] = [];
      if (missing) parts.push(`${missing} with coordinates & no bus`);
      if (unknown) parts.push(`${unknown} referencing an unknown bus`);
      out.push({ sheet, message: parts.join(', ') });
    }
  }
  return out;
}
