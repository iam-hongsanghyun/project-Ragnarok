/**
 * History view — browse and manage persisted past runs.
 *
 * Runs are kept in IndexedDB (see lib/storage/historyStore.ts) so a full-year
 * result survives a reload and can be reopened without rebuilding or exporting
 * it. This view is a single column of run cards with a search filter and a
 * multi-select delete, plus a "Clear all". It shares the same `runHistory`
 * state as the Analytics → Comparison pane and reuses RunHistoryCard, so the
 * two stay in sync.
 *
 * The per-card SELECT checkbox here is local to this view (drives the bulk
 * delete) and is deliberately distinct from each entry's `inComparison` flag,
 * which the card's own comparison checkbox toggles.
 */
import React, { useMemo, useState } from 'react';
import { RunHistoryEntry } from 'lib/types';
import { RunHistoryCard } from '../features/run-history/RunHistoryCard';

interface HistoryViewProps {
  runHistory: RunHistoryEntry[];
  currencySymbol: string;
  onRestoreRun: (entry: RunHistoryEntry) => void;
  onRenameHistoryEntry: (id: string, label: string) => void;
  onPinHistoryEntry: (id: string, pinned: boolean) => void;
  onDeleteHistoryEntry: (id: string) => void;
  onDeleteHistoryEntries: (ids: string[]) => void;
  onClearHistory: () => void;
  onToggleComparison: (id: string, inComparison: boolean) => void;
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
  currencySymbol,
  onRestoreRun,
  onRenameHistoryEntry,
  onPinHistoryEntry,
  onDeleteHistoryEntry,
  onDeleteHistoryEntries,
  onClearHistory,
  onToggleComparison,
}: HistoryViewProps) {
  const [query, setQuery] = useState('');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  const filtered = useMemo(
    () => runHistory.filter((entry) => matchesQuery(entry, query)),
    [runHistory, query],
  );

  // Keep selection in sync with the entries actually on screen.
  const visibleSelectedIds = useMemo(
    () => selectedIds.filter((id) => filtered.some((entry) => entry.id === id)),
    [selectedIds, filtered],
  );
  const allVisibleSelected = filtered.length > 0 && visibleSelectedIds.length === filtered.length;

  const toggleSelect = (id: string, checked: boolean) => {
    setSelectedIds((prev) => {
      if (checked) return prev.includes(id) ? prev : [...prev, id];
      return prev.filter((x) => x !== id);
    });
  };

  const toggleSelectAll = (checked: boolean) => {
    setSelectedIds(checked ? filtered.map((entry) => entry.id) : []);
  };

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
        <button
          className="tb-btn"
          onClick={deleteSelected}
          disabled={visibleSelectedIds.length === 0}
        >
          Delete selected ({visibleSelectedIds.length})
        </button>
        <button
          className="tb-btn tb-btn--muted"
          onClick={onClearHistory}
          disabled={runHistory.length === 0}
        >
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
        <div className="history-column">
          {filtered.map((entry) => (
            <div key={entry.id} className="history-row">
              <label className="history-select-check" title="Select for bulk delete">
                <input
                  type="checkbox"
                  checked={visibleSelectedIds.includes(entry.id)}
                  onChange={(e) => toggleSelect(entry.id, e.target.checked)}
                />
              </label>
              <RunHistoryCard
                entry={entry}
                onView={() => onRestoreRun(entry)}
                onRename={(label) => onRenameHistoryEntry(entry.id, label)}
                onPin={(pinned) => onPinHistoryEntry(entry.id, pinned)}
                onDelete={() => onDeleteHistoryEntry(entry.id)}
                onToggleComparison={(v) => onToggleComparison(entry.id, v)}
                currencySymbol={currencySymbol}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
