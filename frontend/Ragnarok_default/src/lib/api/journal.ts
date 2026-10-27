/**
 * The session's mutation journal (timeline, per-entry diff, undo, revert-to-version).
 *
 * Thin wrappers over `/api/session/journal*`; the same endpoints back the MCP
 * `get_journal` / `undo_journal_entry` / `revert_session` tools. Every edit to
 * the working model - from this browser, an agent, or MCP - is one entry.
 */
import { API_BASE } from 'lib/constants';
import { DEFAULT_SESSION_ID } from 'lib/api/session';

export interface JournalEntry {
  id: number;
  version: number;
  ts: string;
  /** Who made the change: `user` (this GUI), `mcp`, `agent`. */
  actor: string;
  kind: string;
  sheets: Array<{ name?: string; kind?: string }>;
  summary?: string | null;
  /** `none` = not revertible (its snapshot was evicted). */
  undo: { strategy: string };
  hasDetail: boolean;
  /** Set on an entry written by an undo: the id it reverted. */
  reverts?: number;
}

export interface JournalList {
  version: number;
  entries: JournalEntry[];
}

export interface JournalDiff {
  id: number;
  kind: string;
  sheets: Array<{ name?: string; kind?: string }>;
  summary?: string | null;
  detail: Record<string, unknown>;
  undoStrategy: string;
}

async function asJson<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let message = '';
    try {
      const body = (await resp.json()) as { detail?: unknown };
      message = typeof body.detail === 'string' ? body.detail : '';
    } catch { /* non-JSON error body */ }
    throw new Error(message || `Request failed (${resp.status}).`);
  }
  return resp.json() as Promise<T>;
}

const sessionQuery = (sessionId: string) => `session_id=${encodeURIComponent(sessionId)}`;

export async function fetchJournal(limit = 50, sessionId = DEFAULT_SESSION_ID): Promise<JournalList> {
  return asJson<JournalList>(await fetch(`${API_BASE}/api/session/journal?${sessionQuery(sessionId)}&limit=${limit}`));
}

export async function fetchJournalDiff(entryId: number, sessionId = DEFAULT_SESSION_ID): Promise<JournalDiff> {
  return asJson<JournalDiff>(await fetch(`${API_BASE}/api/session/journal/${entryId}/diff?${sessionQuery(sessionId)}`));
}

/** Undo one entry (HTTP 409 when a later entry touches the same sheets). */
export async function undoJournalEntry(entryId: number, sessionId = DEFAULT_SESSION_ID): Promise<{ version: number; undone: number[] }> {
  return asJson(await fetch(`${API_BASE}/api/session/journal/${entryId}/undo?${sessionQuery(sessionId)}`, { method: 'POST' }));
}

/** Undo every entry newer than `toVersion`, newest first. */
export async function revertJournal(toVersion: number, sessionId = DEFAULT_SESSION_ID): Promise<{ version: number; undone: number[] }> {
  return asJson(await fetch(`${API_BASE}/api/session/journal/revert`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId, toVersion }),
  }));
}
