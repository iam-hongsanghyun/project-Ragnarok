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

export type TrainingLevel = 'Beginner' | 'Intermediate' | 'Advanced' | 'Expert';

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
  /**
   * Plain-English name for the field — `p_nom` is meaningless until you are told
   * it is installed capacity. Always supply this for a PyPSA attribute; a learner
   * who only ever sees the symbol has not been taught anything.
   */
  label?: string;
  /** Exactly what to type. Shown verbatim and copyable; never auto-applied. */
  value: string;
  /** Unit of the value, when it carries one (MW, EUR/MWh, h, tCO2/MWh). */
  unit?: string;
  /**
   * What the field controls and why THIS value. Not a restatement of the label:
   * it should say what changes in the answer if the number were different, so the
   * learner could choose their own value next time.
   */
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
  /**
   * Whether the Run dialog must be open for this stop.
   *
   * `'open'` ensures it is, `'closed'` ensures it is not, omitted leaves it
   * alone. Needed for the same reason as `buildStep`: the planning summary and
   * the Dry-run toggle only exist while the dialog is up, and a walkthrough that
   * cannot open it reports its own targets as missing.
   *
   * Opening a dialog is navigation. It does not enter values and does not submit
   * the run — the learner still presses Validate or Run model themselves.
   */
  runDialog?: 'open' | 'closed';
}

/** The three ways a learner may open a module. */
export type TutorialStartChoice = 'empty' | 'prebuilt' | 'complete';

/**
 * How a learner may start a module: with nothing, with the model this module
 * begins from, or with the model it ends with.
 *
 * Declared on the first step of every module, and offered as one three-way
 * choice. Nothing loads on its own — a learner arriving from the previous
 * module already holds the prebuilt model, and silently replacing their own
 * work with a bundled copy is the worst thing this could do.
 *
 * Both ids name bundled `/api/examples` entries, and each names the state at
 * the END of a module — so module N's `prebuilt` is module N-1's `complete`
 * (`training_m1` is module 2's prebuilt and module 1's complete).
 */
export interface StepStartOptions {
  /**
   * The model as it stands at the START of this module — what the previous
   * module finished with. Omitted on module 1, which starts from nothing.
   */
  prebuiltExampleId?: string;
  /**
   * The model as it stands at the END of this module, for a learner who wants
   * to read and run rather than build, or who wants to check their own work
   * against the finished article.
   */
  completeExampleId?: string;
  /** What these models hold, so a learner can tell which one they want. */
  note: string;
}

export interface TutorialStep {
  id: string;
  title: string;
  /**
   * The models a learner may start this module from, when this step opens one.
   * Rendered as a three-way choice; see `StepStartOptions`.
   */
  startOptions?: StepStartOptions;
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

/**
 * One module of a course — the unit a learner picks from the rail.
 *
 * Steps declare which module they belong to with `section`; this is the module
 * itself, carrying the things a step cannot: its level and how long it takes.
 * Kept as its own table rather than repeated on every step so the two cannot
 * disagree.
 */
export interface CourseModule {
  /** Matches the `section` string on this module's steps. */
  section: string;
  /** Module name without its number, for the rail. */
  title: string;
  /** How hard it is, which is how the rail groups modules. */
  level: TrainingLevel;
  /** Rough wall-clock minutes, excluding solve time. */
  minutes: number;
  /** One line on what the module teaches, shown under its name. */
  summary: string;
}

export interface Tutorial {
  id: string;
  title: string;
  /** The modules its steps are grouped into, in teaching order. */
  modules?: CourseModule[];
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
  /**
   * Walkthrough position within a step: step id → last spotlight stop reached.
   *
   * A learner is at step 5, stop 5 of 7, and leaves to do the work. Without this
   * they come back to stop 1 and have to click through five stops again — the
   * walkthrough is the part they were actually in the middle of, so it is the part
   * that most needs remembering.
   */
  guideStop?: Record<string, number>;
  /**
   * Which start a learner chose for each module: step id of a module opener →
   * `'empty'`, `'prebuilt'` or `'complete'`.
   *
   * Persisted rather than held in the component because loading an example
   * rehydrates the model and remounts the view that owns the control, so local
   * state would silently forget the choice.
   */
  startChoice?: Record<string, TutorialStartChoice>;
}
