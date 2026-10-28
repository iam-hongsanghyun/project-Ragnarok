/**
 * Screening HTTP client — `/api/screening/*`.
 *
 * A statistical pre-screen of solar / wind sites on historical series. The
 * datasets live server-side per session (not in the model sheets) and survive
 * reload; every statistic is computed by the backend (`siting/correlation.py`),
 * this module only types and transports. NaN correlations arrive as `null`.
 *
 * Key names mirror the backend responses one to one (camelCase, units in the
 * name: `meanCf` is a 0-1 capacity factor, `km` kilometres, `*Hours` hours).
 */
import { API_BASE } from 'lib/constants';
import { DEFAULT_SESSION_ID } from './session';
import type { WorkbookFragment } from './databases';

const BASE = `${API_BASE}/api/screening`;

export type Technology = 'solar' | 'wind' | 'other';
export type Basis = 'hourly' | 'daily' | 'weekly' | 'monthly' | 'seasonal' | 'diurnal' | 'month_hour' | 'custom';
export type CorrMethod = 'pearson' | 'spearman';
export type GapPolicy = 'interpolate' | 'drop';
export type Layout = 'wide' | 'long';

export interface ScreeningSite {
  name: string;
  lat: number;
  lon: number;
  technology: Technology;
  region: string;
  unit: 'cf' | 'mw';
  capacityMw: number | null;
  /** Mean capacity factor over the stored series, 0-1. */
  meanCf?: number;
}

export interface GapRun {
  from: string;
  steps: number;
}

export interface ValidationReport {
  layout?: Layout;
  timezone?: string;
  timestamps?: { interpretation: string; unparseable: number; rowsRead: number };
  duplicates?: { count: number; resolution: string };
  nonNumericValues?: number;
  sites?: { count: number };
  resolution?: { stepMinutes: number; steps: number; start: string; end: string };
  gaps?: {
    sitesWithGaps: number;
    missingStepsTotal: number;
    bySite: Record<string, { missingSteps: number; runs: number; longestRunSteps: number; first: GapRun[] }>;
    policy: GapPolicy;
    maxInterpolatedSteps: number;
    interpolatedValues?: number;
    rowsDropped?: number;
  };
  units?: {
    outOfRange: Array<{ site: string; unit: string; min: number; max: number; outOfRange: number }>;
    basis: string;
  };
  rowsStored?: number;
  errors: string[];
  warnings: string[];
}

export interface ValidateResponse {
  ok: boolean;
  message: string;
  report: ValidationReport;
  siteCount?: number;
  rows?: number;
}

export type DatasetKind = 'sites' | 'regions' | 'reference';

export interface DatasetSummary {
  id: string;
  name: string;
  kind: DatasetKind;
  referenceKind: string | null;
  unit: string;
  createdAt: string;
  timezone: string;
  stepMinutes: number | null;
  start: string;
  end: string;
  rows: number;
  filename: string;
  /** Sites of a site dataset (0 for the other kinds; 1 for a reference). */
  siteCount: number;
  /** Regions of a region dataset (0 for the other kinds). */
  regionCount: number;
  warnings: number;
}

/** GeoJSON polygon of a region (WGS84, [lon, lat] positions). */
export interface RegionGeometry {
  type: 'Polygon' | 'MultiPolygon';
  coordinates: unknown;
}

/** A row of an uploaded region table. */
export interface StoredRegion {
  name: string;
  lat: number | null;
  lon: number | null;
  technology: string;
  region: string;
  unit: 'cf' | 'mw';
  capacityMw: number | null;
  geometry: RegionGeometry | null;
  meanCf?: number;
}

export interface DatasetMeta extends DatasetSummary {
  /** Sites of a site dataset; empty for a region dataset. */
  sites: ScreeningSite[];
  /** Regions of a region dataset; absent otherwise. */
  regions?: StoredRegion[];
  report: ValidationReport;
}

export type Level = 'site' | 'region';
export type Weighting = 'equal' | 'capacity' | 'custom';

/** How a region series is built from sites (ignored for a region dataset). */
export interface RegionSpec {
  weighting: Weighting;
  /** {site: weight} for weighting `custom`. */
  siteWeights?: Record<string, number>;
  byTechnology: boolean;
  technology?: Technology;
}

export interface Paged<T> {
  items: T[];
  total: number;
}

