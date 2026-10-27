import { describe, it, expect } from '@jest/globals';
import {
  deriveAssetDetails,
  indexInputByTimestamp,
  inputSeriesValueAtStamp,
  normalizeStamp,
  withDerivedAssetDetails,
} from './assetDetails';
import { createEmptyWorkbook } from 'lib/workbook/workbook';
import type { RunResults, WorkbookModel } from 'lib/types';

type Outputs = NonNullable<RunResults['outputs']>;

describe('normalizeStamp', () => {
  it('canonicalises fractional seconds, tz suffix, space separator and missing seconds', () => {
    expect(normalizeStamp('2030-01-01T00:00:00.000000')).toBe('2030-01-01T00:00:00');
    expect(normalizeStamp('2030-01-01 05:00:00+00:00')).toBe('2030-01-01T05:00:00');
    expect(normalizeStamp('2030-01-01T05:00Z')).toBe('2030-01-01T05:00:00');
    expect(normalizeStamp('not a date')).toBe('not a date');
  });
});

describe('input lookups keyed by period|snapshot (RF4)', () => {
  const rows = [
    { period: 2030, snapshot: '2030-01-01T00:00:00', l1: 50 },
    { period: 2040, snapshot: '2030-01-01T00:00:00', l1: 80 },
  ];
  it('reads each period own row; stamp-only lookup still works', () => {
    const idx = indexInputByTimestamp(rows);
    expect(inputSeriesValueAtStamp(idx, '2030-01-01T00:00:00', 'l1', 0, 2030)).toBe(50);
    expect(inputSeriesValueAtStamp(idx, '2030-01-01T00:00:00', 'l1', 0, 2040)).toBe(80);
    expect(inputSeriesValueAtStamp(idx, '2030-01-01T00:00:00', 'l1', 0)).toBe(80);
  });
});

describe('deriveAssetDetails', () => {
  const model = {
    ...createEmptyWorkbook(),
    buses: [{ name: 'b1' }],
    carriers: [{ name: 'AC' }],
    generators: [],
    loads: [{ name: 'l1', bus: 'b1', p_set: 0 }],
    storage_units: [{ name: 's1', bus: 'b1', p_nom: 0, max_hours: 4, p_nom_extendable: true }],
    stores: [{ name: 'st1', bus: 'b1', e_nom: 0, e_nom_extendable: true }],
    'loads-p_set': [
      { period: 2030, snapshot: '2030-01-01T00:00:00', l1: 50 },
      { period: 2040, snapshot: '2030-01-01T00:00:00', l1: 80 },
    ],
  } as unknown as WorkbookModel;
  const outputs = {
    static: { storage_units: { s1: { p_nom_opt: 25 } }, stores: { st1: { e_nom_opt: 90 } } },
    series: {
      'buses-marginal_price': [
        { period: 2030, snapshot: '2030-01-01T00:00:00', b1: 1 },
        { period: 2040, snapshot: '2030-01-01T00:00:00', b1: 2 },
      ],
    },
  } as unknown as Outputs;

  it('shows each pathway period its own demand', () => {
    const d = deriveAssetDetails(model, outputs);
    expect(d.buses.b1.netSeries.map((p) => p.load)).toEqual([50, 80]);
  });

  it('shows solved p_nom_opt / e_nom_opt for extendable storage', () => {
    const d = deriveAssetDetails(model, outputs);
    expect(d.storageUnits.s1.summary[0].value).toBe('25 MW');
    expect(d.storageUnits.s1.summary[1].value).toBe('100 MWh');
    expect(d.stores.st1.summary[0].value).toBe('90 MWh');
  });

  it('withDerivedAssetDetails filters a hydrated pathway series to the selected period', () => {
    const r = withDerivedAssetDetails(model, { outputs, runMeta: { snapshotWeight: 1 } } as unknown as RunResults, '$', 2040);
    expect(r.assetDetails.buses.b1.netSeries.map((p) => p.load)).toEqual([80]);
  });

  it('uses the positional-mean profile for averaged-sampling runs', () => {
    const avgModel = {
      ...model,
      'loads-p_set': [
        { snapshot: '2030-01-01T00:00:00', l1: 10 },
        { snapshot: '2030-01-01T01:00:00', l1: 20 },
        { snapshot: '2030-01-01T02:00:00', l1: 30 },
        { snapshot: '2030-01-01T03:00:00', l1: 40 },
      ],
    } as unknown as WorkbookModel;
    const o = { static: {}, series: { 'buses-marginal_price': [
      { snapshot: '2030-01-01T00:00:00', b1: 1 }, { snapshot: '2030-01-01T01:00:00', b1: 1 },
    ] } } as unknown as Outputs;
    const sampling = { enabled: true, mode: 'average', blockSize: 2, blockCount: 1, gapSnapshots: 0,
      sampledSnapshots: 2, representedSnapshots: 4, scale: 2 } as const;
    const d = deriveAssetDetails(avgModel, o, '$', 2, sampling);
    expect(d.buses.b1.netSeries.map((p) => p.load)).toEqual([20, 30]); // mean(10,30), mean(20,40)
  });
});
