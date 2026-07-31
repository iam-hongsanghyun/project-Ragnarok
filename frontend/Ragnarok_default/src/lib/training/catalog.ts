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
import { Tutorial, TrainingLevel } from './types';

export const TUTORIALS: Tutorial[] = [];

/** Levels in teaching order — drives the grouping in the training rail. */
export const LEVEL_ORDER: TrainingLevel[] = ['Beginner', 'Intermediate', 'Advanced'];

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