/** Selection + analysis basis shared by the statistic routes. */
export interface ScreenParams {
  datasetId: string;
  sites?: string[];
  basis: Basis;
  rule?: string;
  /** Month number (as string) -> season label, for basis `seasonal`. */
  seasonMap?: Record<string, string>;
  start?: string;
  end?: string;
  months?: number[];
  utcOffsetHours: number;
  method: CorrMethod;
  anomaly: boolean;
  anomalyStandardise?: boolean;
  /** `region`: `sites` are region names; the series are aggregated from sites or a region dataset. */
  level?: Level;
  weighting?: Weighting;
  siteWeights?: Record<string, number>;
  byTechnology?: boolean;
  technology?: Technology;
}

export interface ReferenceSpec {
  type: 'load' | 'price' | 'dataset';
  run?: string;
  datasetId?: string;
  modelUtcOffsetHours?: number;
  align?: 'exact' | 'calendar';
}

export interface DistancePair {
  a: string;
  b: string;
  km: number;
  r: number | null;
}

export interface CorrelationResponse {
  datasetId: string;
  level: Level;
  basis: Basis;
  method: CorrMethod;
  anomaly: boolean;
  nObs: number;
  sites: string[];
  matrix: Array<Array<number | null>>;
  distance: DistancePair[];
  reference: { label: string; nOverlap: number; correlations: Record<string, number | null> } | null;
  warnings: string[];
}

export interface ClusterResponse {
  order: string[];
  labels: Record<string, number>;
  linkage: number[][];
  nClusters: number;
  basis: Basis;
  method: CorrMethod;
  nObs: number;
}

export interface LaggedResponse {
  site: string;
  lagsHours: number[];
  series: Record<string, Array<number | null>>;
  best: Record<string, { lagHours: number | null; r: number | null }>;
  stepHours: number;
}

export interface ProfilesResponse {
  sites: string[];
  diurnal: { hours: number[]; series: Record<string, Array<number | null>> };
  monthly: { months: number[]; series: Record<string, Array<number | null>> };
  seasonal: { labels: string[]; series: Record<string, Array<number | null>> };
  timeseries?: { timestamps: string[]; series: Record<string, Array<number | null>>; downsampledFrom: number };
  nObs: number;
}

export interface SeriesStats {
  meanCf: number;
  std: number;
  cv: number | null;
  p10: number;
  p50: number;
  p90: number;
  lowOutputShare: number;
  worstNMeanCf: number;
  worstNLossFrac: number | null;
}

export interface PortfolioStats extends SeriesStats {
  diversificationRatio: number | null;
  rampStd: number;
  maxRamp: number;
}

export interface SiteMatrix {
  sites: string[];
  matrix: Array<Array<number | null>>;
}

export interface DurationCurve {
  x: number[];
  y: number[];
}

export interface MetricsResponse {
  weights: Record<string, number>;
  portfolio: PortfolioStats;
  perSite: Array<SeriesStats & { site: string; weight: number }>;
  coincidentLow: SiteMatrix & { independent: Array<Array<number | null>> };
  rampCorrelation: SiteMatrix;
  nObs: number;
  lowThreshold: number;
  worstN: number;
  durationCurve: { portfolio: DurationCurve; sites: Record<string, DurationCurve> };
}

export interface OptimiseResponse {
  weights: Record<string, number>;
  meanCf: number;
  std: number;
  variance: number;
  objective: 'min_variance' | 'max_mean';
  frontier: Array<{ meanCf: number; std: number }>;
  metrics: MetricsResponse;
}

export interface OptimiseSettings {
  objective: 'min_variance' | 'max_mean';
  targetMeanCf?: number;
  /** Variance cap in CF^2 (the UI asks for a standard deviation and squares it). */
  varianceCap?: number;
  maxWeight: number;
  regionCaps?: Record<string, number>;
  frontierPoints: number;
}

export interface PortfolioSettings {
  lowThreshold: number;
  worstN: number;
}

export interface AlignmentCounts {
  exact: number;
  monthDayHour: number;
  hourOfDay: number;
  unaligned: number;
  total: number;
}

export interface PromoteReport {
  mode: 'model-snapshots' | 'own-snapshots';
  snapshots: number;
  exactShare: number;
  sites: Array<{
    site: string;
    generator: string;
    bus: string;
    busDistanceKm: number | null;
    pNomMw: number;
    meanCf: number;
    alignment: AlignmentCounts;
  }>;
  warnings: string[];
  ok: boolean;
}

