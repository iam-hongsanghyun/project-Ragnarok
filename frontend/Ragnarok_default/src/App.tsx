import React, { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSettings } from './features/settings/useSettings';
import 'leaflet/dist/leaflet.css';
import 'react-calendar/dist/Calendar.css';

import {
  AnalyticsFocus,
  BrowserFileHandle,
  ChartSectionConfig,
  ConstraintSpec,
  CustomConstraint,
  GridRow,
  PathwayConfig,
  RollingHorizonConfig,
  SamplingConfig,
  StochasticConfig,
  SecurityConstrainedConfig,
  PowerFlowConfig,
  ContingencyConfig,
  MgaConfig,
  MerchantConfig,
  FinanceConfig,
  CarbonPriceScheduleEntry,
  CarbonScheduleProfile,
  Primitive,
  BackendRunMeta,
  RunResults,
  ScenarioCatalog,
  ScenarioPreset,
  SheetName,
  TimeSeriesRow,
  TimeSeriesSeries,
  TsSheetName,
  WorkbookModel,
  WorkspaceTab,
  AnalyticsSubTab,
  QueueJob,
} from 'lib/types';
import { API_BASE, DEFAULT_CONSTRAINTS, getDefaultRowForSheet, getNewRowDefaults, RUN_WINDOW, SHEETS } from 'lib/constants';
import { canonicalizeOutputSeries, canonicalizeTemporalRows, createEmptyWorkbook, exportWorkbook, normalizeInputDatesToIso, parseWorkbook, workbookToArrayBuffer } from 'lib/workbook/workbook';
import { mergeWorkbookFragment } from 'lib/workbook/mergeFragment';
import type { WorkbookFragment } from 'lib/api/databases';
import { getBounds, getBusIndex, carrierColor, numberValue, orderByCarrierRows, setCarrierColorOverrides, snapshotMaxFromWorkbook, stringValue } from 'lib/utils/helpers';
import { filenameMatchesScenario, scenarioFilename } from 'lib/utils/scenarioFilename';
import { usePersistedState } from 'shared/hooks/usePersistedState';
import { RagnarokLogo } from 'shared/components/RagnarokLogo';
import { buildRowsFromGeneratorDetails, buildSystemLoadRows, normalizeSeriesPoint } from 'lib/results/analytics';
import { withDerivedAssetDetails } from 'lib/results/assetDetails';
import { deriveRunResults } from 'lib/results/runResults';
import { defaultPathwayConfig, getDefaultSelectedPeriod, readPathwayConfigFromModel, samePathwayConfig, writePathwayConfigToModel } from 'lib/results/pathway';
import { defaultRollingConfig, normalizeRollingConfig, readRollingConfigFromModel, sameRollingConfig, writeRollingConfigToModel } from 'lib/results/rolling';
import { defaultSamplingConfig, normalizeSamplingConfig, readSamplingConfigFromModel, sameSamplingConfig, writeSamplingConfigToModel } from 'lib/results/sampling';
import { readCustomDslFromModel, writeCustomDslToModel } from 'lib/constraints/custom';
import { dslToSpecs, parseConstraintDsl } from 'lib/constraints/dsl';
import { buildScenarioPreset, defaultScenarioCatalog, readScenarioCatalogFromModel, sameScenarioCatalog, writeScenarioCatalogToModel } from 'lib/results/scenarios';
import { readCarbonLibraryFromModel, writeCarbonLibraryToModel, sameCarbonLibrary } from 'lib/results/carbonLibrary';
import { saveSessionControls, loadSessionControls, clearSession, clearSessionModelOnly } from 'lib/storage/sessionStore';
import { clearSessionModel, putSessionModel, putStaticModel, getSessionFullModel, getSessionMeta, getSheetPage, isSeriesSheet, patchSheet, seriesSheetCounts, DEFAULT_SESSION_ID } from 'lib/api/session';
import type { ClusterResult } from 'lib/forge/transforms';
import type { SheetEditOp } from 'lib/api/session';
import { fetchRunOutputSeriesWindows } from 'lib/api/runs';
import { loadExample } from 'lib/api/examples';
import { RunDialog } from './features/run/RunDialog';
import { SettingsView } from './views/SettingsView';
import { PluginsView } from './views/PluginsView';
import { ModelView } from './views/ModelView';
import { HistoryView } from './views/HistoryView';
import { QueueView } from './views/QueueView';
import { ViewPaneHeader } from './shared/components/primitives';
import { BuildView } from './features/build/BuildView';
import { DataView } from './views/DataView';
import { WelcomeView } from './views/WelcomeView';
import { ForgeView } from './views/ForgeView';
import { AnalyticsView } from './views/AnalyticsView';
import { ActivityBar } from './layout/ActivityBar';
import { useModelIssues } from './features/validation/useModelIssues';
import { useFrontendPlugins } from './features/plugins/frontendPlugins';
import { ToastProvider, useToast } from './shared/components/Toast';
import { DialogProvider, useDialog } from './shared/components/Dialog';

/**
 * Strip every trailing project/data extension from a filename so export names
 * never double up (e.g. a re-imported `case.xlsx.xlsx` → `case`). Repeats so
 * stacked extensions collapse; falls back to `ragnarok` when nothing remains.
 */
function projectBaseName(filename: string): string {
  const base = filename.replace(/(\.(xlsx|xls|nc|h5|hdf5|zip))+$/i, '').trim();
  return base || 'ragnarok';
}

/**
 * Drop the heavy time-series sheets from a model so the browser holds only the
 * small static/topology sheets. The series live in the backend session and are
 * paged into the grid on demand. Keeps `snapshots` (the time axis) and all
 * static/config sheets.
 *
 * Starts from an empty workbook so EVERY standard component sheet is always
 * present as an array — a backend-rehydrated model only carries the sheets the
 * session actually had, and consumers like MapPane do `model.lines.map(...)`
 * assuming the sheet exists.
 */
function stripSeriesSheets(model: WorkbookModel): WorkbookModel {
  const out: WorkbookModel = createEmptyWorkbook();
  for (const [sheet, rows] of Object.entries(model)) {
    (out as Record<string, unknown>)[sheet] = isSeriesSheet(sheet) ? [] : rows;
  }
  return out;
}

