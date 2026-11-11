/**
 * Training catalog — the registry of tutorials the Training view offers.
 *
 * The catalog is deliberately empty: tutorials are authored one at a time,
 * reviewed against the live UI, and appended here. The view renders an empty
 * state until the first one lands, so shipping the framework ahead of the
 * content is safe.
 *
 * ── Authoring rules ──────────────────────────────────────────────────────────
 * Enforced by review and by `catalog.test.ts`:
 *
 *   • Every value in a step's `entries` is a value the USER types. Ragnarok
 *     displays it and never writes it. That is what makes this training rather
 *     than a macro: the learner ends up knowing which sheet and which column
 *     the number lives in.
 *   • Every file in `files` is a file the USER imports, named together with the
 *     control that imports it and the shape the file must have.
 *   • Every `run` is a solve the USER starts from the Run dialog.
 *   • Every step ends with `verify` — observable facts, so the learner can tell
 *     a working step from a step that silently did nothing.
 *   • Field addresses use the UI's own vocabulary: `generators.p_nom` for a
 *     sheet column, `Settings → Solver → Threads` for a control.
 *   • `tab` must be the view the step actually happens in — it drives the
 *     "Open <view>" button, the only thing a tutorial is allowed to do to the
 *     app.
 *
 * Add a tutorial by defining it as a `const` above `TUTORIALS` and appending it
 * to that array, in the order it should be taught.
 */
import { CourseModule, Tutorial, TrainingLevel, TutorialProgress, TutorialStep } from './types';
import { guideStopFor, resolveCurrentStepId } from './progress';
import { POWER_MARKET_COURSE } from './course';

export const TUTORIALS: Tutorial[] = [POWER_MARKET_COURSE];

/** Levels in teaching order — drives the grouping in the training rail. */
export const LEVEL_ORDER: TrainingLevel[] = ['Beginner', 'Intermediate', 'Advanced', 'Expert'];

export function findTutorial(id: string | null): Tutorial | null {
  if (!id) return null;
  return TUTORIALS.find((t) => t.id === id) ?? null;
}

/** Tutorials grouped by level, levels in teaching order, empty levels dropped. */
export function tutorialsByLevel(tutorials: Tutorial[] = TUTORIALS): Array<{ level: TrainingLevel; items: Tutorial[] }> {
  return LEVEL_ORDER
    .map((level) => ({ level, items: tutorials.filter((t) => t.level === level) }))
    .filter((group) => group.items.length > 0);
}

/** A module paired with the steps that declare it, and their global positions. */
export interface ModuleWithSteps {
  module: CourseModule;
  /** This module's steps, each with its 1-based position in the whole course. */
  items: Array<{ step: TutorialStep; number: number }>;
}

/**
 * The tutorial's modules, each with its steps, in teaching order.
 *
 * Modules with nothing written yet are dropped rather than shown empty — a rail
 * entry that opens onto no steps is worse than no entry. A tutorial that
 * declares no modules at all yields none, and the caller falls back to a flat
 * step list.
 */
export function modulesWithSteps(tutorial: Tutorial): ModuleWithSteps[] {
  const numbered = tutorial.steps.map((step, i) => ({ step, number: i + 1 }));
  return (tutorial.modules ?? [])
    .map((module) => ({
      module,
      items: numbered.filter(({ step }) => step.section === module.section),
    }))
    .filter((m) => m.items.length > 0);
}

/** Modules grouped by level, levels in teaching order, empty levels dropped. */
export function modulesByLevel(tutorial: Tutorial): Array<{ level: TrainingLevel; items: ModuleWithSteps[] }> {
  const all = modulesWithSteps(tutorial);
  return LEVEL_ORDER
    .map((level) => ({ level, items: all.filter((m) => m.module.level === level) }))
    .filter((group) => group.items.length > 0);
}

export interface StepGroup {
  /** Section heading, or null for steps that declare none. */
  section: string | null;
  /** Steps in this run, paired with their 1-based position in the tutorial. */
  items: Array<{ step: TutorialStep; number: number }>;
}


/** The module `section` a step belongs to, or null for an unknown step or one with no section. */
export function sectionOfStep(tutorial: Tutorial, stepId: string | null): string | null {
  if (!stepId) return null;
  return tutorial.steps.find((s) => s.id === stepId)?.section ?? null;
}

/**
 * Where a step sits inside its own module: 0-based index and the module's step
 * count. The runner shows one module at a time ("Step 3 of 10"), so anything
 * else that names the learner's position has to count the same way.
 */
export function positionInModule(
  tutorial: Tutorial, stepId: string | null,
): { index: number; count: number } | null {
  const section = sectionOfStep(tutorial, stepId);
  const ids = tutorial.steps.filter((s) => section !== null && s.section === section).map((s) => s.id);
  const index = stepId ? ids.indexOf(stepId) : -1;
  return index < 0 ? null : { index, count: ids.length };
}

/**
 * The step a module opens on: the step the learner was last on when it is in
 * this module, otherwise the module's first step not yet ticked, otherwise its
 * first step. Re-entering a module resumes it rather than restarting it.
 */
export function moduleEntryStepId(
  tutorial: Tutorial, progress: TutorialProgress, section: string,
): string | null {
  const steps = tutorial.steps.filter((s) => s.section === section);
  if (steps.length === 0) return null;
  if (progress.currentStepId && steps.some((s) => s.id === progress.currentStepId)) return progress.currentStepId;
  const done = new Set(progress.completed);
  return (steps.find((s) => !done.has(s.id)) ?? steps[0]).id;
}

/**
 * Where "Back to tutorial" takes the learner: the module of the step they were
 * on and, when they closed that step's walkthrough part-way, the stop to resume.
 */
export function resumeTarget(
  tutorial: Tutorial, progress: TutorialProgress,
): { stepId: string | null; section: string | null; guideStop: number } {
  const stepId = resolveCurrentStepId(tutorial, progress);
  const step = tutorial.steps.find((s) => s.id === stepId);
  const stop = stepId ? guideStopFor(progress, stepId) : 0;
  const resumable = !!step?.spotlights && stop > 0 && stop < step.spotlights.length;
  return { stepId, section: step?.section ?? null, guideStop: resumable ? stop : 0 };
}
