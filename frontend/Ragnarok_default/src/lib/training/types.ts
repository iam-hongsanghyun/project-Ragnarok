/**
 * Training tutorial model.
 *
 * A tutorial is a read-only script the user executes by hand. Ragnarok shows
 * WHERE to be, WHAT to type, WHICH file to import and WHEN to run — and then
 * gets out of the way. Nothing in this layer mutates the workbook, the session
 * or the settings; the only thing a tutorial may do to the app is switch the
 * active tab so the user is looking at the right view.
 *
 * That restriction is the whole point: a learner who watches values appear has
 * not learnt where those values live. Every number in `entries` is displayed
 * for the user to type themselves.
 */
import { WorkspaceTab } from 'lib/types';

export type TrainingLevel = 'Beginner' | 'Intermediate' | 'Advanced';

/**
 * One value the USER types. Never written by Ragnarok.
 *
 * `field` is addressed the way the UI addresses it — `generators.p_nom` for a
 * sheet column, `Settings → Solver → Threads` for a control — so the learner
 * can find it without a screenshot.
 */
export interface FieldEntry {
  /** Where the value goes: `sheet.column`, or `View → Section → Control`. */
  field: string;
  /** Exactly what to type. Shown verbatim and copyable; never auto-applied. */
  value: string;
  /** Unit of the value, when it carries one (MW, EUR/MWh, h, tCO2/MWh). */
  unit?: string;
  /** Why this value — the modelling reason, not the mechanics of typing it. */
  why: string;
}

/** One file the USER imports. Ragnarok never fetches or opens it for them. */
export interface FileEntry {
  /** What kind of file, e.g. "Project workbook (.xlsx)". */
  what: string;
  /** Which control performs the import, e.g. "Model → Open". */
  via: string;
  /** What the file must contain for the import to be accepted. */
  requires: string;
  /** Where to obtain the file when the user does not already have one. */
  source?: string;
}

/** A solve the USER starts. Ragnarok never submits a run on their behalf. */
export interface RunAction {
  /** The control to press, e.g. "Run → Run model". */
  label: string;
  /** Paragraphs describing what the run does and how long it takes. */
  detail: string[];
  /** What a successful run looks like from the outside. */
  expect: string;
}

/**
 * One stop on a step's guided walkthrough: a real element in the running app,
 * ringed and annotated so the learner looks at the thing itself rather than at
 * a description of it.
 *
 * The overlay never blocks input — the highlighted control stays clickable
 * throughout, because "click it and see" is the point.
 */
export interface Spotlight {
  /**
   * CSS selector for the element to ring. Resolved against the live document,
   * so it must match a class or attribute the app actually renders. A selector
   * that matches nothing is reported in the overlay rather than skipped
   * silently.
   */
  selector: string;
  /** Short name of what is being pointed at. */
  title: string;
  /** What to notice, or what to click and watch happen. */
  note?: string;
  /** View to switch to before this stop, when the target lives inside one. */
  tab?: WorkspaceTab;
  /**
   * Build wizard step id to open before this stop (`'snapshots'`, `'buses'`, …).
   *
   * Needed because most Build targets only exist on one step, so without this
   * the walkthrough would depend on the learner clicking the right step first —
   * and report its own target as missing when they did not. Opening a step is
   * navigation, in the same category as switching `tab`; it enters no values and
   * starts no runs.
   */
  buildStep?: string;
}

export interface TutorialStep {
  id: string;
  title: string;
  /**
   * Module heading this step belongs to, for a long course that groups its
   * steps ("2 · Economic dispatch"). Consecutive steps sharing a section render
   * under one heading in the rail. Omit on short tutorials.
   */
  section?: string;
  /** The view this step happens in. Drives the "Open <view>" button. */
  tab: WorkspaceTab;
  /** Precise location inside the view, e.g. "Build → Buses step". */
  where: string;
  /**
   * The modelling idea, independent of Ragnarok — what the concept is and why
   * it matters. Rendered ahead of the mechanics so a learner can read the
   * theory without the tool, and the tool without re-deriving the theory.
   */
  concept?: string[];
  /** The detailed explanation of what to do here, one string per paragraph. */
  explain: string[];
  /**
   * Guided walkthrough of the real UI for this step: each stop rings an element
   * and says what to notice. Shown behind a "Show me" button, never automatic.
   */
  spotlights?: Spotlight[];
  /** Values the user types at this step. */
  entries?: FieldEntry[];
  /** Files the user imports at this step. */
  files?: FileEntry[];
  /** The run the user starts at this step. */
  run?: RunAction;
  /** Observable facts that tell the user the step worked. */
  verify: string[];
  /** What commonly goes wrong here, and what it looks like. */
  pitfalls?: string[];
}

export interface Tutorial {
  id: string;
  title: string;
  level: TrainingLevel;
  /** Rough wall-clock time, excluding solve time on large models. */
  minutes: number;
  summary: string;
  /** What the learner can do once they finish. */
  outcomes: string[];
  /** What must already be true before the first step. */
  prerequisites: string[];
  steps: TutorialStep[];
}

/** Per-tutorial progress. Persisted per tutorial id, not globally. */
export interface TutorialProgress {
  /** Step ids the user has ticked off, in no particular order. */
  completed: string[];
  /** The step the runner is showing. Null → resolve to first incomplete. */
  currentStepId: string | null;
}
