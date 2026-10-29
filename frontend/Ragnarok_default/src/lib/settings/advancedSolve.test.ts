import { describe, it, expect } from '@jest/globals';
import { advancedSolveToOptions } from './advancedSolve';

describe('advancedSolveToOptions', () => {
  it('adds nothing for defaults / undefined', () => {
    expect(advancedSolveToOptions(undefined)).toEqual({});
    expect(advancedSolveToOptions({ solverName: 'highs', cycleBasisMethod: 'bfs-refined', transmissionLosses: false })).toEqual({});
  });
  it('emits set keys and cleans piecewise entries', () => {
    expect(advancedSolveToOptions({
      solverName: 'gurobi', transmissionLosses: true, committableBigM: 5000,
      piecewiseOptions: [
        { component: 'Generator', attribute: 'marginal_cost', method: 'sos2', name: ['g1'], sign: '>=' },
        { component: '', attribute: '', method: 'auto' },
      ],
    })).toEqual({
      solverName: 'gurobi', transmissionLosses: true, committableBigM: 5000,
      piecewiseOptions: [{ component: 'Generator', attribute: 'marginal_cost', method: 'sos2', name: ['g1'], sign: '>=' }],
    });
  });
  it('sends committableBigM only when positive', () => {
    expect(advancedSolveToOptions({ committableBigM: 0 })).toEqual({});
    expect(advancedSolveToOptions({ committableBigM: -1 })).toEqual({});
    expect(advancedSolveToOptions({ committableBigM: 250 })).toEqual({ committableBigM: 250 });
  });
});

describe('advancedSolveToOptions run options without an editor before', () => {
  it('sends CVaR, two-stage and iterative expansion as the backend reads them', () => {
    expect(advancedSolveToOptions({
      riskPreference: { alpha: 0.9, omega: 0.3 },
      twoStage: true,
      iterativeExpansion: {
        enabled: true, msqThreshold: 0.1, minIterations: 2, maxIterations: 8, lineUnitSize: 500, lineThreshold: 0.3, fractionalLastUnitSize: true,
        links: [{ link: 'hvdc1', unitSize: 1000, threshold: 0.4 }, { link: 'hvdc2', unitSize: 0 }],
      },
    })).toEqual({
      riskPreference: { alpha: 0.9, omega: 0.3 },
      twoStage: { enabled: true },
      iterativeExpansion: {
        enabled: true, msqThreshold: 0.1, minIterations: 2, maxIterations: 8, fractionalLastUnitSize: true,
        lineUnitSize: 500, lineThreshold: 0.3, linkUnitSize: { hvdc1: 1000 }, linkThreshold: { hvdc1: 0.4 },
      },
    });
  });

  it('omits a disabled iterative expansion and an unset two-stage', () => {
    expect(advancedSolveToOptions({ twoStage: false, iterativeExpansion: { enabled: false, msqThreshold: 0.05, minIterations: 1, maxIterations: 10, fractionalLastUnitSize: false, links: [] } })).toEqual({});
  });

  it('sends an explicit cofiringConfig as set, even when disabled, and nothing when unset', () => {
    expect(advancedSolveToOptions({})).toEqual({});
    expect(advancedSolveToOptions({
      cofiringConfig: { enabled: false, plants: [], minShare: null, maxShare: 0.3, unit: 'vol', scope: 'period', perPlant: { p1: { minShare: 0.1, maxShare: null, unit: 'energy', scope: 'hourly' } } },
    })).toEqual({
      cofiringConfig: {
        enabled: false, plants: [], minShare: null, maxShare: 0.3, unit: 'vol', scope: 'period',
        perPlant: { p1: { minShare: 0.1, maxShare: null, unit: 'energy', scope: 'hourly' } },
      },
    });
  });
});
