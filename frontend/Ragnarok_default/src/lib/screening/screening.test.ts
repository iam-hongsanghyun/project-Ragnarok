/**
 * Screening data shaping: matrix reordering, focus rows, heatmap cells, pair grouping, weight
 * handling, the free-text controls, and the shape / interactivity contract of the chart options.
 * The statistics themselves are the backend's (backend/tests/test_screening_correlation.py).
 */
import { describe, test, expect } from '@jest/globals';
import { FALLBACK_CHART_THEME } from 'lib/charts/theme';
import type { MetricsResponse, OptimiseResponse, ProfilesResponse, RegionRow, ScreeningSite, StructureResponse, ValidationReport } from 'lib/api/screening';
import {
  buildDistanceScatterOption,
  buildDurationOption,
  buildFrontierOption,
  buildHeatmapOption,
  buildLaggedOption,
  buildProfileOption,
  buildSitingHandoff,
  buildWithinBetweenOption,
  HANDOFF_MARGIN_DEG,
  type ScreeningUnit,
  categoryColors,
  correlationColor,
  equalWeights,
  escapeHtml,
  fmt,
  fmtPct,
  focusRow,
  gapRows,
  groupPairs,
  heatmapCells,
  normaliseWeights,
  pairKind,
  parseMonths,
  parseRegionCaps,
  parseSiteWeights,
  regionToUnit,
  siteToUnit,
  parseSeasonMap,
  reorderMatrix,
} from './screening';

const theme = FALLBACK_CHART_THEME;
const site = (name: string, technology: ScreeningSite['technology']): ScreeningSite => ({
  name, lat: 0, lon: 0, technology, region: '', unit: 'cf', capacityMw: null,
});

// `a` and `b` are twins; `c` is anti-correlated with both.
const SITES = ['a', 'c', 'b'];
const M: Array<Array<number | null>> = [
  [1, -0.8, 0.9],
  [-0.8, 1, -0.7],
  [0.9, -0.7, 1],
];

describe('matrix shaping', () => {
  test('reorderMatrix permutes rows and columns together', () => {
    const out = reorderMatrix(SITES, M, ['a', 'b', 'c']);
    expect(out.sites).toEqual(['a', 'b', 'c']);
    expect(out.matrix).toEqual([
      [1, 0.9, -0.8],
      [0.9, 1, -0.7],
      [-0.8, -0.7, 1],
    ]);
    // stays symmetric with a unit diagonal
    out.matrix.forEach((row, i) => row.forEach((v, j) => expect(v).toBe(out.matrix[j][i])));
  });

  test('reorderMatrix keeps sites the order omits (at the end) and ignores unknown names', () => {
    const out = reorderMatrix(SITES, M, ['b', 'ghost']);
    expect(out.sites).toEqual(['b', 'a', 'c']);
    expect(out.matrix[0][0]).toBe(1);
    expect(out.matrix[0][1]).toBe(0.9);
  });

  test('focusRow excludes the focus site and keeps null correlations', () => {
    expect(focusRow(SITES, M, 'a')).toEqual({ c: -0.8, b: 0.9 });
    expect(focusRow(['a', 'k'], [[1, null], [null, 1]], 'a')).toEqual({ k: null });
    expect(focusRow(SITES, M, 'nope')).toEqual({});
  });

  test('heatmapCells lists n^2 cells with the first row on top', () => {
    const cells = heatmapCells([[1, 0.5], [0.5, 1]]);
    expect(cells).toHaveLength(4);
    expect(cells).toContainEqual([1, 1, 0.5]); // row 0 col 1 -> y = n-1-0
    expect(cells).toContainEqual([1, 0, 1]);
  });

  test('pairKind is order independent and groupPairs drops null correlations', () => {
    const sites = [site('s1', 'solar'), site('w1', 'wind'), site('s2', 'solar')];
    expect(pairKind(sites[0], sites[1])).toBe(pairKind(sites[1], sites[0]));
    const groups = groupPairs(
      [
        { a: 's1', b: 's2', km: 10, r: 0.9 },
        { a: 's1', b: 'w1', km: 20, r: 0.1 },
        { a: 's2', b: 'w1', km: 30, r: null },
      ],
      sites,
    );
    expect(Object.keys(groups).sort()).toEqual(['solar - solar', 'solar - wind']);
    expect(groups['solar - wind']).toHaveLength(1);
  });
});

