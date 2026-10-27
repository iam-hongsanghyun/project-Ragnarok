import { describe, it, expect } from '@jest/globals';
import { isScenarioInvariantAttribute } from './ScenarioRow';

describe('isScenarioInvariantAttribute', () => {
  it.each([
    'bus', 'bus1', 'bus2', 'carrier', 'p_nom_set', 's_nom_set', 'e_nom_set', 'delay', 'cyclic_delay2',
    'p_nom_extendable', 'committable', 'build_year', 'lifetime', 'type', 'active', 'sign',
  ])('rejects %s (PyPSA requires it identical across scenarios)', (attr) => {
    expect(isScenarioInvariantAttribute(attr)).toBe(true);
  });

  it.each(['marginal_cost', 'p_set', 'p_max_pu', 'capital_cost', 'efficiency', 'p_nom', 'p_nom_min'])(
    'allows %s', (attr) => {
      expect(isScenarioInvariantAttribute(attr)).toBe(false);
    },
  );
});
