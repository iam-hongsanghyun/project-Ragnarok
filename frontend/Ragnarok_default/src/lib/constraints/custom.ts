import { CustomConstraint, GridRow, WorkbookModel } from '../types';
import { METRIC_DEFS } from '../constants';

/**
 * Persistence for the free-text custom-constraint DSL. Stored as a single-row
 * sheet holding the raw multiline text, mirroring the rolling-config pattern.
 */
export const CUSTOM_DSL_SHEET = 'RAGNAROK_CustomDSL';

/**
 * Carriers that at least one GENERATOR actually carries.
 *
 * This is the set a carrier constraint can bind to: the backend resolves a
 * carrier row with `n.generators.carrier == carrier` (exact, case-sensitive),
 * NOT against the carriers sheet. The carriers sheet is a superset — it also
 * lists network carriers like "AC" that no generator uses — so offering it as
 * the constraint's carrier choices silently produces constraints the solver
 * drops. Always drive the picker (and the run-time check) from this instead.
 */
export function generatorCarriers(model: WorkbookModel): string[] {
  const seen = new Set<string>();
  for (const row of model.generators ?? []) {
    const carrier = String(row.carrier ?? '').trim();
    if (carrier) seen.add(carrier);
  }
  return Array.from(seen).sort((a, b) => a.localeCompare(b));
}

/** Identity of a constraint for comparison — everything that changes the LP. */
function constraintKey(c: CustomConstraint): string {
  return JSON.stringify([c.enabled, c.metric, c.carrier, c.value]);
}

/**
 * Do two constraint tables express the same set of constraints?
 *
 * Order- and label-insensitive: only the fields that reach the solver count.
 * Used to catch edits made in the constraints table that a SCENARIO run would
 * silently ignore — the batch runner builds its payload from each saved preset,
 * never from the live controls, so unsaved edits vanish without a trace.
 */
export function sameConstraintSet(
  a: CustomConstraint[],
  b: CustomConstraint[],
): boolean {
  if (a.length !== b.length) return false;
  const ka = a.map(constraintKey).sort();
  const kb = b.map(constraintKey).sort();
  return ka.every((k, i) => k === kb[i]);
}

/**
 * Enabled constraints whose carrier matches no generator — the solver would
 * skip each of these with only a note, so the run silently ignores them.
 * Returned so the UI can flag them inline and refuse to start the run.
 */
export function unresolvedCarrierConstraints(
  constraints: CustomConstraint[],
  genCarriers: string[],
): CustomConstraint[] {
  const valid = new Set(genCarriers);
  return constraints.filter(
    (c) => c.enabled && METRIC_DEFS[c.metric]?.needsCarrier && !valid.has(c.carrier),
  );
}

export function readCustomDslFromModel(model: WorkbookModel): string {
  const row = (model[CUSTOM_DSL_SHEET] ?? [])[0];
  const text = row?.text;
  return typeof text === 'string' ? text : '';
}

export function writeCustomDslToModel(model: WorkbookModel, text: string): WorkbookModel {
  const rows: GridRow[] = [{ text }];
  return { ...model, [CUSTOM_DSL_SHEET]: rows };
}
