/**
 * Screening — a statistical pre-screen of solar and wind sites, and of the
 * regions they sit in, on their historical series, before the expansion-based
 * siting.
 *
 * Level: Site | Region. At the region level the series analysed are region
 * series, either aggregated from the sites (weighted mean of CF: equal,
 * capacity or user weights, optionally per technology) or uploaded as a region
 * dataset; every panel below (map, heatmap, distance, profiles, lag, portfolio)
 * then reads regions, and the within- vs between-region panel is added.
 *
 * Flow: upload a dataset (series + site or region table) and read the validation report;
 * choose a basis (hourly ... month x hour, custom), a method (Pearson /
 * Spearman), optional anomalies and a date window; read the clustered
 * correlation heatmap, the map (click a site to colour the others by their
 * correlation with it), correlation vs distance, diurnal and seasonal profiles
 * and lagged correlation; then build a portfolio from the selected sites and
 * add it to the model. All statistics are computed by the backend.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { WorkbookFragment } from 'lib/api/databases';
import {
  Basis,
  ClusterResponse,
  CorrMethod,
  CorrelationResponse,
  DatasetKind,
  DatasetMeta,
  LaggedResponse,
  Level,
  ProfilesResponse,
  ReferenceSpec,
  RegionRow,
  RegionsResponse,
  ScreenParams,
  Technology,
  Weighting,
  deleteDataset,
  fetchCluster,
  fetchCorrelation,
  fetchLagged,
  fetchProfiles,
  fetchRegions,
  getDataset,
  listDatasets,
} from 'lib/api/screening';
import { readChartTheme } from 'lib/charts/theme';
import {
  ProfileView,
  ScreeningUnit,
  buildDistanceScatterOption,
  buildHeatmapOption,
  buildLaggedOption,
  buildProfileOption,
  buildSitingHandoff,
  categoryColors,
  fmt,
  fmtPct,
  focusRow,
  groupPairs,
  parseMonths,
  parseSeasonMap,
  parseSiteWeights,
  regionToUnit,
  reorderMatrix,
  siteToUnit,
  type SitingHandoff,
} from 'lib/screening/screening';
import { useAsync } from '../../shared/hooks/useAsync';
import { usePersistedState } from '../../shared/hooks/usePersistedState';
import { useToast } from '../../shared/components/Toast';
import { ChartPanel } from './ChartPanel';
import { MapColorMode, ScreeningMap } from './ScreeningMap';
import { PortfolioPanel } from './PortfolioPanel';
import { RegionMap } from './RegionMap';
import { StructurePanel } from './StructurePanel';
import { UploadPanel } from './UploadPanel';

interface Props {
  buses: Array<{ name: string; x: number; y: number }>;
  targetSnapshots: string[];
  currencySymbol: string;
  discountRate?: number;
  /** Stored run whose system price can serve as the reference series. */
  runName: string | null;
  onApplyFragment: (fragment: WorkbookFragment, databaseName: string, countryName: string) => void;
  /** "Open in Siting": carry the selected sites into the Siting tab (absent = no Siting tab to open). */
  onOpenInSiting?: (handoff: SitingHandoff) => void;
}

const BASES: Array<{ value: Basis; label: string }> = [
  { value: 'hourly', label: 'Hourly (raw)' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'seasonal', label: 'Seasonal (season-year means)' },
  { value: 'diurnal', label: 'Diurnal (hour of day)' },
  { value: 'month_hour', label: 'Month x hour' },
  { value: 'custom', label: 'Custom offset alias' },
];

type Scope = 'all' | 'selected' | 'solar' | 'wind' | 'other';
type TechFilter = 'all' | Technology;
type RefChoice = 'none' | 'load' | 'price' | `dataset:${string}`;

