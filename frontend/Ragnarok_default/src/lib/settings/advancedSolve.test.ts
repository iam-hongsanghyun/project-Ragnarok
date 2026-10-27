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
