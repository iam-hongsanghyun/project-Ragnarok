/**
 * History view — browse and manage persisted past runs.
 *
 * Two run sources are listed together, sorted newest-first, each row carrying
 * a SOURCE chip so the user always knows where a run lives:
 *
 *  - Browser runs (`runHistory`) are kept in IndexedDB (see
 *    lib/storage/historyStore.ts) so a full-year result survives a reload and
 *    can be reopened without rebuilding or exporting it. They keep the flat-row
 *    layout: select checkbox (drives bulk delete), name + metadata, inline
 *    actions (View results, Pin, Delete). Shares `runHistory` with
 *    Analytics → Comparison.
 *  - Backend runs (`backendRuns`) were persisted server-side via the
 *    "Store in backend" run option. They use the same flat-row shape with
 *    actions View results, Download Excel, Delete. There is no multi-select on
 *    backend rows — they use their own inline Delete.
 */
import React, { useMemo, useState } from 'react';
import { RunHistoryEntry, BackendRunMeta } from 'lib/types';
import { formatRelTime } from 'lib/utils/formatRelTime';

interface HistoryViewProps {
  runHistory: RunHistoryEntry[];
  backendRuns: BackendRunMeta[];
  onRestoreRun: (entry: RunHistoryEntry) => void;
  onRenameHistoryEntry: (id: string, label: string) => void;
  onPinHistoryEntry: (id: string, pinned: boolean) => void;
  onDeleteHistoryEntry: (id: string) => void;
  onDeleteHistoryEntries: (ids: string[]) => void;
  onClearHistory: () => void;
  onOpenBackendRun: (name: string) => void;
  onDownloadBackendXlsx: (name: string) => void;
  onDeleteBackendRun: (name: string) => void;
  onDeleteBackendRuns: (names: string[]) => void;
}

/** Case-insensitive match against label, filename, and the saved date string. */
export function matchesQuery(entry: RunHistoryEntry, query: string): boolean {
  if (!query) return true;
  const needle = query.toLowerCase();
  const haystack = [
    entry.label,
    entry.filename,
    entry.savedAt,
    new Date(entry.savedAt).toLocaleString(),
  ]
    .join(' ')
    .toLowerCase();
  return haystack.includes(needle);
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

// A unified list item — either a browser entry or a backend meta — sorted
// together by savedAt.
type ListItem =
  | { source: 'browser'; savedAt: string; entry: RunHistoryEntry }
  | { source: 'backend'; savedAt: string; meta: BackendRunMeta };

export function HistoryView({
  runHistory,
  backendRuns,
  onRestoreRun,
  onRenameHistoryEntry,
  onPinHistoryEntry,
  onDeleteHistoryEntry,
  onDeleteHistoryEntries,
  onClearHistory,
  onOpenBackendRun,
  onDownloadBackendXlsx,
  onDeleteBackendRun,
  onDeleteBackendRuns,
}: HistoryViewProps) {
  const [query, setQuery] = useState('');
  // Selection keys span both sources: `b:<id>` (browser) and `s:<name>` (backend).
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);
  const browserKey = (id: string) => `b:${id}`;
  const backendKey = (name: string) => `s:${name}`;

  const filteredBrowser = useMemo(
    () => runHistory.filter((entry) => matchesQuery(entry, query)),
    [runHistory, query],
  );
  const filteredBackend = useMemo(
    () => backendRuns.filter((meta) => matchesBackendQuery(meta, query)),
    [backendRuns, query],
  );

  const items = useMemo<ListItem[]>(() => {
    const merged: ListItem[] = [
      ...filteredBrowser.map((entry) => ({ source: 'browser' as const, savedAt: entry.savedAt, entry })),
      ...filteredBackend.map((meta) => ({ source: 'backend' as const, savedAt: meta.savedAt, meta })),
    ];
    merged.sort((a, b) => (a.savedAt < b.savedAt ? 1 : a.savedAt > b.savedAt ? -1 : 0));
    return merged;
  }, [filteredBrowser, filteredBackend]);

  // Selection spans both sources; keep it limited to what's currently visible.
  const visibleKeys = useMemo(
    () => [
      ...filteredBrowser.map((entry) => browserKey(entry.id)),
      ...filteredBackend.map((meta) => backendKey(meta.name)),
    ],
    [filteredBrowser, filteredBackend],
  );
  const visibleSelected = useMemo(
    () => selectedKeys.filter((k) => visibleKeys.includes(k)),
    [selectedKeys, visibleKeys],
  );
  const allVisibleSelected = visibleKeys.length > 0 && visibleSelected.length === visibleKeys.length;

  const toggleKey = (key: string, checked: boolean) =>
    setSelectedKeys((prev) => (checked ? (prev.includes(key) ? prev : [...prev, key]) : prev.filter((k) => k !== key)));

  const toggleSelectAll = (checked: boolean) => setSelectedKeys(checked ? visibleKeys : []);

  const deleteSelected = () => {
    const browserIds = visibleSelected.filter((k) => k.startsWith('b:')).map((k) => k.slice(2));
    const backendNames = visibleSelected.filter((k) => k.startsWith('s:')).map((k) => k.slice(2));
    if (browserIds.length === 0 && backendNames.length === 0) return;
    if (browserIds.length) onDeleteHistoryEntries(browserIds);
    if (backendNames.length) onDeleteBackendRuns(backendNames);
    setSelectedKeys([]);
  };

  const totalRuns = runHistory.length + backendRuns.length;

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
            disabled={visibleKeys.length === 0}
          />
          Select all
        </label>
        <button className="tb-btn" onClick={deleteSelected} disabled={visibleSelected.length === 0}>
          Delete selected ({visibleSelected.length})
        </button>
        <button className="tb-btn tb-btn--muted" onClick={onClearHistory} disabled={runHistory.length === 0}>
          Clear all
        </button>
      </div>

      {items.length === 0 ? (
        <div className="history-empty">
          {totalRuns === 0
            ? 'No saved runs yet — run the model to populate history.'
            : 'No runs match your search.'}
        </div>
      ) : (
        <div className="history-list">
          {items.map((item) =>
            item.source === 'browser' ? (
              <BrowserHistoryRow
                key={`browser:${item.entry.id}`}
                entry={item.entry}
                selected={visibleSelected.includes(browserKey(item.entry.id))}
                onSelect={(checked) => toggleKey(browserKey(item.entry.id), checked)}
                onView={() => onRestoreRun(item.entry)}
                onRename={(label) => onRenameHistoryEntry(item.entry.id, label)}
                onPin={(pinned) => onPinHistoryEntry(item.entry.id, pinned)}
                onDelete={() => onDeleteHistoryEntry(item.entry.id)}
              />
            ) : (
              <BackendHistoryRow
                key={`backend:${item.meta.name}`}
                meta={item.meta}
                selected={visibleSelected.includes(backendKey(item.meta.name))}
                onSelect={(checked) => toggleKey(backendKey(item.meta.name), checked)}
                onView={() => onOpenBackendRun(item.meta.name)}
                onDownload={() => onDownloadBackendXlsx(item.meta.name)}
                onDelete={() => onDeleteBackendRun(item.meta.name)}
              />
            ),
          )}
        </div>
      )}
    </div>
  );
}

