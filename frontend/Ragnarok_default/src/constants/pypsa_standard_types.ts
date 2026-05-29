/**
 * PyPSA built-in standard types catalogues.
 *
 * Loaded from `src/config/pypsa_standard_types.json`, which is regenerated
 * from the upstream PyPSA repo by `scripts/generate-pypsa-standard-types.mjs`.
 * Each row mirrors a row PyPSA pre-populates into
 * `pypsa.Network().line_types` / `.transformer_types`.
 */
import rawCatalogue from '../config/pypsa_standard_types.json';
import { GridRow } from '../shared/types';

export interface StandardTypesSource {
  repo: string;
  ref: string;
  commit: string | null;
  generated_at: string;
  note: string;
}

export interface StandardTypesCatalogue {
  source: StandardTypesSource;
  line_types: GridRow[];
  transformer_types: GridRow[];
}

const catalogue = rawCatalogue as unknown as StandardTypesCatalogue;

export const PYPSA_STANDARD_LINE_TYPES: GridRow[] = catalogue.line_types;
export const PYPSA_STANDARD_TRANSFORMER_TYPES: GridRow[] = catalogue.transformer_types;
export const PYPSA_STANDARD_TYPES_SOURCE: StandardTypesSource = catalogue.source;

/** Look up a single standard type by name. */
export function findStandardType(
  sheet: 'line_types' | 'transformer_types',
  name: string,
): GridRow | null {
  const rows = sheet === 'line_types' ? PYPSA_STANDARD_LINE_TYPES : PYPSA_STANDARD_TRANSFORMER_TYPES;
  return rows.find((row) => String(row.name) === name) ?? null;
}
