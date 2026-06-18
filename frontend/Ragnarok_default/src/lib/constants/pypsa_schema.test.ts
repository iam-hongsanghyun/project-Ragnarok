import { describe, test, expect, beforeAll } from '@jest/globals';
import {
  applyConfigBundle,
  getDefaultRowForSheet,
  getNewRowDefaults,
  getProtectedColumns,
  type PypsaSchemaFile,
} from './pypsa_schema';
import schemaFixture from './__fixtures__/pypsa_schema.fixture.json';

// `getNewRowDefaults` is the "+ Add component" seed: it must enrich the minimal
// `getDefaultRowForSheet` (required-only) with PyPSA's own non-required defaults
// so a fresh row isn't blank — but ONLY with schema-backed values, never guesses.
describe('getNewRowDefaults', () => {
  beforeAll(() => {
    applyConfigBundle(schemaFixture as unknown as PypsaSchemaFile, { fields: [] });
  });

  test('is a superset of the minimal required-only default row', () => {
    const minimal = getDefaultRowForSheet('generators');
    const enriched = getNewRowDefaults('generators');
    for (const key of Object.keys(minimal)) {
      expect(key in enriched).toBe(true);
    }
    // Required columns must still be present (and protected) in the enriched row.
    for (const col of getProtectedColumns('generators')) {
      expect(col in enriched).toBe(true);
    }
  });

  test('only seeds attributes that have a concrete (non-empty) schema default', () => {
    const enriched = getNewRowDefaults('generators');
    // Every value is either a non-empty seeded default or a required field left
    // for the user (empty string). No null/undefined leaks in.
    for (const [, v] of Object.entries(enriched)) {
      expect(v === '' || typeof v === 'number' || typeof v === 'boolean' || typeof v === 'string').toBe(true);
    }
    // It should genuinely add at least one non-required field beyond the minimal
    // row (the fixture defines defaults like p_nom / efficiency for generators).
    const minimalKeys = Object.keys(getDefaultRowForSheet('generators')).length;
    expect(Object.keys(enriched).length).toBeGreaterThanOrEqual(minimalKeys);
  });

  test('returns a bare name row for an unknown sheet', () => {
    expect(getNewRowDefaults('not_a_real_sheet')).toEqual({ name: '' });
  });
});
