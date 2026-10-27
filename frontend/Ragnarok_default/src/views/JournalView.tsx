/**
 * Journal view - the working model's edit timeline.
 *
 * Every change to the session model (this GUI, MCP, the agent) is one journal
 * entry: who, when, which sheets, what. A row expands to its (capped) diff, can
 * be undone on its own, or the whole session can be reverted to just after it.
 * After an undo/revert the editor re-reads the model from the session
 * (`onSessionChanged`) - the server is the source of truth, never the stale
 * browser copy.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  JournalEntry,
  JournalDiff,
  fetchJournal,
  fetchJournalDiff,
  revertJournal,
  undoJournalEntry,
} from 'lib/api/journal';
import { formatRelTime } from 'lib/utils/formatRelTime';
import { useToast } from '../shared/components/Toast';

const DIFF_CHAR_CAP = 4000;

interface JournalViewProps {
  /** Re-read the editor's model from the session after the server changed it. */
  onSessionChanged: () => Promise<void> | void;
}

export function JournalView({ onSessionChanged }: JournalViewProps) {
  const { showToast } = useToast();
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const [diff, setDiff] = useState<JournalDiff | null>(null);

  const reload = useCallback(async () => {
    try {
      const list = await fetchJournal();
      setEntries(list.entries);
      setVersion(list.version);
    } catch (err) {
      showToast(`Journal: ${err instanceof Error ? err.message : 'could not load'}`, 'error');
    }
  }, [showToast]);

  useEffect(() => { void reload(); }, [reload]);

  const toggleDiff = async (entry: JournalEntry) => {
    if (openId === entry.id) { setOpenId(null); setDiff(null); return; }
    setOpenId(entry.id);
    setDiff(null);
    try { setDiff(await fetchJournalDiff(entry.id)); } catch { setDiff(null); }
  };

  const apply = async (label: string, action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await action();
      await onSessionChanged();
      await reload();
      setOpenId(null);
      setDiff(null);
      showToast(label, 'success');
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed', 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="history-view">
      <div className="queue-toolbar">
        <span className="queue-conc-label">Model version v{version}</span>
        <button className="tb-btn" disabled={busy} onClick={() => void reload()}>Refresh</button>
      </div>
      <p className="sg-setting-hint queue-conc-hint">
        Every edit to the working model, from this app or an agent. Undo reverses one edit (blocked when a later edit
        touched the same sheets); Revert returns the model to just after that edit.
      </p>
      {entries.length === 0 ? (
        <div className="history-empty"><p>No edits recorded yet.</p></div>
      ) : (
        <div className="history-list">
          {entries.map((entry) => {
            const revertible = entry.undo.strategy !== 'none';
            const sheetNames = entry.sheets.map((s) => s.name).filter(Boolean).join(', ');
            return (
              <div key={entry.id}>
                <div className={`history-row${openId === entry.id ? ' is-selected' : ''}`}>
                  <span className="history-row-chip">v{entry.id}</span>
                  <span className="history-row-name history-row-name--static" title={entry.summary ?? entry.kind}>
                    {entry.summary || entry.kind}
                  </span>
                  <span className="history-row-chip">{entry.actor}</span>
                  <span className="history-row-chip">{entry.kind}</span>
                  {sheetNames && <span className="history-row-chip" title={sheetNames}>{sheetNames.length > 40 ? `${sheetNames.slice(0, 40)}…` : sheetNames}</span>}
                  <span className="history-row-time" title={new Date(entry.ts).toLocaleString()}>{formatRelTime(entry.ts)}</span>
                  <span className="history-row-spacer" />
                  {entry.hasDetail && (
                    <button className="tb-btn" onClick={() => void toggleDiff(entry)}>
                      {openId === entry.id ? 'Hide diff' : 'Diff'}
                    </button>
                  )}
                  <button
                    className="tb-btn"
                    disabled={busy || !revertible}
                    title={revertible ? 'Undo just this edit' : 'Not revertible: its undo snapshot was evicted'}
                    onClick={() => void apply(`Undid v${entry.id}`, () => undoJournalEntry(entry.id))}
                  >
                    Undo
                  </button>
                  <button
                    className="tb-btn"
                    disabled={busy || entry.id >= version}
                    title="Undo every edit newer than this one"
                    onClick={() => void apply(`Reverted to v${entry.id}`, () => revertJournal(entry.id))}
                  >
                    Revert to here
                  </button>
                </div>
                {openId === entry.id && (
                  <pre className="journal-diff">
                    {diff ? JSON.stringify(diff.detail, null, 2).slice(0, DIFF_CHAR_CAP) : 'Loading…'}
                  </pre>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
