/**
 * History view — browse and manage persisted past runs.
 *
 * Runs are kept in IndexedDB (see lib/storage/historyStore.ts) so a full-year
 * result survives a reload and can be reopened without rebuilding or exporting
 * it. Each run is a single flat, full-width row: one select checkbox (drives the
 * bulk delete), the run's name + metadata laid out horizontally, and inline
 * actions. Shares the same `runHistory` state as Analytics → Comparison.
 */
import React, { useMemo, useState } from 'react';
import { RunHistoryEntry } from 'lib/types';
import { formatRelTime } from 'lib/utils/formatRelTime';

interface HistoryViewProps {
  runHistory: RunHistoryEntry[];
  onRestoreRun: (entry: RunHistoryEntry) => void;
  onRenameHistoryEntry: (id: string, label: string) => void;
  onPinHistoryEntry: (id: string, pinned: boolean) => void;
  onDeleteHistoryEntry: (id: string) => void;
  onDeleteHistoryEntries: (ids: string[]) => void;
  onClearHistory: () => void;
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

export function HistoryView({
  runHistory,
  onRestoreRun,
  onRenameHistoryEntry,
  onPinHistoryEntry,
  onDeleteHistoryEntry,
  onDeleteHistoryEntries,
  onClearHistory,
}: HistoryViewProps) {
  const [query, setQuery] = useState('');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  const filtered = useMemo(
    () => runHistory.filter((entry) => matchesQuery(entry, query)),
    [runHistory, query],
  );

  const visibleSelectedIds = useMemo(
    () => selectedIds.filter((id) => filtered.some((entry) => entry.id === id)),
    [selectedIds, filtered],
  );
  const allVisibleSelected = filtered.length > 0 && visibleSelectedIds.length === filtered.length;

  const toggleSelect = (id: string, checked: boolean) =>
    setSelectedIds((prev) => (checked ? (prev.includes(id) ? prev : [...prev, id]) : prev.filter((x) => x !== id)));

  const toggleSelectAll = (checked: boolean) =>
    setSelectedIds(checked ? filtered.map((entry) => entry.id) : []);

  const deleteSelected = () => {
    if (visibleSelectedIds.length === 0) return;
    onDeleteHistoryEntries(visibleSelectedIds);
    setSelectedIds([]);
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
            disabled={filtered.length === 0}
          />
          Select all
        </label>
        <button className="tb-btn" onClick={deleteSelected} disabled={visibleSelectedIds.length === 0}>
          Delete selected ({visibleSelectedIds.length})
        </button>
        <button className="tb-btn tb-btn--muted" onClick={onClearHistory} disabled={runHistory.length === 0}>
          Clear all
        </button>
      </div>

      {filtered.length === 0 ? (
        <div className="history-empty">
          {runHistory.length === 0
            ? 'No saved runs yet — run the model to populate history.'
            : 'No runs match your search.'}
        </div>
      ) : (
        <div className="history-list">
          {filtered.map((entry) => (
            <HistoryRow
              key={entry.id}
              entry={entry}
              selected={visibleSelectedIds.includes(entry.id)}
              onSelect={(checked) => toggleSelect(entry.id, checked)}
              onView={() => onRestoreRun(entry)}
              onRename={(label) => onRenameHistoryEntry(entry.id, label)}
              onPin={(pinned) => onPinHistoryEntry(entry.id, pinned)}
              onDelete={() => onDeleteHistoryEntry(entry.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── One flat run row ────────────────────────────────────────────────────────

function HistoryRow({
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
