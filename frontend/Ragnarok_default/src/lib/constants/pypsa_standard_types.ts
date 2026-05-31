/**
 * PyPSA built-in standard types catalogues.
 *
 * Populated at app boot from ``GET /api/config`` (see ``lib/api/config.ts``).
 * The backend computes the catalogue live from
 * ``pypsa.Network().line_types`` / ``.transformer_types``, so the
 * frontend always sees whatever the installed PyPSA version ships.
 *
 * Same live-binding pattern as ``pypsa_schema.ts`` — empty initial
 * values, ``applyStandardTypesBundle`` reassigns at boot, JS module
 * semantics propagate the new values to consumers without changing
 * their import sites.
 */
import { GridRow } from 'lib/types';

export interface StandardTypesSource {
  source?: string;
  pypsa_version?: string;
  generator?: string;
  note?: string;
  [k: string]: unknown;
}

export interface StandardTypesCatalogue {
  meta?: StandardTypesSource;
  line_types: GridRow[];
  transformer_types: GridRow[];
}

// Live bindings populated by applyStandardTypesBundle — see pypsa_schema.ts.
/* eslint-disable import/no-mutable-exports */
export let PYPSA_STANDARD_LINE_TYPES: GridRow[] = [];
export let PYPSA_STANDARD_TRANSFORMER_TYPES: GridRow[] = [];
export let PYPSA_STANDARD_TYPES_SOURCE: StandardTypesSource = {};
/* eslint-enable import/no-mutable-exports */

/**
 * Reassign the live bindings from a freshly-loaded standard-types
 * bundle. Called once by ``<ConfigBootstrap>`` after ``GET /api/config``
 * resolves.
 */
export function applyStandardTypesBundle(bundle: StandardTypesCatalogue): void {
  PYPSA_STANDARD_LINE_TYPES = bundle.line_types ?? [];
  PYPSA_STANDARD_TRANSFORMER_TYPES = bundle.transformer_types ?? [];
  PYPSA_STANDARD_TYPES_SOURCE = bundle.meta ?? {};
}

/** Look up a single standard type by name. Reads the current live
 *  binding on every call. */
export function findStandardType(
  sheet: 'line_types' | 'transformer_types',
  name: string,
): GridRow | null {
  const rows = sheet === 'line_types' ? PYPSA_STANDARD_LINE_TYPES : PYPSA_STANDARD_TRANSFORMER_TYPES;
  return rows.find((row) => String(row.name) === name) ?? null;
}
