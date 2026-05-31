import React, { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSettings } from './features/settings/useSettings';
import 'leaflet/dist/leaflet.css';
import 'react-calendar/dist/Calendar.css';

import {
  AnalyticsFocus,
  BrowserFileHandle,
  ChartSectionConfig,
  CustomConstraint,
  GridRow,
  PathwayConfig,
  ProjectImportProvenance,
  RollingHorizonConfig,
  StochasticConfig,
  SecurityConstrainedConfig,
  CarbonPriceScheduleEntry,
  Primitive,
  RunHistoryEntry,
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
} from 'lib/types';
import { API_BASE, DEFAULT_CONSTRAINTS, getDefaultRowForSheet, MAX_UNPINNED_HISTORY, PYPSA_SCHEMA_META, RUN_POLLING, RUN_WINDOW, SHEETS } from 'lib/constants';
import { canonicalizeOutputSeries, canonicalizeTemporalRows, createEmptyWorkbook, exportWorkbook, normalizeInputDatesToIso, parseProjectFile, parseWorkbook, projectWorkbookToArrayBuffer, workbookToArrayBuffer } from 'lib/workbook/workbook';
import { mergeWorkbookFragment } from 'lib/workbook/mergeFragment';
import type { WorkbookFragment } from 'lib/api/databases';
import { fullResultsArrayBuffer } from 'lib/export/results';
import { getBounds, getBusIndex, carrierColor, numberValue, orderByCarrierRows, setCarrierColorOverrides, snapshotMaxFromWorkbook } from 'lib/utils/helpers';
import { usePersistedState } from 'shared/hooks/usePersistedState';
import { buildRowsFromGeneratorDetails, buildSystemLoadRows, normalizeSeriesPoint } from 'lib/results/analytics';
import { withDerivedAssetDetails } from 'lib/results/assetDetails';
import { deriveRunResults } from 'lib/results/runResults';
import { defaultPathwayConfig, getDefaultSelectedPeriod, readPathwayConfigFromModel, samePathwayConfig, writePathwayConfigToModel } from 'lib/results/pathway';
import { defaultRollingConfig, normalizeRollingConfig, readRollingConfigFromModel, sameRollingConfig, writeRollingConfigToModel } from 'lib/results/rolling';
import { readCustomDslFromModel, writeCustomDslToModel } from 'lib/constraints/custom';
import { dslToSpecs } from 'lib/constraints/dsl';
import { buildScenarioPreset, defaultScenarioCatalog, readScenarioCatalogFromModel, sameScenarioCatalog, writeScenarioCatalogToModel } from 'lib/results/scenarios';
import { RunDialog } from './features/run/RunDialog';
import { SettingsView } from './views/SettingsView';
import { PluginsView } from './views/PluginsView';
import { ModelView } from './views/ModelView';
import { BuildView } from './features/build/BuildView';
import { DataView } from './views/DataView';
import { WelcomeView } from './views/WelcomeView';
import { AnalyticsView } from './views/AnalyticsView';
import { ActivityBar } from './layout/ActivityBar';
import { useModelIssues } from './features/validation/useModelIssues';
import { useFrontendPlugins } from './features/plugins/frontendPlugins';
import { ToastProvider, useToast } from './shared/components/Toast';