export function ScreeningPane({ buses, targetSnapshots, currencySymbol, discountRate, runName, onApplyFragment, onOpenInSiting }: Props) {
  const { showToast } = useToast();
  const theme = useMemo(() => readChartTheme(), []);

  // ── datasets ──────────────────────────────────────────────────────────
  const [tick, setTick] = useState(0);
  // The response carries the tick it was requested at: a list fetched before a just-uploaded
  // dataset existed must not be mistaken for "that dataset is gone".
  const list = useAsync(`datasets|${tick}`, async () => ({ ...(await listDatasets()), tick }));
  const [activeId, setActiveId] = usePersistedState<string | null>('ragnarok.siting.screening.dataset', null);
  const items = useMemo(() => list.data?.items ?? [], [list.data]);
  const siteDatasets = useMemo(() => items.filter((d) => d.kind === 'sites'), [items]);
  const regionDatasets = useMemo(() => items.filter((d) => d.kind === 'regions'), [items]);
  const refDatasets = useMemo(() => items.filter((d) => d.kind === 'reference'), [items]);
  useEffect(() => {
    if (!list.data || list.data.tick !== tick) return;
    if (activeId && !siteDatasets.some((d) => d.id === activeId)) setActiveId(siteDatasets[0]?.id ?? null);
    else if (!activeId && siteDatasets.length > 0) setActiveId(siteDatasets[0].id);
  }, [list.data, tick, siteDatasets, activeId, setActiveId]);
  // Level: analyse sites, or region series (aggregated from the active site dataset, or an uploaded region dataset).
  const [level, setLevel] = usePersistedState<Level>('ragnarok.screening.level', 'site');
  const [regionSource, setRegionSource] = usePersistedState<string>('ragnarok.screening.regionSource', 'sites');
  useEffect(() => {
    if (!list.data || list.data.tick !== tick) return;
    if (regionSource !== 'sites' && !regionDatasets.some((d) => d.id === regionSource)) setRegionSource('sites');
  }, [list.data, tick, regionDatasets, regionSource, setRegionSource]);
  const [weighting, setWeighting] = useState<Weighting>('equal');
  const [weightText, setWeightText] = useState('');
  const [byTech, setByTech] = useState(false);
  const [techFilter, setTechFilter] = useState<TechFilter>('all');
  const regionLevel = level === 'region';
  const fromRegionDataset = regionLevel && regionSource !== 'sites';
  const dataId = regionLevel ? (fromRegionDataset ? regionSource : activeId) : activeId;
  const meta = useAsync<DatasetMeta>(activeId ? `dataset|${activeId}|${tick}` : null, () => getDataset(activeId as string));
  // Sites of the ACTIVE dataset only: while a switch is loading, the previous dataset's sites
  // must not be sent with the new dataset id (the backend rejects unknown site names).
  const sites = useMemo(() => (meta.data && meta.data.id === activeId ? meta.data.sites : []), [meta.data, activeId]);
  const parsedWeights = useMemo(() => {
    if (weighting !== 'custom') return { weights: undefined as Record<string, number> | undefined, error: null as string | null };
    try {
      return { weights: parseSiteWeights(weightText), error: null as string | null };
    } catch (e) {
      return { weights: undefined, error: e instanceof Error ? e.message : String(e) };
    }
  }, [weighting, weightText]);
  const regionSpec = useMemo(() => ({
    weighting, siteWeights: parsedWeights.weights, byTechnology: byTech && !fromRegionDataset,
    technology: techFilter === 'all' || fromRegionDataset ? undefined : techFilter,
  }), [weighting, parsedWeights, byTech, techFilter, fromRegionDataset]);
  const regionsReady = regionLevel && !!dataId && !parsedWeights.error && (fromRegionDataset || sites.length > 0);
  const regionInfo = useAsync<RegionsResponse>(
    regionsReady ? `regions|${tick}|${JSON.stringify([dataId, regionSpec])}` : null,
    () => fetchRegions({ datasetId: dataId as string, ...regionSpec }),
  );
  // The units analysed: sites, or the regions of the ACTIVE source (a switch in flight shows none).
  const regionRows = useMemo<RegionRow[]>(() => (regionInfo.data && regionInfo.data.datasetId === dataId ? regionInfo.data.regions : []), [regionInfo.data, dataId]);
  const units = useMemo<ScreeningUnit[]>(() => (regionLevel ? regionRows.map(regionToUnit) : sites.map(siteToUnit)), [regionLevel, regionRows, sites]);
  const siteNames = useMemo(() => new Set(units.map((s) => s.name)), [units]);

  // ── analysis controls ─────────────────────────────────────────────────
  const [basis, setBasis] = useState<Basis>('daily');
  const [rule, setRule] = useState('6h');
  const [seasonText, setSeasonText] = useState('');
  const [method, setMethod] = useState<CorrMethod>('pearson');
  const [anomaly, setAnomaly] = useState(false);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [monthsText, setMonthsText] = useState('');
  const [utcOffset, setUtcOffset] = useState(0);
  const [scope, setScope] = useState<Scope>('all');
  const [k, setK] = useState(3);
  const [refChoice, setRefChoice] = useState<RefChoice>('none');
  const [refAlign, setRefAlign] = useState<'exact' | 'calendar'>('exact');
  const [refOffset, setRefOffset] = useState(0);
  const [colorMode, setColorMode] = useState<MapColorMode>('technology');
  const [profileView, setProfileView] = useState<ProfileView>('diurnal');
  const [maxLag, setMaxLag] = useState(48);
  const [pickedSites, setSelected] = useState<string[]>([]);
  const [pickedFocus, setFocus] = useState<string | null>(null);
  // Selection and focus are valid only for sites the active dataset has (switching datasets drops the rest).
  const selected = useMemo(() => pickedSites.filter((s) => siteNames.has(s)), [pickedSites, siteNames]);
  const focus = pickedFocus && siteNames.has(pickedFocus) ? pickedFocus : null;
  useEffect(() => {
    if (!focus && units.length > 0) setFocus(units[0].name);
  }, [units, focus]);

  const parsed = useMemo(() => {
    try {
      return { months: monthsText.trim() ? parseMonths(monthsText) : undefined, seasonMap: parseSeasonMap(seasonText), error: null as string | null };
    } catch (e) {
      return { months: undefined, seasonMap: undefined, error: e instanceof Error ? e.message : String(e) };
    }
  }, [monthsText, seasonText]);
  const anomalyBlocked = basis === 'diurnal' || basis === 'month_hour';
  const useAnomaly = anomaly && !anomalyBlocked;

  const analysisSites = useMemo(() => {
    const all = units.map((s) => s.name);
    if (scope === 'all' || (regionLevel && scope !== 'selected')) return all;
    if (scope === 'selected') return selected;
    return units.filter((s) => s.technology === scope).map((s) => s.name);
  }, [units, scope, selected, regionLevel]);

  const baseParams = useMemo<Omit<ScreenParams, 'sites'> | null>(() => {
    if (!dataId || parsed.error || parsedWeights.error) return null;
    return {
      datasetId: dataId, ...(regionLevel ? { level: 'region' as const, ...regionSpec } : {}), basis, rule: basis === 'custom' ? rule : undefined, seasonMap: parsed.seasonMap,
      start: start || undefined, end: end || undefined, months: parsed.months, utcOffsetHours: utcOffset, method, anomaly: useAnomaly,
    };
  }, [dataId, parsed, parsedWeights.error, regionLevel, regionSpec, basis, rule, start, end, utcOffset, method, useAnomaly]);
  const maxSites = 60;
  const analysisReady = !!baseParams && analysisSites.length >= 2 && analysisSites.length <= maxSites && !(basis === 'custom' && !rule.trim());
  const params = useMemo<ScreenParams | null>(() => (analysisReady && baseParams ? { ...baseParams, sites: analysisSites } : null), [analysisReady, baseParams, analysisSites]);

  const reference = useMemo<ReferenceSpec | null>(() => {
    if (refChoice === 'none') return null;
    if (refChoice === 'load') return { type: 'load', modelUtcOffsetHours: refOffset, align: refAlign };
    if (refChoice === 'price') return runName ? { type: 'price', run: runName, modelUtcOffsetHours: refOffset, align: refAlign } : null;
    return { type: 'dataset', datasetId: refChoice.slice('dataset:'.length), align: refAlign };
  }, [refChoice, refAlign, refOffset, runName]);

  const corr = useAsync<CorrelationResponse>(params ? `corr|${JSON.stringify([params, reference])}` : null, () => fetchCorrelation(params as ScreenParams, reference));
  const clusterK = Math.max(1, Math.min(k, analysisSites.length || 1));
  const clusters = useAsync<ClusterResponse>(params ? `cluster|${JSON.stringify([params, clusterK])}` : null, () => fetchCluster(params as ScreenParams, clusterK));

  const profileSites = useMemo(() => {
    const pick = selected.length > 0 ? selected : analysisSites.slice(0, 6);
    return pick.slice(0, 8);
  }, [selected, analysisSites]);
  const profileParams = useMemo<ScreenParams | null>(
    () => (baseParams && profileSites.length > 0 ? { ...baseParams, sites: profileSites } : null),
    [baseParams, profileSites],
  );
  const profiles = useAsync<ProfilesResponse>(
    profileParams ? `profiles|${JSON.stringify([profileParams.datasetId, profileParams.sites, profileParams.seasonMap, profileParams.start, profileParams.end, profileParams.months, profileParams.utcOffsetHours])}` : null,
    () => fetchProfiles(profileParams as ScreenParams),
  );
  const lagOthers = useMemo(() => analysisSites.filter((s) => s !== focus).slice(0, 8), [analysisSites, focus]);
  const lagParams = useMemo<ScreenParams | null>(
    () => (baseParams && focus && lagOthers.length > 0 && analysisSites.includes(focus) ? { ...baseParams, sites: [focus, ...lagOthers] } : null),
    [baseParams, focus, lagOthers, analysisSites],
  );
  const lagged = useAsync<LaggedResponse>(
    lagParams ? `lag|${JSON.stringify([lagParams.datasetId, lagParams.sites, lagParams.start, lagParams.end, lagParams.months, lagParams.utcOffsetHours, maxLag])}` : null,
    () => fetchLagged(lagParams as ScreenParams, focus as string, lagOthers, maxLag),
  );

  // ── derived view data ─────────────────────────────────────────────────
  const clusterOf = useMemo(() => clusters.data?.labels ?? {}, [clusters.data]);
  // The "base" colour key: technology for sites, the region itself for regions (a region is its own category).
  const baseKey = useCallback((s: ScreeningUnit) => (regionLevel ? s.name : s.technology), [regionLevel]);
  const techColors = useMemo(() => categoryColors(Array.from(new Set(units.map(baseKey))).sort(), theme.seriesPalette), [units, baseKey, theme]);
  const clusterColors = useMemo(() => categoryColors(Object.values(clusterOf).sort((a, b) => a - b).map(String), theme.seriesPalette), [clusterOf, theme]);
  const baseColors = useMemo(() => {
    const out: Record<string, string> = {};
    for (const s of units) {
      out[s.name] = colorMode === 'cluster' && clusterOf[s.name] ? clusterColors[String(clusterOf[s.name])] : techColors[baseKey(s)];
    }
    return out;
  }, [units, colorMode, clusterOf, clusterColors, techColors, baseKey]);
  const lineColors = useMemo(() => {
    const out: Record<string, string> = {};
    units.forEach((s, i) => { out[s.name] = theme.seriesPalette[Math.min(i, theme.seriesPalette.length - 1)]; });
    return out;
  }, [units, theme]);

  const ordered = useMemo(() => {
    if (!corr.data) return null;
    return reorderMatrix(corr.data.sites, corr.data.matrix, clusters.data?.order ?? corr.data.sites);
  }, [corr.data, clusters.data]);
  const focusCorr = useMemo(() => (corr.data && focus ? focusRow(corr.data.sites, corr.data.matrix, focus) : {}), [corr.data, focus]);
  const heatmapOption = useMemo(() => (ordered ? buildHeatmapOption(ordered.sites, ordered.matrix, theme, `${regionLevel ? 'Region ' : ''}${method === 'pearson' ? 'Pearson' : 'Spearman'} correlation, ${basis.replace('_', ' x ')}${useAnomaly ? ', anomalies' : ''}`) : null), [ordered, theme, method, basis, useAnomaly, regionLevel]);
  const distanceOption = useMemo(() => {
    if (!corr.data) return null;
    const groups = groupPairs(corr.data.distance, units);
    return buildDistanceScatterOption(groups, categoryColors(Object.keys(groups).sort(), theme.seriesPalette), theme, regionLevel ? 'Correlation vs distance between centroids' : 'Correlation vs distance');
  }, [corr.data, units, theme, regionLevel]);
  const profileOption = useMemo(() => (profiles.data ? buildProfileOption(profiles.data, profileView, profileSites, lineColors, theme) : null), [profiles.data, profileView, profileSites, lineColors, theme]);
  const lagOption = useMemo(() => (lagged.data ? buildLaggedOption(lagged.data, lineColors, theme) : null), [lagged.data, lineColors, theme]);

  // Within- vs between-region structure needs the sites: it reads the active site dataset, not a region series.
  const structureUnavailable = fromRegionDataset
    ? 'The within- vs between-region comparison needs the sites of a region: choose "Aggregate the sites of the active dataset" as the region source.'
    : !activeId ? 'Upload a site dataset first.' : null;
  const structureParams = useMemo<ScreenParams | null>(() => {
    if (!baseParams || structureUnavailable || !activeId) return null;
    return { ...baseParams, datasetId: activeId };
  }, [baseParams, structureUnavailable, activeId]);
  const structureRegions = useMemo(() => {
    if (scope !== 'selected') return undefined;
    const pick = new Set(selected);
    return Array.from(new Set(regionRows.filter((r) => pick.has(r.name)).map((r) => r.region)));
  }, [scope, selected, regionRows]);

  const toggle = useCallback((name: string) => {
    setSelected((cur) => (cur.includes(name) ? cur.filter((s) => s !== name) : [...cur, name]));
  }, []);
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  // The ticked SITES (a region series has no place to site) with their envelope, for "Open in Siting".
  const selectedHandoff = useMemo(
    () => (regionLevel ? null : buildSitingHandoff(units.filter((u) => selectedSet.has(u.name)))),
    [regionLevel, units, selectedSet],
  );
  const refCorr = corr.data?.reference?.correlations ?? {};

  const onDelete = async (id: string) => {
    try {
      await deleteDataset(id);
      showToast('Dataset deleted.', 'success');
      if (id === activeId) setActiveId(null);
      setTick((t) => t + 1);
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Delete failed.', 'error');
    }
  };

  let hint: string | null = null;
  const noun = regionLevel ? 'region' : 'site';
  if (!activeId && !fromRegionDataset) hint = regionLevel ? 'Upload a site dataset (regions are aggregated from its sites) or a region dataset to start.' : 'Upload a dataset to start screening.';
  else if (parsed.error) hint = parsed.error;
  else if (parsedWeights.error) hint = parsedWeights.error;
  else if (regionLevel && regionInfo.error) hint = null;
  else if (analysisSites.length < 2) hint = scope === 'selected' ? `Tick at least two ${noun}s in the table, or switch the scope to All.` : `The chosen scope has fewer than two ${noun}s.`;
  else if (analysisSites.length > maxSites) hint = `${analysisSites.length} ${noun}s in scope; at most ${maxSites} per analysis. Narrow the scope${regionLevel ? '' : ' to a technology or to selected sites'}.`;
  else if (basis === 'custom' && !rule.trim()) hint = 'Enter a pandas offset alias for the custom basis, for example 6h, 2W or QS.';

  return (
    <div className="scr-layout">
      <aside className="scr-rail">
        <UploadPanel
          datasets={items} datasetsError={list.error} datasetsLoading={list.loading}
          activeId={activeId} activeRegionId={regionSource === 'sites' ? null : regionSource}
          onSelect={(id: string, kind: DatasetKind) => { if (kind === 'regions') { setRegionSource(id); setLevel('region'); } else { setActiveId(id); } }}
          onChanged={(id, kind) => {
            if (id && kind === 'regions') { setRegionSource(id); setLevel('region'); } else if (id) setActiveId(id);
            setTick((t) => t + 1);
          }}
          onDelete={onDelete}
        />

        <div className="scr-card">
          <div className="scr-card-head"><h3>2 · Level</h3></div>
          <div className="scr-field-row" role="group" aria-label="Level">
            <button className={`tb-btn${!regionLevel ? '' : ' tb-btn--muted'}`} aria-pressed={!regionLevel} onClick={() => { setLevel('site'); setScope('all'); setFocus(null); setSelected([]); }}>Site</button>
            <button className={`tb-btn${regionLevel ? '' : ' tb-btn--muted'}`} aria-pressed={regionLevel} onClick={() => { setLevel('region'); setScope('all'); setFocus(null); setSelected([]); }}>Region</button>
          </div>
          {regionLevel && (
            <>
              <div className="scr-field">
                <span className="scr-label">Region series from</span>
                <select className="sg-setting-select" aria-label="Region source" value={regionSource} onChange={(e) => { setRegionSource(e.target.value); setFocus(null); setSelected([]); }}>
                  <option value="sites">Aggregate the sites of the active dataset</option>
                  {regionDatasets.map((d) => <option key={d.id} value={d.id}>Uploaded: {d.name}</option>)}
                </select>
              </div>
              {!fromRegionDataset && (
                <>
                  <div className="scr-field">
                    <span className="scr-label">Site weights</span>
                    <select className="sg-setting-select" aria-label="Weighting" value={weighting} onChange={(e) => setWeighting(e.target.value as Weighting)}>
                      <option value="equal">Equal</option>
                      <option value="capacity">Installed capacity</option>
                      <option value="custom">Custom</option>
                    </select>
                  </div>
                  {weighting === 'custom' && (
                    <div className="scr-field">
                      <span className="scr-label">Weights (site:weight)</span>
                      <input className="scr-input" aria-label="Site weights" value={weightText} onChange={(e) => setWeightText(e.target.value)} placeholder="S1:2, S2:1" />
                      <p className="scr-hint">A site not listed has weight 0.</p>
                    </div>
                  )}
                  <div className="scr-field-row">
                    <label className="scr-label">
                      <input type="checkbox" checked={byTech} onChange={(e) => setByTech(e.target.checked)} /> One series per region and technology
                    </label>
                    <div className="scr-field">
                      <span className="scr-label">Technology</span>
                      <select className="sg-setting-select" aria-label="Aggregate technology" value={techFilter} onChange={(e) => setTechFilter(e.target.value as TechFilter)}>
                        <option value="all">All</option>
                        <option value="solar">Solar only</option>
                        <option value="wind">Wind only</option>
                        <option value="other">Other only</option>
                      </select>
                    </div>
                  </div>
                  <p className="scr-hint">Region CF = sum(w CF) / sum(w) over the region&apos;s sites; with capacity weights this is the region&apos;s output over its installed capacity.</p>
                </>
              )}
            </>
          )}
        </div>

        <div className="scr-card">
          <div className="scr-card-head"><h3>3 · Analysis</h3></div>
          <div className="scr-field">
            <span className="scr-label">{regionLevel ? 'Regions in scope' : 'Sites in scope'}</span>
            <select className="sg-setting-select" aria-label="Scope" value={scope} onChange={(e) => setScope(e.target.value as Scope)}>
              <option value="all">{regionLevel ? 'All regions' : 'All sites'}</option>
              <option value="selected">{regionLevel ? 'Selected regions' : 'Selected sites'}</option>
              {!regionLevel && (
                <>
                  <option value="solar">Solar only</option>
                  <option value="wind">Wind only</option>
                  <option value="other">Other only</option>
                </>
              )}
            </select>
          </div>
          <div className="scr-field">
            <span className="scr-label">Basis</span>
            <select className="sg-setting-select" aria-label="Basis" value={basis} onChange={(e) => setBasis(e.target.value as Basis)}>
              {BASES.map((b) => <option key={b.value} value={b.value}>{b.label}</option>)}
            </select>
          </div>
          {basis === 'custom' && (
            <div className="scr-field">
              <span className="scr-label">Offset alias</span>
              <input className="scr-input" aria-label="Offset alias" value={rule} onChange={(e) => setRule(e.target.value)} placeholder="6h, 2W, QS" />
            </div>
          )}
          {basis === 'seasonal' && (
            <div className="scr-field">
              <span className="scr-label">Season mapping (optional)</span>
              <input className="scr-input" aria-label="Season mapping" value={seasonText} onChange={(e) => setSeasonText(e.target.value)} placeholder="wet:6-9; dry:12,1,2" />
              <p className="scr-hint">Empty = DJF / MAM / JJA / SON. Months not listed are left out.</p>
            </div>
          )}
          <div className="scr-field">
            <span className="scr-label">Method</span>
            <div className="scr-field-row">
              <button className={`tb-btn${method === 'pearson' ? '' : ' tb-btn--muted'}`} onClick={() => setMethod('pearson')}>Pearson</button>
              <button className={`tb-btn${method === 'spearman' ? '' : ' tb-btn--muted'}`} onClick={() => setMethod('spearman')}>Spearman</button>
            </div>
          </div>
          <label className="scr-label">
            <input type="checkbox" checked={useAnomaly} disabled={anomalyBlocked} onChange={(e) => setAnomaly(e.target.checked)} /> Anomalies (remove diurnal and seasonal cycle)
          </label>
          {anomalyBlocked && <p className="scr-hint">Not available on a diurnal basis: it shows the cycle itself.</p>}
          <div className="scr-field">
            <span className="scr-label">Date range (analysis clock)</span>
            <div className="scr-field-row">
              <input className="scr-input" type="date" aria-label="Start date" value={start} onChange={(e) => setStart(e.target.value)} />
              <input className="scr-input" type="date" aria-label="End date" value={end} onChange={(e) => setEnd(e.target.value)} />
            </div>
          </div>
          <div className="scr-field-row">
            <div className="scr-field">
              <span className="scr-label">Months only</span>
              <input className="scr-input" aria-label="Months" value={monthsText} onChange={(e) => setMonthsText(e.target.value)} placeholder="6-8" />
            </div>
            <div className="scr-field">
              <span className="scr-label">Clock = UTC +</span>
              <input className="scr-input scr-input--short" type="number" step={1} aria-label="Clock offset" value={utcOffset} onChange={(e) => setUtcOffset(Number(e.target.value) || 0)} />
            </div>
            <div className="scr-field">
              <span className="scr-label">Clusters</span>
              <input className="scr-input scr-input--short" type="number" min={1} max={analysisSites.length || 1} aria-label="Clusters" value={clusterK} onChange={(e) => setK(Math.max(1, Math.round(Number(e.target.value) || 1)))} />
            </div>
          </div>
          <div className="scr-field">
            <span className="scr-label">Reference series</span>
            <select className="sg-setting-select" aria-label="Reference" value={refChoice} onChange={(e) => setRefChoice(e.target.value as RefChoice)}>
              <option value="none">None</option>
              <option value="load">Model load</option>
              <option value="price">System price of the active run</option>
              {refDatasets.map((d) => <option key={d.id} value={`dataset:${d.id}`}>Uploaded: {d.name}</option>)}
            </select>
          </div>
          {refChoice === 'price' && !runName && <p className="scr-warn">No active run: solve or open a run first.</p>}
                  {refChoice !== 'none' && (
            <div className="scr-field-row">
              <div className="scr-field">
                <span className="scr-label">Alignment</span>
                <select className="sg-setting-select" aria-label="Reference alignment" value={refAlign} onChange={(e) => setRefAlign(e.target.value as 'exact' | 'calendar')}>
                  <option value="exact">Same timestamps</option>
                  <option value="calendar">Same calendar hour, any year</option>
                </select>
              </div>
              {(refChoice === 'load' || refChoice === 'price') && (
                <div className="scr-field">
                  <span className="scr-label">Model clock = UTC +</span>
                  <input className="scr-input scr-input--short" type="number" step={1} aria-label="Reference clock offset" value={refOffset} onChange={(e) => setRefOffset(Number(e.target.value) || 0)} />
                </div>
              )}
            </div>
          )}
        </div>
      </aside>

      <main className="scr-main">
        {meta.error && <p className="scr-error">{meta.error}</p>}
        {regionLevel && regionInfo.error && <p className="scr-error">{regionInfo.error}</p>}
        {regionLevel && regionInfo.loading && units.length === 0 && <div className="scr-card"><p className="scr-hint">Loading regions...</p></div>}
        {regionLevel && regionInfo.data?.warnings.map((w) => <p key={w} className="scr-warn">{w}</p>)}
        {hint && <div className="scr-card"><p className="scr-hint">{hint}</p></div>}

        {units.length > 0 && (
          <div className="scr-card">
            <div className="scr-card-head">
              <h3>{regionLevel ? 'Region map' : 'Site map'}{!regionLevel && meta.data ? ` - ${meta.data.name}` : ''}</h3>
              <div className="scr-field-row">
                <button className={`tb-btn${colorMode === 'technology' ? '' : ' tb-btn--muted'}`} onClick={() => setColorMode('technology')}>{regionLevel ? 'Colour by region' : 'Colour by technology'}</button>
                <button className={`tb-btn${colorMode === 'cluster' ? '' : ' tb-btn--muted'}`} onClick={() => setColorMode('cluster')}>Colour by cluster</button>
                <button className={`tb-btn${colorMode === 'correlation' ? '' : ' tb-btn--muted'}`} onClick={() => setColorMode('correlation')}>Colour by correlation</button>
              </div>
            </div>
            {regionLevel ? (
              <RegionMap
                regions={regionRows} baseColors={baseColors} mode={colorMode} focus={focus} focusCorr={focusCorr}
                selected={selectedSet} clusterOf={clusterOf} onFocus={setFocus}
              />
            ) : (
              <ScreeningMap
                sites={sites} baseColors={baseColors} mode={colorMode} focus={focus} focusCorr={focusCorr}
                selected={selectedSet} clusterOf={clusterOf} onFocus={setFocus}
              />
            )}
            <div className="scr-legend">
              {colorMode === 'cluster'
                ? Object.keys(clusterColors).map((c) => <span key={c}><span className="scr-swatch" style={{ background: clusterColors[c] }} />cluster {c}</span>)
                : Object.entries(techColors).map(([t, c]) => <span key={t}><span className="scr-swatch" style={{ background: c }} />{t}</span>)}
              <span>{focus ? `Focus: ${focus}. Lines and fills show the correlation with it.` : `Click a ${noun} to see its correlation with the others.`}</span>
            </div>
            {corr.data && corr.data.warnings.map((w) => <p key={w} className="scr-warn">{w}</p>)}
            <div className="scr-table-scroll">
              <table className="data-table" data-testid={regionLevel ? 'region-table' : 'site-table'}>
                <thead>
                  <tr>
                    <th>Select</th><th>{regionLevel ? 'Region' : 'Site'}</th>
                    {regionLevel ? <><th>Technology</th><th>Sites</th><th>Capacity MW</th></> : <><th>Technology</th><th>Region</th></>}
                    <th>Mean CF</th><th>Cluster</th>
                    <th>Corr. with {focus ?? 'focus'}</th>{corr.data?.reference && <th>Corr. with reference</th>}
                  </tr>
                </thead>
                <tbody>
                  {units.map((s, i) => (
                    <tr key={s.name} className={s.name === focus ? 'scr-row-focus' : undefined} onClick={() => setFocus(s.name)}>
                      <td onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" aria-label={`Select ${s.name}`} checked={selectedSet.has(s.name)} onChange={() => toggle(s.name)} />
                      </td>
                      <td>{s.name}</td><td>{s.technology}</td>
                      {regionLevel
                        ? <><td className="scr-num">{regionRows[i]?.nSites ?? 'series'}</td><td className="scr-num">{s.capacityMw ? Math.round(s.capacityMw).toLocaleString() : ''}</td></>
                        : <td>{s.region}</td>}
                      <td className="scr-num">{fmtPct(s.meanCf ?? null)}</td>
                      <td className="scr-num">{clusterOf[s.name] ?? ''}</td>
                      <td className="scr-num">{s.name === focus ? '1.00' : fmt(focusCorr[s.name] ?? null, 2)}</td>
                      {corr.data?.reference && <td className="scr-num">{fmt(refCorr[s.name] ?? null, 2)}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="scr-field-row">
              <button className="tb-btn" onClick={() => setSelected(units.map((s) => s.name))}>Select all</button>
              <button className="tb-btn" onClick={() => setSelected([])}>Select none</button>
              {Object.keys(clusterColors).map((c) => (
                <button key={c} className="tb-btn" onClick={() => setSelected(units.filter((s) => clusterOf[s.name] === Number(c)).map((s) => s.name))}>Select cluster {c}</button>
              ))}
              {onOpenInSiting && (
                <button
                  className="tb-btn"
                  disabled={selectedHandoff === null}
                  title={selectedHandoff === null
                    ? (regionLevel ? 'Siting works on sites: switch to the Site level and tick sites.' : 'Tick at least one site that has a location.')
                    : 'Carry the ticked sites into the Siting tab: its candidate region becomes their envelope.'}
                  onClick={() => selectedHandoff && onOpenInSiting(selectedHandoff)}
                >
                  Open in Siting
                </button>
              )}
              {corr.data?.reference && <span className="scr-hint">{corr.data.reference.label}: {corr.data.reference.nOverlap} overlapping observation(s).</span>}
            </div>
          </div>
        )}

        {params && (
          <div className="scr-grid-2">
            <div className="scr-card">
              <ChartPanel option={heatmapOption} loading={corr.loading || clusters.loading} error={corr.error ?? clusters.error} emptyText="No correlation yet." label={regionLevel ? 'Region correlation heatmap' : 'Correlation heatmap'} tall />
              {corr.data && <p className="scr-hint">{corr.data.nObs.toLocaleString()} observations. {regionLevel ? 'Regions' : 'Sites'} ordered by cluster (dendrogram order). Drag the colour scale to filter by r.</p>}
            </div>
            <div className="scr-card">
              <ChartPanel option={distanceOption} loading={corr.loading} error={corr.error} emptyText="No pairs yet." label="Correlation versus distance" tall />
              <p className="scr-hint">{regionLevel ? 'Great-circle distance between region centroids (regions without a location are left out);' : 'Great-circle distance between sites;'} scroll to zoom, drag to pan, click a legend entry to hide a technology pair.</p>
            </div>
          </div>
        )}

        {profileParams && (
          <div className="scr-card">
            <div className="scr-card-head">
              <h3>{regionLevel ? 'Region profiles' : 'Profiles'} - {profileSites.join(', ')}</h3>
              <div className="scr-field-row">
                {(['diurnal', 'monthly', 'seasonal', 'timeseries'] as ProfileView[]).map((v) => (
                  <button key={v} className={`tb-btn${profileView === v ? '' : ' tb-btn--muted'}`} onClick={() => setProfileView(v)}>
                    {v === 'diurnal' ? 'Diurnal' : v === 'monthly' ? 'Monthly' : v === 'seasonal' ? 'Season' : 'Time series'}
                  </button>
                ))}
              </div>
            </div>
            <ChartPanel option={profileOption} loading={profiles.loading} error={profiles.error} emptyText="No profile yet." label={regionLevel ? 'Region profiles' : 'Site profiles'} />
            <p className="scr-hint">Shows the selected {noun}s (up to 8), else the first six in scope. The clock offset and date window apply.</p>
          </div>
        )}

        {lagParams && (
          <div className="scr-card">
            <div className="scr-card-head">
              <h3>Lagged correlation from {focus}</h3>
              <div className="scr-field">
                <span className="scr-label">Max lag (hours)</span>
                <input className="scr-input scr-input--short" type="number" min={1} max={336} aria-label="Max lag" value={maxLag} onChange={(e) => setMaxLag(Math.max(1, Math.min(336, Math.round(Number(e.target.value) || 1))))} />
              </div>
            </div>
            <ChartPanel option={lagOption} loading={lagged.loading} error={lagged.error} emptyText="No lagged correlation yet." label="Lagged correlation" />
            {lagged.data && (
              <p className="scr-hint">
                Best lag: {Object.entries(lagged.data.best).map(([o, b]) => `${o} ${b.lagHours === null ? 'n/a' : `${b.lagHours} h`} (r ${fmt(b.r, 2)})`).join('; ')}.
                A positive lag means the other {noun} repeats what {focus} did that many hours earlier.
              </p>
            )}
          </div>
        )}

        {regionLevel && (
          <StructurePanel
            params={structureParams} regions={structureRegions} unavailable={structureUnavailable} theme={theme}
          />
        )}

        {dataId && baseParams && (regionLevel ? units.length > 0 : true) && (
          <PortfolioPanel
            params={baseParams} sites={units} selected={selected} siteColors={lineColors} theme={theme} level={level}
            buses={buses} targetSnapshots={targetSnapshots} currencySymbol={currencySymbol} discountRate={discountRate} onApplyFragment={onApplyFragment}
          />
        )}
      </main>
    </div>
  );
}