// ── Browser run row ───────────────────────────────────────────────────────

function BrowserHistoryRow({
  entry, selected, onSelect, onView, onRename, onPin, onDelete,
}: {
  entry: RunHistoryEntry;
  selected: boolean;
  onSelect: (checked: boolean) => void;
  onView: () => void;
  onRename: (label: string) => void;
  onPin: (pinned: boolean) => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(entry.label);

  const snaps = Math.max(0, entry.snapshotEnd - entry.snapshotStart);
  const summary = entry.results?.summary ?? [];
  const price = summary[3];
  const emissions = summary[4];

  const commit = () => { onRename(draft.trim() || entry.label); setEditing(false); };

  return (
    <div className={`history-row${selected ? ' is-selected' : ''}${entry.pinned ? ' is-pinned' : ''}`}>
      <input
        type="checkbox"
        className="history-row-select"
        checked={selected}
        onChange={(e) => onSelect(e.target.checked)}
        aria-label={`Select ${entry.label}`}
      />

      <span className="history-row-source history-row-source--browser">Browser</span>

      {editing ? (
        <input
          className="history-row-name-input"
          value={draft}
          autoFocus
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === 'Escape') e.currentTarget.blur(); }}
        />
      ) : (
        <button className="history-row-name" onClick={() => { setDraft(entry.label); setEditing(true); }} title="Click to rename">
          {entry.label}
        </button>
      )}

      <span className="history-row-time" title={new Date(entry.savedAt).toLocaleString()}>
        {formatRelTime(entry.savedAt)}
      </span>
      <span className="history-row-file" title={entry.filename}>{entry.filename}</span>
      {entry.scenarioLabel && <span className="history-row-chip">{entry.scenarioLabel}</span>}
      <span className="history-row-chip">{snaps} snaps</span>
      <span className="history-row-chip">{entry.snapshotWeight}h</span>
      {emissions && <span className="history-row-kpi"><b>{emissions.value}</b> {emissions.label}</span>}
      {price && <span className="history-row-kpi"><b>{price.value}</b> {price.label}</span>}

      <span className="history-row-spacer" />

      <button className="tb-btn" onClick={onView}>View results</button>
      <button className="tb-btn tb-btn--muted" onClick={() => onPin(!entry.pinned)}>{entry.pinned ? 'Unpin' : 'Pin'}</button>
      <button className="tb-btn tb-btn--muted" onClick={onDelete}>Delete</button>
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

      <span className="history-row-source history-row-source--backend">Backend</span>

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
