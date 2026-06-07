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
  onOpenBackendRun: (name: string) => void;
  onDownloadBackendXlsx: (name: string) => void;
  onDeleteBackendRun: (name: string) => void;
  onDeleteBackendRuns: (names: string[]) => void;
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
  onOpenBackendRun,
  onDownloadBackendXlsx,
  onDeleteBackendRun,
  onDeleteBackendRuns,
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
        <button className="tb-btn" onClick={deleteSelected} disabled={visibleSelected.length === 0}>
          Delete selected ({visibleSelected.length})
        </button>
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
              onView={() => onOpenBackendRun(meta.name)}
              onDownload={() => onDownloadBackendXlsx(meta.name)}
              onDelete={() => onDeleteBackendRun(meta.name)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Backend (server-stored) run row ─────────────────────────────────────────

function BackendHistoryRow({
  meta, selected, onSelect, onView, onDownload, onDelete,
}: {
  meta: BackendRunMeta;
  selected: boolean;
  onSelect: (checked: boolean) => void;
  onView: () => void;
  onDownload: () => void;
  onDelete: () => void;
}) {
  const snaps =
    meta.snapshotStart != null && meta.snapshotEnd != null
      ? Math.max(0, meta.snapshotEnd - meta.snapshotStart)
      : null;
  const kpis = meta.kpis ?? [];
  const price = kpis[3];
  const emissions = kpis[2];

  return (
    <div className={`history-row${selected ? ' is-selected' : ''}`}>
      <input
        type="checkbox"
        className="history-row-select"
        checked={selected}
        onChange={(e) => onSelect(e.target.checked)}
        aria-label={`Select ${meta.label || meta.name}`}
      />

      <span className="history-row-name history-row-name--static" title={meta.name}>{meta.label || meta.name}</span>

      <span className="history-row-time" title={new Date(meta.savedAt).toLocaleString()}>
        {formatRelTime(meta.savedAt)}
      </span>
      {meta.filename && <span className="history-row-file" title={meta.filename}>{meta.filename}</span>}
      {snaps != null && <span className="history-row-chip">{snaps} snaps</span>}
      {meta.snapshotWeight != null && <span className="history-row-chip">{meta.snapshotWeight}h</span>}
      {emissions && <span className="history-row-kpi"><b>{emissions.value}</b> {emissions.label}</span>}
      {price && <span className="history-row-kpi"><b>{price.value}</b> {price.label}</span>}

      <span className="history-row-spacer" />

      <button className="tb-btn" onClick={onView}>View results</button>
      <button className="tb-btn tb-btn--muted" onClick={onDownload}>Download Excel</button>
      <button className="tb-btn tb-btn--muted" onClick={onDelete}>Delete</button>
    </div>
  );
}