function AppInner() {
  const { showToast } = useToast();
  const [model, setModel] = useState<WorkbookModel>(() => createEmptyWorkbook());
  // Cell-level undo/redo. Each entry is a full (immutable) model snapshot;
  // since every mutation already builds a fresh object this is cheap to retain.
  const undoStack = useRef<WorkbookModel[]>([]);
  const redoStack = useRef<WorkbookModel[]>([]);
  const HISTORY_LIMIT = 50;
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
  }, [model]);
  const redo = useCallback(() => {
    const next = redoStack.current.pop();
    if (!next) return;
    undoStack.current.push(model);
    setModel(next);
  }, [model]);
  const [tab, setTab] = usePersistedState<WorkspaceTab>('ui:workspace-tab', 'Welcome');
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
  const [analyticsSubTab, setAnalyticsSubTab] = useState<AnalyticsSubTab>('Result');
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
  const [runStatus, setRunStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle');
  const [maxSnapshots, setMaxSnapshots] = useState<number>(RUN_WINDOW.initialMaxSnapshots);
  const [snapshotStart, setSnapshotStart] = useState(RUN_WINDOW.initialSnapshotStart);
  const [snapshotEnd, setSnapshotEnd] = useState(RUN_WINDOW.defaultSnapshotEnd);
  const [snapshotWeight, setSnapshotWeight] = useState(RUN_WINDOW.defaultSnapshotWeight);
  const [constraints, setConstraints] = useState<CustomConstraint[]>(DEFAULT_CONSTRAINTS);
  const [carbonPrice, setCarbonPrice] = useState<number>(0);
  const [forceLp, setForceLp] = useState<boolean>(false);
  const [analyticsFocus, setAnalyticsFocus] = useState<AnalyticsFocus>({ type: 'system' });
  const [chartSections, setChartSections] = useState<ChartSectionConfig[]>([]);
  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [runHistory, setRunHistory] = useState<RunHistoryEntry[]>([]);
  const [pathwayConfig, setPathwayConfig] = useState<PathwayConfig>(() => defaultPathwayConfig());
  const [rollingConfig, setRollingConfig] = useState<RollingHorizonConfig>(() => defaultRollingConfig());
  const [customDsl, setCustomDsl] = useState<string>('');
  const [stochasticConfig, setStochasticConfig] = useState<StochasticConfig>({ enabled: false, scenarios: [] });
  const [sclopfConfig, setSclopfConfig] = useState<SecurityConstrainedConfig>({ enabled: false });
  const [carbonPriceSchedule, setCarbonPriceSchedule] = useState<CarbonPriceScheduleEntry[]>([]);
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
  const [projectProvenance, setProjectProvenance] = useState<ProjectImportProvenance | null>(null);
  const [jumpTo, setJumpTo] = useState<{ sheet: string; rowIndex: number } | null>(null);
  const [runElapsed, setRunElapsed] = useState(0);
  const jobIdRef = useRef<string | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const runStartRef = useRef<number>(0);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current !== null) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const [settings, updateSettings] = useSettings();
  const [scenarioCatalog, setScenarioCatalog] = useState<ScenarioCatalog>(() => defaultScenarioCatalog({
    snapshotStart: RUN_WINDOW.initialSnapshotStart,
    snapshotEnd: RUN_WINDOW.defaultSnapshotEnd,
    snapshotWeight: RUN_WINDOW.defaultSnapshotWeight,
    carbonPrice: 0,
    discountRate: settings.discountRate,
    forceLp: false,
    enableLoadShedding: settings.enableLoadShedding,
    loadSheddingCost: settings.loadSheddingCost,
    pathwayConfig: defaultPathwayConfig(),
    rollingConfig: defaultRollingConfig(),
    constraints: DEFAULT_CONSTRAINTS,
  }));
  const frontendPlugins = useFrontendPlugins();
  const modelIssues = useModelIssues(model);

  // Topology that owns the currently displayed results: the snapshot taken at
  // run/restore time when available, else the live model (e.g. before any run).
  const analyticsModel = resultsModel ?? model;
  // Derivation inputs that own the displayed results: frozen run-time values
  // when available, else the live sliders (e.g. before any run).
  const analyticsCarbonPrice = resultsContext?.carbonPrice ?? carbonPrice;
  const analyticsSnapshotWeight = resultsContext?.snapshotWeight ?? snapshotWeight;
  const analyticsDiscountRate = resultsContext?.discountRate ?? settings.discountRate;

  const displayResults = useMemo(() => {
    if (!results) return null;
    if (!results.pathway?.enabled || !results.outputs) {
      return withDerivedAssetDetails(analyticsModel, results, settings.currencySymbol);
    }
    const selectedPeriod =
      getDefaultSelectedPeriod({
        ...pathwayConfig,
        selectedPeriod: pathwayConfig.selectedPeriod ?? results.pathway.selectedPeriod,
        periods: pathwayConfig.periods.length
          ? pathwayConfig.periods
          : results.pathway.periods.map((period, index) => ({
            period,
            objectiveWeight: results.pathway?.summaries[index]?.objectiveWeight ?? 1,
            yearsWeight: results.pathway?.summaries[index]?.yearsWeight ?? 1,
          })),
      });
    const derived = deriveRunResults(analyticsModel, results.outputs, {
      carbonPrice: analyticsCarbonPrice,
      currencySymbol: settings.currencySymbol,
      discountRate: analyticsDiscountRate,
      snapshotWeight: analyticsSnapshotWeight,
      narrative: results.narrative,
      selectedPeriod,
      pathway: {
        ...results.pathway,
        selectedPeriod,
      },
      rolling: results.rolling,
    });
    return {
      ...results,
      ...derived,
      pluginAnalytics: results.pluginAnalytics,
      meritOrder: results.meritOrder,
      co2Shadow: results.co2Shadow,
      appliedConstraints: results.appliedConstraints,
      emissionsBreakdown: results.emissionsBreakdown,
      outputs: results.outputs,
      pathway: derived.pathway,
      runMeta: derived.runMeta,
    };
  }, [results, analyticsModel, settings.currencySymbol, analyticsDiscountRate, analyticsCarbonPrice, analyticsSnapshotWeight, pathwayConfig]);

  const captureCurrentScenario = useCallback((overrides: Partial<ScenarioPreset> = {}): ScenarioPreset => (
    buildScenarioPreset({
      id: overrides.id,
      label: overrides.label,
      notes: overrides.notes,
      snapshotStart,
      snapshotEnd,
      snapshotWeight,
      carbonPrice,
      discountRate: settings.discountRate,
      forceLp,
      enableLoadShedding: settings.enableLoadShedding,
      loadSheddingCost: settings.loadSheddingCost,
      pathwayConfig: {
        ...pathwayConfig,
        selectedPeriod: getDefaultSelectedPeriod(pathwayConfig),
      },
      rollingConfig: normalizeRollingConfig(rollingConfig),
      constraints,
    })
  ), [
    snapshotStart,
    snapshotEnd,
    snapshotWeight,
    carbonPrice,
    settings.discountRate,
    settings.enableLoadShedding,
    settings.loadSheddingCost,
    forceLp,
    pathwayConfig,
    rollingConfig,
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

  const resetForNewModel = useCallback((nextModel: WorkbookModel, name?: string) => {
    // Single choke point: every temporal sheet in the incoming model becomes
    // ISO-`T` with `snapshot` leading, no matter which path the model came in
    // through (workbook import, project import, demo, plugin preview, history
    // restore, …). Idempotent — a second call on already-canonical data is a
    // no-op, so callers that pre-normalise with a project-specific dateFormat
    // (e.g. handleImportProject) stay correct.
    normalizeInputDatesToIso(nextModel, settings.dateFormat);
    const snapshotMax = snapshotMaxFromWorkbook(nextModel.snapshots);
    const nextPathway = readPathwayConfigFromModel(nextModel);
    const nextRolling = readRollingConfigFromModel(nextModel);
    setCustomDsl(readCustomDslFromModel(nextModel));
    const nextScenarioCatalog = readScenarioCatalogFromModel(nextModel);
    const activeImportedScenario = nextScenarioCatalog.scenarios.find(
      (scenario) => scenario.id === nextScenarioCatalog.activeScenarioId,
    ) ?? null;
    setMaxSnapshots(snapshotMax);
    setSnapshotEnd(snapshotMax);
    setSnapshotStart(RUN_WINDOW.initialSnapshotStart);
    setModel(nextModel);
    setResults(null);
    setResultsModel(null);
    setResultsContext(null);
    // Run history is session-scoped: it survives model swaps (new/demo/workbook/
    // project open) so prior runs stay available for comparison, and is only
    // emptied when the user clicks "Clear all" or reloads/closes Ragnarok (the
    // list lives in in-memory React state and is never persisted). Each entry
    // carries its own topology + results snapshot, so it stays self-contained
    // even after the live model is replaced. Do NOT clear it here.
    setRunStatus('idle');
    setChartSections([]);
    setValidateResult(null);
    setAnalyticsFocus({ type: 'system' });
    setProjectProvenance(null);
    const fallbackPathway = {
      ...nextPathway,
      selectedPeriod: getDefaultSelectedPeriod(nextPathway),
    };
    const fallbackRolling = normalizeRollingConfig(nextRolling);
    const fallbackScenarioCatalog = defaultScenarioCatalog({
      snapshotStart: RUN_WINDOW.initialSnapshotStart,
      snapshotEnd: snapshotMax,
      snapshotWeight,
      carbonPrice,
      discountRate: settings.discountRate,
      forceLp,
      enableLoadShedding: settings.enableLoadShedding,
      loadSheddingCost: settings.loadSheddingCost,
      pathwayConfig: fallbackPathway,
      rollingConfig: fallbackRolling,
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
    } else {
      setPathwayConfig(fallbackPathway);
      setRollingConfig(fallbackRolling);
    }
    setScenarioCatalog(catalogToApply);
    if (name) setFilename(name);
  }, [
    snapshotWeight,
    carbonPrice,
    settings.dateFormat,
    settings.discountRate,
    settings.enableLoadShedding,
    settings.loadSheddingCost,
    forceLp,
    constraints,
    updateSettings,
  ]);

  const prepareModelForBackend = useCallback((source: WorkbookModel): WorkbookModel => {
    const cloned = JSON.parse(JSON.stringify(source)) as WorkbookModel;
    normalizeInputDatesToIso(cloned, settings.dateFormat);
    return cloned;
  }, [settings.dateFormat]);

  // Elapsed-time ticker while running
  useEffect(() => {
    if (runStatus !== 'running') { setRunElapsed(0); return; }
    runStartRef.current = Date.now();
    const id = setInterval(
      () => setRunElapsed(Math.floor((Date.now() - runStartRef.current) / 1000)),
      1000,
    );
    return () => clearInterval(id);
  }, [runStatus]);

  const handleCancelRun = useCallback(async () => {
    stopPolling();
    const jobId = jobIdRef.current;
    jobIdRef.current = null;
    sessionStorage.removeItem('activeJobId');
    if (jobId) {
      try {
        await fetch(`${API_BASE}/api/run/${jobId}`, { method: 'DELETE' });
      } catch { /* ignore — process will be cleaned up server-side */ }
    }
    setRunStatus('idle');
    setStatus('Run cancelled.');
    showToast('Run cancelled', 'info');
  }, [stopPolling, showToast]);
  const [filename, setFilename] = useState('ragnarok_case.xlsx');
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const projectImportInputRef = useRef<HTMLInputElement | null>(null);

  // No workbook is auto-loaded — the user must explicitly Open a file or
  // Import Project. This avoids surprising the user with someone else's data
  // and keeps assumptions out of the empty starting state.

  useEffect(() => {
    setCarrierColorOverrides(model.carriers ?? []);
  }, [model.carriers]);

  useEffect(() => {
    setModel((current) => {
      const next = writePathwayConfigToModel(current, pathwayConfig);
      return samePathwayConfig(readPathwayConfigFromModel(current), pathwayConfig) ? current : next;
    });
  }, [pathwayConfig]);

  useEffect(() => {
    setModel((current) => {
      const next = writeRollingConfigToModel(current, rollingConfig);
      return sameRollingConfig(readRollingConfigFromModel(current), rollingConfig) ? current : next;
    });
  }, [rollingConfig]);

  useEffect(() => {
    setModel((current) => (
      readCustomDslFromModel(current) === customDsl ? current : writeCustomDslToModel(current, customDsl)
    ));
  }, [customDsl]);

  useEffect(() => {
    setModel((current) => {
      const next = writeScenarioCatalogToModel(current, scenarioCatalog);
      return sameScenarioCatalog(readScenarioCatalogFromModel(current), scenarioCatalog) ? current : next;
    });
  }, [scenarioCatalog]);

  const bounds = useMemo(() => getBounds(model), [model.buses]);  // eslint-disable-line react-hooks/exhaustive-deps
  const busIndex = useMemo(() => getBusIndex(model), [model.buses]);  // eslint-disable-line react-hooks/exhaustive-deps
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
  }, [displayResults, analyticsFocus]);

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
    try {
      const { model: nextModel, outputs, metadata } = await parseProjectFile(file);
      const importedPathway = readPathwayConfigFromModel(nextModel);
      const importedScenarios = readScenarioCatalogFromModel(nextModel);
      const importedRunState = metadata.runState;
      const importedSettings = metadata.settings;
      const importDateFormat = importedSettings?.dateFormat ?? settings.dateFormat;
      normalizeInputDatesToIso(nextModel, importDateFormat);
      canonicalizeOutputSeries(outputs.series, importDateFormat);
      const importedSnapshotWeight = importedRunState?.snapshotWeight ?? snapshotWeight;
      const importedCarbonPrice = importedRunState?.carbonPrice ?? carbonPrice;
      const importedDiscountRate = importedSettings?.discountRate ?? settings.discountRate;
      const importedCurrencySymbol = importedSettings?.currencySymbol ?? settings.currencySymbol;
      resetForNewModel(nextModel, file.name || 'ragnarok_project.xlsx');
      setFileHandle(null);
      if (importedSettings) updateSettings(importedSettings);
      if (metadata.constraints) setConstraints(metadata.constraints);
      if (importedRunState) {
        setSnapshotStart(importedRunState.snapshotStart);
        setSnapshotEnd(importedRunState.snapshotEnd);
        setSnapshotWeight(importedRunState.snapshotWeight);
        setCarbonPrice(importedRunState.carbonPrice);
        setForceLp(importedRunState.forceLp);
        if (importedRunState.activeScenarioId) {
          setScenarioCatalog((current) => ({
            ...current,
            activeScenarioId: current.scenarios.some((scenario) => scenario.id === importedRunState.activeScenarioId)
              ? importedRunState.activeScenarioId
              : current.activeScenarioId,
          }));
        }
      }
      setProjectProvenance({
        exportedAt: metadata.provenance?.exportedAt ?? '',
        exportedFilename: metadata.provenance?.exportedFilename ?? file.name,
        schemaCommitSha: metadata.provenance?.schemaCommitSha ?? '',
        schemaGeneratedAt: metadata.provenance?.schemaGeneratedAt ?? '',
        importedFromFilename: file.name,
        importedAt: new Date().toISOString(),
      });
      const hasOutputs =
        Object.keys(outputs.static).length > 0 || Object.keys(outputs.series).length > 0;
      if (hasOutputs) {
        const imported = deriveRunResults(nextModel, outputs, {
          carbonPrice: importedCarbonPrice,
          currencySymbol: importedCurrencySymbol,
          discountRate: importedDiscountRate,
          snapshotWeight: importedSnapshotWeight,
          selectedPeriod: getDefaultSelectedPeriod(importedPathway),
          pathway: metadata.pathway ?? (importedPathway.enabled ? {
            enabled: true,
            periods: importedPathway.periods.map((row) => row.period),
            selectedPeriod: getDefaultSelectedPeriod(importedPathway),
            snapshotMappingMode: importedPathway.snapshotMappingMode,
            summaries: [],
          } : null),
          rolling: metadata.rolling ?? null,
          narrative: metadata.narrative ?? [`Imported project from ${file.name}. Outputs restored from workbook.`],
        });
        imported.pluginAnalytics = metadata.pluginAnalytics;
        // Restore per-plugin form configs from the workbook. setAllConfigs
        // fully replaces the host's config map, so the imported workbook is
        // the single source of truth for plugin state (matches how settings,
        // constraints, and scenarios are restored).
        if (metadata.pluginConfigs) {
          frontendPlugins.setAllConfigs(metadata.pluginConfigs);
        }
        imported.co2Shadow = metadata.co2Shadow ?? imported.co2Shadow;
        imported.runMeta = metadata.runMeta ?? imported.runMeta;
        imported.pathway = metadata.pathway ?? imported.pathway;
        imported.rolling = metadata.rolling ?? imported.rolling;
        if (metadata.rolling) {
          setRollingConfig((current) => normalizeRollingConfig({
            ...current,
            enabled: metadata.rolling?.enabled ?? current.enabled,
            horizonSnapshots: metadata.rolling?.horizonSnapshots ?? current.horizonSnapshots,
            overlapSnapshots: metadata.rolling?.overlapSnapshots ?? current.overlapSnapshots,
            stepSnapshots: metadata.rolling?.stepSnapshots ?? current.stepSnapshots,
          }));
        }
        setResults(imported);
        setResultsModel(structuredClone(nextModel));
        setResultsContext({
          carbonPrice: importedCarbonPrice,
          snapshotWeight: importedSnapshotWeight,
          discountRate: importedDiscountRate,
        });
        setAnalyticsFocus({ type: 'system' });
        const scenarioLabel = importedScenarios.scenarios.find((scenario) => scenario.id === importedRunState?.activeScenarioId)?.label ?? null;
        const importedEntry: RunHistoryEntry = {
          id: Date.now().toString(),
          label: 'Imported project',
          scenarioLabel,
          savedAt: new Date().toISOString(),
          filename: file.name,
          carbonPrice: importedCarbonPrice,
          discountRate: importedDiscountRate,
          snapshotStart: importedRunState?.snapshotStart ?? 0,
          snapshotEnd: importedRunState?.snapshotEnd ?? snapshotMaxFromWorkbook(nextModel.snapshots),
          snapshotWeight: importedSnapshotWeight,
          activeConstraints: metadata.constraints ?? [],
          componentCounts: Object.fromEntries(
            SHEETS.map((sheet) => [sheet, nextModel[sheet]?.length ?? 0]).filter(([, n]) => n > 0),
          ),
          pinned: false,
          inComparison: true,
          results: imported,
          model: structuredClone(nextModel),
        };
        // Prepend to the session history rather than replacing it: prior runs
        // stay available for comparison across a project import.
        setRunHistory((hist) => {
          const withNew = [importedEntry, ...hist];
          const pinned = withNew.filter((e) => e.pinned);
          const unpinned = withNew.filter((e) => !e.pinned).slice(0, MAX_UNPINNED_HISTORY);
          return [...pinned, ...unpinned];
        });
        setStatus(`Imported project: ${file.name}. Full project state restored.`);
      } else {
        setStatus(`Imported project (inputs only): ${file.name}. Metadata restored.`);
      }
      showToast(`Project imported (${file.name})`, 'success');
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Project import failed.';
      setStatus(msg);
      showToast(msg, 'error');
    } finally {
      if (event.target) event.target.value = '';
    }
  };

  // Persist `data` to disk, prompting for path + file name via the File System
  // Access API when available (Chromium), and falling back to a normal download
  // elsewhere. Shared by every export (project, result workbook, HTML report) so
  // they behave identically. Returns silently when the user cancels the picker.
  const saveFileWithPicker = async (opts: {
    suggestedName: string;
    description: string;
    mime: string;
    extensions: string[];
    // Built lazily so the picker can open first (preserving the transient
    // user-activation window) before any heavy serialisation runs, and so any
    // build error is surfaced as a toast rather than a swallowed rejection.
    buildData: () => BlobPart;
    successMsg: string;
  }): Promise<void> => {
    const { suggestedName, description, mime, extensions, buildData, successMsg } = opts;
    const saver = (window as any).showSaveFilePicker;
    if (saver) {
      let handle: any;
      try {
        handle = await saver({
          suggestedName,
          types: [{ description, accept: { [mime]: extensions } }],
        });
      } catch (error) {
        if ((error as Error)?.name === 'AbortError') return;   // user cancelled
        const msg = error instanceof Error ? error.message : 'Export failed.';
        setStatus(msg);
        showToast(msg, 'error');
        return;
      }
      try {
        const data = buildData();
        const writable = await handle.createWritable();
        await writable.write(new Blob([data], { type: mime }));
        await writable.close();
        showToast(`${successMsg} → ${handle.name || suggestedName}`, 'success');
      } catch (error) {
        const msg = error instanceof Error ? error.message : 'Export failed.';
        setStatus(msg);
        showToast(msg, 'error');
      }
      return;
    }
    try {
      const blob = new Blob([buildData()], { type: mime });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = suggestedName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 0);
      showToast(successMsg, 'success');
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Export failed.';
      setStatus(msg);
      showToast(msg, 'error');
    }
  };

  const XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

  const handleExportProject = async () => {
    // Export the currently viewed run as one coherent snapshot: its own
    // topology (`analyticsModel`) paired with its outputs. Run history is a
    // comparison-only, session-scoped list and is never written to the file —
    // to export a different run, view it first (it becomes the current run).
    const base = filename.replace(/\.xlsx$/i, '') || 'ragnarok_project';
    const out = `${base}_project.xlsx`;
    const metadata = {
      pluginAnalytics: results?.pluginAnalytics,
      // Snapshot every installed plugin's stored form-config so the
      // exported workbook reproduces plugin state on the receiving end.
      // Without this, sharing a .xlsx loses everything the user typed
      // into their plugin panels.
      pluginConfigs: frontendPlugins.getAllConfigs(),
      co2Shadow: results?.co2Shadow,
      narrative: results?.narrative,
      runMeta: results?.runMeta,
      pathway: results?.pathway,
      rolling: results?.rolling,
      settings,
      constraints,
      runState: {
        snapshotStart,
        snapshotEnd,
        snapshotWeight,
        carbonPrice,
        forceLp,
        activeScenarioId: scenarioCatalog.activeScenarioId,
      },
      provenance: {
        exportedAt: new Date().toISOString(),
        exportedFilename: filename,
        schemaCommitSha: PYPSA_SCHEMA_META.commit_sha ?? PYPSA_SCHEMA_META.pypsa_version ?? '',
        schemaGeneratedAt: PYPSA_SCHEMA_META.generated_at ?? '',
        importedFromFilename: projectProvenance?.importedFromFilename ?? null,
        importedAt: projectProvenance?.importedAt ?? null,
      },
    };
    const successMsg = results?.outputs
      ? 'Project (inputs + solved outputs) exported'
      : 'Project (inputs only) exported';

    await saveFileWithPicker({
      suggestedName: out,
      description: 'Excel Workbook',
      mime: XLSX_MIME,
      extensions: ['.xlsx'],
      buildData: () => projectWorkbookToArrayBuffer(analyticsModel, results?.outputs, metadata),
      successMsg,
    });
  };

  const handleExportResultWorkbook = async () => {
    if (!displayResults) return;
    const base = filename.replace(/\.xlsx$/i, '') || 'ragnarok';
    await saveFileWithPicker({
      suggestedName: `${base}_results.xlsx`,
      description: 'Excel Workbook',
      mime: XLSX_MIME,
      extensions: ['.xlsx'],
      buildData: () => fullResultsArrayBuffer(analyticsModel, displayResults),
      successMsg: 'Result workbook exported',
    });
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
    exportViaBackend('/api/export/netcdf', `${filename.replace(/\.xlsx$/i, '') || 'ragnarok'}.nc`);
  const handleExportHdf5 = () =>
    exportViaBackend('/api/export/hdf5', `${filename.replace(/\.xlsx$/i, '') || 'ragnarok'}.h5`);

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
    const base = filename.replace(/\.xlsx$/i, '') || 'ragnarok_project';
    const archive = `${base}_csv_folder`;
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
      setModel((current) => mergeWorkbookFragment(current, fragment));
      const counts = Object.entries(fragment.sheets)
        .map(([sheet, rows]) => `${rows.length} ${sheet}`)
        .join(', ');
      const note = counts ? ` (${counts})` : '';
      const msg = `Imported ${databaseName} for ${countryName}${note}`;
      setStatus(msg);
      showToast(msg, 'success');
    },
    [pushHistory, showToast],
  );

  const handleOpenWorkbook = async () => {
    const picker = (window as any).showOpenFilePicker;
    if (!picker) {
      fileInputRef.current?.click();
      return;
    }
    try {
      const [handle] = await picker({
        excludeAcceptAllOption: true,
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
    setStatus(`Pasted ${edits.length} cell${edits.length === 1 ? '' : 's'} into ${sheet}${extraRows > 0 ? ` (+${extraRows} rows)` : ''}.`);
  };

  const addRow = (sheet: SheetName) => {
    pushHistory();
    setModel((current) => {
      const nextRows = [...(current[sheet] ?? []), { ...getDefaultRowForSheet(sheet) }];
      return { ...current, [sheet]: nextRows };
    });
    setStatus(`Added a new row to ${sheet}.`);
  };

  const deleteRow = (sheet: SheetName, rowIndex: number) => {
    pushHistory();
    setModel((current) => {
      const nextRows = current[sheet].filter((_, i) => i !== rowIndex);
      return { ...current, [sheet]: nextRows };
    });
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
  };

  const addColumn = (sheet: SheetName, col: string, defaultValue: string | number | boolean) => {
    pushHistory();
    setModel((current) => {
      const nextRows = current[sheet].map((row) =>
        col in row ? row : { ...row, [col]: defaultValue },
      );
      return { ...current, [sheet]: nextRows };
    });
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
    setStatus(`Renamed column "${oldCol}" to "${newCol}" in ${sheet}.`);
  };

  const clearSheet = (sheet: SheetName) => {
    pushHistory();
    setModel((current) => ({ ...current, [sheet]: [] }));
    setStatus(`Cleared all rows from ${sheet}.`);
  };

  const handleRestoreRun = (entry: RunHistoryEntry) => {
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
    // Load the run's inputs back into the LIVE editable state so the Model tab,
    // Build tab and any export reflect the selected run — not whatever the user
    // last edited. The stored model is the exact (date-normalised) workbook that
    // was submitted, so it drops straight into `model`. Legacy entries with no
    // stored model leave the live model untouched (prior behaviour). The prior
    // working model is pushed onto the undo stack so the swap is reversible.
    if (entry.model) {
      pushHistory();
      const restoredModel = structuredClone(entry.model);
      setModel(restoredModel);
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
    showToast(`Viewing ${entry.label}`, 'success');
  };

  const handleRenameHistoryEntry = (id: string, label: string) => {
    setRunHistory((h) => h.map((e) => (e.id === id ? { ...e, label } : e)));
  };

  const handlePinHistoryEntry = (id: string, pinned: boolean) => {
    setRunHistory((h) => {
      const updated = h.map((e) => (e.id === id ? { ...e, pinned } : e));
      const pinnedEntries = updated.filter((e) => e.pinned);
      const unpinnedEntries = updated.filter((e) => !e.pinned).slice(0, MAX_UNPINNED_HISTORY);
      return [...pinnedEntries, ...unpinnedEntries];
    });
  };

  const handleDeleteHistoryEntry = (id: string) => {
    setRunHistory((h) => h.filter((e) => e.id !== id));
  };

  const handleClearHistory = () => {
    if (runHistory.length === 0) return;
    if (!window.confirm('Clear all run history? This removes every run (including pinned) from the comparison list. The model and the currently displayed result are not affected.')) {
      return;
    }
    setRunHistory([]);
  };

  const handleToggleComparison = (id: string, inComparison: boolean) => {
    setRunHistory((h) => h.map((e) => (e.id === id ? { ...e, inComparison } : e)));
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
      const requested = window.prompt('Save workbook as', suggestedName) || suggestedName;
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

  const handleRunModel = async () => {
    // Guard against double-submit while a job is already in flight
    if (runStatus === 'running') return;
    const snapshotCount = snapshotEnd - snapshotStart;
    const scenario = {
      constraints: constraints.filter((c) => c.enabled),
      constraintSpecs: dslToSpecs(customDsl),
      carbonPrice,
      discountRate: settings.discountRate,
    };
    const options = {
      // Optimisation backend selector (backend registry resolves this; PyPSA
      // is the only adapter today). Threaded now so a future backend toggle
      // has a channel without a payload-shape change.
      backend: 'pypsa',
      snapshotCount, snapshotStart, snapshotWeight, forceLp,
      dateFormat: settings.dateFormat,
      solverThreads: settings.solverThreads, solverType: settings.solverType,
      currencySymbol: settings.currencySymbol,
      enableLoadShedding: settings.enableLoadShedding,
      loadSheddingCost: settings.loadSheddingCost,
      pathwayConfig: {
        ...pathwayConfig,
        selectedPeriod: getDefaultSelectedPeriod(pathwayConfig),
      },
      rollingConfig: normalizeRollingConfig(rollingConfig),
      stochasticConfig,
      securityConstrainedConfig: sclopfConfig,
      carbonPriceSchedule,
    };

    setRunDialogOpen(false);

    // Same ISO normalization as import/open so the backend always receives
    // canonical snapshot timestamps (and the grid stays in sync).
    const modelForRun = prepareModelForBackend(model);
    setModel(modelForRun);

    if (dryRun) {
      // Validate still receives JSON model — it's a cheap structural check
      // and does not need to round-trip through Excel.
      setStatus('Validating model structure...');
      try {
        const response = await fetch(`${API_BASE}/api/validate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model: modelForRun, scenario, options }),
        });
        const result = await response.json();
        setValidateResult(result);
        setTab('Analytics');
        setAnalyticsSubTab('Validation');
        const vMsg = result.valid ? 'Validation passed.' : `Validation failed: ${result.errors.length} error(s).`;
        setStatus(vMsg);
        showToast(vMsg, result.valid ? 'success' : 'error');
      } catch (error) {
        setStatus(error instanceof Error ? error.message : 'Validation request failed.');
      }
      return;
    }

    setRunStatus('running');
    setStatus(`Running — ${snapshotCount} snapshots…`);

    // ── Step 1: Start the job ────────────────────────────────────────────────
    // Send the in-memory workbook as JSON. The backend builds the PyPSA
    // network directly from the per-sheet rows via bulk `network.add()`.
    let jobId: string;
    try {
      const startResp = await fetch(`${API_BASE}/api/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelForRun, scenario, options }),
      });
      if (!startResp.ok) {
        const msg = await startResp.text();
        throw new Error(msg || `Failed to start run (status ${startResp.status}).`);
      }
      const { jobId: jid } = await startResp.json() as { jobId: string };
      jobId = jid;
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Failed to start run.';
      setRunStatus('error');
      setStatus(msg);
      showToast(msg, 'error');
      return;
    }

    jobIdRef.current = jobId;
    sessionStorage.setItem('activeJobId', jobId);

    // ── Step 2: Apply completed result ───────────────────────────────────────
    const applyResult = (rawResults: RunResults) => {
      sessionStorage.removeItem('activeJobId');
      jobIdRef.current = null;
      // Canonicalise backend output time-series in place (ISO-`T` snapshots,
      // `snapshot` column leading) so all downstream rendering, derivation,
      // and re-exports see uniformly PyPSA-canonical data.
      if (rawResults.outputs?.series) {
        canonicalizeOutputSeries(rawResults.outputs.series, settings.dateFormat);
      }
      const selectedPeriod = rawResults.pathway?.enabled
        ? (rawResults.pathway.selectedPeriod ?? rawResults.pathway.periods[0] ?? null)
        : null;
      setPathwayConfig((current) => rawResults.pathway?.enabled ? ({
        ...current,
        planningMode: 'pathway',
        enabled: true,
        periods: rawResults.pathway?.summaries?.map((row) => ({
          period: row.period,
          objectiveWeight: row.objectiveWeight,
          yearsWeight: row.yearsWeight,
        })) ?? current.periods,
        selectedPeriod,
      }) : {
        ...current,
        enabled: false,
        planningMode: 'single_period',
        selectedPeriod: null,
      });
      setRollingConfig((current) => rawResults.rolling ? normalizeRollingConfig({
        ...current,
        enabled: rawResults.rolling?.enabled ?? current.enabled,
        horizonSnapshots: rawResults.rolling?.horizonSnapshots ?? current.horizonSnapshots,
        overlapSnapshots: rawResults.rolling?.overlapSnapshots ?? current.overlapSnapshots,
        stepSnapshots: rawResults.rolling?.stepSnapshots ?? current.stepSnapshots,
      }) : {
        ...current,
        enabled: false,
      });
      setResults(rawResults);
      // Freeze the exact topology submitted to the backend so analytics (map,
      // asset derivation) stay tied to this run even after later edits.
      setResultsModel(structuredClone(modelForRun));
      // Freeze the derivation inputs this run was solved with, so later slider
      // edits don't silently recompute the displayed pathway KPIs.
      setResultsContext({ carbonPrice, snapshotWeight, discountRate: settings.discountRate });
      setRunStatus('done');
      setAnalyticsFocus({ type: 'system' });
      const visible = rawResults.pathway?.enabled && rawResults.outputs
        ? deriveRunResults(modelForRun, rawResults.outputs, {
          carbonPrice,
          currencySymbol: settings.currencySymbol,
          discountRate: settings.discountRate,
          snapshotWeight,
          narrative: rawResults.narrative,
          selectedPeriod,
          pathway: rawResults.pathway,
          rolling: rawResults.rolling,
        })
        : withDerivedAssetDetails(modelForRun, rawResults, settings.currencySymbol);
      const doneMsg = `Completed — ${visible.runMeta.snapshotCount} snapshots, ${visible.runMeta.modeledHours} h.`;
      setStatus(doneMsg);
      showToast(doneMsg, 'success');
      // Run finished — tell the Log tab (if open) to refresh so the user
      // sees the freshly-captured solve transcript without waiting for the
      // next poll. The LogPane listens for this on `window`. No-op when
      // the Log tab is not mounted.
      window.dispatchEvent(new CustomEvent('ragnarok:log-refresh'));
      setRunHistory((hist) => {
        const next = hist.length + 1;
        const entry: RunHistoryEntry = {
          id: Date.now().toString(),
          label: `Run ${next}`,
          scenarioLabel: activeScenario?.label ?? null,
          savedAt: new Date().toISOString(),
          filename,
          carbonPrice,
          discountRate: settings.discountRate,
          snapshotStart,
          snapshotEnd,
          snapshotWeight,
          activeConstraints: constraints.filter((c) => c.enabled),
          componentCounts: Object.fromEntries(
            SHEETS.map((sheet) => [sheet, modelForRun[sheet]?.length ?? 0]).filter(([, n]) => n > 0),
          ),
          pinned: false,
          inComparison: true,
          results: rawResults,
          model: structuredClone(modelForRun),
        };
        const withNew = [entry, ...hist];
        const pinned = withNew.filter((e) => e.pinned);
        const unpinned = withNew.filter((e) => !e.pinned).slice(0, MAX_UNPINNED_HISTORY);
        return [...pinned, ...unpinned];
      });
    };

    // ── Step 3: Poll until done ──────────────────────────────────────────────
    // The job runs independently on the backend — a brief network disconnect
    // just means polling retries, it does NOT kill the solve.
    const poll = async (): Promise<void> => {
      if (jobIdRef.current !== jobId) return; // cancelled or superseded

      let data: { jobId: string; status: string; result?: RunResults };
      try {
        const resp = await fetch(`${API_BASE}/api/run/${jobId}`);

        if (resp.status === 404) {
          // Server restarted and lost the job
          sessionStorage.removeItem('activeJobId');
          jobIdRef.current = null;
          setRunStatus('error');
          setStatus('Run disconnected — server restarted. Please run again.');
          showToast('Run disconnected — server restarted.', 'error');
          window.dispatchEvent(new CustomEvent('ragnarok:log-refresh'));
          return;
        }

        if (!resp.ok) {
          const msg = await resp.text();
          sessionStorage.removeItem('activeJobId');
          jobIdRef.current = null;
          setRunStatus('error');
          setStatus(msg || 'Backend run failed.');
          showToast(msg || 'Backend run failed.', 'error');
          window.dispatchEvent(new CustomEvent('ragnarok:log-refresh'));
          return;
        }

        data = await resp.json();
      } catch {
        // Network error — keep retrying silently
        if (jobIdRef.current === jobId) {
          pollTimerRef.current = setTimeout(poll, RUN_POLLING.retryDelayMs);
        }
        return;
      }

      if (data.status === 'running') {
        pollTimerRef.current = setTimeout(poll, RUN_POLLING.runningDelayMs);
        return;
      }

      // Done
      applyResult(data.result!);
    };

    // First poll after a short delay to let the process spin up
    pollTimerRef.current = setTimeout(poll, RUN_POLLING.initialDelayMs);
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
      <input ref={fileInputRef} type="file" accept=".xlsx,.xls" hidden onChange={handleImport} />
      <input ref={projectImportInputRef} type="file" accept=".xlsx,.xls" hidden onChange={handleImportProject} />
      <input ref={csvFolderImportInputRef} type="file" accept=".zip" hidden onChange={handleImportCsvFolder} />
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
            Ragnarok
          </button>
          <button
            className="run-button"
            onClick={() => setRunDialogOpen(true)}
            disabled={runStatus === 'running'}
            title={runStatus === 'running' ? 'A run is already in progress' : undefined}
          >
            Run
          </button>
          <button
            className="tb-btn tb-btn--muted"
            onClick={() => {
              if (!window.confirm(
                'Clear the entire cache?\n\n'
                + 'This removes:\n'
                + '  • the loaded model + every unsaved edit + every result\n'
                + '  • every persisted UI preference (column widths, panel sizes,\n'
                + '    Data-view selection, settings, run history, recent files)\n'
                + '  • every localStorage entry Ragnarok wrote\n\n'
                + 'Ragnarok will reload to the Welcome page.',
              )) return;
              // Wipe every Ragnarok-owned localStorage key. The prefixes are
              // stable across the codebase: `pypsa.*` for layout-level state,
              // `ragnarok:*` for feature-level state, `ui:*` for view-level
              // state. Untouched: third-party origin storage (none today, but
              // future-proofs against accidental cross-app erasure).
              try {
                const doomed: string[] = [];
                for (let i = 0; i < window.localStorage.length; i += 1) {
                  const key = window.localStorage.key(i);
                  if (!key) continue;
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
              // Reload so every component re-reads its now-empty persisted
              // state and the Welcome view is restored as the landing page.
              window.location.reload();
            }}
            title="Remove the loaded model AND wipe every persisted UI preference"
          >
            Clear
          </button>
          {runStatus === 'running' ? (
            <>
              <span className="topbar-running">
                <span className="topbar-spinner" />
                {Math.floor(runElapsed / 60) > 0 ? `${Math.floor(runElapsed / 60)}m ` : ''}{(runElapsed % 60).toString().padStart(2, '0')}s
              </span>
              <button className="tb-btn tb-btn--muted topbar-cancel" onClick={handleCancelRun}>Cancel</button>
            </>
          ) : null}
        </div>
        <div className="topbar-right">
          <span className="topbar-file" title={filename}>{filename}</span>
          {displayResults && (
            <span className="topbar-run-meta">{displayResults.runMeta.snapshotCount} snaps · {displayResults.runMeta.snapshotWeight}h</span>
          )}
          {runStatus !== 'running' && (
            <span className="topbar-status" title={status}>{status}</span>
          )}
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
              stochasticConfig={stochasticConfig}
              onStochasticConfigChange={setStochasticConfig}
              sclopfConfig={sclopfConfig}
              onSclopfConfigChange={setSclopfConfig}
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
              onSolverThreadsChange={(v) => updateSettings({ solverThreads: v })}
              onSolverTypeChange={(v) => updateSettings({ solverType: v })}
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
              hasResults={Boolean(results)}
              onOpen={handleOpenWorkbook}
              onSave={saveWorkbook}
              onSaveAs={saveAsWorkbook}
              onImportProject={() => projectImportInputRef.current?.click()}
              onExportProject={handleExportProject}
              onExportResult={handleExportResultWorkbook}
              onImportCsvFolder={() => csvFolderImportInputRef.current?.click()}
              onExportCsvFolder={handleExportCsvFolder}
              onImportNetcdf={() => netcdfImportInputRef.current?.click()}
              onExportNetcdf={handleExportNetcdf}
              onImportHdf5={() => hdf5ImportInputRef.current?.click()}
              onExportHdf5={handleExportHdf5}
            />
          )}

          {tab === 'Welcome' && <WelcomeView onNavigate={setTab} />}

          {tab === 'Data' && <DataView onApplyFragment={handleApplyImportedFragment} />}

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
              runHistory={runHistory}
              currencySymbol={settings.currencySymbol}
              pathwayConfig={pathwayConfig}
              onSelectedPeriodChange={(period) => setPathwayConfig((current) => ({ ...current, selectedPeriod: period }))}
              onExportAll={handleExportResultWorkbook}
              onToggleComparison={handleToggleComparison}
              onRestoreRun={handleRestoreRun}
              onRenameHistoryEntry={handleRenameHistoryEntry}
              onPinHistoryEntry={handlePinHistoryEntry}
              onDeleteHistoryEntry={handleDeleteHistoryEntry}
              onClearHistory={handleClearHistory}
            />
          )}

          {tab === 'Plugins' && (
            <PluginsView
              host={frontendPlugins}
              model={model}
              onReplaceModel={(next) => resetForNewModel(next)}
              onMergeSheets={(sheets) => setModel((prev) => ({ ...prev, ...sheets }))}
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
        onForceLpChange={setForceLp}
        onDryRunChange={setDryRun}
        onRun={handleRunModel}
      />
    </div>
  );
}

function App() {
  return (
    <ToastProvider>
      <AppInner />
    </ToastProvider>
  );
}

export default App;