function AppInner() {
  const { showToast } = useToast();
  const { confirm: confirmDialog, prompt: promptDialog } = useDialog();
  const [model, setModel] = useState<WorkbookModel>(() => createEmptyWorkbook());
  // Cell-level undo/redo. Each entry is a full (immutable) model snapshot;
  // since every mutation already builds a fresh object this is cheap to retain.
  const undoStack = useRef<WorkbookModel[]>([]);
  const redoStack = useRef<WorkbookModel[]>([]);
  // ── Static edits → backend (the session is the source of truth) ───────────
  // Cell/row edits on static sheets map 1:1 to precise PATCH ops — row-level
  // SQL writes, exactly like the temporal sheets. Structural changes that have
  // no op equivalent (column add/delete/rename, clear, reorder, undo/redo)
  // bump `staticResyncTick` → ONE static-merge resync (effect lives below,
  // after prepareModelForBackend). The React model stays only as a small read
  // cache for the map/Forge/validation views — never the truth.
  const modelRef = useRef<WorkbookModel>(model);
  modelRef.current = model;
  const [staticResyncTick, setStaticResyncTick] = useState(0);
  const requestStaticResync = useCallback(() => setStaticResyncTick((t) => t + 1), []);
  const pushStaticOps = useCallback(
    (sheet: SheetName, ops: SheetEditOp[]) => {
      // On any failure (e.g. the sheet has no session table yet) fall back to a
      // full static merge so the backend can never silently drift from the UI.
      void patchSheet(String(sheet), ops).catch(() => requestStaticResync());
    },
    [requestStaticResync],
  );

  // Undo depth. Each entry retains the model object as it was before an edit;
  // editing big time-series sheets makes these add up, so keep the window small
  // (the backend is the source of truth — deep client-side history isn't needed).
  const HISTORY_LIMIT = 5;
  const pushHistory = useCallback(() => {
    undoStack.current.push(model);
    if (undoStack.current.length > HISTORY_LIMIT) undoStack.current.shift();
    redoStack.current = [];
  }, [model]);
  const undo = useCallback(() => {
    const prev = undoStack.current.pop();
    if (!prev) return;
    redoStack.current.push(model);
    setModel(prev);
    requestStaticResync(); // mirror reverted → re-merge it into the session
  }, [model, requestStaticResync]);
  const redo = useCallback(() => {
    const next = redoStack.current.pop();
    if (!next) return;
    undoStack.current.push(model);
    setModel(next);
    requestStaticResync();
  }, [model, requestStaticResync]);
  // Always open on the Welcome / intro screen — the workspace tab is NOT
  // persisted across reloads (was restoring the last view, e.g. Comparison).
  const [tab, setTab] = useState<WorkspaceTab>('Welcome');
  // Ctrl/Cmd+Z / Ctrl+Y (or Shift+Z) undo-redo for model edits, only on the
  // Model/Build tabs and never while a text field is focused (so it doesn't
  // hijack native input undo).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (tab !== 'Model' && tab !== 'Build') return;
      const el = document.activeElement as HTMLElement | null;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return;
      if (!(e.metaKey || e.ctrlKey)) return;
      const k = e.key.toLowerCase();
      if (k === 'z' && !e.shiftKey) { e.preventDefault(); undo(); }
      else if ((k === 'z' && e.shiftKey) || k === 'y') { e.preventDefault(); redo(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [tab, undo, redo]);
  // Persisted so the analytics sub-tab the user last viewed sticks across tab
  // navigation and reloads — never auto-yanked back to a default.
  const [analyticsSubTab, setAnalyticsSubTab] = usePersistedState<AnalyticsSubTab>('ui:analytics-subtab', 'Result');
  // History top-tab sub-navigation: the live run Queue, or the persisted run History.
  const [historySubTab, setHistorySubTab] = usePersistedState<'Queue' | 'History'>('ui:history-subtab', 'History');
  const [results, setResults] = useState<RunResults | null>(null);
  // Topology snapshot taken at the moment `results` were produced/restored.
  // Analytics (map, asset derivation) must reflect the run that owns the
  // displayed results, not the live model the user may have since edited.
  const [resultsModel, setResultsModel] = useState<WorkbookModel | null>(null);
  // Derivation inputs frozen at the moment `results` were produced/restored.
  // Pathway analytics re-derive per-period KPIs from these; without freezing,
  // restoring an old run while the live sliders differ would recompute its
  // charts with the current carbon price / resolution / discount rate.
  const [resultsContext, setResultsContext] = useState<
    { carbonPrice: number; snapshotWeight: number; discountRate: number } | null
  >(null);
  const [maxSnapshots, setMaxSnapshots] = useState<number>(RUN_WINDOW.initialMaxSnapshots);
  const [snapshotStart, setSnapshotStart] = useState(RUN_WINDOW.initialSnapshotStart);
  const [snapshotEnd, setSnapshotEnd] = useState(RUN_WINDOW.defaultSnapshotEnd);
  const [snapshotWeight, setSnapshotWeight] = useState(RUN_WINDOW.defaultSnapshotWeight);
  const [constraints, setConstraints] = useState<CustomConstraint[]>(DEFAULT_CONSTRAINTS);
  const [carbonPrice, setCarbonPrice] = useState<number>(0);
  const [forceLp, setForceLp] = useState<boolean>(false);
  // Persisted so the asset the user was inspecting (system / a bus / a
  // generator …) survives tab navigation and reloads. Only the safety effect
  // below clears it — and only when that asset is genuinely absent from the
  // current results.
  const [analyticsFocus, setAnalyticsFocus] = usePersistedState<AnalyticsFocus>('ui:analytics-focus', { type: 'system' });
  const [chartSections, setChartSections] = useState<ChartSectionConfig[]>([]);
  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [backendRuns, setBackendRuns] = useState<BackendRunMeta[]>([]);
  // Temporal sheet name → row count in the backend session. Time-series sheets
  // are stripped from the in-memory model (held server-side, paged on demand),
  // so this is what makes them visible + selectable in the Model tree. Set from
  // the loaded model's own series, and refreshed from the session after a
  // backend-plugin build (which rehydrates the editor static-only).
  const [sessionSeriesCounts, setSessionSeriesCounts] = useState<Record<string, number>>({});
  // Filenames of external result imports currently being converted to History
  // entries. Importing a full-year result takes tens of seconds (parse + derive
  // analytics + build the run db), so History shows a "Converting…" placeholder
  // row per in-flight import until the real entry lands.
  const [convertingImports, setConvertingImports] = useState<string[]>([]);
  // Per-stored-run in-flight activity (run name → label like "Importing" /
  // "Exporting" / "Deleting"), so each History row shows a spinner + label while
  // an action on it is running — the way the Queue shows "Running".
  const [runActivity, setRunActivity] = useState<Record<string, string>>({});
  const setRunBusy = useCallback((name: string, label: string | null) => {
    setRunActivity((current) => {
      if (label === null) {
        if (!(name in current)) return current;
        const next = { ...current };
        delete next[name];
        return next;
      }
      return { ...current, [name]: label };
    });
  }, []);
  // Name of the backend run currently shown in the viewer — drives the
  // Comparison "active" column highlight. Set after a run completes (to the
  // newest stored meta) and when opening a stored run.
  const [activeRunName, setActiveRunName] = useState<string | null>(null);
  // Per-component output series fetched on demand for the active run. The light
  // "View" bundle strips them (`outputs.series = null`); without them the
  // per-asset analytics (generator / storage / bus / branch charts and the map
  // asset-detail popups) derive empty. Cached for one run at a time; refetched
  // when `activeRunName` changes. See the hydration effect + `displayResults`.
  // Per-run cache of hydrated output series. `series[sheet]` holds the rows;
  // `ends[sheet]` records how many snapshots that sheet was fetched at, so a
  // chart whose slider extends past it triggers a longer refetch.
  const [hydratedRunSeries, setHydratedRunSeries] = useState<
    { runName: string; series: Record<string, GridRow[]>; ends: Record<string, number> } | null
  >(null);
  // Per output-series sheet, the MAX number of snapshots the displayed analytics
  // layout's per-asset charts need loaded (each chart's slider right edge).
  // Driven by the dashboard. Empty {} for system-only layouts → no hydration
  // fetch, so the common result view stays instant.
  const [neededRunWindows, setNeededRunWindows] = useState<Record<string, number>>({});
  const [pathwayConfig, setPathwayConfig] = useState<PathwayConfig>(() => defaultPathwayConfig());
  const [rollingConfig, setRollingConfig] = useState<RollingHorizonConfig>(() => defaultRollingConfig());
  const [samplingConfig, setSamplingConfig] = useState<SamplingConfig>(() => defaultSamplingConfig());
  const [customDsl, setCustomDsl] = useState<string>('');
  const [stochasticConfig, setStochasticConfig] = useState<StochasticConfig>({ enabled: false, scenarios: [] });
  const [sclopfConfig, setSclopfConfig] = useState<SecurityConstrainedConfig>({ enabled: false });
  const [powerFlowConfig, setPowerFlowConfig] = useState<PowerFlowConfig>({ enabled: false, linear: false });
  const [contingencyConfig, setContingencyConfig] = useState<ContingencyConfig>({ enabled: false });
  const [mgaConfig, setMgaConfig] = useState<MgaConfig>({ enabled: false, slack: 0.05, carriers: [] });
  const [merchantConfig, setMerchantConfig] = useState<MerchantConfig>({ enabled: false, owner: '', priceSource: 'lmp', flatPrice: 0 });
  const [ownerColumn, setOwnerColumn] = useState<string>('owner');
  const [financeConfig, setFinanceConfig] = useState<FinanceConfig>({ gearing: 0, interestRate: 0.05, tenorYears: 15 });
  const [carbonPriceSchedule, setCarbonPriceSchedule] = useState<CarbonPriceScheduleEntry[]>([]);
  const [carbonLibrary, setCarbonLibrary] = useState<CarbonScheduleProfile[]>([]);
  const [validateResult, setValidateResult] = useState<{
    valid: boolean;
    errors: string[];
    warnings: string[];
    notes: string[];
    snapshotCount: number;
    networkSummary: Record<string, number>;
  } | null>(null);
  const [status, setStatus] = useState('Ready. Open a workbook or import a project.');
  const [fileHandle, setFileHandle] = useState<BrowserFileHandle | null>(null);
  const [jumpTo, setJumpTo] = useState<{ sheet: string; rowIndex: number } | null>(null);
  // Server-side run queue. Runs are enqueued and execute up to `queueConcurrency`
  // at a time (1 = serial queue, the default); the frontend polls /api/queue,
  // shows retained queue rows in the Queue tab, and is notified when active rows
  // finish (successful runs also appear in History).
  const [queueJobs, setQueueJobs] = useState<QueueJob[]>([]);
  const [queueConcurrency, setQueueConcurrency] = useState(1);
  const [queueCpuCount, setQueueCpuCount] = useState(1);
  const seenTerminalRef = useRef<Set<string>>(new Set());
  const queueStatusRef = useRef<Map<string, QueueJob['status']>>(new Map());

  const [settings, updateSettings] = useSettings();
  const [scenarioCatalog, setScenarioCatalog] = useState<ScenarioCatalog>(() => defaultScenarioCatalog({
    snapshotStart: RUN_WINDOW.initialSnapshotStart,
    snapshotEnd: RUN_WINDOW.defaultSnapshotEnd,
    snapshotWeight: RUN_WINDOW.defaultSnapshotWeight,
    carbonPrice: 0,
    carbonPriceSchedule: [],
    discountRate: settings.discountRate,
    forceLp: false,
    enableLoadShedding: settings.enableLoadShedding,
    loadSheddingCost: settings.loadSheddingCost,
    pathwayConfig: defaultPathwayConfig(),
    rollingConfig: defaultRollingConfig(),
    samplingConfig: defaultSamplingConfig(),
    stochasticConfig: { enabled: false, scenarios: [] },
    securityConstrainedConfig: { enabled: false },
    powerFlowConfig: { enabled: false, linear: false },
    contingencyConfig: { enabled: false },
    mgaConfig: { enabled: false, slack: 0.05, carriers: [] },
    merchantConfig: { enabled: false, owner: '', priceSource: 'lmp', flatPrice: 0 },
    ownerColumn: 'owner',
    financeConfig: { gearing: 0, interestRate: 0.05, tenorYears: 15 },
    constraints: DEFAULT_CONSTRAINTS,
  }));
  const frontendPlugins = useFrontendPlugins();
  const modelIssues = useModelIssues(model);

  // Topology that owns the currently displayed results: the snapshot taken at
  // run/restore time when available, else the live model (e.g. before any run).
  // A restored/imported topology can be PARTIAL — an external results file may
  // carry no `lines` / `transformers` / `stores` sheet at all, and the light
  // analytics view only ships the sheets that exist. Spread it over an empty
  // workbook so EVERY component sheet is guaranteed an array; analytics cards
  // (which already treat an empty sheet as "no components") then never hit
  // `undefined.map`. The live `model` is already full, so it passes through.
  const analyticsModel = useMemo(
    () => (resultsModel ? { ...createEmptyWorkbook(), ...resultsModel } : model),
    [resultsModel, model],
  );
  // Derivation inputs that own the displayed results: frozen run-time values
  // when available, else the live sliders (e.g. before any run).
  const analyticsCarbonPrice = resultsContext?.carbonPrice ?? carbonPrice;
  const analyticsSnapshotWeight = resultsContext?.snapshotWeight ?? snapshotWeight;
  const analyticsDiscountRate = resultsContext?.discountRate ?? settings.discountRate;

  const displayResults = useMemo(() => {
    if (!results) return null;
    // In the light "View" bundle the per-component output series are stripped
    // (`outputs.series === null`) and fetched back on demand. Splice in any
    // we've hydrated for THIS run so per-asset analytics (assetDetails) derive
    // with data; the system charts read inline aggregates and don't need this.
    const baseOutputs = results.outputs;
    const canHydrate =
      !!baseOutputs && !baseOutputs.series &&
      !!hydratedRunSeries && hydratedRunSeries.runName === activeRunName &&
      Object.keys(hydratedRunSeries.series).length > 0;
    const effResults = canHydrate
      ? { ...results, outputs: { ...baseOutputs!, series: hydratedRunSeries!.series } }
      : results;
    // A normal solved run arrives with the full backend-derived analytics
    // (summary, carrierMix, …) attached; trust them as-is. A *reconstructed*
    // bundle — an imported project — carries only `outputs` and re-derives its
    // analytics on the client, so it must fall through to deriveRunResults even
    // when it isn't a pathway run. (Without this, KPI/summary cards read
    // `undefined.reduce` and crash.)
    const hasDerivedSummary = Array.isArray(effResults.summary) && effResults.summary.length > 0;
    if (!effResults.outputs || (!effResults.pathway?.enabled && hasDerivedSummary)) {
      return withDerivedAssetDetails(analyticsModel, effResults, settings.currencySymbol);
    }
    const activePathway = effResults.pathway?.enabled ? effResults.pathway : null;
    const selectedPeriod: number | null = activePathway
      ? getDefaultSelectedPeriod({
        ...pathwayConfig,
        selectedPeriod: pathwayConfig.selectedPeriod ?? activePathway.selectedPeriod,
        periods: pathwayConfig.periods.length
          ? pathwayConfig.periods
          : activePathway.periods.map((period, index) => ({
            period,
            objectiveWeight: activePathway.summaries[index]?.objectiveWeight ?? 1,
            yearsWeight: activePathway.summaries[index]?.yearsWeight ?? 1,
          })),
      })
      : null;
    const derived = deriveRunResults(analyticsModel, effResults.outputs, {
      carbonPrice: analyticsCarbonPrice,
      currencySymbol: settings.currencySymbol,
      discountRate: analyticsDiscountRate,
      snapshotWeight: analyticsSnapshotWeight,
      narrative: effResults.narrative,
      selectedPeriod,
      pathway: activePathway ? { ...activePathway, selectedPeriod } : null,
      rolling: effResults.rolling,
    });
    return {
      ...effResults,
      ...derived,
      pluginAnalytics: effResults.pluginAnalytics,
      meritOrder: effResults.meritOrder,
      co2Shadow: effResults.co2Shadow,
      // Backend-provided (deriveRunResults doesn't recompute it); preserve it
      // through the merge like meritOrder/co2Shadow so it survives for pathway
      // and reconstructed bundles that carry it.
      generatorEconomics: effResults.generatorEconomics,
      appliedConstraints: effResults.appliedConstraints,
      emissionsBreakdown: effResults.emissionsBreakdown,
      outputs: effResults.outputs,
      pathway: derived.pathway,
      runMeta: derived.runMeta,
    };
  }, [results, analyticsModel, settings.currencySymbol, analyticsDiscountRate, analyticsCarbonPrice, analyticsSnapshotWeight, pathwayConfig, hydratedRunSeries, activeRunName]);

  // Hydrate the active run's stripped per-component output series ON DEMAND.
  // The light "View" bundle ships `outputs.series = null` to render instantly;
  // per-asset analytics need the real series. Fetch ONLY the sheets the
  // displayed dashboard needs, each at the MAX window its charts ask for
  // (`neededRunWindows`, driven by each chart's gear) — pulling + client-
  // deriving the whole bundle on every view froze the tab on large runs.
  // System-only layouts need nothing, so the common result view does zero work
  // here. Fetched sheets merge into a per-run cache; revisiting is free.
  useEffect(() => {
    const outputs = results?.outputs;
    if (!outputs || outputs.series || !activeRunName) return;
    const sheets = Object.keys(neededRunWindows);
    if (sheets.length === 0) return;
    // Per sheet, the snapshot count the layout needs loaded. Fetch a sheet only
    // when it's absent OR cached at a SHORTER window than now requested (then
    // refetch longer — the longer series covers shorter-window charts, which
    // clamp their display down to their own slider range).
    const available = new Set(outputs.seriesSheets ?? []);
    const cache = hydratedRunSeries?.runName === activeRunName ? hydratedRunSeries : null;
    const toFetch: Array<{ sheet: string; end: number }> = [];
    for (const sheet of sheets) {
      if (!available.has(sheet)) continue;
      const end = neededRunWindows[sheet];
      const cachedEnd = cache?.ends[sheet];
      if (!cache || !(sheet in cache.series) || cachedEnd === undefined || cachedEnd < end) {
        toFetch.push({ sheet, end });
      }
    }
    if (toFetch.length === 0) return;
    const runName = activeRunName;
    let cancelled = false;
    void fetchRunOutputSeriesWindows(runName, toFetch)
      .then((fetched) => {
        if (cancelled) return;
        setHydratedRunSeries((prev) => {
          const same = prev?.runName === runName ? prev : null;
          const series = { ...(same?.series ?? {}), ...fetched };
          const ends = { ...(same?.ends ?? {}) };
          for (const { sheet, end } of toFetch) if (sheet in fetched) ends[sheet] = end;
          return { runName, series, ends };
        });
      })
      .catch(() => { /* leave per-asset charts empty — system charts still render */ });
    return () => { cancelled = true; };
  }, [results, activeRunName, neededRunWindows, hydratedRunSeries]);

  const captureCurrentScenario = useCallback((overrides: Partial<ScenarioPreset> = {}): ScenarioPreset => (
    buildScenarioPreset({
      id: overrides.id,
      label: overrides.label,
      notes: overrides.notes,
      snapshotStart,
      snapshotEnd,
      snapshotWeight,
      carbonPrice,
      carbonPriceSchedule,
      discountRate: settings.discountRate,
      forceLp,
      enableLoadShedding: settings.enableLoadShedding,
      loadSheddingCost: settings.loadSheddingCost,
      pathwayConfig: {
        ...pathwayConfig,
        selectedPeriod: getDefaultSelectedPeriod(pathwayConfig),
      },
      rollingConfig: normalizeRollingConfig(rollingConfig),
      samplingConfig: normalizeSamplingConfig(samplingConfig),
      stochasticConfig,
      securityConstrainedConfig: sclopfConfig,
      powerFlowConfig,
      contingencyConfig,
      mgaConfig,
      merchantConfig,
      ownerColumn,
      financeConfig,
      constraints,
    })
  ), [
    snapshotStart,
    snapshotEnd,
    snapshotWeight,
    carbonPrice,
    carbonPriceSchedule,
    settings.discountRate,
    settings.enableLoadShedding,
    settings.loadSheddingCost,
    forceLp,
    pathwayConfig,
    rollingConfig,
    samplingConfig,
    stochasticConfig,
    sclopfConfig,
    powerFlowConfig,
    contingencyConfig,
    mgaConfig,
    merchantConfig,
    ownerColumn,
    financeConfig,
    constraints,
  ]);

  const activeScenario = useMemo(
    () => scenarioCatalog.scenarios.find((scenario) => scenario.id === scenarioCatalog.activeScenarioId) ?? null,
    [scenarioCatalog],
  );

  const scenarioDirty = useMemo(() => {
    if (!activeScenario) return false;
    return JSON.stringify(captureCurrentScenario({
      id: activeScenario.id,
      label: activeScenario.label,
      notes: activeScenario.notes,
    })) !== JSON.stringify(activeScenario);
  }, [activeScenario, captureCurrentScenario]);

  const resetForNewModel = useCallback((nextModel: WorkbookModel, name?: string, opts?: { pushToSession?: boolean }) => {
    // The backend session is the source of truth for the working model. Every
    // load path funnels through here, so mirror the model into the session once
    // per load (not per edit — that per-keystroke full-model serialisation is
    // what spiked the heap). Skip when we are *restoring from* the session on
    // boot (the model is already there).
    // Single choke point: every temporal sheet in the incoming model becomes
    // ISO-`T` with `snapshot` leading, no matter which path the model came in
    // through (workbook import, project import, demo, plugin preview, history
    // restore, …). Idempotent — a second call on already-canonical data is a
    // no-op, so callers that pre-normalise with a project-specific dateFormat
    // (e.g. handleImportProject) stay correct.
    normalizeInputDatesToIso(nextModel, settings.dateFormat);
    // Resolve the model's OWN active scenario up front — it both names the working
    // file and is mirrored into the session meta so the topbar and the backend
    // record agree. Use the imported scenario (null when the model carried none),
    // NOT the synthetic "Base case" fallback, so a scenario-less model → "untitled".
    const nextScenarioCatalog = readScenarioCatalogFromModel(nextModel);
    const activeImportedScenario = nextScenarioCatalog.scenarios.find(
      (scenario) => scenario.id === nextScenarioCatalog.activeScenarioId,
    ) ?? null;
    // The working-model name is ALWAYS `{scenario||untitled}_{ISO-T}.xlsx`. A fresh
    // load (import/build/demo/open) mints the name now; a RESTORE (boot, stored
    // run — `pushToSession:false`) keeps the name it was saved under, so the stamp
    // reflects when the model was created, not when it reloaded.
    const isRestore = opts?.pushToSession === false;
    const builtFilename = isRestore && name && name.trim()
      ? name
      : scenarioFilename(activeImportedScenario?.label);
    // Push the FULL (normalised) model to the backend session — the source of
    // truth. Done once per load (not per edit). Skipped when restoring FROM the
    // session on boot (it's already there).
    if (opts?.pushToSession !== false) {
      void putSessionModel(nextModel, {
        filename: builtFilename,
        scenarioName: activeImportedScenario?.label ?? '',
      }).catch(() => { /* best-effort */ });
    }
    const snapshotMax = snapshotMaxFromWorkbook(nextModel.snapshots);
    const nextPathway = readPathwayConfigFromModel(nextModel);
    const nextRolling = readRollingConfigFromModel(nextModel);
    const nextSampling = readSamplingConfigFromModel(nextModel);
    setCustomDsl(readCustomDslFromModel(nextModel));
    setCarbonLibrary(readCarbonLibraryFromModel(nextModel));
    setMaxSnapshots(snapshotMax);
    setSnapshotEnd(snapshotMax);
    setSnapshotStart(RUN_WINDOW.initialSnapshotStart);
    // React holds only the small static sheets; the heavy time-series stay in
    // the backend session and are paged into the grid on demand. Record the
    // incoming model's series-sheet row counts so the Model tree still lists
    // them (and the table can lazy-load them) even though they're stripped here.
    const incomingSeriesCounts: Record<string, number> = {};
    for (const [sheetName, rows] of Object.entries(nextModel)) {
      if (isSeriesSheet(sheetName) && Array.isArray(rows) && rows.length > 0) {
        incomingSeriesCounts[sheetName] = rows.length;
      }
    }
    setSessionSeriesCounts(incomingSeriesCounts);
    setModel(stripSeriesSheets(nextModel));
    setResults(null);
    setResultsModel(null);
    setResultsContext(null);
    setHydratedRunSeries(null);
    // Run history is session-scoped: it survives model swaps (new/demo/workbook/
    // project open) so prior runs stay available for comparison, and is only
    // emptied when the user clicks "Clear all" or reloads/closes Ragnarok (the
    // list lives in in-memory React state and is never persisted). Each entry
    // carries its own topology + results snapshot, so it stays self-contained
    // even after the live model is replaced. Do NOT clear it here.
    setChartSections([]);
    setValidateResult(null);
    setAnalyticsFocus({ type: 'system' });
    const fallbackPathway = {
      ...nextPathway,
      selectedPeriod: getDefaultSelectedPeriod(nextPathway),
    };
    const fallbackRolling = normalizeRollingConfig(nextRolling);
    const fallbackSampling = normalizeSamplingConfig(nextSampling);
    const fallbackScenarioCatalog = defaultScenarioCatalog({
      snapshotStart: RUN_WINDOW.initialSnapshotStart,
      snapshotEnd: snapshotMax,
      snapshotWeight,
      carbonPrice,
      carbonPriceSchedule,
      discountRate: settings.discountRate,
      forceLp,
      enableLoadShedding: settings.enableLoadShedding,
      loadSheddingCost: settings.loadSheddingCost,
      pathwayConfig: fallbackPathway,
      rollingConfig: fallbackRolling,
      samplingConfig: fallbackSampling,
      stochasticConfig,
      securityConstrainedConfig: sclopfConfig,
      powerFlowConfig,
      contingencyConfig,
      mgaConfig,
      merchantConfig,
      ownerColumn,
      financeConfig,
      constraints,
    });
    const catalogToApply = nextScenarioCatalog.scenarios.length > 0
      ? nextScenarioCatalog
      : fallbackScenarioCatalog;
    const activeScenarioToApply = activeImportedScenario
      ?? catalogToApply.scenarios.find((scenario) => scenario.id === catalogToApply.activeScenarioId)
      ?? null;

    if (activeScenarioToApply) {
      setSnapshotStart(activeScenarioToApply.snapshotStart);
      setSnapshotEnd(activeScenarioToApply.snapshotEnd);
      setSnapshotWeight(activeScenarioToApply.snapshotWeight);
      setCarbonPrice(activeScenarioToApply.carbonPrice);
      setForceLp(activeScenarioToApply.forceLp);
      setConstraints(activeScenarioToApply.constraints.map((row) => ({ ...row })));
      updateSettings({
        discountRate: activeScenarioToApply.discountRate,
        enableLoadShedding: activeScenarioToApply.enableLoadShedding,
        loadSheddingCost: activeScenarioToApply.loadSheddingCost,
      });
      setPathwayConfig({
        ...activeScenarioToApply.pathwayConfig,
        selectedPeriod: getDefaultSelectedPeriod(activeScenarioToApply.pathwayConfig),
      });
      setRollingConfig(normalizeRollingConfig(activeScenarioToApply.rollingConfig));
      setSamplingConfig(normalizeSamplingConfig(activeScenarioToApply.samplingConfig ?? fallbackSampling));
    } else {
      setPathwayConfig(fallbackPathway);
      setRollingConfig(fallbackRolling);
      setSamplingConfig(fallbackSampling);
    }
    setScenarioCatalog(catalogToApply);
    setFilename(builtFilename);
  }, [
    snapshotWeight,
    carbonPrice,
    carbonPriceSchedule,
    settings.dateFormat,
    settings.discountRate,
    settings.enableLoadShedding,
    settings.loadSheddingCost,
    forceLp,
    stochasticConfig,
    sclopfConfig,
    powerFlowConfig,
    contingencyConfig,
    mgaConfig,
    merchantConfig,
    ownerColumn,
    financeConfig,
    constraints,
    updateSettings,
    setAnalyticsFocus,
  ]);

  const prepareModelForBackend = useCallback((source: WorkbookModel): WorkbookModel => {
    const cloned = structuredClone(source);
    normalizeInputDatesToIso(cloned, settings.dateFormat);
    return cloned;
  }, [settings.dateFormat]);

  // Forge → network clustering. Sync the working model to the session (same as a
  // run — the browser holds only static sheets, the backend keeps the series),
  // then ask the backend to reduce it. Returns the reduced model for preview.
  const handleClusterPreview = useCallback(
    async (nClusters: number, method: string): Promise<ClusterResult> => {
      await putStaticModel(prepareModelForBackend(model));
      const resp = await fetch(`${API_BASE}/api/transform/cluster`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sessionId: DEFAULT_SESSION_ID, nClusters, method }),
      });
      if (!resp.ok) {
        throw new Error((await resp.text()) || `Clustering failed (HTTP ${resp.status})`);
      }
      return (await resp.json()) as ClusterResult;
    },
    [model, prepareModelForBackend],
  );

  // Apply a previewed clustering: the reduced topology becomes the new working
  // model (it's a different network, so a full replace, not a sheet merge).
  const handleClusterApply = useCallback(
    (clustered: WorkbookModel) => {
      resetForNewModel(clustered);
      setActiveRunName(null);
      showToast('Network reduced — clustered model loaded into the editor', 'success');
    },
    [resetForNewModel],
  );

  // Guard against accidental session loss on browser back / forward / refresh /
  // close. The workbook lives only in memory and there is no client-side
  // router, so a stray back-swipe (the macOS trackpad gesture) unloads the app
  // and resets it to the empty Welcome state, orphaning any running solve.
  // While a run is in progress OR a model is loaded, ask the browser to confirm
  // before unloading: clicking "Stay" cancels the navigation and keeps the
  // model and the solve intact. The dialog is browser-native (its wording is
  // fixed by the browser) and only armed when there is work to protect, so the
  // empty Welcome screen never prompts.
  useEffect(() => {
    const hasWork =
      queueJobs.length > 0 || SHEETS.some((sheet) => (model[sheet]?.length ?? 0) > 0);
    if (!hasWork) return undefined;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = ''; // Chrome/Edge require returnValue to be set to prompt.
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [queueJobs.length, model]);

  const [filename, setFilename] = useState('ragnarok_case.xlsx');
  // The working-file name ALWAYS tracks the ACTIVE scenario
  // (`{scenario}_{ISO-T}.xlsx`) — not just at model load. Creating, renaming or
  // switching the active scenario mints a fresh name; when the current name
  // already carries this scenario's stem it is kept, so the timestamp stays the
  // creation time (reloads/restores don't re-stamp).
  useEffect(() => {
    const label = activeScenario?.label?.trim();
    if (!label) return;
    setFilename((current) => (filenameMatchesScenario(current, label) ? current : scenarioFilename(label)));
  }, [activeScenario?.label]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const projectImportInputRef = useRef<HTMLInputElement | null>(null);
  const resultImportInputRef = useRef<HTMLInputElement | null>(null);

  // No workbook is auto-loaded — the user must explicitly Open a file or
  // Import Project. This avoids surprising the user with someone else's data
  // and keeps assumptions out of the empty starting state.

  useEffect(() => {
    setCarrierColorOverrides(model.carriers ?? []);
  }, [model.carriers]);

  // Config writes land in RAGNAROK_* model sheets; when one actually changes,
  // request a static-merge resync so the backend session (the source of truth)
  // carries the new config too — not just the in-memory mirror.
  useEffect(() => {
    setModel((current) => {
      const next = writePathwayConfigToModel(current, pathwayConfig);
      if (samePathwayConfig(readPathwayConfigFromModel(current), pathwayConfig)) return current;
      requestStaticResync();
      return next;
    });
  }, [pathwayConfig, requestStaticResync]);

  useEffect(() => {
    setModel((current) => {
      const next = writeRollingConfigToModel(current, rollingConfig);
      if (sameRollingConfig(readRollingConfigFromModel(current), rollingConfig)) return current;
      requestStaticResync();
      return next;
    });
  }, [rollingConfig, requestStaticResync]);

  useEffect(() => {
    setModel((current) => {
      const next = writeSamplingConfigToModel(current, samplingConfig);
      if (sameSamplingConfig(readSamplingConfigFromModel(current), samplingConfig)) return current;
      requestStaticResync();
      return next;
    });
  }, [samplingConfig, requestStaticResync]);

  useEffect(() => {
    setModel((current) => {
      if (readCustomDslFromModel(current) === customDsl) return current;
      requestStaticResync();
      return writeCustomDslToModel(current, customDsl);
    });
  }, [customDsl, requestStaticResync]);

  useEffect(() => {
    setModel((current) => {
      const next = writeScenarioCatalogToModel(current, scenarioCatalog);
      if (sameScenarioCatalog(readScenarioCatalogFromModel(current), scenarioCatalog)) return current;
      requestStaticResync();
      return next;
    });
  }, [scenarioCatalog, requestStaticResync]);

  // Persist the carbon-schedule library into its model sheet (travels with export).
  useEffect(() => {
    setModel((current) => {
      const next = writeCarbonLibraryToModel(current, carbonLibrary);
      if (sameCarbonLibrary(readCarbonLibraryFromModel(current), carbonLibrary)) return current;
      requestStaticResync();
      return next;
    });
  }, [carbonLibrary, requestStaticResync]);

  // ── Session persistence (IndexedDB) ─────────────────────────────────────
  // Restore the last working session on load, then auto-save it as it changes,
  // so a plain reload remembers everything (model + carbon library + scenarios
  // + run controls). Only the Clear button wipes it.
  const sessionRestoredRef = useRef(false);
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        // Controls (small) still come from IndexedDB; the heavy model is
        // rehydrated from the backend session (the source of truth) instead.
        // Use the controls-only loader so we never deserialise a stale heavy
        // model record from IndexedDB on boot.
        const controls = await loadSessionControls();
        // Rehydrate only the small static sheets; series stay in the backend and
        // are paged into the grid on demand (keeps boot light).
        const savedModel = await getSessionFullModel({ staticOnly: true }).catch(() => null);
        const hasRows = !!savedModel && Object.values(savedModel).some((rows) => Array.isArray(rows) && rows.length > 0);
        if (!cancelled && savedModel && hasRows) {
          // Already in the session — don't push it straight back.
          resetForNewModel(savedModel, controls?.filename, { pushToSession: false });
          // Static rehydrate drops series; learn them from the session meta so
          // the Model tree lists the temporal sheets (paged into the grid on
          // demand) instead of hiding them.
          try {
            const sessionMeta = await getSessionMeta();
            if (!cancelled) setSessionSeriesCounts(seriesSheetCounts(sessionMeta));
          } catch { /* tree just won't list series until next load */ }
          if (controls) {
            setCarbonPrice(controls.carbonPrice);
            setCarbonPriceSchedule((controls.carbonPriceSchedule ?? []).map((r) => ({ ...r })));
            setSnapshotWeight(controls.snapshotWeight);
            setSnapshotStart(controls.snapshotStart);
            setSnapshotEnd(controls.snapshotEnd);
            setForceLp(controls.forceLp);
            if (controls.constraints) setConstraints(controls.constraints);
            // Re-apply the last live rolling/pathway AFTER resetForNewModel, so a
            // restored scenario's defaults can't quietly flip them back.
            if (controls.rollingConfig) setRollingConfig(normalizeRollingConfig(controls.rollingConfig));
            if (controls.samplingConfig) setSamplingConfig(normalizeSamplingConfig(controls.samplingConfig));
            if (controls.pathwayConfig) setPathwayConfig(controls.pathwayConfig);
          }
          setStatus('Restored your last session.');
          // Transient: clear the boot notice after a few seconds so it doesn't
          // sit in the topbar forever (the next real action sets its own status).
          window.setTimeout(() => { if (!cancelled) setStatus(''); }, 6000);
        }
      } finally {
        if (!cancelled) sessionRestoredRef.current = true;
      }
    })();
    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // NOTE: the heavy model is NO LONGER mirrored into the browser's IndexedDB.
  // Repeatedly structured-cloning a full-year, multi-region workbook on every
  // edit was a prime driver of the multi-GB heap. The backend session is now the
  // source of truth (mirrored on load via resetForNewModel and before every run);
  // the editor rehydrates from it on boot. Only the small run controls persist
  // client-side below.

  // Persist the lightweight run controls separately — cheap, so a shorter debounce.
  useEffect(() => {
    if (!sessionRestoredRef.current) return undefined;
    const id = window.setTimeout(() => {
      void saveSessionControls({
        filename, carbonPrice, carbonPriceSchedule,
        snapshotStart, snapshotEnd, snapshotWeight, forceLp,
        constraints, rollingConfig, samplingConfig, pathwayConfig,
        savedAt: Date.now(),
      });
    }, 400);
    return () => window.clearTimeout(id);
  }, [filename, carbonPrice, carbonPriceSchedule, snapshotStart, snapshotEnd, snapshotWeight, forceLp, constraints, rollingConfig, samplingConfig, pathwayConfig]);

  // Structural static-model changes (column ops, clear, reorder, undo/redo)
  // have no row-op equivalent — they request ONE static-merge resync here.
  // Cell/row edits never come through this path (they PATCH precise ops).
  useEffect(() => {
    if (staticResyncTick === 0) return undefined;
    const id = window.setTimeout(() => {
      void putStaticModel(prepareModelForBackend(modelRef.current)).catch(() => { /* best-effort */ });
    }, 300);
    return () => window.clearTimeout(id);
  }, [staticResyncTick, prepareModelForBackend]);

  // Run history lives entirely on the backend (the single source of truth) —
  // see `refreshBackendRuns` / `backendRuns` below. There is no browser-side
  // history store anymore.

  const bounds = useMemo(() => getBounds(model), [model.buses]);  // eslint-disable-line react-hooks/exhaustive-deps
  const busIndex = useMemo(() => getBusIndex(model), [model.buses]);  // eslint-disable-line react-hooks/exhaustive-deps
  // Carbon-readiness of the current model: how many generators use an emitting
  // carrier (co2_emissions > 0). Drives the "Apply to model" pre-check — a
  // carbon price has no effect without emitting generators.
  const carbonCheck = useMemo(() => {
    const carriers = model.carriers ?? [];
    const co2 = new Map<string, number>();
    let hasCo2Column = false;
    for (const c of carriers) {
      if ('co2_emissions' in c) hasCo2Column = true;
      const name = stringValue(c.name).trim();
      if (name) co2.set(name, numberValue(c.co2_emissions));
    }
    const generators = model.generators ?? [];
    let emittingGenerators = 0;
    for (const g of generators) {
      const carrier = stringValue(g.carrier).trim();
      if (carrier && (co2.get(carrier) ?? 0) > 0) emittingGenerators += 1;
    }
    return { emittingGenerators, hasCo2Column, totalGenerators: generators.length };
  }, [model.carriers, model.generators]);
  // Distinct values of the chosen owner column across generators + storage —
  // drives the merchant (price-taker) owner picker. The column is user-chosen
  // (e.g. `owner`, `Company`) and authored in the Model grid.
  const merchantOwners = useMemo(() => {
    const col = (ownerColumn || 'owner').trim() || 'owner';
    const seen: string[] = [];
    for (const row of [...(model.generators ?? []), ...(model.storage_units ?? [])]) {
      const owner = stringValue(row[col]).trim();
      if (owner && !seen.includes(owner)) seen.push(owner);
    }
    return seen;
  }, [model.generators, model.storage_units, ownerColumn]);
  // Map geometry for the analytics view follows the results-owning topology.
  const analyticsBounds = useMemo(() => getBounds(analyticsModel), [analyticsModel.buses]);  // eslint-disable-line react-hooks/exhaustive-deps
  const analyticsBusIndex = useMemo(() => getBusIndex(analyticsModel), [analyticsModel.buses]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    // Reset focus to 'system' when results disappear or the previously-focused
    // asset is no longer present. Guarded so we never call setState if the
    // focus is already 'system' (otherwise a new {type:'system'} object would
    // trigger an infinite re-render loop on every effect tick).
    if (analyticsFocus.type === 'system') return;
    if (!displayResults) { setAnalyticsFocus({ type: 'system' }); return; }
    if (analyticsFocus.type === 'generator' && displayResults.assetDetails.generators[analyticsFocus.key]) return;
    if (analyticsFocus.type === 'bus' && displayResults.assetDetails.buses[analyticsFocus.key]) return;
    if (analyticsFocus.type === 'storageUnit' && displayResults.assetDetails.storageUnits[analyticsFocus.key]) return;
    if (analyticsFocus.type === 'store' && displayResults.assetDetails.stores[analyticsFocus.key]) return;
    if (analyticsFocus.type === 'branch' && displayResults.assetDetails.branches[analyticsFocus.key]) return;
    setAnalyticsFocus({ type: 'system' });
  }, [displayResults, analyticsFocus, setAnalyticsFocus]);

  const applyScenarioPreset = useCallback((scenario: ScenarioPreset) => {
    setScenarioCatalog((current) => ({
      ...current,
      activeScenarioId: scenario.id,
    }));
    const nextEnd = Math.max(1, Math.min(maxSnapshots, scenario.snapshotEnd));
    const nextStart = Math.max(0, Math.min(scenario.snapshotStart, nextEnd - 1));
    setSnapshotStart(nextStart);
    setSnapshotEnd(nextEnd);
    setSnapshotWeight(scenario.snapshotWeight);
    setCarbonPrice(scenario.carbonPrice);
    setCarbonPriceSchedule((scenario.carbonPriceSchedule ?? []).map((row) => ({ ...row })));
    setForceLp(scenario.forceLp);
    setConstraints(scenario.constraints.map((row) => ({ ...row })));
    updateSettings({
      discountRate: scenario.discountRate,
      enableLoadShedding: scenario.enableLoadShedding,
      loadSheddingCost: scenario.loadSheddingCost,
    });
    setPathwayConfig({
      ...scenario.pathwayConfig,
      selectedPeriod: getDefaultSelectedPeriod(scenario.pathwayConfig),
    });
    setRollingConfig(normalizeRollingConfig(scenario.rollingConfig));
    // Presets saved before these modes were captured normalize to disabled —
    // applying a preset restores the FULL run configuration either way.
    setSamplingConfig(normalizeSamplingConfig(scenario.samplingConfig ?? defaultSamplingConfig()));
    setStochasticConfig(scenario.stochasticConfig ?? { enabled: false, scenarios: [] });
    setSclopfConfig(scenario.securityConstrainedConfig ?? { enabled: false });
    setPowerFlowConfig(scenario.powerFlowConfig ?? { enabled: false, linear: false });
    setContingencyConfig(scenario.contingencyConfig ?? { enabled: false });
    setMgaConfig(scenario.mgaConfig ?? { enabled: false, slack: 0.05, carriers: [] });
    setMerchantConfig(scenario.merchantConfig ?? { enabled: false, owner: '', priceSource: 'lmp', flatPrice: 0 });
    setOwnerColumn(scenario.ownerColumn ?? 'owner');
    setFinanceConfig(scenario.financeConfig ?? { gearing: 0, interestRate: 0.05, tenorYears: 15 });
    setStatus(`Applied scenario: ${scenario.label}`);
    showToast(`Scenario applied: ${scenario.label}`, 'success');
  }, [maxSnapshots, showToast, updateSettings]);

  const handleImport = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const nextModel = await parseWorkbook(file);
      normalizeInputDatesToIso(nextModel, settings.dateFormat);
      resetForNewModel(nextModel, file.name || 'ragnarok_case.xlsx');
      setFileHandle(null);
      setStatus(`Imported workbook: ${file.name}. Analytics will populate after the next run.`);
      showToast(`Opened ${file.name}`, 'success');
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Workbook import failed.';
      setStatus(msg);
      showToast(msg, 'error');
    } finally {
      if (event.target) event.target.value = '';
    }
  };

  const handleImportProject = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    // Progress feedback (mirrors the export flow): a persistent topbar status +
    // a bottom-right toast, since parsing a full-year project takes a moment.
    setStatus(`Importing ${file.name}…`);
    showToast(`Importing ${file.name} — this can take a moment for a full run.`, 'info');
    try {
      // Importing a project is OPENING A FILE — load its model + solved results
      // into the editor (like File→Open). It does NOT create a History entry:
      // History is an audit trail of solves + explicit result imports, not of
      // files the user opened. Re-run the loaded model to put it in History.
      // The backend parses the project (.zip / .xlsx) and returns the bundle
      // WITHOUT persisting; the heavy load-into-editor happens client-side.
      const form = new FormData();
      form.append('file', file);
      const resp = await fetch(`${API_BASE}/api/import/project/load`, { method: 'POST', body: form });
      if (!resp.ok) {
        throw new Error((await resp.text()) || `Import failed (HTTP ${resp.status})`);
      }
      const bundle = (await resp.json()) as {
        model?: WorkbookModel;
        scenario?: { constraints?: CustomConstraint[]; carbonPrice?: number; discountRate?: number };
        options?: { snapshotStart?: number; snapshotEnd?: number; snapshotWeight?: number };
        result?: RunResults;
        filename?: string;
      };
      const importedModel = bundle.model;
      // Input dates land canonical (ISO) for Ragnarok-exported projects; a
      // hand-built workbook may not — normalise before loading, as the CSV /
      // netCDF import paths do.
      if (importedModel) normalizeInputDatesToIso(importedModel, settings.dateFormat);
      handleRestoreRun(
        {
          label: bundle.filename || file.name,
          results: (bundle.result ?? {}) as RunResults,
          model: importedModel,
          carbonPrice: bundle.scenario?.carbonPrice ?? 0,
          discountRate: bundle.scenario?.discountRate,
          snapshotStart: bundle.options?.snapshotStart ?? 0,
          snapshotEnd: bundle.options?.snapshotEnd ?? 0,
          snapshotWeight: bundle.options?.snapshotWeight ?? 1,
        },
        { loadIntoEditor: true },
      );
      // No backing stored run — clear the active-run pin so Export Project falls
      // back to the live {model, result} path and Comparison won't highlight a
      // run that doesn't exist.
      setActiveRunName(null);
      // Restore the project's custom constraints so a re-run uses them.
      const importedConstraints = bundle.scenario?.constraints;
      if (Array.isArray(importedConstraints)) {
        setConstraints(importedConstraints);
      }
      setStatus(`Imported project: ${file.name} — loaded into the editor.`);
      showToast(`Project loaded (${file.name})`, 'success');
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Project import failed.';
      setStatus(msg);
      showToast(msg, 'error');
    } finally {
      if (event.target) event.target.value = '';
    }
  };

  const handleImportResultXlsx = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    if (event.target) event.target.value = '';
    if (files.length === 0) return;
    // Show a "Converting…" placeholder per file in History immediately — the
    // backend parse + analytics derivation + db build takes tens of seconds for
    // a full-year result, and a silent wait reads as "nothing happened".
    setConvertingImports((prev) => [...prev, ...files.map((f) => f.name)]);

    // Import each result-bearing file as a persistent History entry. Accepts a
    // Ragnarok project .zip / embedded-bundle .xlsx (full model + results
    // round-trip verbatim) OR a bare results .xlsx (analytics derived from the
    // stored outputs). Unlike Import Project (which only loads into the editor),
    // this writes to the run store, so each entry is permanent. Files are
    // imported sequentially so one slow conversion can't stall the others'
    // placeholders; a per-file failure is reported but doesn't abort the batch.
    let lastImported: string | null = null;
    let ok = 0;
    for (const file of files) {
      setStatus(`Converting ${file.name}…`);
      try {
        const form = new FormData();
        form.append('file', file);
        const resp = await fetch(`${API_BASE}/api/import/result`, { method: 'POST', body: form });
        if (!resp.ok) {
          throw new Error((await resp.text()) || `Import failed (HTTP ${resp.status})`);
        }
        const { name } = (await resp.json()) as { name?: string };
        if (name) lastImported = name;
        ok += 1;
        showToast(`Result imported (${file.name})`, 'success');
      } catch (error) {
        const msg = error instanceof Error ? error.message : 'Result import failed.';
        setStatus(`${file.name}: ${msg}`);
        showToast(`${file.name}: ${msg}`, 'error');
      } finally {
        setConvertingImports((prev) => prev.filter((n) => n !== file.name));
      }
    }

    await refreshBackendRuns();
    // Open the last successfully imported run so the user lands on a result.
    if (lastImported) {
      await handleOpenBackendRun(lastImported);
      setTab('Analytics');
      setAnalyticsSubTab('Result');
    }
    if (ok > 0) {
      setStatus(
        files.length === 1
          ? `Imported result: ${files[0].name} — stored in History.`
          : `Imported ${ok} of ${files.length} results — stored in History.`,
      );
    }
  };

  const handleExportProject = async () => {
    // Export the currently viewed run as a Ragnarok Project package (.zip): the
    // canonical JSON bundle (lossless, re-importable) + a readable xlsx. Built
    // SERVER-SIDE so the heavy build never OOMs the tab.
    //
    // When the view IS a stored run (the common case after a solve or a History
    // open), stream its package straight from the canonical bundle on disk — so
    // NOTHING is dropped and it re-imports identically. Only an unsaved,
    // never-run model falls back to POSTing the live {model, result}.
    if (activeRunName) {
      window.open(`${API_BASE}/api/runs/${encodeURIComponent(activeRunName)}/package`, '_blank');
      showToast('Project exported (.zip from stored run)', 'success');
      return;
    }
    const out = `${projectBaseName(filename)}_project.zip`;
    try {
      const resp = await fetch(`${API_BASE}/api/export/project`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: analyticsModel, result: displayResults ?? {} }),
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || `Export failed (HTTP ${resp.status})`);
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = out;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 0);
      const successMsg = displayResults?.outputs
        ? 'Project (inputs + solved outputs) exported'
        : 'Project (inputs only) exported';
      showToast(`${successMsg} → ${out}`, 'success');
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Export failed.';
      setStatus(msg);
      showToast(msg, 'error');
    }
  };


  const csvFolderImportInputRef = useRef<HTMLInputElement | null>(null);
  const netcdfImportInputRef = useRef<HTMLInputElement | null>(null);
  const hdf5ImportInputRef = useRef<HTMLInputElement | null>(null);

  async function exportViaBackend(endpoint: string, filenameOut: string): Promise<void> {
    const scenarioForExport = {
      constraints: constraints.filter((c) => c.enabled),
      constraintSpecs: dslToSpecs(customDsl),
      carbonPrice,
      discountRate: settings.discountRate,
    };
    const modelForBackend = prepareModelForBackend(model);
    try {
      const resp = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelForBackend, scenario: scenarioForExport, options: {} }),
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || `Export failed (HTTP ${resp.status})`);
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filenameOut;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast(`Exported ${filenameOut}`, 'success');
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Export failed.';
      setStatus(msg);
      showToast(msg, 'error');
    }
  }

  async function importViaBackend(endpoint: string, file: File): Promise<void> {
    try {
      const form = new FormData();
      form.append('file', file);
      const resp = await fetch(`${API_BASE}${endpoint}`, { method: 'POST', body: form });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || `Import failed (HTTP ${resp.status})`);
      }
      const json = await resp.json();
      const nextModel = json.model as WorkbookModel;
      normalizeInputDatesToIso(nextModel, settings.dateFormat);
      resetForNewModel(nextModel, file.name.replace(/\.(nc|h5|hdf5)$/i, '.xlsx'));
      setStatus(`Imported ${file.name}`);
      showToast(`Imported ${file.name}`, 'success');
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Import failed.';
      setStatus(msg);
      showToast(msg, 'error');
    }
  }

  const handleExportNetcdf = () =>
    exportViaBackend('/api/export/netcdf', `${projectBaseName(filename)}.nc`);
  const handleExportHdf5 = () =>
    exportViaBackend('/api/export/hdf5', `${projectBaseName(filename)}.h5`);

  const handleImportNetcdf = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file) await importViaBackend('/api/import/netcdf', file);
  };
  const handleImportHdf5 = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file) await importViaBackend('/api/import/hdf5', file);
  };

  const handleExportCsvFolder = async () => {
    const archive = `${projectBaseName(filename)}_csv_folder`;
    try {
      const { exportModelAsCsvFolderZip } = await import('lib/workbook/csvFolder');
      const blob = exportModelAsCsvFolderZip(model, archive);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${archive}.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast(`Exported PyPSA CSV folder to ${archive}.zip`, 'success');
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'CSV folder export failed.';
      setStatus(msg);
      showToast(msg, 'error');
    }
  };

  const handleImportCsvFolder = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const { importCsvFolderZip } = await import('lib/workbook/csvFolder');
      const { model: nextModel, unknownFiles, importedSheets } = await importCsvFolderZip(file);
      normalizeInputDatesToIso(nextModel, settings.dateFormat);
      resetForNewModel(nextModel, file.name.replace(/\.zip$/i, '.xlsx'));
      const note = unknownFiles.length
        ? ` (${unknownFiles.length} unknown file${unknownFiles.length === 1 ? '' : 's'} skipped)`
        : '';
      setStatus(`Imported ${importedSheets.length} sheet(s) from CSV folder${note}.`);
      showToast(`Imported PyPSA CSV folder: ${importedSheets.length} sheets${note}`, 'success');
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'CSV folder import failed.';
      setStatus(msg);
      showToast(msg, 'error');
    }
  };

  // ── Data view importer subsystem ───────────────────────────────────────
  // Called by DataView when the user clicks "Add to workbook" after picking
  // a database, country, and filters. Merges the fragment into the current
  // model (carriers union, name dedupe, provenance row appended).
  const handleApplyImportedFragment = useCallback(
    (fragment: WorkbookFragment, databaseName: string, countryName: string) => {
      pushHistory();
      // Merge once (deterministic), apply to the mirror, then push to the
      // session: static sheets via the merge resync; any SERIES sheets in the
      // fragment (e.g. demand profiles) are replaced sheet-by-sheet via PATCH
      // because static merges deliberately skip time-series.
      const merged = mergeWorkbookFragment(modelRef.current, fragment);
      setModel(merged);
      requestStaticResync();
      for (const sheet of Object.keys(fragment.sheets)) {
        if (!isSeriesSheet(sheet)) continue;
        const rows = (merged[sheet] as GridRow[] | undefined) ?? [];
        void (async () => {
          const previous = await getSheetPage(sheet, { offset: 0, limit: 0 })
            .then((page) => page.total)
            .catch(() => 0);
          await patchSheet(sheet, [
            ...(previous ? [{ op: 'deleteRows' as const, rows: Array.from({ length: previous }, (_, i) => i) }] : []),
            ...rows.map((r) => ({ op: 'addRow' as const, values: r as Record<string, unknown> })),
          ]);
        })().catch(() => { /* best-effort */ });
      }
      const counts = Object.entries(fragment.sheets)
        .map(([sheet, rows]) => `${rows.length} ${sheet}`)
        .join(', ');
      const note = counts ? ` (${counts})` : '';
      const msg = `Imported ${databaseName} for ${countryName}${note}`;
      setStatus(msg);
      showToast(msg, 'success');
    },
    [pushHistory, showToast, requestStaticResync],
  );

  const handleOpenWorkbook = async () => {
    const picker = (window as any).showOpenFilePicker;
    if (!picker) {
      fileInputRef.current?.click();
      return;
    }
    try {
      const [handle] = await picker({
        // Keep the "All Files" option so the OS open panel always has a
        // non-greyed escape hatch — macOS dims type-restricted files until it
        // finishes resolving each file's UTI / Gatekeeper quarantine, which on
        // first open can leave even valid .xlsx files unselectable.
        excludeAcceptAllOption: false,
        multiple: false,
        types: [{ description: 'Excel Workbook', accept: { 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'] } }],
      });
      const file = await handle.getFile();
      const nextModel = await parseWorkbook(file);
      normalizeInputDatesToIso(nextModel, settings.dateFormat);
      resetForNewModel(nextModel, file.name || 'ragnarok_case.xlsx');
      setFileHandle(handle);
      setStatus(`Opened workbook: ${file.name}`);
      showToast(`Opened ${file.name}`, 'success');
    } catch (error) {
      if ((error as Error)?.name !== 'AbortError') {
        setStatus('Workbook open failed.');
        showToast('Workbook open failed.', 'error');
      }
    }
  };

  const updateRowValue = (sheet: SheetName, rowIndex: number, key: string, value: Primitive) => {
    pushHistory();
    setModel((current) => {
      const nextRows = (current[sheet] ?? []).map((row, index) => (index === rowIndex ? { ...row, [key]: value } : row));
      return { ...current, [sheet]: nextRows };
    });
    pushStaticOps(sheet, [{ op: 'set', row: rowIndex, column: key, value }]);
  };

  // Atomic paste: grow the sheet by `extraRows` (seeded from the schema default)
  // then apply every edit, in a single state update so a multi-row Excel paste
  // lands as one undoable operation.
  const bulkPaste = (
    sheet: SheetName,
    edits: { rowIndex: number; col: string; val: Primitive }[],
    extraRows: number,
  ) => {
    if (edits.length === 0 && extraRows === 0) return;
    pushHistory();
    setModel((current) => {
      const base = current[sheet] ?? [];
      const grown = extraRows > 0
        ? [...base, ...Array.from({ length: extraRows }, () => ({ ...getDefaultRowForSheet(sheet) }))]
        : [...base];
      for (const { rowIndex, col, val } of edits) {
        if (rowIndex < 0 || rowIndex >= grown.length) continue;
        grown[rowIndex] = { ...grown[rowIndex], [col]: val };
      }
      return { ...current, [sheet]: grown };
    });
    pushStaticOps(sheet, [
      ...Array.from({ length: extraRows }, () => ({
        op: 'addRow' as const,
        values: { ...getDefaultRowForSheet(sheet) } as Record<string, unknown>,
      })),
      ...edits.map((e) => ({ op: 'set' as const, row: e.rowIndex, column: e.col, value: e.val })),
    ]);
    setStatus(`Pasted ${edits.length} cell${edits.length === 1 ? '' : 's'} into ${sheet}${extraRows > 0 ? ` (+${extraRows} rows)` : ''}.`);
  };

  const addRow = (sheet: SheetName) => {
    pushHistory();
    const defaults = getNewRowDefaults(sheet);
    setModel((current) => {
      const nextRows = [...(current[sheet] ?? []), { ...defaults }];
      return { ...current, [sheet]: nextRows };
    });
    pushStaticOps(sheet, [
      { op: 'addRow', values: { ...defaults } as Record<string, unknown> },
    ]);
    setStatus(`Added a new row to ${sheet}.`);
  };

  const deleteRow = (sheet: SheetName, rowIndex: number) => {
    pushHistory();
    setModel((current) => {
      const nextRows = current[sheet].filter((_, i) => i !== rowIndex);
      return { ...current, [sheet]: nextRows };
    });
    pushStaticOps(sheet, [{ op: 'deleteRows', rows: [rowIndex] }]);
    setStatus(`Removed row ${rowIndex + 1} from ${sheet}.`);
  };

  const reorderRow = (sheet: SheetName, fromIndex: number, toIndex: number) => {
    if (fromIndex === toIndex) return;
    pushHistory();
    setModel((current) => {
      const rows = current[sheet] ?? [];
      if (fromIndex < 0 || fromIndex >= rows.length || toIndex < 0 || toIndex >= rows.length) return current;
      const nextRows = [...rows];
      const [row] = nextRows.splice(fromIndex, 1);
      nextRows.splice(toIndex, 0, row);
      return { ...current, [sheet]: nextRows };
    });
    requestStaticResync(); // row order matters; no row-op equivalent
  };

  const addColumn = (sheet: SheetName, col: string, defaultValue: string | number | boolean) => {
    pushHistory();
    setModel((current) => {
      const nextRows = current[sheet].map((row) =>
        col in row ? row : { ...row, [col]: defaultValue },
      );
      return { ...current, [sheet]: nextRows };
    });
    requestStaticResync();
    setStatus(`Added column "${col}" to ${sheet}.`);
  };

  const deleteColumn = (sheet: SheetName, col: string) => {
    pushHistory();
    setModel((current) => {
      const nextRows = current[sheet].map((row) => {
        const { [col]: _removed, ...rest } = row as Record<string, Primitive>;
        return rest as GridRow;
      });
      return { ...current, [sheet]: nextRows };
    });
    requestStaticResync();
    setStatus(`Removed column "${col}" from ${sheet}.`);
  };

  const renameColumn = (sheet: SheetName, oldCol: string, newCol: string) => {
    if (!newCol || newCol === oldCol) return;
    pushHistory();
    setModel((current) => {
      const nextRows = current[sheet].map((row) => {
        const r = row as Record<string, Primitive>;
        if (!(oldCol in r)) return row;
        const { [oldCol]: val, ...rest } = r;
        return { ...rest, [newCol]: val } as GridRow;
      });
      return { ...current, [sheet]: nextRows };
    });
    requestStaticResync();
    setStatus(`Renamed column "${oldCol}" to "${newCol}" in ${sheet}.`);
  };

  const clearSheet = (sheet: SheetName) => {
    pushHistory();
    setModel((current) => ({ ...current, [sheet]: [] }));
    requestStaticResync(); // empties the sheet server-side too (merge writes [])
    setStatus(`Cleared all rows from ${sheet}.`);
  };

  // The subset of a fetched backend bundle that `handleRestoreRun` needs to
  // load a stored run back into the viewer. Built in `handleOpenBackendRun`.
  type RestorableRun = {
    label: string;
    results: RunResults;
    model?: WorkbookModel;
    carbonPrice: number;
    discountRate?: number;
    snapshotStart: number;
    snapshotEnd: number;
    snapshotWeight: number;
  };

  const handleRestoreRun = (entry: RestorableRun, opts?: { loadIntoEditor?: boolean; sessionAlreadyLoaded?: boolean }) => {
    // Older persisted entries may predate canonicalisation — re-canonicalise
    // the restored outputs in place so display/derivation see ISO-`T` + leading
    // `snapshot` consistently.
    if (entry.results.outputs?.series) {
      canonicalizeOutputSeries(entry.results.outputs.series, settings.dateFormat);
    }
    setResults(entry.results);
    // Pin analytics to the topology that produced this run. Legacy entries
    // (saved before per-run topology snapshots) carry no model → fall back to
    // the live model, preserving prior behaviour.
    setResultsModel(entry.model ?? null);
    // Pin pathway derivation inputs to this run's stored values so re-derived
    // KPIs match the run, not the live sliders. discountRate is optional on
    // older entries → fall back to the current setting.
    setResultsContext({
      carbonPrice: entry.carbonPrice,
      snapshotWeight: entry.snapshotWeight,
      discountRate: entry.discountRate ?? settings.discountRate,
    });
    // VIEW vs IMPORT. Plain "View results" must NOT clone the run's model into
    // the live editable state: that structuredClone (a full workbook) plus the
    // pushHistory() it triggers is the dominant browser-memory sink — viewing
    // several runs stacks many independent full-model copies on the undo stack.
    // Viewing only needs `resultsModel` (set above, by reference) to pin the
    // analytics topology. The heavy load-into-editor happens solely on explicit
    // "Import project" (loadIntoEditor), which is the path for edit + re-run.
    if (entry.model && opts?.loadIntoEditor) {
      pushHistory();
      const restoredModel = structuredClone(entry.model);
      setModel(restoredModel);
      // The session is the source of truth and runs submit by sessionId — push
      // the FULL restored model (incl. its time-series; a static merge would
      // leave the previous model's series in place and the next run would solve
      // a chimera). SKIP when the session ALREADY holds this model server-side
      // (the History "Import project" fast path promoted it DB→session, and
      // `entry.model` here is only the static topology) — re-pushing would wipe
      // the series.
      if (!opts?.sessionAlreadyLoaded) {
        void putSessionModel(restoredModel, { filename: entry.label ?? '' }).catch(() => { /* best-effort */ });
      }
      const snapshotMax = snapshotMaxFromWorkbook(restoredModel.snapshots);
      setMaxSnapshots(snapshotMax);
      setSnapshotStart(entry.snapshotStart);
      setSnapshotEnd(entry.snapshotEnd);
    }
    setSnapshotWeight(entry.snapshotWeight);
    setCarbonPrice(entry.carbonPrice);
    if (entry.discountRate !== undefined) updateSettings({ discountRate: entry.discountRate });
    setPathwayConfig((current) => entry.results.pathway?.enabled ? ({
      ...current,
      enabled: true,
      planningMode: 'pathway',
      periods: entry.results.pathway?.summaries?.map((row) => ({
        period: row.period,
        objectiveWeight: row.objectiveWeight,
        yearsWeight: row.yearsWeight,
      })) ?? current.periods,
      selectedPeriod: entry.results.pathway?.selectedPeriod ?? current.selectedPeriod,
    }) : {
      ...current,
      enabled: false,
      planningMode: 'single_period',
      selectedPeriod: null,
    });
    setRollingConfig((current) => entry.results.rolling ? normalizeRollingConfig({
      ...current,
      enabled: entry.results.rolling?.enabled ?? current.enabled,
      horizonSnapshots: entry.results.rolling?.horizonSnapshots ?? current.horizonSnapshots,
      overlapSnapshots: entry.results.rolling?.overlapSnapshots ?? current.overlapSnapshots,
      stepSnapshots: entry.results.rolling?.stepSnapshots ?? current.stepSnapshots,
    }) : {
      ...current,
      enabled: false,
    });
    // Stay on whatever view/sub-tab the user is currently on — do not yank them
    // to a default Result pane. Any stale asset focus that the restored results
    // don't contain is dropped by the focus-reset effect above.
    showToast(
      opts?.loadIntoEditor ? `Imported ${entry.label} into the editor` : `Viewing ${entry.label}`,
      'success',
    );
  };

  // ── Backend-stored runs ─────────────────────────────────────────────────
  // Every successful solve is persisted server-side (the backend is the single
  // source of truth for run history). These handlers list, open, download, and
  // delete those runs; `backendRuns` powers both the History tab and Analytics
  // → Comparison.
  const refreshBackendRuns = useCallback(async (): Promise<BackendRunMeta[]> => {
    try {
      const resp = await fetch(`${API_BASE}/api/runs`);
      if (!resp.ok) return [];
      const data = await resp.json();
      const runs: BackendRunMeta[] = Array.isArray(data.runs) ? data.runs : [];
      setBackendRuns(runs);
      return runs;
    } catch {
      // Backend unreachable — leave the list as-is.
      return [];
    }
  }, []);

  useEffect(() => {
    void refreshBackendRuns();
  }, [refreshBackendRuns]);

  // Rename a stored run in place (History row label → input). The backend
  // renames the .db, identity, and display labels together; here we patch the
  // list with the returned meta and follow the active-run pointer so the open
  // result viewer / package download keep working under the new name.
  const handleRenameBackendRun = useCallback(async (name: string, newNameRaw: string) => {
    const newName = newNameRaw.trim();
    if (!newName || newName === name) return;
    try {
      const resp = await fetch(`${API_BASE}/api/runs/${encodeURIComponent(name)}/rename`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ newName }),
      });
      if (!resp.ok) {
        const detail = await resp.json().catch(() => null) as { detail?: string } | null;
        throw new Error(detail?.detail || `Rename failed (status ${resp.status}).`);
      }
      const meta = (await resp.json()) as BackendRunMeta;
      setBackendRuns((prev) => prev.map((m) => (m.name === name ? meta : m)));
      setActiveRunName((current) => (current === name ? meta.name : current));
      showToast(`Renamed run to ${meta.name}`, 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Rename failed.', 'error');
    }
  }, [showToast]);

  // Auto-refresh the History list while the History tab is open, so a run that
  // finishes elsewhere (or an import) appears without a browser reload. Polling
  // only runs while the tab is visible to avoid needless backend chatter.
  useEffect(() => {
    if (tab !== 'History') return;
    const timer = setInterval(() => void refreshBackendRuns(), 5000);
    return () => clearInterval(timer);
  }, [tab, refreshBackendRuns]);

  // ── Run queue polling ──────────────────────────────────────────────────────
  // Always poll the queue (regardless of tab) so a completion notification fires
  // wherever the user is. On each tick: refresh the visible (queued/running)
  // jobs, and for any job that newly reached a terminal state, toast once and
  // refresh History (where the finished run now lives).
  const refreshQueue = useCallback(async (): Promise<void> => {
    try {
      const resp = await fetch(`${API_BASE}/api/queue`);
      if (!resp.ok) return;
      const data = await resp.json();
      const jobs: QueueJob[] = Array.isArray(data.jobs) ? data.jobs : [];
      if (typeof data.concurrency === 'number') setQueueConcurrency(data.concurrency);
      if (typeof data.cpuCount === 'number') setQueueCpuCount(data.cpuCount);
      const previousStatuses = queueStatusRef.current;
      setQueueJobs(jobs);
      let anyFinished = false;
      for (const job of jobs) {
        const previous = previousStatuses.get(job.id);
        const becameTerminal =
          (previous === 'queued' || previous === 'running')
          && (job.status === 'done' || job.status === 'error' || job.status === 'cancelled');
        if (becameTerminal && !seenTerminalRef.current.has(job.id)) {
          seenTerminalRef.current.add(job.id);
          anyFinished = true;
          if (job.status === 'done') {
            showToast(`Run "${job.label}" finished — added to History`, 'success');
          } else if (job.status === 'error') {
            showToast(`Run "${job.label}" failed: ${job.error ?? 'unknown error'}`, 'error');
          } else {
            showToast(`Run "${job.label}" cancelled`, 'info');
          }
          window.dispatchEvent(new CustomEvent('ragnarok:log-refresh'));
        }
      }
      queueStatusRef.current = new Map(jobs.map((job) => [job.id, job.status]));
      if (anyFinished) void refreshBackendRuns();
    } catch {
      /* backend unreachable — leave the queue as-is */
    }
  }, [showToast, refreshBackendRuns]);

  // Set how many solves run at once (1 = serial queue). The backend clamps to
  // the core count and persists the choice; running jobs are never interrupted.
  const handleSetQueueConcurrency = useCallback(async (value: number): Promise<void> => {
    try {
      const resp = await fetch(`${API_BASE}/api/queue/concurrency`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value }),
      });
      if (!resp.ok) throw new Error((await resp.text()) || 'Failed to update concurrency.');
      const data = await resp.json();
      if (typeof data.concurrency === 'number') setQueueConcurrency(data.concurrency);
      if (typeof data.cpuCount === 'number') setQueueCpuCount(data.cpuCount);
      showToast(
        data.concurrency > 1
          ? `Running up to ${data.concurrency} solves at once`
          : 'Queue mode — one solve at a time',
        'info',
      );
      void refreshQueue();
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Failed to update concurrency.', 'error');
    }
  }, [showToast, refreshQueue]);

  // Poll fast (2.5s) while jobs are active so the Queue tab stays live and the
  // completion toast fires promptly; back off to a slow heartbeat (15s) when the
  // queue is empty (a new run is enqueued from this same client, which refreshes
  // immediately, so idle fast-polling would just be wasted chatter).
  const activeQueueJobs = queueJobs.filter((job) => job.status === 'queued' || job.status === 'running');
  const hasActiveJobs = activeQueueJobs.length > 0;
  const activePollMs = Math.max(500, settings.queuePollSeconds * 1000);
  useEffect(() => {
    void refreshQueue();
    // Active: user-configured interval (Settings → Solver). Idle: a slow
    // heartbeat (>= 15s) since a new run is enqueued from this client anyway.
    const timer = setInterval(() => void refreshQueue(), hasActiveJobs ? activePollMs : Math.max(15000, activePollMs));
    return () => clearInterval(timer);
  }, [refreshQueue, hasActiveJobs, activePollMs]);

  const handleCancelQueueItem = useCallback(async (id: string) => {
    try {
      await fetch(`${API_BASE}/api/queue/${encodeURIComponent(id)}/cancel`, { method: 'POST' });
    } catch {
      /* ignore — the next poll reflects the real server state */
    }
    void refreshQueue();
  }, [refreshQueue]);

  const handleRerunQueueItem = useCallback(async (id: string) => {
    try {
      const resp = await fetch(`${API_BASE}/api/queue/${encodeURIComponent(id)}/rerun`, { method: 'POST' });
      if (!resp.ok) throw new Error(await resp.text());
      const { position } = (await resp.json()) as { position?: number };
      const posMsg = position && position > 1 ? ` — position ${position} in queue` : '';
      showToast(`Run queued${posMsg}`, 'info');
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Failed to rerun queued model.', 'error');
    }
    void refreshQueue();
  }, [refreshQueue, showToast]);

  const handleDeleteQueueItem = useCallback(async (id: string) => {
    try {
      await fetch(`${API_BASE}/api/queue/${encodeURIComponent(id)}`, { method: 'DELETE' });
    } catch {
      /* ignore — the next poll reflects the real server state */
    }
    void refreshQueue();
  }, [refreshQueue]);

  // Welcome → "Start from scratch": a fresh empty model, straight into Build.
  const handleStartFromScratch = useCallback(() => {
    resetForNewModel(createEmptyWorkbook(), 'untitled.xlsx');
    setTab('Build');
    showToast('Started a new model', 'success');
  }, [resetForNewModel, setTab, showToast]);

  // Welcome → "Start with an example": the backend copies the example's
  // project.db into the session; we rehydrate the editor from there (same path
  // as Import project) and open the guided builder.
  const handleLoadExample = useCallback(async (id: string) => {
    try {
      const { label } = await loadExample(id);
      const savedModel = await getSessionFullModel({ staticOnly: true });
      if (!savedModel) throw new Error('Example could not be read back from the session.');
      resetForNewModel(savedModel, label, { pushToSession: false });
      try { setSessionSeriesCounts(seriesSheetCounts(await getSessionMeta())); } catch { /* tree just won't list series */ }
      setTab('Build');
      showToast(`Loaded "${label}"`, 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Failed to load example.', 'error');
    }
  }, [resetForNewModel, setTab, showToast]);

  // Import project (Queue tab): load a queued/finished item's retained model
  // snapshot into the editor as a new working project. The backend writes it to
  // the session; we then rehydrate the editor from there (static sheets only —
  // series stay server-side and page into the grid). A subsequent Run/Queue
  // makes a NEW entry, so the original queue card is left untouched.
  const handleImportQueueItem = useCallback(async (id: string) => {
    try {
      const resp = await fetch(`${API_BASE}/api/queue/${encodeURIComponent(id)}/import`, { method: 'POST' });
      if (!resp.ok) throw new Error((await resp.text()) || 'Import failed.');
      const meta = (await resp.json()) as { filename?: string };
      const savedModel = await getSessionFullModel({ staticOnly: true });
      if (!savedModel) throw new Error('Imported model could not be read back from the session.');
      resetForNewModel(savedModel, meta.filename, { pushToSession: false });
      setTab('Model');
      showToast('Imported queued model into the editor', 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Failed to import queued model.', 'error');
    }
  }, [resetForNewModel, setTab, showToast]);

  const handleOpenBackendRun = async (
    name: string,
    opts?: { restoreConstraints?: boolean; asProject?: boolean },
  ) => {
    if (opts?.asProject) setRunBusy(name, 'Importing');
    try {
      if (opts?.asProject) {
        // FAST IMPORT. Promote the run into the session SERVER-SIDE (model copied
        // db→session, no full year of series through the browser), then rehydrate
        // the editor static-only and fetch the LIGHT analytics for the results.
        // The series page into the grid on demand, exactly like a fresh load.
        setStatus(`Importing ${name}…`);
        showToast(`Importing ${name} — this can take a moment for a full run.`, 'info');
        const promoteResp = await fetch(`${API_BASE}/api/runs/${encodeURIComponent(name)}/promote`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sessionId: DEFAULT_SESSION_ID }),
        });
        if (!promoteResp.ok) {
          showToast('Stored run could not be imported.', 'error');
          return;
        }
        const promoted = (await promoteResp.json()) as {
          scenario?: { constraints?: CustomConstraint[]; carbonPrice?: number; discountRate?: number; label?: string };
          snapshotStart?: number; snapshotEnd?: number; snapshotWeight?: number; filename?: string;
        };
        const aResp = await fetch(`${API_BASE}/api/runs/${encodeURIComponent(name)}/analytics`);
        const light = aResp.ok ? await aResp.json() : {};
        handleRestoreRun(
          {
            label: light.label || promoted.filename || name,
            results: (light.result ?? {}) as RunResults,
            // Static topology only — the editor pages the series on demand; the
            // FULL model already lives in the session (promoted above).
            model: light.modelStatic ?? {},
            carbonPrice: light.scenario?.carbonPrice ?? promoted.scenario?.carbonPrice ?? 0,
            discountRate: light.scenario?.discountRate ?? promoted.scenario?.discountRate,
            snapshotStart: promoted.snapshotStart ?? light.options?.snapshotStart ?? 0,
            snapshotEnd: promoted.snapshotEnd ?? light.options?.snapshotEnd ?? 0,
            snapshotWeight: promoted.snapshotWeight ?? light.options?.snapshotWeight ?? 1,
          },
          { loadIntoEditor: true, sessionAlreadyLoaded: true },
        );
        setActiveRunName(name);
        // List the session's temporal sheets in the Model tree (they're not in
        // the static model; selecting one pages its rows from the session).
        try {
          setSessionSeriesCounts(seriesSheetCounts(await getSessionMeta()));
        } catch { /* tree just won't list series */ }
        const importedConstraints = promoted.scenario?.constraints;
        if (Array.isArray(importedConstraints)) setConstraints(importedConstraints);
        return;
      }

      // VIEW is light: the analytics endpoint omits the input model and the
      // heavy per-component output series (charts get the small carrier-level
      // series + KPIs inline).
      const resp = await fetch(`${API_BASE}/api/runs/${encodeURIComponent(name)}/analytics`);
      if (!resp.ok) {
        showToast('Stored run could not be opened.', 'error');
        return;
      }
      const bundle = await resp.json();
      const result: RunResults = bundle.result;
      handleRestoreRun({
        label: bundle.label || name,
        results: result,
        model: bundle.modelStatic,
        carbonPrice: bundle.scenario?.carbonPrice ?? 0,
        discountRate: bundle.scenario?.discountRate,
        snapshotStart: bundle.snapshotStart ?? bundle.options?.snapshotStart ?? 0,
        snapshotEnd: bundle.snapshotEnd ?? bundle.options?.snapshotEnd ?? 0,
        snapshotWeight: bundle.snapshotWeight ?? bundle.options?.snapshotWeight ?? 1,
      }, { loadIntoEditor: false });
      // Mark this stored run as the active one so Comparison highlights it.
      setActiveRunName(name);
      if (opts?.restoreConstraints && Array.isArray(bundle.scenario?.constraints)) {
        setConstraints(bundle.scenario.constraints);
      }
      // Intentionally do NOT switch tabs here — opening a run leaves the user
      // exactly where they are.
    } catch {
      showToast('Stored run could not be opened.', 'error');
    } finally {
      if (opts?.asProject) setRunBusy(name, null);
    }
  };

  // History toolbar "View result": one selected run → its Result pane; several →
  // the Comparison pane (which reads the lightweight run metas, so it stays
  // cheap). Navigation lives here so History rows can stay action-free.
  const handleViewSelectedRuns = (names: string[]) => {
    if (names.length === 0) return;
    if (names.length === 1) {
      void handleOpenBackendRun(names[0]);
      setTab('Analytics');
      setAnalyticsSubTab('Result');
    } else {
      void handleOpenBackendRun(names[0]);
      setTab('Analytics');
      setAnalyticsSubTab('Comparison');
    }
  };

  // Run an export as a BACKGROUND JOB: POST to create it, poll until the build
  // finishes (a full-year workbook can take minutes), then stream the download
  // — the backend deletes the artefact once the bytes are sent. The browser
  // never hangs on a pending download, and progress is surfaced via toasts.
  const runExportJob = async (
    name: string,
    kind: 'xlsx' | 'package',
    parts?: string[],
  ): Promise<void> => {
    const label = kind === 'package' ? 'project (.zip)' : 'workbook (.xlsx)';
    setRunBusy(name, 'Exporting');
    try {
      const createResp = await fetch(`${API_BASE}/api/exports`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, kind, parts }),
      });
      if (!createResp.ok) {
        throw new Error((await createResp.text()) || `Export failed (HTTP ${createResp.status}).`);
      }
      const { jobId } = (await createResp.json()) as { jobId: string };
      setStatus(`Building ${label}…`);
      showToast(`Building ${label} — this can take a moment for a full run.`, 'info');

      // Poll for completion. Generous ceiling for a full-year Result export.
      const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
      const deadline = Date.now() + 10 * 60 * 1000;
      for (;;) {
        await sleep(800);
        const stResp = await fetch(`${API_BASE}/api/exports/${encodeURIComponent(jobId)}`);
        if (!stResp.ok) throw new Error('Export job expired before it finished.');
        const job = (await stResp.json()) as { status: string; error?: string };
        if (job.status === 'ready') break;
        if (job.status === 'error') throw new Error(job.error || 'Export build failed.');
        if (Date.now() > deadline) throw new Error('Export timed out while building.');
      }

      // Ready: trigger the download via a programmatic <a download> click. The
      // GET streams the file and the backend deletes it afterwards. (A bare
      // window.open here would be popup-blocked — it runs after the async poll,
      // outside the original click's gesture context.)
      const a = document.createElement('a');
      a.href = `${API_BASE}/api/exports/${encodeURIComponent(jobId)}/download`;
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setStatus(`${label} ready — downloading.`);
      showToast(`${label} ready`, 'success');
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Export failed.';
      setStatus(msg);
      showToast(msg, 'error');
    } finally {
      setRunBusy(name, null);
    }
  };

  // Explicit Excel export — the ONLY path that creates a workbook (the backend
  // never auto-writes xlsx). `parts` mirrors the Export dialog's checkboxes.
  // Export one or more stored runs as Excel workbooks. Runs are built and
  // downloaded sequentially so a multi-select doesn't fire N concurrent export
  // jobs at the backend (or N simultaneous browser downloads).
  const handleDownloadBackendXlsx = (names: string[], parts?: string[]) => {
    void (async () => {
      for (const name of names) await runExportJob(name, 'xlsx', parts);
    })();
  };

  // Export one or more stored runs as full Ragnarok Project packages (.zip of
  // all three files: bundle JSON + meta JSON + readable xlsx). Sequential, same
  // rationale as the xlsx path above.
  const handleExportBackendProject = (names: string[]) => {
    void (async () => {
      for (const name of names) await runExportJob(name, 'package');
    })();
  };

  const handleDeleteBackendRuns = async (names: string[]) => {
    // Delete all selected, then refresh once.
    names.forEach((name) => setRunBusy(name, 'Deleting'));
    await Promise.all(
      names.map((name) =>
        fetch(`${API_BASE}/api/runs/${encodeURIComponent(name)}`, { method: 'DELETE' }).catch(() => undefined),
      ),
    );
    names.forEach((name) => setRunBusy(name, null));
    setActiveRunName((current) => (current && names.includes(current) ? null : current));
    void refreshBackendRuns();
  };

  const handleSelectScenario = (scenarioId: string) => {
    const scenario = scenarioCatalog.scenarios.find((row) => row.id === scenarioId);
    if (!scenario) return;
    applyScenarioPreset(scenario);
  };

  const handleCreateScenarioFromCurrent = () => {
    const nextIndex = scenarioCatalog.scenarios.length + 1;
    const scenario = captureCurrentScenario({
      label: `Scenario ${nextIndex}`,
      notes: '',
    });
    setScenarioCatalog((current) => ({
      activeScenarioId: scenario.id,
      scenarios: [...current.scenarios, scenario],
    }));
    setStatus(`Created scenario: ${scenario.label}`);
    showToast(`Scenario created: ${scenario.label}`, 'success');
  };

  const handleDuplicateScenario = () => {
    if (!activeScenario) return;
    const duplicate = buildScenarioPreset({
      ...activeScenario,
      id: undefined,
      label: `${activeScenario.label} copy`,
    });
    setScenarioCatalog((current) => ({
      activeScenarioId: duplicate.id,
      scenarios: [...current.scenarios, duplicate],
    }));
    showToast(`Scenario duplicated: ${duplicate.label}`, 'success');
  };

  const handleUpdateActiveScenarioFromCurrent = () => {
    if (!activeScenario) return;
    const updated = captureCurrentScenario({
      id: activeScenario.id,
      label: activeScenario.label,
      notes: activeScenario.notes,
    });
    setScenarioCatalog((current) => ({
      ...current,
      scenarios: current.scenarios.map((scenario) => (
        scenario.id === activeScenario.id ? updated : scenario
      )),
    }));
    setStatus(`Updated scenario: ${activeScenario.label}`);
    showToast(`Scenario updated: ${activeScenario.label}`, 'success');
  };

  const handleDeleteScenario = () => {
    if (!activeScenario || scenarioCatalog.scenarios.length <= 1) return;
    const remaining = scenarioCatalog.scenarios.filter((scenario) => scenario.id !== activeScenario.id);
    const nextActive = remaining[0] ?? null;
    setScenarioCatalog({
      activeScenarioId: nextActive?.id ?? null,
      scenarios: remaining,
    });
    if (nextActive) applyScenarioPreset(nextActive);
  };

  const handleRenameScenario = (scenarioId: string, label: string) => {
    setScenarioCatalog((current) => ({
      ...current,
      scenarios: current.scenarios.map((scenario) => (
        scenario.id === scenarioId
          ? { ...scenario, label: label.trim() || scenario.label }
          : scenario
      )),
    }));
  };

  const handleScenarioNotesChange = (scenarioId: string, notes: string) => {
    setScenarioCatalog((current) => ({
      ...current,
      scenarios: current.scenarios.map((scenario) => (
        scenario.id === scenarioId
          ? { ...scenario, notes }
          : scenario
      )),
    }));
  };

  const handleImportTsSheet = (sheet: TsSheetName, rows: GridRow[]) => {
    // Canonicalise to ISO-`T` snapshots + `snapshot`-first column order at the
    // CSV/manual import boundary so the in-memory model stays PyPSA-canonical.
    const canonical = canonicalizeTemporalRows(rows, settings.dateFormat);
    setModel((current) => ({ ...current, [sheet]: canonical }));
    // Keep the tree's series-count map in step (imported sheet now has rows;
    // an empty import clears it).
    setSessionSeriesCounts((c) => {
      const next = { ...c };
      if (canonical.length > 0) next[String(sheet)] = canonical.length;
      else delete next[String(sheet)];
      return next;
    });
    // Time-series live in the backend session (static merges skip them) —
    // replace the sheet there too, like the Model tab's CSV import does. The
    // current row count comes from the BACKEND (the mirror strips series).
    void (async () => {
      const previous = await getSheetPage(String(sheet), { offset: 0, limit: 0 })
        .then((page) => page.total)
        .catch(() => 0);
      await patchSheet(String(sheet), [
        ...(previous ? [{ op: 'deleteRows' as const, rows: Array.from({ length: previous }, (_, i) => i) }] : []),
        ...canonical.map((r) => ({ op: 'addRow' as const, values: r as Record<string, unknown> })),
      ]);
    })().catch(() => { /* best-effort */ });
    if (canonical.length > 0) {
      showToast(`Imported ${canonical.length} rows into ${sheet}`, 'success');
      setStatus(`Imported ${canonical.length} rows into ${sheet}.`);
    } else {
      showToast(`Cleared ${sheet}`, 'success');
      setStatus(`Cleared ${sheet}.`);
    }
  };

  const saveAsWorkbook = async () => {
    const saver = (window as any).showSaveFilePicker;
    const suggestedName = filename || 'ragnarok_case.xlsx';
    if (!saver) {
      const requested = (await promptDialog('Save workbook as', { title: 'Save workbook', defaultValue: suggestedName, confirmText: 'Save' })) || suggestedName;
      exportWorkbook(model, requested, settings.dateFormat);
      setFilename(requested);
      setStatus(`Saved workbook as ${requested}.`);
      showToast(`Saved as ${requested}`, 'success');
      return;
    }
    try {
      const handle = await saver({
        suggestedName,
        types: [{ description: 'Excel Workbook', accept: { 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'] } }],
      });
      const writable = await handle.createWritable();
      await writable.write(workbookToArrayBuffer(model, settings.dateFormat));
      await writable.close();
      setFileHandle(handle);
      setFilename(handle.name || suggestedName);
      setStatus(`Saved workbook as ${handle.name || suggestedName}.`);
      showToast(`Saved as ${handle.name || suggestedName}`, 'success');
    } catch (error) {
      if ((error as Error)?.name !== 'AbortError') {
        setStatus('Save As failed.');
        showToast('Save failed.', 'error');
      }
    }
  };

  const saveWorkbook = async () => {
    if (!fileHandle) {
      await saveAsWorkbook();
      return;
    }
    try {
      const writable = await fileHandle.createWritable();
      await writable.write(workbookToArrayBuffer(model, settings.dateFormat));
      await writable.close();
      setStatus(`Saved workbook ${filename}.`);
    } catch {
      await saveAsWorkbook();
    }
  };

  const handleRunModel = async (staged = false) => {
    const snapshotCount = snapshotEnd - snapshotStart;
    // Parse the constraint DSL with per-line errors: invalid lines are NOT
    // applied, and that must never be silent — warn loudly before the run so
    // "constraint I typed had a typo" can't masquerade as a clean result.
    const dslLines = parseConstraintDsl(customDsl);
    const dslErrors = dslLines.filter((line) => line.error);
    if (dslErrors.length > 0) {
      const first = dslErrors[0];
      showToast(
        `${dslErrors.length} custom-constraint line(s) have syntax errors and are NOT applied `
        + `(line ${first.lineNo}: ${first.error}). Fix them in Settings → Constraints → Advanced.`,
        'error',
      );
    }
    const scenario = {
      constraints: constraints.filter((c) => c.enabled),
      constraintSpecs: dslLines.map((line) => line.spec).filter((s): s is ConstraintSpec => !!s),
      carbonPrice,
      discountRate: settings.discountRate,
    };
    const options = {
      // Optimisation backend selector (backend registry resolves this; PyPSA
      // is the only adapter today). Threaded now so a future backend toggle
      // has a channel without a payload-shape change.
      backend: 'pypsa',
      snapshotCount, snapshotStart, snapshotEnd, snapshotWeight, forceLp,
      // Carried so the backend run store can label the stored run with the
      // active scenario for Analytics → Comparison's cross-scenario pivot.
      scenarioLabel: activeScenario?.label ?? null,
      filename,
      dateFormat: settings.dateFormat,
      solverThreads: settings.solverThreads, solverType: settings.solverType,
      solveAcceptance: settings.solveAcceptance,
      objectiveAutoScale: settings.objectiveAutoScale,
      currencySymbol: settings.currencySymbol,
      enableLoadShedding: settings.enableLoadShedding,
      loadSheddingCost: settings.loadSheddingCost,
      pathwayConfig: {
        ...pathwayConfig,
        selectedPeriod: getDefaultSelectedPeriod(pathwayConfig),
      },
      rollingConfig: normalizeRollingConfig(rollingConfig),
      samplingConfig: normalizeSamplingConfig(samplingConfig),
      stochasticConfig,
      securityConstrainedConfig: sclopfConfig,
      powerFlowConfig,
      contingencyConfig,
      mgaConfig,
      merchantConfig,
      ownerColumn,
      financeConfig,
      carbonPriceSchedule,
    };

    setRunDialogOpen(false);

    // Same ISO normalization as import/open so the backend always receives
    // canonical snapshot timestamps (and the grid stays in sync).
    const modelForRun = prepareModelForBackend(model);
    setModel(modelForRun);

    // Sync static edits to the session (MERGE — the browser only holds static
    // sheets; the backend keeps the heavy series it already has), then submit by
    // sessionId only. The backend snapshots the session model into the queue
    // item, so later edits can't change an already-queued run.
    try {
      await putStaticModel(modelForRun);
    } catch {
      setStatus('Could not sync the model to the backend session.');
      showToast('Could not reach the backend to start the run.', 'error');
      return;
    }

    if (dryRun) {
      setStatus('Validating model structure...');
      try {
        const response = await fetch(`${API_BASE}/api/validate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sessionId: DEFAULT_SESSION_ID, scenario, options }),
        });
        const result = await response.json();
        setValidateResult(result);
        // Don't auto-switch tabs — the pass/fail is reported via the toast/status
        // below; the user opens Analytics → Validation themselves for detail.
        const vMsg = result.valid ? 'Validation passed.' : `Validation failed: ${result.errors.length} error(s).`;
        setStatus(vMsg);
        showToast(vMsg, result.valid ? 'success' : 'error');
      } catch (error) {
        setStatus(error instanceof Error ? error.message : 'Validation request failed.');
      }
      return;
    }

    // Enqueue the run on the backend's serial queue and return immediately. The
    // queue poller notifies on completion and the finished run appears in
    // History — the UI never blocks on a live solve here. ``staged`` parks the
    // job ("Queue next Run") so it won't auto-run until the user activates it
    // from the Queue tab; the default ("Run") runs now if idle, else next.
    setStatus(staged ? `Staging run — ${snapshotCount} snapshots…` : `Queuing run — ${snapshotCount} snapshots…`);
    try {
      const resp = await fetch(`${API_BASE}/api/queue${staged ? '?staged=true' : ''}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sessionId: DEFAULT_SESSION_ID, scenario, options }),
      });
      if (!resp.ok) {
        throw new Error((await resp.text()) || `Failed to queue run (status ${resp.status}).`);
      }
      const { position } = (await resp.json()) as { id: string; position: number };
      if (staged) {
        setStatus('Run staged. Activate it from the Queue tab when you want it to run.');
        showToast('Run staged for later', 'info');
      } else {
        const posMsg = position > 1 ? ` — position ${position} in queue` : '';
        setStatus(`Run queued${posMsg}. You'll be notified when it finishes; it then appears in History.`);
        showToast(`Run queued${posMsg}`, 'info');
      }
      void refreshQueue();
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Failed to queue run.';
      setStatus(msg);
      showToast(msg, 'error');
    }
  };

  // ── Metric series derived data ────────────────────────────────────────────

  const rawSystemDispatchRows: TimeSeriesRow[] = (displayResults?.dispatchSeries || []).map(normalizeSeriesPoint);
  const systemDispatchRows: TimeSeriesRow[] =
    rawSystemDispatchRows.some((row) =>
      Object.keys(row).some((key) => !['label', 'timestamp', 'total'].includes(key) && Math.abs(numberValue(row[key] as string | number | undefined)) > 1e-6),
    )
      ? rawSystemDispatchRows
      : buildRowsFromGeneratorDetails(displayResults?.assetDetails.generators || {}, 'carrier');
  const inferredDispatchKeys = Array.from(
    new Set(systemDispatchRows.flatMap((row) => Object.keys(row).filter((key) => !['label', 'timestamp', 'total'].includes(key)))),
  );
  const dispatchKeys =
    inferredDispatchKeys.length > 0
      ? orderByCarrierRows(model.carriers, inferredDispatchKeys)
      : (displayResults?.carrierMix || []).map((item) => item.label).filter(Boolean);
  const systemDispatchSeries: TimeSeriesSeries[] = dispatchKeys.map((key) => ({ key, label: key, color: carrierColor(key) }));

  const systemPriceRows: TimeSeriesRow[] = (displayResults?.systemPriceSeries || []).map((point) => ({ label: point.label, timestamp: point.timestamp, price: point.value }));
  const storageRows: TimeSeriesRow[] = (displayResults?.storageSeries || []).map((point) => ({ label: point.label, timestamp: point.timestamp, charge: point.charge, discharge: point.discharge, state: point.state }));
  const systemLoadRows: TimeSeriesRow[] = buildSystemLoadRows(displayResults);

  // Seed a default chart card when results first arrive; don't reset on map-focus changes.
  useEffect(() => {
    if (!displayResults) {
      setChartSections([]);
      return;
    }
    setChartSections([
      {
        id: 1,
        focusType: 'system',
        focusKeys: [],
        groupBy: 'carrier',
        busFilter: [],
        carrierFilter: [],
        metricKey: 'dispatch',
        chartType: 'area',
        timeframe: 'hourly',
        startIndex: 0,
        endIndex: Math.max((displayResults.dispatchSeries.length || 1) - 1, 0),
        stacked: true,
      },
    ]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displayResults]);

  return (
    <div className="studio-shell">
      <input ref={fileInputRef} type="file" accept=".xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel" hidden onChange={handleImport} />
      <input ref={projectImportInputRef} type="file" accept=".zip,application/zip,.xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel" hidden onChange={handleImportProject} />
      <input ref={resultImportInputRef} type="file" accept=".zip,application/zip,.xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel" hidden multiple onChange={handleImportResultXlsx} />
      <input ref={csvFolderImportInputRef} type="file" accept=".zip,application/zip" hidden onChange={handleImportCsvFolder} />
      <input ref={netcdfImportInputRef} type="file" accept=".nc" hidden onChange={handleImportNetcdf} />
      <input ref={hdf5ImportInputRef} type="file" accept=".h5,.hdf5" hidden onChange={handleImportHdf5} />

      {/* ── Top bar ──
        Layout: [Brand] [Run] [Clear]   …spacer…   <filename> <status>
        View switching lives in the far-left activity bar (see below).
        File ops other than Clear live in Model view's toolbar only. */}
      <header className="topbar">
        <div className="topbar-left">
          <button
            type="button"
            className="topbar-brand topbar-brand--button"
            onClick={() => setTab('Welcome')}
            title="Go to Welcome page"
            aria-label="Go to Welcome page"
          >
            <RagnarokLogo size={18} title="" className="topbar-brand-mark" />
            Ragnarok
          </button>
          <button
            className="run-button"
            onClick={() => setRunDialogOpen(true)}
            title="Queue a run (runs execute one at a time)"
          >
            Run
          </button>
          <button
            className="tb-btn tb-btn--muted"
            onClick={async () => {
              if (!(await confirmDialog(
                'This removes the loaded model, every unsaved edit, and the current '
                + 'results — on both the frontend and the backend session.\n\n'
                + 'Your settings, run controls, history, and installed plugins are KEPT. '
                + '(Use "Clear cache" to also wipe settings and reload.)',
                { title: 'Clear the model?', confirmText: 'Clear model', danger: true },
              ))) return;
              // Clear the MODEL only: reset the frontend workbook + results, drop
              // the backend session model, and remove just the persisted model
              // record (controls/settings/prefs survive). No reload.
              resetForNewModel(createEmptyWorkbook(), 'untitled.xlsx');
              setFileHandle(null);
              void clearSessionModel();
              await clearSessionModelOnly();
              setStatus('Model cleared. Settings kept.');
            }}
            title="Remove the loaded model (frontend + backend), keep settings"
          >
            Clear
          </button>
          <button
            className="tb-btn tb-btn--muted"
            onClick={async () => {
              if (!(await confirmDialog(
                'This removes:\n'
                + '  • the loaded model + every unsaved edit + every result\n'
                + '  • every persisted UI preference (column widths, panel sizes,\n'
                + '    Data-view selection, settings, run history, recent files)\n\n'
                + 'Installed plugins are KEPT (uninstall them from the Plugins tab).\n\n'
                + 'Ragnarok will reload to the Welcome page.',
                { title: 'Clear the cache?', confirmText: 'Clear cache', danger: true },
              ))) return;
              // Wipe Ragnarok-owned cache / preference keys (`pypsa.*`,
              // `ragnarok:*`, `ui:*`). Installed plugins are USER-OWNED
              // CONTENT, not cache — Clear must NOT uninstall them (same
              // PRESERVE rule as the build-id wipe in index.tsx). Plugin
              // keys live under `ragnarok:fe-plugins:`.
              try {
                const PRESERVE = ['ragnarok:fe-plugins:'];
                const doomed: string[] = [];
                for (let i = 0; i < window.localStorage.length; i += 1) {
                  const key = window.localStorage.key(i);
                  if (!key) continue;
                  if (PRESERVE.some((p) => key.startsWith(p))) continue;
                  if (
                    key.startsWith('pypsa.')
                    || key.startsWith('ragnarok:')
                    || key.startsWith('ui:')
                  ) {
                    doomed.push(key);
                  }
                }
                for (const key of doomed) window.localStorage.removeItem(key);
              } catch {
                /* storage unavailable */
              }
              resetForNewModel(createEmptyWorkbook(), 'untitled.xlsx');
              setFileHandle(null);
              // Drop the backend session model too (fire-and-forget; the reload
              // below doesn't depend on it).
              void clearSessionModel();
              // Wipe the persisted IndexedDB session too, and await it so the
              // delete commits before the reload (otherwise it would restore).
              await clearSession();
              // Reload so every component re-reads its now-empty persisted
              // state and the Welcome view is restored as the landing page.
              window.location.reload();
            }}
            title="Remove the loaded model AND wipe every persisted UI preference"
          >
            Clear cache
          </button>
          {activeQueueJobs.length > 0 && (
            <button
              className="tb-btn topbar-queue"
              onClick={() => { setTab('History'); setHistorySubTab('Queue'); }}
              title="Open the run queue"
            >
              <span className="topbar-spinner" />
              {activeQueueJobs.some((j) => j.status === 'running') ? 'Running' : 'Queued'} ({activeQueueJobs.length})
            </button>
          )}
        </div>
        <div className="topbar-right">
          <span className="topbar-file" title={filename}>{filename}</span>
          {displayResults && (
            <span className="topbar-run-meta">{displayResults.runMeta.snapshotCount} snaps · {Number(displayResults.runMeta.snapshotWeight.toFixed(2))}h</span>
          )}
          <span className="topbar-status" title={status}>{status}</span>
        </div>
      </header>

      <div className="workspace-body">
        <ActivityBar
          tab={tab}
          onTabChange={setTab}
          validateResult={validateResult}
          pluginCount={frontendPlugins.installed.length}
        />
        <div className="workspace-main">

          {/* ── Settings tab ── */}
          {tab === 'Settings' && (
            <SettingsView
              model={model}
              scenarioCatalog={scenarioCatalog}
              activeScenarioLabel={activeScenario?.label ?? null}
              scenarioDirty={scenarioDirty}
              onSelectScenario={handleSelectScenario}
              onCreateScenarioFromCurrent={handleCreateScenarioFromCurrent}
              onDuplicateScenario={handleDuplicateScenario}
              onUpdateActiveScenarioFromCurrent={handleUpdateActiveScenarioFromCurrent}
              onDeleteScenario={handleDeleteScenario}
              onRenameScenario={handleRenameScenario}
              onScenarioNotesChange={handleScenarioNotesChange}
              pathwayConfig={pathwayConfig}
              onPathwayConfigChange={setPathwayConfig}
              rollingConfig={rollingConfig}
              onRollingConfigChange={(config) => setRollingConfig(normalizeRollingConfig(config))}
              samplingConfig={samplingConfig}
              onSamplingConfigChange={(config) => setSamplingConfig(normalizeSamplingConfig(config))}
              stochasticConfig={stochasticConfig}
              onStochasticConfigChange={setStochasticConfig}
              sclopfConfig={sclopfConfig}
              onSclopfConfigChange={setSclopfConfig}
              powerFlowConfig={powerFlowConfig}
              onPowerFlowConfigChange={setPowerFlowConfig}
              contingencyConfig={contingencyConfig}
              onContingencyConfigChange={setContingencyConfig}
              mgaConfig={mgaConfig}
              onMgaConfigChange={setMgaConfig}
              merchantConfig={merchantConfig}
              onMerchantConfigChange={setMerchantConfig}
              merchantOwners={merchantOwners}
              ownerColumn={ownerColumn}
              onOwnerColumnChange={setOwnerColumn}
              financeConfig={financeConfig}
              onFinanceConfigChange={setFinanceConfig}
              maxSnapshots={maxSnapshots}
              snapshotStart={snapshotStart}
              snapshotEnd={snapshotEnd}
              snapshotWeight={snapshotWeight}
              onSnapshotStartChange={setSnapshotStart}
              onSnapshotEndChange={setSnapshotEnd}
              onSnapshotWeightChange={setSnapshotWeight}
              carbonPrice={carbonPrice}
              onCarbonPriceChange={setCarbonPrice}
              carbonPriceSchedule={carbonPriceSchedule}
              onCarbonPriceScheduleChange={setCarbonPriceSchedule}
              carbonLibrary={carbonLibrary}
              onCarbonLibraryChange={setCarbonLibrary}
              carbonCheck={carbonCheck}
              constraints={constraints}
              onConstraintsChange={setConstraints}
              customDsl={customDsl}
              onCustomDslChange={setCustomDsl}
              appliedConstraints={displayResults?.appliedConstraints}
              onUpdateRow={updateRowValue}
              onAddRow={addRow}
              onDeleteRow={deleteRow}
              dateFormat={settings.dateFormat}
              onDateFormatChange={(f) => updateSettings({ dateFormat: f })}
              currencyCode={settings.currencyCode}
              currencySymbol={settings.currencySymbol}
              onCurrencyChange={(code, symbol) => updateSettings({ currencyCode: code, currencySymbol: symbol })}
              discountRate={settings.discountRate}
              onDiscountRateChange={(v) => updateSettings({ discountRate: v })}
              enableLoadShedding={settings.enableLoadShedding}
              onEnableLoadSheddingChange={(v) => updateSettings({ enableLoadShedding: v })}
              loadSheddingCost={settings.loadSheddingCost}
              onLoadSheddingCostChange={(v) => updateSettings({ loadSheddingCost: v })}
              solverThreads={settings.solverThreads}
              solverType={settings.solverType}
              solveAcceptance={settings.solveAcceptance}
              objectiveAutoScale={settings.objectiveAutoScale}
              queuePollSeconds={settings.queuePollSeconds}
              onSolverThreadsChange={(v) => updateSettings({ solverThreads: v })}
              onSolverTypeChange={(v) => updateSettings({ solverType: v })}
              onSolveAcceptanceChange={(v) => updateSettings({ solveAcceptance: v })}
              onObjectiveAutoScaleChange={(v) => updateSettings({ objectiveAutoScale: v })}
              onQueuePollSecondsChange={(v) => updateSettings({ queuePollSeconds: v })}
              onCarrierColorChange={(rowIndex, color) => updateRowValue('carriers', rowIndex, 'color', color)}
              onCarrierReorder={(fromIndex, toIndex) => reorderRow('carriers', fromIndex, toIndex)}
              lineCount={model.lines.length}
              transformerCount={model.transformers.length}
            />
          )}

          {tab === 'Build' && (
            <BuildView
              model={model}
              busIndex={busIndex}
              onUpdateRow={updateRowValue}
              onAddRow={addRow}
              onDeleteRow={deleteRow}
              onAddColumn={addColumn}
              onDeleteColumn={deleteColumn}
              onRenameColumn={renameColumn}
              onClearTable={clearSheet}
              onImportTsSheet={handleImportTsSheet}
              onBulkPaste={bulkPaste}
              modelIssues={modelIssues}
              currencySymbol={settings.currencySymbol}
              dateFormat={settings.dateFormat}
              onOpenRunSetup={() => { setDryRun(false); setRunDialogOpen(true); }}
            />
          )}

          {tab === 'Model' && (
            <ModelView
              model={model}
              bounds={bounds}
              busIndex={busIndex}
              onUpdateRow={updateRowValue}
              onAddRow={addRow}
              onDeleteRow={deleteRow}
              onAddColumn={addColumn}
              onDeleteColumn={deleteColumn}
              onRenameColumn={renameColumn}
              onClearTable={clearSheet}
              onImportTsSheet={handleImportTsSheet}
              onBulkPaste={bulkPaste}
              modelIssues={modelIssues}
              jumpTo={jumpTo}
              currencySymbol={settings.currencySymbol}
              dateFormat={settings.dateFormat}
              seriesSheetCounts={sessionSeriesCounts}
              hasResults={Boolean(results)}
              onOpen={handleOpenWorkbook}
              onSave={saveWorkbook}
              onSaveAs={saveAsWorkbook}
              onImportProject={() => projectImportInputRef.current?.click()}
              onExportProject={handleExportProject}
              onImportCsvFolder={() => csvFolderImportInputRef.current?.click()}
              onExportCsvFolder={handleExportCsvFolder}
              onImportNetcdf={() => netcdfImportInputRef.current?.click()}
              onExportNetcdf={handleExportNetcdf}
              onImportHdf5={() => hdf5ImportInputRef.current?.click()}
              onExportHdf5={handleExportHdf5}
            />
          )}

          {tab === 'Welcome' && (
            <WelcomeView
              onNavigate={setTab}
              onStartScratch={handleStartFromScratch}
              onLoadExample={handleLoadExample}
            />
          )}

          {tab === 'Data' && <DataView onApplyFragment={handleApplyImportedFragment} />}

          {tab === 'Forge' && (
            <ForgeView
              model={model}
              onApplySheets={(partial) => {
                setModel((prev) => ({ ...prev, ...partial }));
                requestStaticResync(); // Forge edits static sheets → sync the session
              }}
              onClusterPreview={handleClusterPreview}
              onClusterApply={handleClusterApply}
            />
          )}

          {tab === 'Analytics' && (
            <AnalyticsView
              analyticsSubTab={analyticsSubTab}
              onAnalyticsSubTabChange={setAnalyticsSubTab}
              validateResult={validateResult}
              modelIssues={modelIssues}
              onValidate={() => { setDryRun(true); setRunDialogOpen(true); }}
              onRun={() => { setDryRun(false); setRunDialogOpen(true); }}
              onNavigateToTable={(sheet, rowIndex) => {
                setTab('Model');
                setJumpTo({ sheet, rowIndex });
              }}
              displayResults={displayResults}
              filename={filename}
              model={analyticsModel}
              bounds={analyticsBounds}
              busIndex={analyticsBusIndex}
              analyticsFocus={analyticsFocus}
              setAnalyticsFocus={setAnalyticsFocus}
              chartSections={chartSections}
              setChartSections={setChartSections}
              dispatchRows={systemDispatchRows}
              dispatchSeries={systemDispatchSeries}
              systemLoadRows={systemLoadRows}
              systemPriceRows={systemPriceRows}
              storageRows={storageRows}
              currencySymbol={settings.currencySymbol}
              pathwayConfig={pathwayConfig}
              onSelectedPeriodChange={(period) => setPathwayConfig((current) => ({ ...current, selectedPeriod: period }))}
              onNeedSeries={setNeededRunWindows}
              backendRuns={backendRuns}
              activeRunName={activeRunName}
            />
          )}

          {tab === 'History' && (
            <div className="analytics-view">
              <div className="analytics-view-main">
                <ViewPaneHeader variant="analytics">
                  <nav className="subnav">
                    <button
                      className={`subnav-btn${historySubTab === 'Queue' ? ' subnav-btn--active' : ''}`}
                      onClick={() => setHistorySubTab('Queue')}
                    >
                      Queue{queueJobs.length > 0 ? ` (${queueJobs.length})` : ''}
                    </button>
                    <button
                      className={`subnav-btn${historySubTab === 'History' ? ' subnav-btn--active' : ''}`}
                      onClick={() => setHistorySubTab('History')}
                    >
                      History
                    </button>
                  </nav>
                </ViewPaneHeader>
                {historySubTab === 'Queue' ? (
                  <QueueView
                    jobs={queueJobs}
                    concurrency={queueConcurrency}
                    cpuCount={queueCpuCount}
                    onSetConcurrency={(n) => void handleSetQueueConcurrency(n)}
                    onCancel={handleCancelQueueItem}
                    onRerun={handleRerunQueueItem}
                    onImport={handleImportQueueItem}
                    onDelete={handleDeleteQueueItem}
                  />
                ) : (
                  <HistoryView
                    backendRuns={backendRuns}
                    onViewSelected={handleViewSelectedRuns}
                    onImportBackendRun={(name) => void handleOpenBackendRun(name, { asProject: true, restoreConstraints: true })}
                    onImportResult={() => resultImportInputRef.current?.click()}
                    convertingImports={convertingImports}
                    runActivity={runActivity}
                    onDownloadBackendXlsx={handleDownloadBackendXlsx}
                    onExportBackendProject={handleExportBackendProject}
                    onDeleteBackendRuns={handleDeleteBackendRuns}
                    onRenameBackendRun={(name, newName) => void handleRenameBackendRun(name, newName)}
                    onReload={() => void refreshBackendRuns()}
                  />
                )}
              </div>
            </div>
          )}

          {tab === 'Plugins' && (
            <PluginsView
              host={frontendPlugins}
              model={model}
              onBackendModelBuilt={async (meta) => {
                // A backend plugin already wrote the model into the session;
                // rehydrate the editor (static sheets only — series stay server-
                // side) and jump to the Model tab so the user sees the result.
                try {
                  const savedModel = await getSessionFullModel({ staticOnly: true });
                  if (savedModel) resetForNewModel(savedModel, meta.filename, { pushToSession: false });
                  // The static rehydrate carries no series, so learn the session's
                  // temporal sheets from its meta — otherwise the Model tree would
                  // hide them and they'd look "missing" (they're solved either way).
                  try {
                    setSessionSeriesCounts(seriesSheetCounts(await getSessionMeta()));
                  } catch { /* tree just won't list series; they still solve */ }
                  setTab('Model');
                } catch {
                  showToast('Built, but the editor could not reload from the session.', 'error');
                }
              }}
              onReplaceModel={(next) => resetForNewModel(next)}
              onMergeSheets={(sheets) => {
                // A plugin's contributed sheets must reach the BACKEND session
                // (the source of truth), not just the in-memory workbook —
                // otherwise the relayed model would be lost on the next run,
                // which submits by sessionId. Merge locally for the preview,
                // then relay the merged static sheets; if there's no session
                // yet, fall back to a full put.
                const next = { ...model, ...sheets };
                setModel(next);
                void putStaticModel(next).catch(() => {
                  void putSessionModel(next, { filename }).catch(() => { /* best-effort */ });
                });
              }}
              customDsl={customDsl}
              onCustomDslChange={setCustomDsl}
              results={displayResults}
            />
          )}
        </div>
      </div>

      {/* ── Run dialog ── */}
      <RunDialog
        open={runDialogOpen}
        onClose={() => setRunDialogOpen(false)}
        forceLp={forceLp}
        dryRun={dryRun}
        activeScenarioLabel={activeScenario?.label ?? null}
        activeConstraintCount={constraints.filter((row) => row.enabled).length}
        snapshotStart={snapshotStart}
        snapshotEnd={snapshotEnd}
        snapshotWeight={snapshotWeight}
        pathwayConfig={pathwayConfig}
        rollingConfig={rollingConfig}
        samplingConfig={samplingConfig}
        onForceLpChange={setForceLp}
        onDryRunChange={setDryRun}
        onRun={() => void handleRunModel(false)}
        onQueueNext={() => void handleRunModel(true)}
      />
    </div>
  );
}

function App() {
  return (
    <ToastProvider>
      <DialogProvider>
        <AppInner />
      </DialogProvider>
    </ToastProvider>
  );
}

export default App;
