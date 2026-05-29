import { describe, test, expect } from '@jest/globals';
import {
  PYPSA_STANDARD_LINE_TYPES,
  PYPSA_STANDARD_TRANSFORMER_TYPES,
  PYPSA_STANDARD_TYPES_SOURCE,
  findStandardType,
} from './pypsa_standard_types';

describe('pypsa standard types catalogue', () => {
  test('non-empty catalogues with required electrical columns', () => {
    expect(PYPSA_STANDARD_LINE_TYPES.length).toBeGreaterThan(0);
    expect(PYPSA_STANDARD_TRANSFORMER_TYPES.length).toBeGreaterThan(0);

    for (const row of PYPSA_STANDARD_LINE_TYPES) {
      expect(typeof row.name).toBe('string');
      expect(typeof row.r_per_length).toBe('number');
      expect(typeof row.x_per_length).toBe('number');
      expect(typeof row.i_nom).toBe('number');
    }
    for (const row of PYPSA_STANDARD_TRANSFORMER_TYPES) {
      expect(typeof row.name).toBe('string');
      expect(typeof row.s_nom).toBe('number');
      expect(typeof row.v_nom_0).toBe('number');
      expect(typeof row.v_nom_1).toBe('number');
    }
  });

  test('source metadata is present', () => {
    expect(PYPSA_STANDARD_TYPES_SOURCE.repo).toBe('PyPSA/PyPSA');
    expect(PYPSA_STANDARD_TYPES_SOURCE.ref).toBe('master');
    expect(typeof PYPSA_STANDARD_TYPES_SOURCE.commit).toBe('string');
  });

  test('findStandardType resolves a known row', () => {
    const firstLine = PYPSA_STANDARD_LINE_TYPES[0];
    const found = findStandardType('line_types', String(firstLine.name));
    expect(found).not.toBeNull();
    expect(found?.name).toBe(firstLine.name);

    expect(findStandardType('line_types', '__does_not_exist__')).toBeNull();
  });
});
