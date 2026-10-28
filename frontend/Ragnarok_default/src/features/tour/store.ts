/**
 * Tour progress, persisted in localStorage.
 *
 * The blob is versioned and read defensively: storage can be unavailable (private
 * mode, quota) or hold something from another release, and the tour must then start
 * fresh rather than throw. One small external store, so the host overlay and the
 * "Take the tour" buttons share state without prop plumbing through App.
 */
export const TOUR_STORAGE_KEY = 'ragnarok:tour:v1';
const TOUR_STORAGE_VERSION = 1;

/**
 * unseen   - never offered
 * active   - walking (resumes at `stepId` after a reload)
 * paused   - skipped part-way with Esc; "Resume" continues at `stepId`
 * declined - the first-run offer was dismissed
 * done     - finished
 */
export type TourStatus = 'unseen' | 'active' | 'paused' | 'declined' | 'done';

export interface PersistedTour {
  status: TourStatus;
  stepId: string | null;
}

const STATUSES: readonly TourStatus[] = ['unseen', 'active', 'paused', 'declined', 'done'];

export const UNSEEN: PersistedTour = { status: 'unseen', stepId: null };

/** Parse a stored blob; anything unrecognised is "never seen". */
export function parsePersisted(raw: string | null): PersistedTour {
  if (!raw) return UNSEEN;
  try {
    const data = JSON.parse(raw) as Record<string, unknown> | null;
    if (!data || typeof data !== 'object' || data.v !== TOUR_STORAGE_VERSION) return UNSEEN;
    const status = STATUSES.find((s) => s === data.status);
    if (!status) return UNSEEN;
    return { status, stepId: typeof data.stepId === 'string' ? data.stepId : null };
  } catch {
    return UNSEEN;
  }
}

export function serializePersisted(p: PersistedTour): string {
  return JSON.stringify({ v: TOUR_STORAGE_VERSION, status: p.status, stepId: p.stepId });
}

function readStorage(): PersistedTour {
  try {
    return parsePersisted(window.localStorage.getItem(TOUR_STORAGE_KEY));
  } catch {
    return UNSEEN;
  }
}

let current: PersistedTour = readStorage();
const listeners = new Set<() => void>();

export const tourStore = {
  get: (): PersistedTour => current,
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  },
  set(next: PersistedTour): void {
    if (next.status === current.status && next.stepId === current.stepId) return;
    current = next;
    try {
      window.localStorage.setItem(TOUR_STORAGE_KEY, serializePersisted(next));
    } catch {
      /* storage unavailable: the tour still works for this page load */
    }
    listeners.forEach((l) => l());
  },
  /** Start walking at `stepId`. */
  begin(stepId: string): void {
    tourStore.set({ status: 'active', stepId });
  },
};
