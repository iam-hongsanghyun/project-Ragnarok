/**
 * Auto-saved working session, in IndexedDB.
 *
 * The workbook model can be tens of MB (a full-year network), far past
 * localStorage's quota — IndexedDB holds it comfortably and stores structured
 * data without JSON round-tripping. The model carries everything project-side
 * (components, time series, and the `RAGNAROK_*` config sheets: scenarios,
 * carbon library, constraints, DSL, pathway, rolling).
 *
 * The heavy `model` and the lightweight run `controls` are stored under
 * SEPARATE keys, so changing a control (carbon price, snapshot window) only
 * rewrites the small controls record — it does NOT re-serialise the whole model
 * on every slider tick. The session is cleared only by the explicit "Clear
 * cache" button — a plain reload restores it.
 */
import type {
  CarbonPriceScheduleEntry,
  CustomConstraint,
  PathwayConfig,
  RollingHorizonConfig,
  WorkbookModel,
} from 'lib/types';

const DB_NAME = 'ragnarok';
const STORE = 'session';
const MODEL_KEY = 'model';
const CONTROLS_KEY = 'controls';
const DB_VERSION = 1;

/** Lightweight run controls — cheap to serialise on every change. */
export interface SessionControls {
  filename: string;
  carbonPrice: number;
  carbonPriceSchedule: CarbonPriceScheduleEntry[];
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  forceLp: boolean;
  // Custom/global constraints ("cc rules") — live React state that isn't
  // embedded in the model, so it's carried here to survive a reload.
  constraints?: CustomConstraint[];
  // Rolling-horizon and pathway toggles + their detailed settings. These DO
  // round-trip through the model, but a restored active scenario can override
  // them with its defaults — so the last live values are carried here and
  // re-applied after restore, guaranteeing "stay as I left it".
  rollingConfig?: RollingHorizonConfig;
  pathwayConfig?: PathwayConfig;
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

function put(key: string, value: unknown): Promise<void> {
  return openDb().then(
    (db) =>
      new Promise<void>((resolve, reject) => {
        const tx = db.transaction(STORE, 'readwrite');
        tx.objectStore(STORE).put(value, key);
        tx.oncomplete = () => { db.close(); resolve(); };
        tx.onerror = () => { db.close(); reject(tx.error); };
        tx.onabort = () => { db.close(); reject(tx.error); };
      }),
  );
}

function get<T>(key: string): Promise<T | null> {
  return openDb().then(
    (db) =>
      new Promise<T | null>((resolve, reject) => {
        const tx = db.transaction(STORE, 'readonly');
        const req = tx.objectStore(STORE).get(key);
        req.onsuccess = () => { db.close(); resolve((req.result as T) ?? null); };
        req.onerror = () => { db.close(); reject(req.error); };
      }),
  );
}

/** Persist the heavy workbook model (debounce in the caller). Best-effort. */
export async function saveSessionModel(model: WorkbookModel): Promise<void> {
  try {
    await put(MODEL_KEY, model);
  } catch {
    /* storage unavailable / quota — best effort */
  }
}

/** Persist the lightweight run controls. Best-effort. */
export async function saveSessionControls(controls: SessionControls): Promise<void> {
  try {
    await put(CONTROLS_KEY, controls);
  } catch {
    /* best effort */
  }
}

export async function loadSession(): Promise<{ model: WorkbookModel | null; controls: SessionControls | null }> {
  try {
    const [model, controls] = await Promise.all([
      get<WorkbookModel>(MODEL_KEY),
      get<SessionControls>(CONTROLS_KEY),
    ]);
    return { model, controls };
  } catch {
    return { model: null, controls: null };
  }
}

/** Remove the saved session (the Clear button). Awaited so it commits before reload. */
export async function clearSession(): Promise<void> {
  try {
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).delete(MODEL_KEY);
      tx.objectStore(STORE).delete(CONTROLS_KEY);
      tx.oncomplete = () => { db.close(); resolve(); };
      tx.onerror = () => { db.close(); reject(tx.error); };
      tx.onabort = () => { db.close(); reject(tx.error); };
    });
  } catch {
    /* ignore */
  }
}