/** One region series in use: members and weights (null for an uploaded region series), centroid, polygon. */
export interface RegionRow {
  name: string;
  /** The region label (equals `name` unless split by technology). */
  region: string;
  /** `all` when the region mixes technologies. */
  technology: string;
  nSites: number | null;
  members: Array<{ site: string; weight: number }> | null;
  capacityMw: number | null;
  lat: number | null;
  lon: number | null;
  geometry: RegionGeometry | null;
  /** Mean capacity factor, 0-1. */
  meanCf: number;
}

export interface RegionsResponse {
  datasetId: string;
  source: 'sites' | 'regions';
  weighting: Weighting | null;
  byTechnology: boolean;
  regions: RegionRow[];
  unassigned: string[];
  warnings: string[];
}

/** Distribution of a set of pairwise correlations (a box plot's five numbers and the mean). */
export interface PairStats {
  n: number;
  mean: number | null;
  median: number | null;
  std: number | null;
  min: number | null;
  q1: number | null;
  q3: number | null;
  max: number | null;
}

export interface SiteVsRegion {
  sites: string[];
  regions: string[];
  regionOf: Record<string, string>;
  /** sites x regions; the own region is leave-one-out. */
  matrix: Array<Array<number | null>>;
  own: Record<string, number | null>;
  bestOther: Record<string, { region: string | null; r: number | null }>;
  behavesLike: Array<{ site: string; region: string; ownRegion: string; ownR: number; otherR: number; delta: number }>;
}

export interface StructureResponse {
  datasetId: string;
  level: 'region';
  basis: Basis;
  method: CorrMethod;
  anomaly: boolean;
  nObs: number;
  nSites: number;
  groups: string[];
  within: Array<PairStats & { region: string; nSites: number }>;
  between: Array<PairStats & { a: string; b: string; aggregateR: number | null }>;
  summary: {
    withinMean: number | null;
    withinMedian: number | null;
    nWithinPairs: number;
    betweenMean: number | null;
    betweenMedian: number | null;
    nBetweenPairs: number;
    /** withinMean - betweenMean. */
    gain: number | null;
  };
  siteVsRegion: SiteVsRegion;
  warnings: string[];
}

export interface PromoteRequest {
  datasetId: string;
  sites: string[];
  utcOffset: number;
  pNomMw?: Record<string, number>;
  extendable: boolean;
  capitalCost?: Record<string, number>;
  marginalCost: number;
  busOverrides?: Record<string, string>;
  buses?: Array<{ name: string; x: number; y: number }>;
  targetSnapshots?: string[];
}

export interface PromoteResponse {
  applied: boolean;
  report: PromoteReport;
  counts: Record<string, number>;
  generators: string[];
  fragment?: WorkbookFragment;
}

/** Error carrying the validation report the backend attaches to a rejected upload. */
export class ScreeningError extends Error {
  readonly report?: ValidationReport;
  readonly status: number;
  constructor(message: string, status: number, report?: ValidationReport) {
    super(message);
    this.status = status;
    this.report = report;
  }
}

async function failure(resp: Response, what: string): Promise<ScreeningError> {
  let message = resp.statusText;
  let report: ValidationReport | undefined;
  try {
    const body = await resp.json();
    const detail = body?.detail;
    if (typeof detail === 'string') message = detail;
    else if (detail && typeof detail === 'object') {
      message = typeof detail.message === 'string' ? detail.message : JSON.stringify(detail);
      report = detail.report as ValidationReport | undefined;
    }
  } catch {
    /* non-JSON error body */
  }
  return new ScreeningError(`${what} failed (${resp.status}): ${message}`, resp.status, report);
}

