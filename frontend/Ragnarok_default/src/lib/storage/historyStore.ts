/**
 * Persistent run history, in IndexedDB.
 *
 * A full-year run carries its entire model + results — far too large for
 * localStorage and crashes the browser if exported to xlsx (SheetJS builds the
 * whole workbook in RAM). IndexedDB structured-clones the existing JSON objects
 * with no file build and no quota grief, so past runs survive a reload and can
 * be reopened from the History tab.
 *
 * A SEPARATE database (`ragnarok-history`) is used so this never has to
 * coordinate schema versions with the working-session store in sessionStore.ts.
 * The store `runs` is keyed by each entry's `id`. The set is bounded by the
 * prune cap (pinned kept, unpinned capped), so `saveHistory` simply replaces
 * the whole set: clear, then put all. Every call is best-effort — a storage
 * failure logs a warning and no-ops rather than crashing the app.
 */
import type { RunHistoryEntry } from 'lib/types';

const DB_NAME = 'ragnarok-history';
const STORE = 'runs';
const DB_VERSION = 1;

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) {
        req.result.createObjectStore(STORE, { keyPath: 'id' });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/**
 * Replace the entire persisted history with `entries`. Clears the store, then
 * puts every entry in a single transaction. Best-effort.
 */
export async function saveHistory(entries: RunHistoryEntry[]): Promise<void> {
  try {
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      const store = tx.objectStore(STORE);
      store.clear();
      for (const entry of entries) store.put(entry);
      tx.oncomplete = () => { db.close(); resolve(); };
      tx.onerror = () => { db.close(); reject(tx.error); };
      tx.onabort = () => { db.close(); reject(tx.error); };
    });
  } catch (err) {
    console.warn('historyStore: saveHistory failed, run history not persisted', err);
  }
}

/** Load every persisted run. Returns an empty array on any failure. */
export async function loadHistory(): Promise<RunHistoryEntry[]> {
  try {
    const db = await openDb();
    return await new Promise<RunHistoryEntry[]>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly');
      const req = tx.objectStore(STORE).getAll();
      req.onsuccess = () => {
        db.close();
        // getAll() returns IndexedDB key (id) order; restore the app's display
        // shape: pinned first, then most-recent first (savedAt is ISO, so a
        // reverse string compare is chronological).
        const rows = ((req.result as RunHistoryEntry[]) ?? []).slice().sort((a, b) => {
          if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
          return String(b.savedAt).localeCompare(String(a.savedAt));
        });
        resolve(rows);
      };
      req.onerror = () => { db.close(); reject(req.error); };
    });
  } catch (err) {
    console.warn('historyStore: loadHistory failed, starting with empty history', err);
    return [];
  }
}

/** Remove every persisted run. Best-effort. */
export async function clearHistory(): Promise<void> {
  try {
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).clear();
      tx.oncomplete = () => { db.close(); resolve(); };
      tx.onerror = () => { db.close(); reject(tx.error); };
      tx.onabort = () => { db.close(); reject(tx.error); };
    });
  } catch (err) {
    console.warn('historyStore: clearHistory failed', err);
  }
}
