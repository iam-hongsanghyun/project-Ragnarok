import { describe, it, expect } from '@jest/globals';
import { buildScenarioPreset } from 'lib/results/scenarios';
import { defaultPathwayConfig } from 'lib/results/pathway';
import { defaultRollingConfig } from 'lib/results/rolling';
import { buildRunPayload, RunUiOptions } from './buildRunPayload';

const UI: RunUiOptions = {
  scenarioLabel: 'High carbon',
  filename: 'case.xlsx',
  dateFormat: 'ymd',
  solverThreads: 4,
  solverType: 'auto',
  solveAcceptance: 'lenient',
  objectiveAutoScale: true,
  currencySymbol: '$',
};

function preset(overrides = {}) {
  return buildScenarioPreset({
    label: 'High carbon',
    snapshotStart: 0,
    snapshotEnd: 24,
    snapshotWeight: 1,
    carbonPrice: 90,
    discountRate: 0.05,
    forceLp: false,
    enableLoadShedding: true,
    loadSheddingCost: 1000,
    pathwayConfig: defaultPathwayConfig(),
    rollingConfig: defaultRollingConfig(),
    constraints: [
      { id: 'c1', enabled: true } as never,
      { id: 'c2', enabled: false } as never,
    ],
    ...overrides,
  });
}

describe('buildRunPayload', () => {
  it('maps preset + uiOpts + specs into the run body', () => {
    const { scenario, options } = buildRunPayload(preset(), UI, [{ foo: 1 } as never]);
    expect(scenario.carbonPrice).toBe(90);
    expect(scenario.discountRate).toBe(0.05);
    expect(scenario.constraintSpecs).toEqual([{ foo: 1 }]);
    // Only enabled constraints are sent.
    expect(scenario.constraints.map((c) => c.id)).toEqual(['c1']);

    expect(options.backend).toBe('pypsa');
    expect(options.snapshotCount).toBe(24);
    expect(options.snapshotStart).toBe(0);
    expect(options.snapshotEnd).toBe(24);
    expect(options.scenarioLabel).toBe('High carbon');
    expect(options.filename).toBe('case.xlsx');
    expect(options.dateFormat).toBe('ymd');
    expect(options.solverThreads).toBe(4);
    expect(options.enableLoadShedding).toBe(true);
    expect(options.loadSheddingCost).toBe(1000);
  });

  it('omits modelOverrides when empty, includes them when present', () => {
    expect(buildRunPayload(preset(), UI, []).options.modelOverrides).toBeUndefined();

    const withOv = buildRunPayload(
      preset({ modelOverrides: [{ sheet: 'generators', name: 'g1', column: 'p_nom', value: 500 }] }),
      UI,
      [],
    );
    expect(withOv.options.modelOverrides).toEqual([
      { sheet: 'generators', name: 'g1', column: 'p_nom', value: 500 },
    ]);
  });

  it('uses the caller-supplied scenarioLabel, not the preset label', () => {
    const { options } = buildRunPayload(preset({ label: 'IGNORED' }), { ...UI, scenarioLabel: 'From caller' }, []);
    expect(options.scenarioLabel).toBe('From caller');
  });
});
