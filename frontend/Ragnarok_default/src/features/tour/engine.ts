/**
 * Guided-tour step engine — pure, so the overlay holds no logic.
 *
 * A tour is a declarative list of steps (`steps.ts`). Each step may name a view to
 * show (`tab`), a control to ring (`target`, matched against `data-tour="..."`), and
 * a `done` predicate over the app state. A step with `done` is an ACTION step: the
 * tour waits for the app to change (a model loaded, a run queued) and then advances
 * on its own. The engine never mutates the app; it only decides which step is next.
 *
 * Two rules keep the walk honest:
 *   - A step that is already satisfied when the tour arrives at it going FORWARD is
 *     skipped (nobody needs "load an example" when a model is already open).
 *   - Going BACK never auto-advances, otherwise a satisfied action step could not be
 *     revisited.
 */

/** The slice of app state the steps look at. Plain data, so tests need no React. */
export interface TourContext {
  /** Active workspace tab. */
  tab: string;
  /** The editor holds a model with rows. */
  hasModel: boolean;
  /** The Run configuration dialog is open. */
  runDialogOpen: boolean;
  /** Queued or running solves. */
  activeJobs: number;
  /** Finished runs stored in History. */
  runCount: number;
  /** A run's results are loaded for the Analytics view. */
  hasResults: boolean;
}

export interface TourStep {
  id: string;
  title: string;
  body: string;
  /** `data-tour` value of the control to ring. Absent: a centred card with no ring. */
  target?: string;
  /** View to switch to when the step is entered. */
  tab?: string;
  /** What the user must do, shown under the body. Present on action steps. */
  action?: string;
  /**
   * Action steps: true once the user has done it. `anchor` is the context captured on
   * entering the most recent step flagged `anchor`, for "something increased" checks.
   */
  done?: (ctx: TourContext, anchor: TourContext) => boolean;
  /** Capture the context on entry, for later `done` predicates. */
  anchor?: boolean;
}

/** Where the walk is. `seq` changes on every move so the host navigates once per entry. */
export interface TourRun {
  index: number;
  entry: 'forward' | 'back';
  anchor: TourContext | null;
  seq: number;
}

/** Enter step `index`. Out-of-range indices clamp to the tour. */
export function enter(
  steps: readonly TourStep[], index: number, ctx: TourContext,
  entry: 'forward' | 'back', prev: TourRun | null,
): TourRun {
  const i = Math.min(Math.max(index, 0), steps.length - 1);
  const anchor = steps[i]?.anchor ? ctx : (prev?.anchor ?? null);
  return { index: i, entry, anchor, seq: (prev?.seq ?? 0) + 1 };
}

/** Whether step `step` is satisfied now. Steps without `done` always are. */
export function isDone(step: TourStep, ctx: TourContext, run: TourRun): boolean {
  return !step.done || step.done(ctx, run.anchor ?? ctx);
}

/** The next run, or `null` when `run` was the last step (the tour is finished). */
export function next(steps: readonly TourStep[], run: TourRun, ctx: TourContext): TourRun | null {
  if (run.index + 1 >= steps.length) return null;
  return enter(steps, run.index + 1, ctx, 'forward', run);
}

export function back(steps: readonly TourStep[], run: TourRun, ctx: TourContext): TourRun {
  return enter(steps, run.index - 1, ctx, 'back', run);
}

/**
 * Apply auto-advance: while the current step is an action step the user has just
 * satisfied (or one that was satisfied on arrival, going forward), move on.
 * Returns `null` when that runs off the end of the tour.
 */
export function settle(steps: readonly TourStep[], run: TourRun, ctx: TourContext): TourRun | null {
  let current: TourRun | null = run;
  for (let guard = 0; current && guard <= steps.length; guard += 1) {
    const step: TourStep | undefined = steps[current.index];
    if (!step || current.entry !== 'forward' || !step.done || !step.done(ctx, current.anchor ?? ctx)) {
      return current;
    }
    current = next(steps, current, ctx);
  }
  return current;
}

/** Index of `id`, or 0 for an unknown or missing id (the script changed between releases). */
export function indexOfStep(steps: readonly TourStep[], id: string | null | undefined): number {
  const i = id ? steps.findIndex((s) => s.id === id) : -1;
  return i < 0 ? 0 : i;
}

/** "3 / 11" progress for the callout header. */
export function progressLabel(steps: readonly TourStep[], run: TourRun): string {
  return `${run.index + 1} / ${steps.length}`;
}

/**
 * Whether the editor holds a network worth touring. Not `sessionHasModel`: config sheets
 * (scenarios, pathway, carbon library) get a row written into an empty model at boot, so
 * "any sheet has rows" is true before anything was loaded.
 */
export function hasNetwork(model: Record<string, unknown> | null | undefined): boolean {
  if (!model) return false;
  return ['buses', 'generators', 'loads'].some((sheet) => {
    const rows = model[sheet];
    return Array.isArray(rows) && rows.length > 0;
  });
}
