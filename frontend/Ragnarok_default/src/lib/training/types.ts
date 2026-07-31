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

export interface TutorialStep {
  id: string;
  title: string;
  /** The view this step happens in. Drives the "Open <view>" button. */
  tab: WorkspaceTab;
  /** Precise location inside the view, e.g. "Build → Buses step". */
  where: string;
  /** The detailed explanation, one string per paragraph. */
  explain: string[];
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
