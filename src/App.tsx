import React, { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSettings } from './features/settings/useSettings';
import 'leaflet/dist/leaflet.css';

import {
  AnalyticsFocus,
  BrowserFileHandle,
  ChartSectionConfig,
  CustomConstraint,
  GridRow,
  ModuleConfigField,
  ModuleDescriptor,
  PathwayConfig,
  ProjectImportProvenance,
  RollingHorizonConfig,
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
  ModelSubTab,
  AnalyticsSubTab,
} from './shared/types';
import { API_BASE, DEFAULT_CONSTRAINTS, getDefaultRowForSheet, MAX_UNPINNED_HISTORY, PYPSA_SCHEMA_META, RUN_POLLING, RUN_WINDOW, SHEETS } from './constants';
import { createEmptyWorkbook, exportProjectWorkbook, exportWorkbook, parseProjectFile, parseWorkbook, workbookToArrayBuffer } from './shared/utils/workbook';
import { exportFullResults } from './shared/utils/exportResults';
import { exportReportHtml } from './shared/utils/exportReport';
import { getBounds, getBusIndex, carrierColor, numberValue, orderByCarrierRows, setCarrierColorOverrides, snapshotMaxFromWorkbook } from './shared/utils/helpers';
import { buildRowsFromGeneratorDetails, buildSystemLoadRows, normalizeSeriesPoint } from './shared/utils/analytics';
import { withDerivedAssetDetails } from './shared/utils/deriveAssetDetails';
import { deriveRunResults } from './shared/utils/deriveRunResults';
import { defaultPathwayConfig, getDefaultSelectedPeriod, readPathwayConfigFromModel, samePathwayConfig, writePathwayConfigToModel } from './shared/utils/pathway';
import { defaultRollingConfig, normalizeRollingConfig, readRollingConfigFromModel, sameRollingConfig, writeRollingConfigToModel } from './shared/utils/rolling';
import { buildScenarioPreset, defaultScenarioCatalog, readScenarioCatalogFromModel, sameScenarioCatalog, writeScenarioCatalogToModel } from './shared/utils/scenarios';
import { RunDialog } from './features/run/RunDialog';
import { Sidebar } from './layout/Sidebar';
import { MapPane } from './features/map/MapPane';
import { TablesPane } from './features/input/TablesPane';
import { ValidationPane } from './features/validation/ValidationPane';
import { useModelIssues } from './features/validation/useModelIssues';
import { AnalyticsPane, EmptyAnalytics } from './features/analytics/AnalyticsPane';
import { ComparisonPane } from './features/analytics/ComparisonPane';
import { useModuleHost } from './features/modules/useModuleHost';
import { PluginPanel } from './features/plugins/PluginPanel';
import { ToastProvider, useToast } from './shared/components/Toast';

