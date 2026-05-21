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
  Primitive,
  RunHistoryEntry,
  RunResults,
  SheetName,
  TimeSeriesRow,
  TimeSeriesSeries,
  TsSheetName,
  WorkbookModel,
  WorkspaceTab,
  ModelSubTab,
  AnalyticsSubTab,
} from './shared/types';
import { API_BASE, DEFAULT_CONSTRAINTS, DEFAULT_SHEET_ROWS, MAX_UNPINNED_HISTORY, RUN_POLLING, RUN_WINDOW } from './constants';
import { createEmptyWorkbook, exportWorkbook, loadSampleWorkbook, parseWorkbook, workbookToArrayBuffer } from './shared/utils/workbook';
import { exportFullResults } from './shared/utils/exportResults';
import { getBounds, getBusIndex, carrierColor, numberValue, orderByCarrierRows, setCarrierColorOverrides, snapshotMaxFromWorkbook } from './shared/utils/helpers';
import { buildRowsFromGeneratorDetails, buildSystemLoadRows, normalizeSeriesPoint } from './shared/utils/analytics';
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
  const [validateResult, setValidateResult] = useState<{
    valid: boolean;
    errors: string[];
    warnings: string[];
    notes: string[];
    snapshotCount: number;
    networkSummary: Record<string, number>;
  } | null>(null);
  const [status, setStatus] = useState('Ready. Open a workbook or try the demo model.');
  const [fileHandle, setFileHandle] = useState<BrowserFileHandle | null>(null);
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
  const moduleHost = useModuleHost();
  const modelIssues = useModelIssues(model);

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
  }, [model, constraints, carbonPrice, settings.discountRate, moduleHost.moduleConfigs, showToast]);

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

  // No workbook is auto-loaded — the user must explicitly Open a file or click
  // the Demo button. This avoids surprising the user with someone else's data
  // and keeps assumptions out of the empty starting state.

  useEffect(() => {
    setCarrierColorOverrides(model.carriers);
  }, [model.carriers]);

  const bounds = useMemo(() => getBounds(model), [model.buses]);  // eslint-disable-line react-hooks/exhaustive-deps
  const busIndex = useMemo(() => getBusIndex(model), [model.buses]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    // Reset focus to 'system' when results disappear or the previously-focused
    // asset is no longer present. Guarded so we never call setState if the
    // focus is already 'system' (otherwise a new {type:'system'} object would
    // trigger an infinite re-render loop on every effect tick).
    if (analyticsFocus.type === 'system') return;
    if (!results) { setAnalyticsFocus({ type: 'system' }); return; }
    if (analyticsFocus.type === 'generator' && results.assetDetails.generators[analyticsFocus.key]) return;
    if (analyticsFocus.type === 'bus' && results.assetDetails.buses[analyticsFocus.key]) return;
    if (analyticsFocus.type === 'storageUnit' && results.assetDetails.storageUnits[analyticsFocus.key]) return;
    if (analyticsFocus.type === 'store' && results.assetDetails.stores[analyticsFocus.key]) return;
    if (analyticsFocus.type === 'branch' && results.assetDetails.branches[analyticsFocus.key]) return;
    setAnalyticsFocus({ type: 'system' });
  }, [results, analyticsFocus]);

  const resetForNewModel = (nextModel: WorkbookModel, name?: string) => {
    const snapshotMax = snapshotMaxFromWorkbook(nextModel.snapshots);
    setMaxSnapshots(snapshotMax);
    // Default run window covers the FULL snapshot range of the loaded model,
    // so analytics charts show the entire output. Users can shrink the window
    // in the Run dialog if they want a shorter solve.
    setSnapshotEnd(snapshotMax);
    setSnapshotStart(RUN_WINDOW.initialSnapshotStart);
    setModel(nextModel);
    setResults(null);
    setRunStatus('idle');
    setChartSections([]);
    setValidateResult(null);
    setAnalyticsFocus({ type: 'system' });
    if (name) setFilename(name);
  };

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
      const nextRows = [...current[sheet], { ...DEFAULT_SHEET_ROWS[sheet] }];
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
    const applyResult = (nextResults: RunResults) => {
      sessionStorage.removeItem('activeJobId');
      jobIdRef.current = null;
      setResults(nextResults);
      setRunStatus('done');
      setAnalyticsFocus({ type: 'system' });
      const doneMsg = `Completed — ${nextResults.runMeta.snapshotCount} snapshots, ${nextResults.runMeta.modeledHours} h.`;
      setStatus(doneMsg);
      showToast(doneMsg, 'success');
      setRunHistory((hist) => {
        const next = hist.length + 1;
        const entry: RunHistoryEntry = {
          id: Date.now().toString(),
          label: `Run ${next}`,
          savedAt: new Date().toISOString(),
          filename,
          carbonPrice,
          snapshotStart,
          snapshotEnd,
          snapshotWeight,
          activeConstraints: constraints.filter((c) => c.enabled),
          componentCounts: {
            generators: model.generators.length,
            buses: model.buses.length,
            lines: model.lines.length,
            links: model.links.length,
            storageUnits: model.storage_units.length,
          },
          pinned: false,
          inComparison: true,
          results: nextResults,
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

  const rawSystemDispatchRows: TimeSeriesRow[] = (results?.dispatchSeries || []).map(normalizeSeriesPoint);
  const systemDispatchRows: TimeSeriesRow[] =
    rawSystemDispatchRows.some((row) =>
      Object.keys(row).some((key) => !['label', 'timestamp', 'total'].includes(key) && Math.abs(numberValue(row[key] as string | number | undefined)) > 1e-6),
    )
      ? rawSystemDispatchRows
      : buildRowsFromGeneratorDetails(results?.assetDetails.generators || {}, 'carrier');
  const inferredDispatchKeys = Array.from(
    new Set(systemDispatchRows.flatMap((row) => Object.keys(row).filter((key) => !['label', 'timestamp', 'total'].includes(key)))),
  );
  const dispatchKeys =
    inferredDispatchKeys.length > 0
      ? orderByCarrierRows(model.carriers, inferredDispatchKeys)
      : (results?.carrierMix || []).map((item) => item.label).filter(Boolean);
  const systemDispatchSeries: TimeSeriesSeries[] = dispatchKeys.map((key) => ({ key, label: key, color: carrierColor(key) }));

  const systemPriceRows: TimeSeriesRow[] = (results?.systemPriceSeries || []).map((point) => ({ label: point.label, timestamp: point.timestamp, price: point.value }));
  const storageRows: TimeSeriesRow[] = (results?.storageSeries || []).map((point) => ({ label: point.label, timestamp: point.timestamp, charge: point.charge, discharge: point.discharge, state: point.state }));
  const systemLoadRows: TimeSeriesRow[] = buildSystemLoadRows(results);

  // Seed a default chart card when results first arrive; don't reset on map-focus changes.
  useEffect(() => {
    if (!results) {
      setChartSections([]);
      return;
    }
    setChartSections([
      {
        id: 1,
        focusType: 'system',
        focusKeys: [],
        groupBy: 'carrier',
        metricKey: 'dispatch',
        chartType: 'area',
        timeframe: 'hourly',
        startIndex: 0,
        endIndex: Math.max((results.dispatchSeries.length || 1) - 1, 0),
        stacked: true,
      },
    ]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results]);

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
          {results && (
            <span className="topbar-run-meta">{results.runMeta.snapshotCount} snaps · {results.runMeta.snapshotWeight}h res</span>
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
              onDemo={() => {
                loadSampleWorkbook()
                  .then((m) => resetForNewModel(m, 'sample_model.xlsx'))
                  .catch(() => setStatus('Could not reload sample model.'));
              }}
              onExport={() => {
                if (!results) return;
                exportFullResults(model, results, filename.replace(/\.xlsx$/i, ''));
                showToast('Full model exported to Excel', 'success');
              }}
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
                {results && analyticsSubTab !== 'Validation' && (
                  <div className="inline-stats">
                    <span>{filename}</span>
                    <span>{results.runMeta.snapshotCount} snapshots</span>
                    <span>{results.runMeta.snapshotWeight}h weight</span>
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
                <ComparisonPane runHistory={runHistory} activeResults={results} onToggleComparison={handleToggleComparison} currencySymbol={settings.currencySymbol} />
              )}

              {(analyticsSubTab === 'Result' || analyticsSubTab === 'Analytics') && (
                !results ? (
                  <EmptyAnalytics />
                ) : (
                  <AnalyticsPane
                    results={results}
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
                    onExportAll={() => {
                      exportFullResults(model, results, filename.replace(/\.xlsx$/i, ''));
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
                pluginAnalytics={results?.pluginAnalytics ?? {}}
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
        maxSnapshots={maxSnapshots}
        snapshotStart={snapshotStart}
        snapshotEnd={snapshotEnd}
        snapshotWeight={snapshotWeight}
        forceLp={forceLp}
        dryRun={dryRun}
        snapshots={model.snapshots}
        dateFormat={settings.dateFormat}
        onSnapshotStartChange={setSnapshotStart}
        onSnapshotEndChange={setSnapshotEnd}
        onSnapshotWeightChange={setSnapshotWeight}
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
