/**
 * History view — browse and manage persisted past runs.
 *
 * The backend is the single source of truth for run history: every successful
 * solve is stored server-side (see backend/app/run_store.py) and listed here as
 * a lightweight meta sidecar, so a full-year result never has to be downloaded
 * just to enumerate runs. Each row offers a select checkbox (drives bulk
 * delete), name + metadata, and inline actions: View results (fetches the full
 * bundle into the viewer), Download Excel, Delete.
 */
import React, { useMemo, useState } from 'react';
import { BackendRunMeta } from 'lib/types';
import { formatRelTime } from 'lib/utils/formatRelTime';

interface HistoryViewProps {
  backendRuns: BackendRunMeta[];
  /** View the current selection: 1 → its Result, 2+ → side-by-side Comparison. */
  onViewSelected: (names: string[]) => void;
  /** Import the run's model into the editable session for edit + re-run (heavy). */
  onImportBackendRun: (name: string) => void;
  onDownloadBackendXlsx: (name: string) => void;
  /** Download the full project package (.zip of bundle JSON + meta JSON + xlsx). */
  onExportBackendProject: (name: string) => void;
  onDeleteBackendRuns: (names: string[]) => void;
  /** Manually re-fetch the run list from the backend. */
  onReload?: () => void;
}

/** Case-insensitive match for a backend run's meta. */
export function matchesBackendQuery(meta: BackendRunMeta, query: string): boolean {
  if (!query) return true;
  const needle = query.toLowerCase();
  const haystack = [
    meta.label,
    meta.name,
    meta.filename,
    meta.savedAt,
    new Date(meta.savedAt).toLocaleString(),
  ]
    .join(' ')
    .toLowerCase();
  return haystack.includes(needle);
}