async function postJson<T>(route: string, body: unknown, what: string): Promise<T> {
  const resp = await fetch(`${BASE}/${route}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId: DEFAULT_SESSION_ID, ...(body as object) }),
  });
  if (!resp.ok) throw await failure(resp, what);
  return (await resp.json()) as T;
}

export interface UploadForm {
  file: File;
  sitesFile?: File | null;
  name?: string;
  layout: Layout;
  timezone: string;
  gapPolicy: GapPolicy;
  maxInterpSteps?: number;
  kind: DatasetKind;
  /** GeoJSON FeatureCollection of region polygons (kind `regions`); features match regions by `properties.name`. */
  geojsonFile?: File | null;
  referenceKind?: 'load' | 'price';
  defaultUnit: 'cf' | 'mw';
  unit?: string;
}

function toFormData(f: UploadForm, withSession: boolean): FormData {
  const fd = new FormData();
  fd.append('file', f.file);
  if (f.sitesFile) fd.append('sitesFile', f.sitesFile);
  if (f.geojsonFile) fd.append('geojsonFile', f.geojsonFile);
  if (withSession) fd.append('sessionId', DEFAULT_SESSION_ID);
  if (f.name) fd.append('name', f.name);
  fd.append('layout', f.layout);
  fd.append('timezone', f.timezone);
  fd.append('gapPolicy', f.gapPolicy);
  if (f.maxInterpSteps !== undefined) fd.append('maxInterpSteps', String(f.maxInterpSteps));
  fd.append('kind', f.kind);
  if (f.referenceKind) fd.append('referenceKind', f.referenceKind);
  fd.append('defaultUnit', f.defaultUnit);
  if (f.unit) fd.append('unit', f.unit);
  return fd;
}

/** Validate an upload and get the report; nothing is stored. */
export async function validateUpload(f: UploadForm): Promise<ValidateResponse> {
  const resp = await fetch(`${BASE}/validate`, { method: 'POST', body: toFormData(f, false) });
  if (!resp.ok) throw await failure(resp, 'validation');
  return (await resp.json()) as ValidateResponse;
}

export async function uploadDataset(f: UploadForm): Promise<DatasetMeta> {
  const resp = await fetch(`${BASE}/datasets`, { method: 'POST', body: toFormData(f, true) });
  if (!resp.ok) throw await failure(resp, 'upload');
  return (await resp.json()) as DatasetMeta;
}

export async function listDatasets(kind?: DatasetKind): Promise<Paged<DatasetSummary>> {
  const q = new URLSearchParams({ sessionId: DEFAULT_SESSION_ID, limit: '200' });
  if (kind) q.set('kind', kind);
  const resp = await fetch(`${BASE}/datasets?${q.toString()}`);
  if (!resp.ok) throw await failure(resp, 'dataset list');
  return (await resp.json()) as Paged<DatasetSummary>;
}

export async function getDataset(id: string): Promise<DatasetMeta> {
  const resp = await fetch(`${BASE}/datasets/${encodeURIComponent(id)}?sessionId=${encodeURIComponent(DEFAULT_SESSION_ID)}`);
  if (!resp.ok) throw await failure(resp, 'dataset load');
  return (await resp.json()) as DatasetMeta;
}

export async function deleteDataset(id: string): Promise<boolean> {
  const resp = await fetch(
    `${BASE}/datasets/${encodeURIComponent(id)}?sessionId=${encodeURIComponent(DEFAULT_SESSION_ID)}`,
    { method: 'DELETE' },
  );
  if (!resp.ok) throw await failure(resp, 'dataset delete');
  return ((await resp.json()) as { deleted: boolean }).deleted;
}

export const fetchCorrelation = (p: ScreenParams, reference?: ReferenceSpec | null) =>
  postJson<CorrelationResponse>('correlation', { ...p, reference: reference ?? undefined }, 'correlation');

export const fetchCluster = (p: ScreenParams, k: number) =>
  postJson<ClusterResponse>('cluster', { ...p, k }, 'clustering');

export const fetchLagged = (p: ScreenParams, site: string, others: string[], maxLagHours: number) =>
  postJson<LaggedResponse>('lagged', { ...p, site, others, maxLagHours }, 'lagged correlation');

export const fetchProfiles = (p: ScreenParams) =>
  postJson<ProfilesResponse>('profiles', { ...p, includeSeries: true }, 'profiles');

export const fetchMetrics = (p: ScreenParams, weights: Record<string, number>, s: PortfolioSettings) =>
  postJson<MetricsResponse>('metrics', { ...p, weights, ...s }, 'portfolio metrics');

export const fetchOptimise = (p: ScreenParams, o: OptimiseSettings, s: PortfolioSettings) =>
  postJson<OptimiseResponse>('optimise', { ...p, ...o, ...s }, 'optimisation');

export const promotePreview = (req: PromoteRequest) =>
  postJson<PromoteResponse>('promote', { ...req, apply: false, includeFragment: true }, 'promotion preview');


/** Region series in use (members, weights, centroids, polygons). `p.sites` narrows to named regions. */
export const fetchRegions = (p: Pick<ScreenParams, 'datasetId'> & Partial<RegionSpec> & { sites?: string[] }) =>
  postJson<RegionsResponse>('regions', p, 'regions');

/** Within- vs between-region correlation and each site against its own and the other regions (site datasets). */
export const fetchStructure = (p: ScreenParams, regions?: string[]) =>
  postJson<StructureResponse>('regions/structure', { ...p, regions }, 'region structure');