describe('weights and colours', () => {
  test('equalWeights sums to 1 and normaliseWeights drops non-positive entries', () => {
    const w = equalWeights(['a', 'b', 'c', 'd']);
    expect(Object.values(w).reduce((x, y) => x + y, 0)).toBeCloseTo(1, 12);
    expect(equalWeights([])).toEqual({});
    const n = normaliseWeights({ a: 2, b: 6, c: 0, d: -1, e: Number.NaN });
    expect(n).toEqual({ a: 0.25, b: 0.75 });
    expect(normaliseWeights({ a: 0 })).toEqual({});
  });

  test('categoryColors assigns the palette in first-seen order and never overruns it', () => {
    const c = categoryColors(['x', 'y', 'x', 'z'], ['p1', 'p2']);
    expect(c).toEqual({ x: 'p1', y: 'p2', z: 'p2' });
  });

  test('correlationColor is warm for negative, blue for positive, grey for null', () => {
    expect(correlationColor(0.9)).toMatch(/^hsl\(214 /);
    expect(correlationColor(-0.9)).toMatch(/^hsl\(18 /);
    expect(correlationColor(null)).toBe('hsl(40 6% 70%)');
    expect(correlationColor(5)).toBe(correlationColor(1)); // clamped
  });

  test('formatters print n/a for missing values', () => {
    expect(fmt(null)).toBe('n/a');
    expect(fmt(Number.NaN)).toBe('n/a');
    expect(fmt(0.12345, 3)).toBe('0.123');
    expect(fmtPct(0.256)).toBe('25.6%');
    expect(fmtPct(undefined)).toBe('n/a');
  });

  test('escapeHtml neutralises markup in site names', () => {
    expect(escapeHtml('<img src=x onerror="a()">&\'')).toBe('&lt;img src=x onerror=&quot;a()&quot;&gt;&amp;&#39;');
  });
});

describe('free-text controls', () => {
  test('parseMonths reads lists and ranges, sorted and unique', () => {
    expect(parseMonths('6-8, 12, 7')).toEqual([6, 7, 8, 12]);
    expect(parseMonths('')).toEqual([]);
    expect(() => parseMonths('13')).toThrow(/month/);
    expect(() => parseMonths('8-6')).toThrow();
    expect(() => parseMonths('jun')).toThrow();
  });

  test('parseSeasonMap builds the month -> label map, empty text means the default', () => {
    expect(parseSeasonMap('')).toBeUndefined();
    expect(parseSeasonMap('wet:6-9; dry:12,1,2')).toEqual({ 6: 'wet', 7: 'wet', 8: 'wet', 9: 'wet', 12: 'dry', 1: 'dry', 2: 'dry' });
    expect(() => parseSeasonMap('wet:6-9; dry:9-10')).toThrow(/both/);
    expect(() => parseSeasonMap('nocolon')).toThrow(/name:months/);
  });

  test('parseRegionCaps validates shares', () => {
    expect(parseRegionCaps('north:0.5, south:0.6')).toEqual({ north: 0.5, south: 0.6 });
    expect(parseRegionCaps(' ')).toBeUndefined();
    expect(() => parseRegionCaps('north:1.5')).toThrow();
    expect(() => parseRegionCaps('north')).toThrow();
  });

  test('gapRows lists the worst site first', () => {
    const report = {
      errors: [], warnings: [],
      gaps: {
        sitesWithGaps: 2, missingStepsTotal: 13, policy: 'drop', maxInterpolatedSteps: 48,
        bySite: {
          a: { missingSteps: 3, runs: 1, longestRunSteps: 3, first: [{ from: '2019-01-01T05:00:00', steps: 3 }] },
          b: { missingSteps: 10, runs: 2, longestRunSteps: 6, first: [] },
        },
      },
    } as ValidationReport;
    const rows = gapRows(report);
    expect(rows.map((r) => r.site)).toEqual(['b', 'a']);
    expect(rows[1].firstFrom).toBe('2019-01-01T05:00:00');
    expect(gapRows(undefined)).toEqual([]);
  });
});

describe('chart options', () => {
  const isFn = (v: unknown) => typeof v === 'function';

  test('heatmap: n^2 cells, visual map -1..1, tooltip escapes site names and prints the value', () => {
    const names = ['<b>a', 'c'];
    const opt = buildHeatmapOption(names, [[1, -0.25], [-0.25, 1]], theme) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    expect(opt.series[0].type).toBe('heatmap');
    expect(opt.series[0].data).toHaveLength(4);
    expect(opt.visualMap.min).toBe(-1);
    expect(opt.visualMap.max).toBe(1);
    expect(opt.visualMap.calculable).toBe(true);
    // zrender cannot parse the space-separated hsl() form (it paints black): every scale colour must be hex
    opt.visualMap.inRange.color.forEach((c: string) => expect(c).toMatch(/^#[0-9a-f]{6}$/i));
    expect(opt.toolbox.show).toBe(true);
    expect(isFn(opt.tooltip.formatter)).toBe(true);
    const html: string = opt.tooltip.formatter({ value: [1, 1, -0.25] });
    expect(html).toContain('-0.250');
    expect(html).toContain('&lt;b&gt;a');
    expect(html).not.toContain('<b>a');
    // more than 24 sites: no in-cell labels
    const many = Array.from({ length: 30 }, (_, i) => `s${i}`);
    const big = buildHeatmapOption(many, many.map(() => many.map(() => 0)), theme) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    expect(big.series[0].label.show).toBe(false);
  });

  test('distance scatter: one series per technology pair, legend only when several, zoomable', () => {
    const groups = {
      'solar - solar': [{ a: 'a', b: 'b', km: 10, r: 0.9 }],
      'solar - wind': [{ a: 'a', b: 'w', km: 50, r: 0.1 }, { a: 'b', b: 'w', km: 60, r: 0.2 }],
    };
    const opt = buildDistanceScatterOption(groups, { 'solar - solar': '#1', 'solar - wind': '#2' }, theme) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    expect(opt.series.map((s: { name: string }) => s.name)).toEqual(['solar - solar', 'solar - wind']);
    expect(opt.series[1].data).toHaveLength(2);
    expect(opt.legend).toBeTruthy();
    expect(opt.dataZoom).toHaveLength(2);
    expect(opt.yAxis.min).toBe(-1);
    const one = buildDistanceScatterOption({ 'solar - solar': groups['solar - solar'] }, { 'solar - solar': '#1' }, theme) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    expect(one.legend).toBeUndefined();
  });

  const profiles: ProfilesResponse = {
    sites: ['a', 'b'],
    diurnal: { hours: [0, 1, 2], series: { a: [0, 0.1, 0.2], b: [0.3, 0.3, 0.3] } },
    monthly: { months: [1, 2], series: { a: [0.1, 0.2], b: [0.3, 0.4] } },
    seasonal: { labels: ['DJF', 'JJA'], series: { a: [0.1, 0.3], b: [0.2, 0.2] } },
    timeseries: { timestamps: ['t0', 't1', 't2'], series: { a: [0, 1, 0], b: [1, 0, 1] }, downsampledFrom: 9 },
    nObs: 9,
  };

  test('profile: each view maps its own labels; only the time series is zoomable', () => {
    const colors = { a: '#a', b: '#b' };
    const d = buildProfileOption(profiles, 'diurnal', ['a', 'b'], colors, theme) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    expect(d.xAxis.data).toEqual(['00:00', '01:00', '02:00']);
    expect(d.series).toHaveLength(2);
    expect(d.dataZoom).toBeUndefined();
    expect(d.legend).toBeTruthy();
    const m = buildProfileOption(profiles, 'monthly', ['a'], colors, theme) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    expect(m.xAxis.data).toEqual(['Jan', 'Feb']);
    expect(m.legend).toBeUndefined(); // a single line needs no legend
    const s = buildProfileOption(profiles, 'seasonal', ['a', 'b'], colors, theme) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    expect(s.xAxis.data).toEqual(['DJF', 'JJA']);
    const t = buildProfileOption(profiles, 'timeseries', ['a', 'b'], colors, theme) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    expect(t.dataZoom).toHaveLength(2);
    expect(t.series[0].showSymbol).toBe(false);
    // a site the response does not carry is skipped rather than drawn empty
    const x = buildProfileOption(profiles, 'diurnal', ['a', 'ghost'], colors, theme) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    expect(x.series).toHaveLength(1);
  });

  test('duration: portfolio on by default, sites hidden until toggled in the legend, zoomable', () => {
    const curves: MetricsResponse['durationCurve'] = {
      portfolio: { x: [1, 50, 100], y: [0.9, 0.4, 0] },
      sites: { a: { x: [1, 50, 100], y: [1, 0.3, 0] }, b: { x: [1, 50, 100], y: [0.8, 0.5, 0] } },
    };
    const opt = buildDurationOption(curves, { a: '#a', b: '#b' }, theme) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    expect(opt.series.map((s: { name: string }) => s.name)).toEqual(['Portfolio', 'a', 'b']);
    expect(opt.legend.selected).toEqual({ Portfolio: true, a: false, b: false });
    expect(opt.series[0].data).toEqual([[1, 0.9], [50, 0.4], [100, 0]]);
    expect(opt.dataZoom).toHaveLength(2);
    expect(opt.xAxis.max).toBe(100);
  });

  test('frontier: frontier line, site points and the optimised portfolio marker (x = std, y = mean)', () => {
    const optimised = {
      weights: { a: 0.5, b: 0.5 }, meanCf: 0.4, std: 0.1, variance: 0.01, objective: 'min_variance',
      frontier: [{ meanCf: 0.35, std: 0.09 }, { meanCf: 0.45, std: 0.12 }],
      metrics: {} as MetricsResponse,
    } as OptimiseResponse;
    const opt = buildFrontierOption(optimised, [{ site: 'a', meanCf: 0.3, std: 0.2 }], { a: '#a' }, theme) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    expect(opt.series[0].data).toEqual([{ value: [0.09, 0.35] }, { value: [0.12, 0.45] }]);
    expect(opt.series[1].data[0].value).toEqual([0.2, 0.3]);
    expect(opt.series[2].data[0].value).toEqual([0.1, 0.4]);
  });

  test('lagged: one line per other site over the lag axis, null points kept as gaps', () => {
    const opt = buildLaggedOption(
      { site: 'w1', lagsHours: [-1, 0, 1], series: { w2: [0.1, 0.5, null], w3: [0, 0, 0] }, best: {}, stepHours: 1 },
      { w2: '#2', w3: '#3' }, theme,
    ) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    expect(opt.series).toHaveLength(2);
    expect(opt.series[0].data).toEqual([[-1, 0.1], [0, 0.5], [1, null]]);
    expect(opt.xAxis.min).toBe(-1);
    expect(opt.xAxis.max).toBe(1);
    expect(opt.legend).toBeTruthy();
  });
});


describe('region level', () => {
  test('parseSiteWeights reads site:weight pairs and rejects bad ones', () => {
    expect(parseSiteWeights('')).toBeUndefined();
    expect(parseSiteWeights('N1:2, N 2 :0.5')).toEqual({ N1: 2, 'N 2': 0.5 });
    expect(() => parseSiteWeights('N1')).toThrow(/site:weight/);
    expect(() => parseSiteWeights('N1:-1')).toThrow(/at least 0/);
    expect(() => parseSiteWeights(':3')).toThrow();
  });

  test('sites and regions become the same unit shape; a region may have no location', () => {
    const r: RegionRow = {
      name: 'north', region: 'north', technology: 'all', nSites: null, members: null, capacityMw: null,
      lat: null, lon: null, geometry: null, meanCf: 0.31,
    };
    expect(regionToUnit(r)).toEqual({ name: 'north', technology: 'all', region: 'north', meanCf: 0.31, capacityMw: null, lat: null, lon: null });
    expect(siteToUnit(site('S1', 'solar')).technology).toBe('solar');
    // regions group into one legend entry "all - all" on the distance scatter
    expect(pairKind(regionToUnit(r), regionToUnit(r))).toBe('all - all');
  });

  const pair = (n: number, mean: number | null, q1: number | null, q3: number | null) =>
    ({ n, mean, median: mean, std: 0.1, min: q1 === null ? null : q1 - 0.1, q1, q3, max: q3 === null ? null : q3 + 0.1 });
  const structure: StructureResponse = {
    datasetId: 'd', level: 'region', basis: 'daily', method: 'pearson', anomaly: false, nObs: 100, nSites: 5,
    groups: ['A', 'B', 'C'],
    within: [{ region: 'A', nSites: 3, ...pair(3, 0.8, 0.75, 0.85) }, { region: 'B', nSites: 2, ...pair(1, 0.7, 0.7, 0.7) }, { region: 'C', nSites: 1, ...pair(0, null, null, null) }],
    between: [{ a: 'A', b: 'B', aggregateR: 0.2, ...pair(6, 0.1, 0.05, 0.15) }],
    summary: { withinMean: 0.775, withinMedian: 0.8, nWithinPairs: 4, betweenMean: 0.1, betweenMedian: 0.1, nBetweenPairs: 6, gain: 0.675 },
    siteVsRegion: { sites: [], regions: [], regionOf: {}, matrix: [], own: {}, bestOther: {}, behavesLike: [] },
    warnings: [],
  };

  test('the within / between box plot skips regions without pairs and keeps index alignment', () => {
    const opt = buildWithinBetweenOption(structure, theme) as {
      xAxis: { data: string[] };
      series: Array<{ type: string; name: string; data: Array<unknown> }>;
      tooltip: { formatter: (p: { dataIndex: number }) => string };
    };
    expect(opt.xAxis.data).toEqual(['within A', 'within B', 'A / B']);  // C has one site: no within pair
    const [box, mean, agg] = opt.series;
    expect(box.type).toBe('boxplot');
    expect(box.data).toHaveLength(3);
    expect(mean.data).toEqual([[0, 0.8], [1, 0.7], [2, 0.1]]);
    expect(agg.data).toEqual([[0, null], [1, null], [2, 0.2]]);  // the diamond only on the between box
    expect(opt.tooltip.formatter({ dataIndex: 2 })).toContain('aggregated regions');
    expect(opt.tooltip.formatter({ dataIndex: 0 })).not.toContain('aggregated regions');
  });

  test('region names reach the tooltip escaped', () => {
    const evil = { ...structure, within: [{ region: '<b>x</b>', nSites: 2, ...pair(1, 0.5, 0.5, 0.5) }], between: [] };
    const opt = buildWithinBetweenOption(evil, theme) as { tooltip: { formatter: (p: { dataIndex: number }) => string } };
    expect(opt.tooltip.formatter({ dataIndex: 0 })).not.toContain('<b>x');
  });
});

describe('buildSitingHandoff (Screening -> Siting)', () => {
  const unit = (name: string, technology: string, lat: number | null, lon: number | null, capacityMw?: number): ScreeningUnit =>
    ({ name, technology, region: 'r', lat, lon, capacityMw });

  test('the region is the sites\' envelope plus the margin, the technologies are those present', () => {
    const h = buildSitingHandoff([unit('a', 'solar', 35, 127, 50), unit('b', 'wind', 37, 129)]);
    expect(h).not.toBeNull();
    expect(h!.bbox).toEqual([127 - HANDOFF_MARGIN_DEG, 35 - HANDOFF_MARGIN_DEG, 129 + HANDOFF_MARGIN_DEG, 37 + HANDOFF_MARGIN_DEG]);
    expect(h!.technologies).toEqual(['solar', 'wind']);
    expect(h!.sites.map((s) => s.name)).toEqual(['a', 'b']);
    expect(h!.sites[0].capacityMw).toBe(50);
    expect(h!.sites[1].capacityMw).toBeNull();
  });

  test('a single site still encloses an area', () => {
    const h = buildSitingHandoff([unit('only', 'wind', 36, 128)])!;
    expect(h.bbox[2] - h.bbox[0]).toBeCloseTo(2 * HANDOFF_MARGIN_DEG);
    expect(h.bbox[3] - h.bbox[1]).toBeCloseTo(2 * HANDOFF_MARGIN_DEG);
    expect(h.technologies).toEqual(['wind']);
  });

  test('units without coordinates are left behind and named; none located gives null; other technologies are not scanned', () => {
    const h = buildSitingHandoff([unit('nowhere', 'solar', null, null), unit('hydro', 'other', 36, 128)])!;
    expect(h.withoutLocation).toEqual(['nowhere']);
    expect(h.technologies).toEqual([]);
    expect(buildSitingHandoff([unit('x', 'solar', null, 128)])).toBeNull();
    expect(buildSitingHandoff([])).toBeNull();
  });
});
