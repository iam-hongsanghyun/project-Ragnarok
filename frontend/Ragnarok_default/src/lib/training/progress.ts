/**
 * Tutorial progress arithmetic — pure, so the runner component holds no logic.
 *
 * Progress is stored as a set of completed step ids rather than an index, so
 * that reordering or inserting a step in the catalog does not silently mark
 * unrelated steps as done: an id that no longer exists is simply ignored.
 */
import { Tutorial, TutorialProgress } from './types';

export const emptyProgress = (): TutorialProgress => ({ completed: [], currentStepId: null });

/** Completed ids that still exist in the tutorial, deduplicated. */
export function liveCompleted(tutorial: Tutorial, progress: TutorialProgress): string[] {
  const known = new Set(tutorial.steps.map((s) => s.id));
  return Array.from(new Set(progress.completed)).filter((id) => known.has(id));
}

/** Completed step count, ignoring ids the catalog no longer defines. */
export function completedCount(tutorial: Tutorial, progress: TutorialProgress): number {
  return liveCompleted(tutorial, progress).length;
}

/** Whole-percent completion, 0–100. An empty tutorial counts as 0. */
export function percentComplete(tutorial: Tutorial, progress: TutorialProgress): number {
  if (tutorial.steps.length === 0) return 0;
  return Math.round((completedCount(tutorial, progress) / tutorial.steps.length) * 100);
}

export function isStepComplete(progress: TutorialProgress, stepId: string): boolean {
  return progress.completed.includes(stepId);
}

export function isTutorialComplete(tutorial: Tutorial, progress: TutorialProgress): boolean {
  return tutorial.steps.length > 0 && completedCount(tutorial, progress) === tutorial.steps.length;
}

/** First step not yet ticked, or the last step when everything is done. */
export function firstIncompleteStepId(tutorial: Tutorial, progress: TutorialProgress): string | null {
  if (tutorial.steps.length === 0) return null;
  const done = new Set(liveCompleted(tutorial, progress));
  const next = tutorial.steps.find((s) => !done.has(s.id));
  return next ? next.id : tutorial.steps[tutorial.steps.length - 1].id;
}

/**
 * The step the runner should show: the stored one when it still exists,
 * otherwise the first incomplete step.
 */
export function resolveCurrentStepId(tutorial: Tutorial, progress: TutorialProgress): string | null {
  if (progress.currentStepId && tutorial.steps.some((s) => s.id === progress.currentStepId)) {
    return progress.currentStepId;
  }
  return firstIncompleteStepId(tutorial, progress);
}

/** Position of a step id in the tutorial, or -1. */
export function stepIndex(tutorial: Tutorial, stepId: string | null): number {
  if (!stepId) return -1;
  return tutorial.steps.findIndex((s) => s.id === stepId);
}

/** Toggle a step's done state, leaving the current step untouched. */
export function toggleStep(progress: TutorialProgress, stepId: string): TutorialProgress {
  const done = new Set(progress.completed);
  if (done.has(stepId)) done.delete(stepId);
  else done.add(stepId);
  return { ...progress, completed: Array.from(done) };
}

/**
 * Tick `stepId` and advance to the next step. On the last step the current
 * step stays put — the runner shows the completion panel instead.
 */
export function completeAndAdvance(tutorial: Tutorial, progress: TutorialProgress, stepId: string): TutorialProgress {
  const done = new Set(progress.completed);
  done.add(stepId);
  const idx = stepIndex(tutorial, stepId);
  const nextId = idx >= 0 && idx + 1 < tutorial.steps.length ? tutorial.steps[idx + 1].id : stepId;
  return { completed: Array.from(done), currentStepId: nextId };
}

/** Move `delta` steps from the current position, clamped to the tutorial. */
export function moveBy(tutorial: Tutorial, progress: TutorialProgress, delta: number): TutorialProgress {
  const current = resolveCurrentStepId(tutorial, progress);
  const idx = stepIndex(tutorial, current);
  if (idx < 0) return progress;
  const clamped = Math.min(Math.max(idx + delta, 0), tutorial.steps.length - 1);
  return { ...progress, currentStepId: tutorial.steps[clamped].id };
}