function AppInner() {
  const { showToast } = useToast();
  const [model, setModel] = useState<WorkbookModel>(() => createEmptyWorkbook());
  const [tab, setTab] = useState<WorkspaceTab>('Model');
  const [modelSubTab, setModelSubTab] = useState<ModelSubTab>('Map');
  const [analyticsSubTab, setAnalyticsSubTab] = useState<AnalyticsSubTab>('Result');
  const [results, setResults] = useState<RunResults | null>(null);
  const [runStatus, setRunStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle');
  const [maxSnapshots, setMaxSnapshots] = useState<number>(RUN_WINDOW.initialMaxSnapshots);
  const [snapshotStart, setSnapshotStart] = useState(RUN_WINDOW.initialSnapshotStart);
  const [snapshotEnd, setSnapshotEnd] = useState(RUN_WINDOW.defaultSnapshotEnd);
  const [snapshotWeight, setSnapshotWeight] = useState(RUN_WINDOW.defaultSnapshotWeight);
  const [constraints, setConstraints] = useState<CustomConstraint[]>(DEFAULT_CONSTRAINTS);
  const [carbonPrice, setCarbonPrice] = useState<number>(0);
  const [forceLp, setForceLp] = useState<boolean>(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(252);
  const [isDraggingSidebar, setIsDraggingSidebar] = useState(false);
  const dragStartX = useRef<number>(0);
  const dragStartWidth = useRef<number>(252);
  const [analyticsFocus, setAnalyticsFocus] = useState<AnalyticsFocus>({ type: 'system' });
  const [chartSections, setChartSections] = useState<ChartSectionConfig[]>([]);
  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [runHistory, setRunHistory] = useState<RunHistoryEntry[]>([]);
  const [pathwayConfig, setPathwayConfig] = useState<PathwayConfig>(() => defaultPathwayConfig());
  const [rollingConfig, setRollingConfig] = useState<RollingHorizonConfig>(() => defaultRollingConfig());
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
  const moduleHost = useModuleHost();
  const modelIssues = useModelIssues(model);

  const displayResults = useMemo(() => {
    if (!results) return null;
    if (!results.pathway?.enabled || !results.outputs) {
      return withDerivedAssetDetails(model, results, settings.currencySymbol);
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
    const derived = deriveRunResults(model, results.outputs, {
      carbonPrice,
      currencySymbol: settings.currencySymbol,
      discountRate: settings.discountRate,
      snapshotWeight,
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
      emissionsBreakdown: results.emissionsBreakdown,
      outputs: results.outputs,
      pathway: derived.pathway,
      runMeta: derived.runMeta,
    };
  }, [results, model, settings.currencySymbol, settings.discountRate, carbonPrice, snapshotWeight, pathwayConfig]);

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
    const snapshotMax = snapshotMaxFromWorkbook(nextModel.snapshots);
    const nextPathway = readPathwayConfigFromModel(nextModel);
    const nextRolling = readRollingConfigFromModel(nextModel);
    const nextScenarioCatalog = readScenarioCatalogFromModel(nextModel);
    const activeImportedScenario = nextScenarioCatalog.scenarios.find(
      (scenario) => scenario.id === nextScenarioCatalog.activeScenarioId,
    ) ?? null;
    setMaxSnapshots(snapshotMax);
    setSnapshotEnd(snapshotMax);
    setSnapshotStart(RUN_WINDOW.initialSnapshotStart);
    setModel(nextModel);
    setResults(null);
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
    settings.discountRate,
    settings.enableLoadShedding,
    settings.loadSheddingCost,
    forceLp,
    constraints,
    updateSettings,
  ]);

  const handleInstallModule = useCallback(async (file: File) => {
    const result = await moduleHost.installFromFile(file);
    if (!result.ok) {
      showToast(result.error || 'Module install failed.', 'error');
      setStatus(result.error || 'Module install failed.');
      return;
    }
    const moduleId = result.moduleId ? ` (${result.moduleId})` : '';
    showToast(`Module installed${moduleId}`, 'success');
    setStatus(`Installed local module${moduleId}.`);
  }, [moduleHost, showToast]);

  const handleUninstallModule = useCallback(async (module: ModuleDescriptor) => {
    const confirmed = window.confirm(`Uninstall local module "${module.name || module.id}"? This removes it completely from the managed module directory.`);
    if (!confirmed) return;
    const result = await moduleHost.uninstall(module.id);
    if (!result.ok) {
      showToast(result.error || 'Module uninstall failed.', 'error');
      setStatus(result.error || 'Module uninstall failed.');
      return;
    }
    showToast(`Module uninstalled (${module.id})`, 'success');
    setStatus(`Uninstalled local module ${module.id}.`);
  }, [moduleHost, showToast]);

  const handleModuleAction = useCallback(async (
    moduleId: string,
    fieldKey: string,
    field: ModuleConfigField,
  ) => {
    if (field.type !== 'action') return;
    if (field.hook && field.hook !== 'transform') {
      showToast(`Unsupported action hook "${field.hook}".`, 'error');
      return;
    }
    const scenario = {
      constraints: constraints.filter((c) => c.enabled),
      carbonPrice,
      discountRate: settings.discountRate,
    };
    const options = {
      moduleConfigs: moduleHost.moduleConfigs,
    };
    try {
      const resp = await fetch(`${API_BASE}/api/modules/${encodeURIComponent(moduleId)}/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model, scenario, options }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        const detail = typeof data.detail === 'string' ? data.detail : `Preview failed (${resp.status}).`;
        showToast(detail, 'error');
        setStatus(detail);
        return;
      }
      if (!data.model) {
        showToast('Plugin returned no model.', 'error');
        return;
      }
      resetForNewModel(data.model as WorkbookModel);
      const msg = field.successMessage || 'Model loaded into Ragnarok workbook.';
      showToast(msg, 'success');
      setStatus(msg);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Plugin preview failed.';
      showToast(msg, 'error');
      setStatus(msg);
    }
  }, [model, constraints, carbonPrice, settings.discountRate, moduleHost.moduleConfigs, resetForNewModel, showToast]);

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
    setCarrierColorOverrides(model.carriers);
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
    setModel((current) => {
      const next = writeScenarioCatalogToModel(current, scenarioCatalog);
      return sameScenarioCatalog(readScenarioCatalogFromModel(current), scenarioCatalog) ? current : next;
    });
  }, [scenarioCatalog]);

  const bounds = useMemo(() => getBounds(model), [model.buses]);  // eslint-disable-line react-hooks/exhaustive-deps
  const busIndex = useMemo(() => getBusIndex(model), [model.buses]);  // eslint-disable-line react-hooks/exhaustive-deps

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
      if (metadata.runHistory) setRunHistory(metadata.runHistory);
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
        setAnalyticsFocus({ type: 'system' });
        if (!metadata.runHistory || metadata.runHistory.length === 0) {
          const scenarioLabel = importedScenarios.scenarios.find((scenario) => scenario.id === importedRunState?.activeScenarioId)?.label ?? null;
          setRunHistory([{
            id: Date.now().toString(),
            label: 'Imported project',
            scenarioLabel,
            savedAt: new Date().toISOString(),
            filename: file.name,
            carbonPrice: importedCarbonPrice,
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
          }]);
        }
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

  const handleExportProject = () => {
    const base = filename.replace(/\.xlsx$/i, '') || 'ragnarok_project';
    const out = `${base}_project.xlsx`;
    try {
      exportProjectWorkbook(model, results?.outputs, {
        pluginAnalytics: results?.pluginAnalytics,
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
        runHistory,
        provenance: {
          exportedAt: new Date().toISOString(),
          exportedFilename: filename,
          schemaCommitSha: PYPSA_SCHEMA_META.commit_sha,
          schemaGeneratedAt: PYPSA_SCHEMA_META.generated_at,
          importedFromFilename: projectProvenance?.importedFromFilename ?? null,
          importedAt: projectProvenance?.importedAt ?? null,
        },
      }, out);
      showToast(
        results?.outputs
          ? 'Project (inputs + solved outputs) exported'
          : 'Project (inputs only) exported',
        'success',
      );
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Project export failed.';
      setStatus(msg);
      showToast(msg, 'error');
    }
  };

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
    setModel((current) => {
      const nextRows = current[sheet].map((row, index) => (index === rowIndex ? { ...row, [key]: value } : row));
      return { ...current, [sheet]: nextRows };
    });
  };

  const addRow = (sheet: SheetName) => {
    setModel((current) => {
      const nextRows = [...(current[sheet] ?? []), { ...getDefaultRowForSheet(sheet) }];
      return { ...current, [sheet]: nextRows };
    });
    setStatus(`Added a new row to ${sheet}.`);
  };

  const deleteRow = (sheet: SheetName, rowIndex: number) => {
    setModel((current) => {
      const nextRows = current[sheet].filter((_, i) => i !== rowIndex);
      return { ...current, [sheet]: nextRows };
    });
    setStatus(`Removed row ${rowIndex + 1} from ${sheet}.`);
  };

  const moveRow = (sheet: SheetName, rowIndex: number, direction: -1 | 1) => {
    setModel((current) => {
      const nextIndex = rowIndex + direction;
      if (nextIndex < 0 || nextIndex >= current[sheet].length) return current;
      const nextRows = [...current[sheet]];
      const [row] = nextRows.splice(rowIndex, 1);
      nextRows.splice(nextIndex, 0, row);
      return { ...current, [sheet]: nextRows };
    });
  };

  const addColumn = (sheet: SheetName, col: string, defaultValue: string | number | boolean) => {
    setModel((current) => {
      const nextRows = current[sheet].map((row) =>
        col in row ? row : { ...row, [col]: defaultValue },
      );
      return { ...current, [sheet]: nextRows };
    });
    setStatus(`Added column "${col}" to ${sheet}.`);
  };

  const deleteColumn = (sheet: SheetName, col: string) => {
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

  const handleRestoreRun = (entry: RunHistoryEntry) => {
    setResults(entry.results);
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
    setTab('Analytics');
    setAnalyticsSubTab('Result');
    setAnalyticsFocus({ type: 'system' });
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
    setModel((current) => ({ ...current, [sheet]: rows }));
    if (rows.length > 0) {
      showToast(`Imported ${rows.length} rows into ${sheet}`, 'success');
      setStatus(`Imported ${rows.length} rows into ${sheet}.`);
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
      exportWorkbook(model, requested);
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
      await writable.write(workbookToArrayBuffer(model));
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
      await writable.write(workbookToArrayBuffer(model));
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
      carbonPrice,
      discountRate: settings.discountRate,
    };
    const options = {
      snapshotCount, snapshotStart, snapshotWeight, forceLp,
      dateFormat: settings.dateFormat,
      solverThreads: settings.solverThreads, solverType: settings.solverType,
      currencySymbol: settings.currencySymbol,
      enableLoadShedding: settings.enableLoadShedding,
      loadSheddingCost: settings.loadSheddingCost,
      enabledModules: moduleHost.enabledIds,
      moduleConfigs: moduleHost.moduleConfigs,
      pathwayConfig: {
        ...pathwayConfig,
        selectedPeriod: getDefaultSelectedPeriod(pathwayConfig),
      },
      rollingConfig: normalizeRollingConfig(rollingConfig),
    };

    setRunDialogOpen(false);

    if (dryRun) {
      // Validate still receives JSON model — it's a cheap structural check
      // and does not need to round-trip through Excel.
      setStatus('Validating model structure...');
      try {
        const response = await fetch(`${API_BASE}/api/validate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model, scenario, options }),
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
        body: JSON.stringify({ model, scenario, options }),
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
      setRunStatus('done');
      setAnalyticsFocus({ type: 'system' });
      const visible = rawResults.pathway?.enabled && rawResults.outputs
        ? deriveRunResults(model, rawResults.outputs, {
          carbonPrice,
          currencySymbol: settings.currencySymbol,
          discountRate: settings.discountRate,
          snapshotWeight,
          narrative: rawResults.narrative,
          selectedPeriod,
          pathway: rawResults.pathway,
          rolling: rawResults.rolling,
        })
        : withDerivedAssetDetails(model, rawResults, settings.currencySymbol);
      const doneMsg = `Completed — ${visible.runMeta.snapshotCount} snapshots, ${visible.runMeta.modeledHours} h.`;
      setStatus(doneMsg);
      showToast(doneMsg, 'success');
      setRunHistory((hist) => {
        const next = hist.length + 1;
        const entry: RunHistoryEntry = {
          id: Date.now().toString(),
          label: `Run ${next}`,
          scenarioLabel: activeScenario?.label ?? null,
          savedAt: new Date().toISOString(),
          filename,
          carbonPrice,
          snapshotStart,
          snapshotEnd,
          snapshotWeight,
          activeConstraints: constraints.filter((c) => c.enabled),
          componentCounts: Object.fromEntries(
            SHEETS.map((sheet) => [sheet, model[sheet]?.length ?? 0]).filter(([, n]) => n > 0),
          ),
          pinned: false,
          inComparison: true,
          results: rawResults,
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
          return;
        }

        if (!resp.ok) {
          const msg = await resp.text();
          sessionStorage.removeItem('activeJobId');
          jobIdRef.current = null;
          setRunStatus('error');
          setStatus(msg || 'Backend run failed.');
          showToast(msg || 'Backend run failed.', 'error');
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

  // ── Sidebar resize handlers ──────────────────────────────────────────────────
  const handleResizeMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragStartX.current = e.clientX;
    dragStartWidth.current = sidebarWidth;
    setIsDraggingSidebar(true);

    const onMove = (ev: MouseEvent) => {
      const delta = ev.clientX - dragStartX.current;
      const next  = Math.min(520, Math.max(180, dragStartWidth.current + delta));
      setSidebarWidth(next);
    };
    const onUp = () => {
      setIsDraggingSidebar(false);
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [sidebarWidth]);

  return (
    <div className="studio-shell">
      <input ref={fileInputRef} type="file" accept=".xlsx,.xls" hidden onChange={handleImport} />
      <input ref={projectImportInputRef} type="file" accept=".xlsx,.xls" hidden onChange={handleImportProject} />

      {/* ── Top bar ── */}
      <header className="topbar">
        <div className="topbar-left">
          <span className="topbar-brand">Ragnarok</span>
          <div className="topbar-divider" />
          <button
            className="run-button"
            onClick={() => setRunDialogOpen(true)}
            disabled={runStatus === 'running'}
            title={runStatus === 'running' ? 'A run is already in progress' : undefined}
          >
            Run
          </button>
          <button className="tb-btn" onClick={handleOpenWorkbook}>Open</button>
          <button
            className="tb-btn tb-btn--muted"
            onClick={() => {
              if (!window.confirm('Clear the loaded model? All unsaved edits and results will be lost.')) return;
              resetForNewModel(createEmptyWorkbook(), 'untitled.xlsx');
              setFileHandle(null);
              setStatus('Model cleared.');
              showToast('Model cleared', 'success');
            }}
            title="Remove the currently loaded model and start from an empty workbook"
          >
            Clear
          </button>
          <div className="topbar-divider" />
          <span className="topbar-file">{filename}</span>
          {displayResults && (
            <span className="topbar-run-meta">{displayResults.runMeta.snapshotCount} snaps · {displayResults.runMeta.snapshotWeight}h res</span>
          )}
          {runStatus === 'running' ? (
            <>
              <span className="topbar-running">
                <span className="topbar-spinner" />
                Running… {Math.floor(runElapsed / 60) > 0 ? `${Math.floor(runElapsed / 60)}m ` : ''}{(runElapsed % 60).toString().padStart(2, '0')}s
              </span>
              <button className="tb-btn tb-btn--muted topbar-cancel" onClick={handleCancelRun}>Cancel</button>
            </>
          ) : (
            <span className="topbar-status" title={status}>{status}</span>
          )}
        </div>
        <nav className="tab-nav">
          {(['Model', 'Analytics'] as WorkspaceTab[]).map((item) => (
            <button
              key={item}
              className={`tab-button ${tab === item ? 'is-active' : ''}`}
              onClick={() => setTab(item)}
            >
              {item}
              {item === 'Analytics' && validateResult && (
                <span className={`tab-badge ${validateResult.valid ? 'tab-badge--ok' : 'tab-badge--error'}`}>
                  {validateResult.valid ? 'ok' : `${validateResult.errors.length + validateResult.warnings.length}`}
                </span>
              )}
            </button>
          ))}
          {moduleHost.enabledIds.length > 0 && (
            <button
              className={`tab-button ${tab === 'Plugins' ? 'is-active' : ''}`}
              onClick={() => setTab('Plugins')}
            >
              Plugins
              <span className="tab-badge tab-badge--ok">
                {moduleHost.enabledIds.length}
              </span>
            </button>
          )}
        </nav>
      </header>

      {/* ── Sidebar + Main ── */}
      <div className="workspace-body" style={isDraggingSidebar ? { userSelect: 'none', cursor: 'col-resize' } : undefined}>
        <aside
          className={`app-sidebar${sidebarOpen ? '' : ' app-sidebar--collapsed'}`}
          style={sidebarOpen ? { width: sidebarWidth } : undefined}
        >
          <button className="sidebar-toggle" onClick={() => setSidebarOpen((o) => !o)} title={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}>
            {sidebarOpen ? '<' : '>'}
          </button>
          {sidebarOpen && (
            <Sidebar
              model={model}
              results={results}
              constraints={constraints}
              onConstraintsChange={setConstraints}
              onOpen={handleOpenWorkbook}
              onSave={saveWorkbook}
              onSaveAs={saveAsWorkbook}
              onImportProject={() => projectImportInputRef.current?.click()}
              onExportProject={handleExportProject}
              onExportResult={() => {
                if (!displayResults) return;
                exportFullResults(model, displayResults, filename.replace(/\.xlsx$/i, ''));
                showToast('Result workbook exported', 'success');
              }}
              onExportReport={() => {
                if (!displayResults) return;
                const base = filename.replace(/\.xlsx$/i, '') || 'ragnarok_report';
                exportReportHtml(displayResults, {
                  filename: `${base}_report`,
                  projectName: base,
                  currencySymbol: settings.currencySymbol,
                });
                showToast('HTML report exported', 'success');
              }}
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
              maxSnapshots={maxSnapshots}
              snapshotStart={snapshotStart}
              snapshotEnd={snapshotEnd}
              snapshotWeight={snapshotWeight}
              onSnapshotStartChange={setSnapshotStart}
              onSnapshotEndChange={setSnapshotEnd}
              onSnapshotWeightChange={setSnapshotWeight}
              runHistory={runHistory}
              onRestoreRun={handleRestoreRun}
              onRenameHistoryEntry={handleRenameHistoryEntry}
              onPinHistoryEntry={handlePinHistoryEntry}
              onDeleteHistoryEntry={handleDeleteHistoryEntry}
              onToggleComparison={handleToggleComparison}
              dateFormat={settings.dateFormat}
              onDateFormatChange={(f) => updateSettings({ dateFormat: f })}
              solverThreads={settings.solverThreads}
              solverType={settings.solverType}
              onSolverThreadsChange={(v) => updateSettings({ solverThreads: v })}
              onSolverTypeChange={(v) => updateSettings({ solverType: v })}
              currencyCode={settings.currencyCode}
              currencySymbol={settings.currencySymbol}
              onCurrencyChange={(code, symbol) => updateSettings({ currencyCode: code, currencySymbol: symbol })}
              carbonPrice={carbonPrice}
              onCarbonPriceChange={setCarbonPrice}
              enableLoadShedding={settings.enableLoadShedding}
              onEnableLoadSheddingChange={(v) => updateSettings({ enableLoadShedding: v })}
              loadSheddingCost={settings.loadSheddingCost}
              onLoadSheddingCostChange={(v) => updateSettings({ loadSheddingCost: v })}
              discountRate={settings.discountRate}
              onDiscountRateChange={(v) => updateSettings({ discountRate: v })}
              moduleInventory={moduleHost.inventory}
              moduleHostLoading={moduleHost.loading}
              moduleHostError={moduleHost.error}
              enabledModuleIds={moduleHost.enabledIds}
              isModuleEnabled={moduleHost.isEnabled}
              isModuleEnableEligible={moduleHost.isEnableEligible}
              onToggleModuleEnabled={moduleHost.toggleEnabled}
              onInstallModule={handleInstallModule}
              onUninstallModule={handleUninstallModule}
              onCarrierColorChange={(rowIndex, color) => updateRowValue('carriers', rowIndex, 'color', color)}
              onCarrierMove={(rowIndex, direction) => moveRow('carriers', rowIndex, direction)}
            />
          )}
        </aside>

        {/* Drag-to-resize handle */}
        {sidebarOpen && (
          <div
            className={`sidebar-resize-handle${isDraggingSidebar ? ' sidebar-resize-handle--dragging' : ''}`}
            onMouseDown={handleResizeMouseDown}
            title="Drag to resize sidebar"
          />
        )}

        <div className="workspace-main">

          {/* ── Model tab ── */}
          {tab === 'Model' && (
            <div className="pane model-pane">
              <div className="pane-header model-pane-header">
                <nav className="subnav">
                  {(['Map', 'Table'] as ModelSubTab[]).map((s) => (
                    <button
                      key={s}
                      className={`subnav-btn${modelSubTab === s ? ' subnav-btn--active' : ''}`}
                      onClick={() => setModelSubTab(s)}
                    >{s}</button>
                  ))}
                </nav>
              </div>
              {modelSubTab === 'Map' && (
                <MapPane model={model} bounds={bounds} busIndex={busIndex} />
              )}
              {modelSubTab === 'Table' && (
                <TablesPane
                  model={model}
                  onUpdate={updateRowValue}
                  onAddRow={addRow}
                  onDeleteRow={deleteRow}
                  onAddColumn={addColumn}
                  onDeleteColumn={deleteColumn}
                  onRenameColumn={renameColumn}
                  onImportTsSheet={handleImportTsSheet}
                  issues={modelIssues}
                  jumpTo={jumpTo}
                  currencySymbol={settings.currencySymbol}
                />
              )}
            </div>
          )}

          {/* ── Analytics tab ── */}
          {tab === 'Analytics' && (
            <div className="pane analytics-outer-pane">
              <div className="pane-header analytics-outer-header">
                <nav className="subnav">
                  {(['Validation', 'Result', 'Analytics', 'Comparison'] as AnalyticsSubTab[]).map((s) => (
                    <button
                      key={s}
                      className={`subnav-btn${analyticsSubTab === s ? ' subnav-btn--active' : ''}${
                        s === 'Validation' && validateResult && !validateResult.valid ? ' subnav-btn--error' : ''}${
                        s === 'Validation' && validateResult?.valid ? ' subnav-btn--ok' : ''}`}
                      onClick={() => setAnalyticsSubTab(s)}
                    >
                      {s}
                      {s === 'Validation' && modelIssues.filter(i => i.severity === 'error').length > 0 && (
                        <span className="tab-badge tab-badge--error">
                          {modelIssues.filter(i => i.severity === 'error').length}
                        </span>
                      )}
                      {s === 'Validation' && modelIssues.filter(i => i.severity === 'error').length === 0 && validateResult && (
                        <span className={`tab-badge ${validateResult.valid ? 'tab-badge--ok' : 'tab-badge--error'}`}>
                          {validateResult.valid ? 'ok' : validateResult.errors.length + validateResult.warnings.length}
                        </span>
                      )}
                    </button>
                  ))}
                </nav>
                {displayResults && analyticsSubTab !== 'Validation' && (
                  <div className="inline-stats">
                    <span>{filename}</span>
                    <span>{displayResults.runMeta.snapshotCount} snapshots</span>
                    <span>{displayResults.runMeta.snapshotWeight}h weight</span>
                  </div>
                )}
              </div>

              {analyticsSubTab === 'Validation' && (
                <ValidationPane
                  validateResult={validateResult}
                  issues={modelIssues}
                  onValidate={() => { setDryRun(true); setRunDialogOpen(true); }}
                  onRun={() => { setDryRun(false); setRunDialogOpen(true); }}
                  onNavigate={(sheet, rowIndex) => {
                    setTab('Model');
                    setModelSubTab('Table');
                    setJumpTo({ sheet, rowIndex });
                  }}
                />
              )}

              {analyticsSubTab === 'Comparison' && (
              <ComparisonPane runHistory={runHistory} activeResults={displayResults} onToggleComparison={handleToggleComparison} currencySymbol={settings.currencySymbol} />
            )}

              {(analyticsSubTab === 'Result' || analyticsSubTab === 'Analytics') && (
                !displayResults ? (
                  <EmptyAnalytics />
                ) : (
                  <AnalyticsPane
                    results={displayResults}
                    filename={filename}
                    model={model}
                    bounds={bounds}
                    busIndex={busIndex}
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
                    subTab={analyticsSubTab}
                    currencySymbol={settings.currencySymbol}
                    pathwayConfig={pathwayConfig}
                    onSelectedPeriodChange={(period) => setPathwayConfig((current) => ({ ...current, selectedPeriod: period }))}
                    onExportAll={() => {
                      exportFullResults(model, displayResults, filename.replace(/\.xlsx$/i, ''));
                      showToast('Full results exported to Excel', 'success');
                    }}
                  />
                )
              )}
            </div>
          )}

          {tab === 'Plugins' && (() => {
            const enabledModules = moduleHost.modules.filter(
              (m) => moduleHost.enabledIds.includes(m.id) && moduleHost.isEnableEligible(m)
            );
            const carriers = Array.from(
              new Set(model.carriers.map((c) => String(c.name ?? '')).filter(Boolean))
            );
            return (
              <PluginPanel
                modules={enabledModules}
                moduleConfigs={moduleHost.moduleConfigs}
                onModuleConfigChange={moduleHost.setModuleConfig}
                carriers={carriers}
                pluginAnalytics={displayResults?.pluginAnalytics ?? {}}
                onModuleAction={handleModuleAction}
              />
            );
          })()}
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
