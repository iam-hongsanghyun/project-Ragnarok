import React, { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSettings } from './features/settings/useSettings';
import 'leaflet/dist/leaflet.css';

import {
  AnalyticsFocus,
  BrowserFileHandle,
  ChartSectionConfig,
  CustomConstraint,
  GridRow,
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
} from './types';
import { API_BASE, DEFAULT_CONSTRAINTS, DEFAULT_SHEET_ROWS, MAX_UNPINNED_HISTORY } from './constants';
import { createEmptyWorkbook, exportWorkbook, loadSampleWorkbook, parseWorkbook, workbookToArrayBuffer, parseCsvToGridRows } from './shared/utils/workbook';
import { exportFullResults } from './shared/utils/exportResults';
import { getBounds, getBusIndex, carrierColor, hashColor, numberValue, setCarrierColorOverrides as setSharedCarrierColorOverrides, snapshotMaxFromWorkbook } from './shared/utils/helpers';
import { setCarrierColorOverrides as setLegacyCarrierColorOverrides } from './utils/helpers';
import { buildRowsFromGeneratorDetails, buildSystemLoadRows, normalizeSeriesPoint } from './shared/utils/analytics';
import { RunDialog } from './features/run/RunDialog';
import { Sidebar } from './layout/Sidebar';
import { MapPane } from './features/map/MapPane';
import { TablesPane } from './features/input/TablesPane';
import { ValidationPane } from './features/validation/ValidationPane';
import { useModelIssues } from './features/validation/useModelIssues';
import { AnalyticsPane, EmptyAnalytics } from './features/analytics/AnalyticsPane';
import { ComparisonPane } from './features/analytics/ComparisonPane';
import { ToastProvider, useToast } from './shared/components/Toast';

function AppInner() {
  const { showToast } = useToast();
  const [model, setModel] = useState<WorkbookModel>(() => createEmptyWorkbook());
  const [tab, setTab] = useState<WorkspaceTab>('Model');
  const [modelSubTab, setModelSubTab] = useState<ModelSubTab>('Map');
  const [analyticsSubTab, setAnalyticsSubTab] = useState<AnalyticsSubTab>('Result');
  const [results, setResults] = useState<RunResults | null>(null);
  const [runStatus, setRunStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle');
  const [maxSnapshots, setMaxSnapshots] = useState<number>(1);
  const [snapshotStart, setSnapshotStart] = useState(0);
  const [snapshotEnd, setSnapshotEnd] = useState(24);
  const [snapshotWeight, setSnapshotWeight] = useState(1);
  const [constraints, setConstraints] = useState<CustomConstraint[]>(DEFAULT_CONSTRAINTS);
  const [carbonPrice, setCarbonPrice] = useState<number>(0);
  const [forceLp, setForceLp] = useState<boolean>(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [analyticsFocus, setAnalyticsFocus] = useState<AnalyticsFocus>({ type: 'system' });
  const [chartSections, setChartSections] = useState<ChartSectionConfig[]>([]);
  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [runHistory, setRunHistory] = useState<RunHistoryEntry[]>([]);
  const [runCount, setRunCount] = useState(0);
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
  const modelIssues = useModelIssues(model);

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

  useEffect(() => {
    loadSampleWorkbook().then((sampleModel) => {
      if (!sampleModel) return;
      const snapshotMax = snapshotMaxFromWorkbook(sampleModel.snapshots);
      setMaxSnapshots(snapshotMax);
      setSnapshotEnd(Math.min(24, snapshotMax));
      setModel(sampleModel);
    }).catch(() => null);
  }, []);

  useEffect(() => {
    setSharedCarrierColorOverrides(model.carriers);
    setLegacyCarrierColorOverrides(model.carriers);
  }, [model.carriers]);

  const bounds = useMemo(() => getBounds(model), [model.buses]);  // eslint-disable-line react-hooks/exhaustive-deps
  const busIndex = useMemo(() => getBusIndex(model), [model.buses]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!results) { setAnalyticsFocus({ type: 'system' }); return; }
    if (analyticsFocus.type === 'system') return;
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
    setSnapshotEnd(Math.min(24, snapshotMax));
    setSnapshotStart(0);
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
    const runOptions = {
      model,
      scenario: { constraints: constraints.filter((c) => c.enabled), carbonPrice },
      options: { snapshotCount, snapshotStart, snapshotWeight, forceLp, dateFormat: settings.dateFormat, solverThreads: settings.solverThreads, solverType: settings.solverType, currencySymbol: settings.currencySymbol, enableLoadShedding: settings.enableLoadShedding },
    };

    setRunDialogOpen(false);

    if (dryRun) {
      setStatus('Validating model structure...');
      try {
        const response = await fetch(`${API_BASE}/api/validate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(runOptions),
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
    let jobId: string;
    try {
      const startResp = await fetch(`${API_BASE}/api/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(runOptions),
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
      setRunCount((n) => {
        const next = n + 1;
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
        setRunHistory((hist) => {
          const withNew = [entry, ...hist];
          const pinned = withNew.filter((e) => e.pinned);
          const unpinned = withNew.filter((e) => !e.pinned).slice(0, MAX_UNPINNED_HISTORY);
          return [...pinned, ...unpinned];
        });
        return next;
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
          pollTimerRef.current = setTimeout(poll, 2000);
        }
        return;
      }

      if (data.status === 'running') {
        pollTimerRef.current = setTimeout(poll, 1500);
        return;
      }

      // Done
      applyResult(data.result!);
    };

    // First poll after a short delay to let the process spin up
    pollTimerRef.current = setTimeout(poll, 1000);
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
      ? inferredDispatchKeys
      : (results?.carrierMix || []).map((item) => item.label).filter(Boolean);
  const systemDispatchSeries: TimeSeriesSeries[] = dispatchKeys.map((key) => ({ key, label: key, color: carrierColor(key) }));

  const rawSystemGeneratorDispatchRows: TimeSeriesRow[] = (results?.generatorDispatchSeries || []).map(normalizeSeriesPoint);
  const systemGeneratorDispatchRows: TimeSeriesRow[] =
    rawSystemGeneratorDispatchRows.some((row) =>
      Object.keys(row).some((key) => !['label', 'timestamp', 'total'].includes(key) && Math.abs(numberValue(row[key] as string | number | undefined)) > 1e-6),
    )
      ? rawSystemGeneratorDispatchRows
      : buildRowsFromGeneratorDetails(results?.assetDetails.generators || {}, 'generator');
  const generatorDispatchKeys = Array.from(
    new Set(systemGeneratorDispatchRows.flatMap((row) => Object.keys(row).filter((key) => !['label', 'timestamp', 'total'].includes(key)))),
  );
  const systemGeneratorDispatchSeries: TimeSeriesSeries[] = generatorDispatchKeys.map((key) => ({ key, label: key, color: hashColor(key) }));

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
        </nav>
      </header>

      {/* ── Sidebar + Main ── */}
      <div className="workspace-body">
        <aside className={`app-sidebar${sidebarOpen ? '' : ' app-sidebar--collapsed'}`}>
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
            />
          )}
        </aside>

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
