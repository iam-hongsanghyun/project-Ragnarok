/**
 * Editor guidance for PyPSA 1.3/1.4 attributes (P46).
 *
 * The generic grid shows every schema column but cannot say that `v_ang_min`
 * is now ignored, that `phase_shift_*` are degrees, or that `start_up_cost`
 * may be a time series. This is the one place that knowledge lives; the table
 * header and the attribute-doc panel read it.
 */

export interface AttributeHint {
  /** Logical group shown as a chip ("Maintenance", "Phase shifter", ...). */
  group?: string;
  /** Unit that overrides the schema's (the schema says "Degrees"/"degrees"). */
  unit?: string;
  /** Marks a deprecated attribute (header gets a `[deprecated]` badge). */
  deprecated?: boolean;
  /** One-sentence guidance shown in the attribute-doc panel. */
  note: string;
}

const MAINTENANCE_SHEETS = new Set(['generators', 'links', 'processes']);
const MAINTENANCE_ATTRS = new Set([
  'maintainable', 'maintenance_duration', 'maintenance_pu', 'maintenance_events',
]);
const ANGLE_SHEETS = new Set(['lines', 'transformers']);
const TS_COST_ATTRS = new Set(['start_up_cost', 'shut_down_cost']);

export function getAttributeHint(sheet: string, attribute: string): AttributeHint | null {
  if (MAINTENANCE_SHEETS.has(sheet) && MAINTENANCE_ATTRS.has(attribute)) {
    const unit = attribute === 'maintenance_duration' ? 'h' : attribute === 'maintenance_pu' ? 'p.u.' : undefined;
    return {
      group: 'Maintenance',
      unit,
      note:
        'Scheduled maintenance (PyPSA 1.3+): set maintainable = true and the solver places '
        + '`maintenance_events` outages of `maintenance_duration` hours, each derating capacity by '
        + '`maintenance_pu`. Adds binary variables (a MILP) - Force-LP relaxes it.',
    };
  }
  if (sheet === 'transformers' && (attribute === 'phase_shift_min' || attribute === 'phase_shift_max')) {
    return {
      group: 'Phase shifter',
      unit: 'deg',
      note:
        'Bounds of an optimised phase-shifting transformer. When min < max the shift is a per-snapshot '
        + 'decision variable and the `phase_shift` setpoint is ignored; min = max fixes it.',
    };
  }
  if (sheet === 'transformers' && attribute === 'phase_shift') {
    return {
      group: 'Phase shifter',
      unit: 'deg',
      note: 'Fixed phase-shift setpoint (can be a time series). Ignored when phase_shift_min < phase_shift_max.',
    };
  }
  if (ANGLE_SHEETS.has(sheet) && attribute === 'v_ang_max') {
    return {
      unit: 'deg',
      note:
        'Enforced in PyPSA 1.4 as a symmetric cap on |angle difference| across the branch '
        + '(for transformers including the phase shift). inf = no limit.',
    };
  }
  if (ANGLE_SHEETS.has(sheet) && attribute === 'v_ang_min') {
    return {
      deprecated: true,
      unit: 'deg',
      note:
        'Deprecated and ignored since PyPSA 1.4 - a finite value is warned about and dropped before the '
        + 'solve. Use v_ang_max (symmetric).',
    };
  }
  if (MAINTENANCE_SHEETS.has(sheet) && TS_COST_ATTRS.has(attribute)) {
    return {
      note:
        `Can be a time series: add a \`${sheet}-${attribute}\` sheet (one column per component) to price `
        + 'each start/stop by snapshot. Only applies to committable units.',
    };
  }
  return null;
}

/** Header label: `name (unit) *`, with the deprecated badge and the hint's unit applied. */
export function decorateHeader(
  sheet: string,
  col: string,
  schemaUnit: string | undefined,
  required: boolean,
): string {
  const hint = getAttributeHint(sheet, col);
  const rawUnit = hint?.unit ?? (schemaUnit && schemaUnit !== 'n/a' ? schemaUnit : '');
  const unit = rawUnit ? ` (${rawUnit})` : '';
  return `${col}${unit}${required ? ' *' : ''}${hint?.deprecated ? ' [deprecated]' : ''}`;
}