export function HistoryView({
  backendRuns,
  onViewSelected,
  onImportBackendRun,
  onDownloadBackendXlsx,
  onExportBackendProject,
  onDeleteBackendRuns,
  onReload,
}: HistoryViewProps) {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<string[]>([]);

  const filtered = useMemo(
    () => backendRuns.filter((meta) => matchesBackendQuery(meta, query)),
    [backendRuns, query],
  );

  const sorted = useMemo(
    () => [...filtered].sort((a, b) => (a.savedAt < b.savedAt ? 1 : a.savedAt > b.savedAt ? -1 : 0)),
    [filtered],
  );

  const visibleNames = useMemo(() => sorted.map((m) => m.name), [sorted]);
  const visibleSelected = useMemo(
    () => selected.filter((n) => visibleNames.includes(n)),
    [selected, visibleNames],
  );
  const allVisibleSelected = visibleNames.length > 0 && visibleSelected.length === visibleNames.length;

  const toggleName = (name: string, checked: boolean) =>
    setSelected((prev) => (checked ? (prev.includes(name) ? prev : [...prev, name]) : prev.filter((n) => n !== name)));

  const toggleSelectAll = (checked: boolean) => setSelected(checked ? visibleNames : []);

  const deleteSelected = () => {
    if (visibleSelected.length === 0) return;
    onDeleteBackendRuns(visibleSelected);
    setSelected([]);
  };

  // Actions live at the top and act on the selection: Import needs exactly one
  // model; View shows one run's Result, or several side-by-side in Comparison.
  const single = visibleSelected.length === 1 ? visibleSelected[0] : null;
  const n = visibleSelected.length;

  return (
    <div className="history-view">
      <div className="history-toolbar">
        <input
          className="history-search"
          type="text"
          placeholder="Search runs by name, file, or date"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label className="history-select-all">
          <input
            type="checkbox"
            checked={allVisibleSelected}
            onChange={(e) => toggleSelectAll(e.target.checked)}
            disabled={visibleNames.length === 0}
          />
          Select all
        </label>
        <button
          className="tb-btn tb-btn--primary"
          onClick={() => onViewSelected(visibleSelected)}
          disabled={n === 0}
          title={n > 1 ? 'Compare the selected runs side by side' : 'View this run’s results'}
        >
          {n > 1 ? `Compare results (${n})` : 'View result'}
        </button>
        <button
          className="tb-btn"
          onClick={() => single && onImportBackendRun(single)}
          disabled={!single}
          title={single ? 'Load this run’s model into the editor to edit and re-run' : 'Select exactly one run to import'}
        >
          Import project
        </button>
        <button
          className="tb-btn"
          onClick={() => single && onExportBackendProject(single)}
          disabled={!single}
          title="Download the full project package (.zip)"
        >
          Export
        </button>
        <button
          className="tb-btn"
          onClick={() => single && onDownloadBackendXlsx(single)}
          disabled={!single}
          title="Download the run workbook (.xlsx)"
        >
          Excel
        </button>
        <span className="history-toolbar-spacer" />
        <button className="tb-btn" onClick={deleteSelected} disabled={n === 0}>
          Delete ({n})
        </button>
        {onReload && (
          <button className="tb-btn" onClick={onReload} title="Re-fetch run history from the backend">
            Reload
          </button>
        )}
      </div>

      {sorted.length === 0 ? (
        <div className="history-empty">
          {backendRuns.length === 0
            ? 'No saved runs yet — run the model to populate history.'
            : 'No runs match your search.'}
        </div>
      ) : (
        <div className="history-list">
          {sorted.map((meta) => (
            <BackendHistoryRow
              key={meta.name}
              meta={meta}
              selected={visibleSelected.includes(meta.name)}
              onSelect={(checked) => toggleName(meta.name, checked)}
              onActivate={() => onViewSelected([meta.name])}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** Annual energy demand (MWh) → a compact TWh / GWh / MWh label. */
function formatDemand(mwh: number | null | undefined): string | null {
  if (mwh == null || !Number.isFinite(mwh) || mwh <= 0) return null;
  if (mwh >= 1e6) return `${(mwh / 1e6).toLocaleString(undefined, { maximumFractionDigits: 1 })} TWh`;
  if (mwh >= 1e3) return `${(mwh / 1e3).toLocaleString(undefined, { maximumFractionDigits: 1 })} GWh`;
  return `${Math.round(mwh).toLocaleString()} MWh`;
}

// ── Backend (server-stored) run row ─────────────────────────────────────────

function BackendHistoryRow({
  meta, selected, onSelect, onActivate,
}: {
  meta: BackendRunMeta;
  selected: boolean;
  onSelect: (checked: boolean) => void;
  /** Double-click / Enter on the row → view this single run (toolbar handles the rest). */
  onActivate: () => void;
}) {
  // The run's display name IS the scenario name (falls back to the stored label).
  const name = meta.scenarioLabel || meta.label || meta.name;

  // Rows are display-only: select with the checkbox (or click the row), then use
  // the toolbar actions at the top. This keeps every row a clean, aligned line
  // instead of a ragged strip of buttons.
  return (
    <div
      className={`history-row${selected ? ' is-selected' : ''}`}
      onDoubleClick={onActivate}
    >
      <input
        type="checkbox"
        className="history-row-select"
        checked={selected}
        onChange={(e) => onSelect(e.target.checked)}
        aria-label={`Select ${name}`}
      />

      <span className="history-row-name history-row-name--static" title={meta.name}>{name}</span>

      <span className="history-row-time" title={new Date(meta.savedAt).toLocaleString()}>
        {formatRelTime(meta.savedAt)}
      </span>
      {meta.scenarioYear != null && <span className="history-row-chip">{meta.scenarioYear}</span>}
      {meta.resolutionHours != null && <span className="history-row-chip">{meta.resolutionHours}h res</span>}
      {meta.windowCount != null && meta.windowCount > 0 && (
        <span className="history-row-chip">{meta.windowCount} batches</span>
      )}
      {formatDemand(meta.totalDemandMwh) && (
        <span className="history-row-kpi"><b>{formatDemand(meta.totalDemandMwh)}</b> demand</span>
      )}
      {(meta.tags ?? []).map((t) => (
        <span key={t} className="history-row-chip history-row-chip--tag">{t}</span>
      ))}

      <span className="history-row-spacer" />
      {!meta.xlsxReady && <span className="history-row-chip" title="Workbook still being prepared for download/export">Preparing…</span>}
    </div>
  );
}
