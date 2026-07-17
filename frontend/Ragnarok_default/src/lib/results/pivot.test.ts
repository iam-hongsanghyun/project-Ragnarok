import { describe, test, expect, beforeAll } from '@jest/globals';
import type { RunResults, WorkbookModel } from 'lib/types';
import { applyConfigBundle, PypsaAttribute, PypsaComponentSchema } from 'lib/constants/pypsa_schema';
import { PivotChartConfig } from 'lib/dashboard/types';
import {
  buildPivotCategory,
  buildPivotDailyProfile,
  buildPivotDurationCurve,
  buildPivotMix,
  buildPivotScatter,
  buildPivotSeries,
  pivotSeriesSheet,
  pivotValueKind,
} from './pivot';

const attr = (a: string, type: string, status: 'input' | 'output', storage: 'static' | 'series'): PypsaAttribute => ({
  attribute: a, type, unit: type === 'string' ? 'n/a' : 'MW', default: '', description: '', status, raw_status: status, required: false, storage,
});

beforeAll(() => {
  const generators: PypsaComponentSchema = {
    unique_id: 'generators', component_name: 'Generator', list_name: 'generators', sheet_name: 'generators',
    label: 'Generator', category: 'gen', source_file: '',
    attributes: [attr('p', 'float', 'output', 'series'), attr('p_nom_opt', 'float', 'output', 'static'), attr('p_nom', 'float', 'input', 'static'), attr('carrier', 'string', 'input', 'static')],
    input_attributes: ['p_nom', 'carrier'], output_attributes: ['p', 'p_nom_opt'],
    temporal_attributes: ['p'], static_attributes: ['p_nom_opt', 'p_nom', 'carrier'],
    input_temporal_attributes: [], input_static_attributes: ['p_nom', 'carrier'], order: 1,
  };
  applyConfigBundle({ meta: {}, components: { generators } }, { fields: [] });
});

const model: WorkbookModel = {
  generators: [
    { name: 'g1', carrier: 'wind', bus: 'b1', p_nom: 100 },
    { name: 'g2', carrier: 'wind', bus: 'b1', p_nom: 50 },
    { name: 'g3', carrier: 'solar', bus: 'b2', p_nom: 200 },
  ],
  carriers: [{ name: 'wind' }, { name: 'solar' }],
} as unknown as WorkbookModel;

const results = {
  runMeta: { snapshotWeight: 1 },
  outputs: {
    static: { generators: { g1: { p_nom_opt: 100 }, g2: { p_nom_opt: 50 }, g3: { p_nom_opt: 200 } } },
    series: {
      'generators-p': [
        { snapshot: 't0', g1: 10, g2: 20, g3: 5 },
        { snapshot: 't1', g1: 60, g2: 0, g3: 100 },
      ],
    },
  },
} as unknown as RunResults;

const base: PivotChartConfig = {
  id: 1, sheet: 'generators', valueAttribute: 'p', groupBy: ['carrier'], filters: [],
  aggregate: 'sum', chartType: 'area', timeframe: 'hourly', stacked: true, startIndex: 0, endIndex: 100,
};

