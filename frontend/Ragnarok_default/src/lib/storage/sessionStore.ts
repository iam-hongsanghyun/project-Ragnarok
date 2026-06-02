/**
 * Auto-saved working session, in IndexedDB.
 *
 * The workbook model can be tens of MB (a full-year network), far past
 * localStorage's quota — IndexedDB holds it comfortably and stores structured
 * data without JSON round-tripping. The model carries everything project-side
 * (components, time series, and the `RAGNAROK_*` config sheets: scenarios,
 * carbon library, constraints, DSL, pathway, rolling), so persisting it plus
 * the live run controls restores the whole session on reload.
 *
 * The session is cleared only by the explicit "Clear cache" button — a plain
 * reload restores it.
 */
import type { CarbonPriceScheduleEntry, WorkbookModel } from 'lib/types';

const DB_NAME = 'ragnarok';
const STORE = 'session';
const KEY = 'session';
const DB_VERSION = 1;

export interface SessionSnapshot {
  model: WorkbookModel;
  filename: string;
  carbonPrice: number;
  carbonPriceSchedule: CarbonPriceScheduleEntry[];
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  forceLp: boolean;
  savedAt: number;
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/** Persist the session. Best-effort — storage errors (quota, privacy) are swallowed. */
export async function saveSession(snapshot: SessionSnapshot): Promise<void> {
  try {
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).put(snapshot, KEY);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
    db.close();
  } catch {
    /* storage unavailable — best effort */
  }
}

export async function loadSession(): Promise<SessionSnapshot | null> {
  try {
    const db = await openDb();
    const result = await new Promise<SessionSnapshot | null>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly');
      const req = tx.objectStore(STORE).get(KEY);
      req.onsuccess = () => resolve((req.result as SessionSnapshot) ?? null);
      req.onerror = () => reject(req.error);
    });
    db.close();
    return result;
  } catch {
    return null;
  }
}

/** Remove the saved session (the Clear button). Awaited so it commits before reload. */
export async function clearSession(): Promise<void> {
  try {
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).delete(KEY);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
    db.close();
  } catch {
    /* ignore */
  }
}
