import { describe, expect, it } from '@jest/globals';
import { importQuery, summariseModel } from './pypsaIo';

describe('pypsaIo helpers', () => {
  it('sends only the options each importer reads', () => {
    expect(importQuery('pypsa-excel', { skipTime: true, extraLineData: true })).toBe('?skipTime=true');
    expect(importQuery('matpower', { overwriteZeroSNom: 250 })).toBe('?overwriteZeroSNom=250');
    expect(importQuery('pandapower', { extraLineData: true, usePandapowerIndex: true })).toBe('?extraLineData=true&usePandapowerIndex=true');
    expect(importQuery('pypsa-csv', {})).toBe('');
  });
  it('summarises non-empty sheets, largest first', () => {
    expect(summariseModel({ a: [{ n: 1 }], b: [{ n: 1 }, { n: 2 }], c: [] } as never)).toEqual([{ sheet: 'b', rows: 2 }, { sheet: 'a', rows: 1 }]);
  });
});
