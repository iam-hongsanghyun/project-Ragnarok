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
  SamplingConfig,
  ScenarioPreset,
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
  dryRun?: boolean;
  // Custom/global constraints ("cc rules") — live React state that isn't
  // embedded in the model, so it's carried here to survive a reload.
  constraints?: CustomConstraint[];
  // Rolling-horizon and pathway toggles + their detailed settings. These DO
  // round-trip through the model, but a restored active scenario can override
  // them with its defaults — so the last live values are carried here and
  // re-applied after restore, guaranteeing "stay as I left it".
  rollingConfig?: RollingHorizonConfig;
  samplingConfig?: SamplingConfig;
  pathwayConfig?: PathwayConfig;
  // The FULL live run configuration (window, carbon, every run-mode config:
  // stochastic, SCLOPF, reserve, ramp, MGA, ESS, ...) captured as a scenario, so
  // a reload restores all of it - not just the handful of fields above. Absent in
  // records written by older builds.
  scenario?: ScenarioPreset;
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


/** localStorage key of the live run controls. In localStorage (not IndexedDB) so they travel with the
 *  project like every other setting (lib/appState). */
export const CONTROLS_STORAGE_KEY = 'ragnarok:session:controls';

/** Persist the lightweight run controls. Best-effort. */
export async function saveSessionControls(controls: SessionControls): Promise<void> {
  try {
    window.localStorage.setItem(CONTROLS_STORAGE_KEY, JSON.stringify(controls));
  } catch {
    /* best effort */
  }
}

/** Load ONLY the lightweight run controls (no heavy model deserialisation).

 * The model is no longer stored in IndexedDB — the backend session owns it — so
 * boot must not pay to read a (possibly stale, multi-MB) model record here. */
export async function loadSessionControls(): Promise<SessionControls | null> {
  try {
    const raw = window.localStorage.getItem(CONTROLS_STORAGE_KEY);
    if (raw) return JSON.parse(raw) as SessionControls;
  } catch {
    /* fall through to the IndexedDB copy older builds wrote */
  }
  // One-off move of the copy older builds kept in IndexedDB: read it once, keep it in localStorage (where it
  // travels with the project) and delete it, so a project opened later without controls never inherits it.
  try {
    const legacy = await get<SessionControls>(CONTROLS_KEY);
    if (legacy) {
      window.localStorage.setItem(CONTROLS_STORAGE_KEY, JSON.stringify(legacy));
      await deleteKey(CONTROLS_KEY);
    }
    return legacy;
  } catch {
    return null;
  }
}

function deleteKey(key: string): Promise<void> {
  return openDb().then(
    (db) =>
      new Promise<void>((resolve, reject) => {
        const tx = db.transaction(STORE, 'readwrite');
        tx.objectStore(STORE).delete(key);
        tx.oncomplete = () => { db.close(); resolve(); };
        tx.onerror = () => { db.close(); reject(tx.error); };
        tx.onabort = () => { db.close(); reject(tx.error); };
      }),
  );
}

/** Remove only the persisted model (the "Clear" button — keeps controls/settings). */
export async function clearSessionModelOnly(): Promise<void> {
  try {
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).delete(MODEL_KEY);
      tx.oncomplete = () => { db.close(); resolve(); };
      tx.onerror = () => { db.close(); reject(tx.error); };
      tx.onabort = () => { db.close(); reject(tx.error); };
    });
  } catch {
    /* ignore */
  }
}

/** Remove the saved session (the "Clear cache" button). Awaited so it commits before reload. */
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
