/**
 * The core-loop tour script: build, edit, run, analyse.
 *
 * Declarative: each entry names the view, the control (`data-tour="..."`, added to the
 * real component) and, for action steps, the app-state change that completes it. Add or
 * reorder steps here only; the engine and overlay are generic. Ids are persisted, so
 * renaming one sends a returning user back to the first step.
 */
import type { TourStep } from './engine';

export const TOUR_STEPS: readonly TourStep[] = [
  {
    id: 'welcome',
    tab: 'Welcome',
    title: 'Welcome to Ragnarok',
    body: 'This two-minute tour walks the loop you will repeat for every study: open a network, edit it, '
      + 'run it, read the answer. It uses a bundled example, so nothing of yours is touched. '
      + 'Use the arrow keys or the buttons to move; Esc leaves the tour and you can resume it later.',
  },
  {
    id: 'load-example',
    tab: 'Welcome',
    target: 'start-example',
    title: 'Open an example network',
    body: 'Examples are complete, ready-to-solve models. They are the quickest way to see every view with real data.',
    action: 'Choose Start with an example, then pick one (the three-bus network is the smallest).',
    done: (ctx) => ctx.hasModel,
  },
  {
    id: 'build',
    tab: 'Build',
    target: 'build-steps',
    title: 'Build: structure the network',
    body: 'Build is the guided editor for the network itself: snapshots (the time axis), buses, generators, '
      + 'loads, storage and links, one step at a time. Use it to assemble a model from scratch or to extend an example.',
  },
  {
    id: 'model-table',
    tab: 'Model',
    target: 'model-table',
    title: 'Model: edit any value',
    body: 'Model shows every sheet of the workbook. Pick a sheet in the left tree, click a cell, type a value and '
      + 'press Enter. Edits are saved to the working session on the server straight away.',
  },
  {
    id: 'model-add-row',
    tab: 'Model',
    target: 'add-row',
    title: 'Add a component',
    body: 'This button adds a row to the open sheet: a new generator on the Generators sheet, a new bus on Buses. '
      + 'Sheet columns are PyPSA attributes, so the names match the PyPSA documentation.',
  },
  {
    id: 'run-open',
    target: 'run-button',
    anchor: true,
    title: 'Run: solve the model',
    body: 'The Run button is available from every view. Runs are queued and solved one at a time on the server, '
      + 'so the interface stays responsive while a solve is in progress.',
    action: 'Press Run.',
    done: (ctx) => ctx.runDialogOpen,
  },
  {
    id: 'run-submit',
    target: 'run-submit',
    title: 'Start the solve',
    body: 'The dialog summarises the study window and the active constraints. The defaults are fine for an example.',
    action: 'Press Run model.',
    done: (ctx, anchor) => ctx.activeJobs + ctx.runCount > anchor.activeJobs + anchor.runCount,
  },
  {
    id: 'run-wait',
    target: 'nav-history',
    title: 'The run is solving',
    body: 'A Running chip appears in the top bar while the solver works. When it finishes, the run is stored in History '
      + 'so you can reopen it any time without solving again. An example takes a few seconds.',
    action: 'Wait for the run to finish.',
    done: (ctx, anchor) => ctx.activeJobs === 0 && ctx.runCount > anchor.runCount,
  },
  {
    id: 'history-open',
    tab: 'History',
    target: 'view-result',
    title: 'Open the result',
    body: 'History lists every finished run. Tick one, or several to compare them side by side. View result opens the selection.',
    action: 'Tick your run, then press View result.',
    done: (ctx) => ctx.tab === 'Analytics' && ctx.hasResults,
  },
  {
    id: 'analytics',
    tab: 'Analytics',
    target: 'analytics-view',
    title: 'Analytics: read the answer',
    body: 'Dispatch by carrier, prices, costs, emissions and per-asset detail for the run you opened. '
      + 'Click an element on the map or a chart legend to drill into it.',
  },
  {
    id: 'finish',
    tab: 'Analytics',
    title: 'That is the loop',
    body: 'Build or import, edit, run, analyse. The Training tab has step-by-step courses that go deeper, and '
      + 'Take the tour in the top bar replays this walkthrough whenever you want it.',
  },
];
