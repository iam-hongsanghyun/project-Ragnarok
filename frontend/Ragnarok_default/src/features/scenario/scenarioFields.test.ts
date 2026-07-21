import { describe, it, expect } from '@jest/globals';
import { buildScenarioPreset } from 'lib/results/scenarios';
import { defaultPathwayConfig } from 'lib/results/pathway';
import { defaultRollingConfig } from 'lib/results/rolling';
import {
  cellValue,
  flattenScenario,
  getOverride,
  overridePath,
  parseOverridePath,
  scenarioDiffColumns,
  setOverride,
} from './scenarioFields';

function preset(over = {}) {
  return buildScenarioPreset({
    label: 'S',
    snapshotStart: 0, snapshotEnd: 24, snapshotWeight: 1,
    carbonPrice: 50, discountRate: 0.05, forceLp: false,
    enableLoadShedding: false, loadSheddingCost: 1000,
    pathwayConfig: defaultPathwayConfig(), rollingConfig: defaultRollingConfig(),
    constraints: [],
    ...over,
  });
}

describe('flattenScenario', () => {
  it('flattens nested configs and skips identity fields', () => {
    const flat = flattenScenario(preset({ label: 'ignore me' }));
    expect(flat.carbonPrice).toBe('50');
    expect(flat['marketSimConfig.enabled']).toBe('off');
    expect(flat.label).toBeUndefined(); // identity, not a setting
  });

  it('exposes model overrides as readable paths', () => {
    const flat = flattenScenario(preset({ modelOverrides: [{ sheet: 'generators', name: 'g1', column: 'p_nom', value: 500 }] }));
    expect(flat['model.generators.g1.p_nom']).toBe('500');
  });
});

/**
 * Regression: the constraints array fell through stringifyLeaf's JSON.stringify,
 * so the diff cell showed the raw `[{"id":"cc_...","enabled":true,...}]` blob.
 */
describe('constraints column formatting', () => {
  // The exact payload a user saw rendered raw in the scenario table.
  const reported = [
    { id: 'cc_1781793221370', enabled: true, label: 'Max Carrier Capacity Factor (nuclear) ≤ 85 %', metric: 'carrier_max_cf', carrier: 'nuclear', value: 85, unit: '%' },
    { id: 'cc_1781793222769', enabled: true, label: 'Max Carrier Capacity Factor (coal) ≤ 50 %', metric: 'carrier_max_cf', carrier: 'coal', value: 50, unit: '%' },
  ];

  it('renders a readable summary, not raw JSON', () => {
    const flat = flattenScenario(preset({ constraints: reported }));
    expect(flat.constraints).toBe(
      'Max Carrier Capacity Factor (nuclear) ≤ 85 %; Max Carrier Capacity Factor (coal) ≤ 50 %',
    );
    expect(flat.constraints).not.toContain('cc_1781793221370');
    expect(flat.constraints).not.toContain('{');
  });

  it('says "none" for an empty table', () => {
    expect(flattenScenario(preset({ constraints: [] })).constraints).toBe('none');
  });

  it('marks a disabled row so it cannot look active', () => {
    const flat = flattenScenario(preset({ constraints: [{ ...reported[0], enabled: false }] }));
    expect(flat.constraints).toContain('[off]');
  });

  it('still distinguishes scenarios whose constraints differ', () => {
    const cols = scenarioDiffColumns([
      preset({ constraints: reported }),
      preset({ constraints: [reported[0]] }),
    ]);
    expect(cols.map((c) => c.path)).toContain('constraints');
  });

  it('treats identical constraint sets as equal despite different ids/labels', () => {
    const renamed = [{ ...reported[0], id: 'zzz', label: 'my nuclear cap' }];
    const cols = scenarioDiffColumns([
      preset({ constraints: [reported[0]] }),
      preset({ constraints: renamed }),
    ]);
    expect(cols.map((c) => c.path)).not.toContain('constraints');
  });
});

describe('scenarioDiffColumns', () => {
  it('returns only paths that differ across scenarios', () => {
    const cols = scenarioDiffColumns([preset({ carbonPrice: 50 }), preset({ carbonPrice: 90 })]);
    const paths = cols.map((c) => c.path);
    expect(paths).toContain('carbonPrice');
    expect(paths).not.toContain('discountRate'); // identical → not a column
  });

  it('surfaces a capacity override difference and sorts overrides last', () => {
    const cols = scenarioDiffColumns([
      preset({ carbonPrice: 50 }),
      preset({ carbonPrice: 50, modelOverrides: [{ sheet: 'generators', name: 'g1', column: 'p_nom', value: 800 }] }),
    ]);
    const override = cols.find((c) => c.isOverride);
    expect(override?.path).toBe('model.generators.g1.p_nom');
    expect(cols[cols.length - 1].isOverride).toBe(true); // overrides sorted to the end
  });

  it('includeAll returns identical paths too', () => {
    const cols = scenarioDiffColumns([preset(), preset()], { includeAll: true });
    expect(cols.some((c) => c.path === 'discountRate')).toBe(true);
  });
});

describe('cellValue', () => {
  it('shows the value, or an em dash when the scenario lacks the path', () => {
    const withOv = preset({ modelOverrides: [{ sheet: 'generators', name: 'g1', column: 'p_nom', value: 800 }] });
    expect(cellValue(withOv, 'model.generators.g1.p_nom')).toBe('800');
    expect(cellValue(preset(), 'model.generators.g1.p_nom')).toBe('—');
  });
});

describe('override helpers', () => {
  it('round-trips an override path', () => {
    expect(parseOverridePath(overridePath('generators', 'g1', 'p_nom')))
      .toEqual({ sheet: 'generators', name: 'g1', column: 'p_nom' });
    expect(parseOverridePath('carbonPrice')).toBeNull();
  });

  it('round-trips a component name containing dots (legal PyPSA name)', () => {
    const path = overridePath('generators', 'gen.1.unitA', 'p_nom');
    expect(parseOverridePath(path)).toEqual({ sheet: 'generators', name: 'gen.1.unitA', column: 'p_nom' });
  });

  it('setOverride adds/updates/removes and keeps numbers numeric', () => {
    let ovs = setOverride([], 'generators', 'g1', 'p_nom', '500');
    expect(ovs).toEqual([{ sheet: 'generators', name: 'g1', column: 'p_nom', value: 500 }]);
    ovs = setOverride(ovs, 'generators', 'g1', 'p_nom', '600');
    expect(ovs).toEqual([{ sheet: 'generators', name: 'g1', column: 'p_nom', value: 600 }]);
    ovs = setOverride(ovs, 'generators', 'g1', 'p_nom', '  ');
    expect(ovs).toEqual([]); // blank removes
    ovs = setOverride([], 'generators', 'g1', 'carrier', 'gas');
    expect(getOverride(preset({ modelOverrides: ovs }), 'generators', 'g1', 'carrier')?.value).toBe('gas');
  });
});