describe('pivot engine', () => {
  test('kind + series sheet detection', () => {
    expect(pivotValueKind('generators', 'p')).toBe('series');
    expect(pivotValueKind('generators', 'p_nom_opt')).toBe('static');
    expect(pivotValueKind('generators', 'p_nom')).toBe('input');
    expect(pivotSeriesSheet('generators', 'p')).toBe('generators-p');
    expect(pivotSeriesSheet('generators', 'p_nom_opt')).toBeNull();
  });

  test('generation by carrier (sum across components per snapshot)', () => {
    const { rows, series } = buildPivotSeries(base, results, model, 1);
    expect(series.map((s) => s.key)).toEqual(['wind', 'solar']); // carrier order
    expect(rows[0].wind).toBe(30); // 10 + 20
    expect(rows[0].solar).toBe(5);
    expect(rows[1].wind).toBe(60); // 60 + 0
    expect(rows[1].solar).toBe(100);
  });

  test('unit stays MW for an hourly (unbucketed) sum — components combine, time does not integrate', () => {
    const { unit } = buildPivotSeries(base, results, model, 1); // base: timeframe 'hourly', aggregate 'sum'
    expect(unit).toBe('MW');
  });

  test('unit stays MW for a bucketed MEAN — only `sum` integrates over time', () => {
    const { unit } = buildPivotSeries({ ...base, timeframe: 'aggregated', aggregate: 'mean' }, results, model, 1);
    expect(unit).toBe('MW');
  });

  test('unit becomes MWh for a bucketed (time-integrated) SUM — MW power integrates to energy', () => {
    const { unit, rows } = buildPivotSeries({ ...base, timeframe: 'aggregated' }, results, model, 2);
    expect(unit).toBe('MWh');
    // sum across snapshots × snapshot weight: wind (30+60)*2=180, solar (5+100)*2=210.
    expect(rows[0].wind).toBe(180);
    expect(rows[0].solar).toBe(210);
  });

  test('donut / category unit becomes MWh — they always integrate a series sum (no time axis to bucket)', () => {
    const mix = buildPivotMix({ ...base, chartType: 'donut' }, results, model, 1);
    const cat = buildPivotCategory({ ...base, chartType: 'grouped-bar' }, results, model, 1);
    expect(mix.unit).toBe('MWh');
    expect(cat.unit).toBe('MWh');
  });

  test('component numeric filter (p_nom > 100) drops generators', () => {
    const cfg: PivotChartConfig = { ...base, filters: [{ scope: 'component', field: 'p_nom', op: '>', value: 100 }] };
    const { rows, series } = buildPivotSeries(cfg, results, model, 1);
    expect(series.map((s) => s.key)).toEqual(['solar']); // only g3 (200) survives
    expect(rows[1].solar).toBe(100);
    expect(rows[1].wind).toBeUndefined();
  });

  test('per-hour value threshold (value > 50) drops sub-threshold snapshots', () => {
    const cfg: PivotChartConfig = { ...base, filters: [{ scope: 'value', field: '', op: '>', value: 50 }] };
    const { rows } = buildPivotSeries(cfg, results, model, 1);
    // t0: all values <= 50 → dropped; t1: g1=60 (wind), g3=100 (solar) kept.
    expect(rows[0].wind).toBeUndefined();
    expect(rows[1].wind).toBe(60);
    expect(rows[1].solar).toBe(100);
  });

  test('donut energy by carrier (sum × weight over window)', () => {
    const { data } = buildPivotMix({ ...base, chartType: 'donut' }, results, model, 1);
    expect(data.map((d) => d.label)).toEqual(['solar', 'wind']); // sorted desc
    expect(data.find((d) => d.label === 'wind')?.value).toBe(90);  // 30 + 60
    expect(data.find((d) => d.label === 'solar')?.value).toBe(105); // 5 + 100
  });

  test('static attribute (p_nom_opt) by carrier — donut', () => {
    const { data } = buildPivotMix({ ...base, valueAttribute: 'p_nom_opt', chartType: 'donut' }, results, model, 1);
    expect(data.find((d) => d.label === 'wind')?.value).toBe(150); // 100 + 50
    expect(data.find((d) => d.label === 'solar')?.value).toBe(200);
  });

  test('category bar by carrier — single series with per-bar colours', () => {
    const cat = buildPivotCategory({ ...base, chartType: 'grouped-bar' }, results, model, 1);
    expect(cat.labels).toEqual(['wind', 'solar']);          // carrier order
    expect(cat.series).toHaveLength(1);
    expect(cat.series[0].values).toEqual([90, 105]);        // energy sum×weight
    expect(cat.barColors).toHaveLength(2);                   // one colour per bar
  });

  test('category bar static (p_nom_opt) by carrier', () => {
    const cat = buildPivotCategory({ ...base, valueAttribute: 'p_nom_opt', chartType: 'hbar' }, results, model, 1);
    const v = (l: string) => cat.series[0].values[cat.labels.indexOf(l)];
    expect(v('wind')).toBe(150);
    expect(v('solar')).toBe(200);
  });

  test('category bar grouped by two dims → multi series', () => {
    const cat = buildPivotCategory({ ...base, valueAttribute: 'p_nom_opt', groupBy: ['carrier', 'bus'], chartType: 'grouped-bar' }, results, model, 1);
    // category axis = first dim (carrier); series = second dim (bus).
    expect(cat.labels).toContain('wind');
    expect(cat.series.length).toBeGreaterThanOrEqual(1);
  });

  test('scatter: p_nom (input X) vs p_nom_opt (static Y), one point per component', () => {
    const cfg: PivotChartConfig = { ...base, valueAttribute: 'p_nom', scatterYAttribute: 'p_nom_opt', groupBy: [], chartType: 'scatter' };
    const { points, loading } = buildPivotScatter(cfg, results, model, 1);
    expect(loading).toBe(false);
    const byLabel = Object.fromEntries(points.map((p) => [p.label, p]));
    expect(byLabel.g1).toMatchObject({ x: 100, y: 100 });
    expect(byLabel.g3).toMatchObject({ x: 200, y: 200 });
  });

  test('scatter with no Y attribute → empty', () => {
    const { points } = buildPivotScatter({ ...base, chartType: 'scatter' }, results, model, 1);
    expect(points).toEqual([]);
  });

  test('duration curve: one curve per group, each sorted independently (not pooled)', () => {
    const { series } = buildPivotDurationCurve({ ...base, chartType: 'duration' }, results, model, 1);
    // per-snapshot carrier sums: t0 wind=30 solar=5, t1 wind=60 solar=100.
    // Pooling both groups into one ranking would give [100, 60, 30, 5] — wrong,
    // since t0's wind and t1's solar have nothing to do with each other's rank.
    const byKey = Object.fromEntries(series.map((s) => [s.key, s.values]));
    expect(byKey.wind).toEqual([60, 30]);
    expect(byKey.solar).toEqual([100, 5]);
  });

  test('daily profile: mean by hour-of-day', () => {
    const hourly = {
      runMeta: { snapshotWeight: 1 },
      outputs: {
        static: {},
        series: {
          'generators-p': [
            { snapshot: '2030-01-01T00:00:00', g1: 10, g2: 20, g3: 5 },
            { snapshot: '2030-01-02T00:00:00', g1: 30, g2: 40, g3: 15 },  // hour 0 again
            { snapshot: '2030-01-01T01:00:00', g1: 60, g2: 0, g3: 100 },  // hour 1
          ],
        },
      },
    } as unknown as RunResults;
    const { rows } = buildPivotDailyProfile({ ...base, chartType: 'daily-profile' }, hourly, model, 1);
    expect(rows).toHaveLength(24);
    // hour 0: wind mean of (10+20)=30 and (30+40)=70 → 50; hour 1: wind 60.
    expect(rows[0].wind).toBe(50);
    expect(rows[1].wind).toBe(60);
  });
});
