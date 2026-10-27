/**
 * Type-specific guidance for PyPSA `global_constraints` rows and carrier growth
 * limits (P27). Mirrors the server's `validate_model` checks
 * (`backend/pypsa/network/constraint_checks.py`) so the editor can flag a row the
 * moment it is typed instead of at solve time.
 */
import type { GridRow } from 'lib/types';

export interface ConstraintHint {
  severity: 'error' | 'warning' | 'info';
  message: string;
}

export interface ConstraintHintContext {
  /** Names on the carriers sheet. */
  carriers: string[];
  /** Column names present on the carriers sheet. */
  carrierAttributes: string[];
  /** Configured investment periods (empty when pathway mode is off). */
  investmentPeriods: number[];
  pathwayEnabled: boolean;
}

/** One-line description of what each type reads, shown under the row. */
export const TYPE_DESCRIPTION: Record<string, string> = {
  primary_energy:
    'Caps/floors a weighted sum over carriers: carrier_attribute names a carriers-sheet column (e.g. co2_emissions); constant is the limit.',
  operational_limit:
    'Limits energy produced by a carrier over the (period\'s) snapshots; carrier_attribute is the carrier name.',
  tech_capacity_expansion_limit:
    'Limits installed capacity of one carrier (optionally on one bus); carrier_attribute is the carrier name.',
  transmission_volume_expansion_limit:
    'Limits total expanded line/link volume (MW km); carrier_attribute lists the carriers, comma-separated.',
  transmission_expansion_cost_limit:
    'Limits total transmission expansion cost; carrier_attribute lists the carriers, comma-separated.',
};

const PERIOD_SENSITIVE = new Set(['primary_energy', 'operational_limit']);

const blank = (v: unknown): boolean =>
  v === undefined || v === null || v === '' || (typeof v === 'number' && Number.isNaN(v));

export function globalConstraintHints(row: GridRow, ctx: ConstraintHintContext): ConstraintHint[] {
  const out: ConstraintHint[] = [];
  const type = String(row.type ?? '').trim() || 'primary_energy';
  const sense = String(row.sense ?? '').trim() || '==';
  const attr = String(row.carrier_attribute ?? '').trim();

  if (!(type in TYPE_DESCRIPTION)) {
    out.push({ severity: 'error', message: `Unknown type "${type}".` });
  }
  if (!['<=', '==', '>='].includes(sense)) {
    out.push({ severity: 'error', message: `sense must be <=, == or >=, got "${sense}".` });
  }
  if (!blank(row.investment_period)) {
    const period = Number(row.investment_period);
    if (!ctx.pathwayEnabled && PERIOD_SENSITIVE.has(type)) {
      out.push({
        severity: 'error',
        message: `investment_period is set but the run has no investment periods; PyPSA 1.4 raises ValueError for ${type}. Clear it or enable pathway mode.`,
      });
    } else if (ctx.pathwayEnabled && ctx.investmentPeriods.length > 0 && !ctx.investmentPeriods.includes(period)) {
      out.push({
        severity: 'warning',
        message: `investment_period ${period} is not one of the configured periods (${ctx.investmentPeriods.join(', ')}); the constraint will not bind.`,
      });
    }
  }
  if (type === 'primary_energy' && attr && ctx.carrierAttributes.length > 0 && !ctx.carrierAttributes.includes(attr)) {
    out.push({ severity: 'warning', message: `carrier_attribute "${attr}" is not a column of the carriers sheet.` });
  }
  if (type === 'tech_capacity_expansion_limit') {
    if (!attr) {
      out.push({ severity: 'error', message: 'tech_capacity_expansion_limit needs carrier_attribute (the carrier).' });
    } else if (ctx.carriers.length > 0 && !ctx.carriers.includes(attr)) {
      out.push({ severity: 'warning', message: `carrier_attribute is the carrier name; "${attr}" is not a carrier.` });
    }
  }
  return out;
}

export interface GrowthHint {
  severity: 'error' | 'warning';
  message: string;
}

/** Why a carrier's growth limit would not bind (mirrors `check_growth_limits`). */
export function growthLimitHint(
  attribute: 'max_growth' | 'max_relative_growth',
  value: unknown,
  pathwayEnabled: boolean,
): GrowthHint | null {
  if (blank(value)) return null;
  const v = Number(value);
  if (!Number.isFinite(v)) return null; // inf = unlimited
  if (attribute === 'max_relative_growth' && v === 0) return null; // PyPSA default: unlimited
  if (v < 0) return { severity: 'error', message: `${attribute} is negative.` };
  if (!pathwayEnabled) {
    return { severity: 'warning', message: 'Limits new capacity per investment period; no effect on a single-period run.' };
  }
  return null;
}
