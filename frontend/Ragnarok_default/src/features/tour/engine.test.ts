import { describe, it, expect } from '@jest/globals';
import { back, enter, hasNetwork, indexOfStep, isDone, next, settle, type TourContext, type TourStep } from './engine';
import { placeCard } from './placement';
import { TOUR_STEPS } from './steps';
import { parsePersisted, serializePersisted, UNSEEN } from './store';

const ctx0: TourContext = {
  tab: 'Welcome', hasModel: false, runDialogOpen: false, activeJobs: 0, runCount: 0, hasResults: false,
};
const c = (over: Partial<TourContext>): TourContext => ({ ...ctx0, ...over });

const steps: TourStep[] = [
  { id: 'intro', title: 'a', body: 'a' },
  { id: 'load', title: 'b', body: 'b', done: (x) => x.hasModel },
  { id: 'open', title: 'c', body: 'c', anchor: true, done: (x) => x.runDialogOpen },
  { id: 'queued', title: 'd', body: 'd', done: (x, a) => x.activeJobs + x.runCount > a.activeJobs + a.runCount },
  { id: 'end', title: 'e', body: 'e' },
];

describe('step engine', () => {
  it('waits on an action step until the app state changes, then advances', () => {
    let run = enter(steps, 1, ctx0, 'forward', null);
    expect(settle(steps, run, ctx0)).toBe(run);
    expect(isDone(steps[1], ctx0, run)).toBe(false);
    const after = settle(steps, run, c({ hasModel: true }));
    expect(after?.index).toBe(2);
    run = after!;
    expect(run.seq).toBeGreaterThan(1);
  });

  it('skips an action step that is already satisfied on arrival going forward', () => {
    const withModel = c({ hasModel: true });
    const run = enter(steps, 0, withModel, 'forward', null);
    const moved = next(steps, run, withModel)!;
    expect(moved.index).toBe(1);
    expect(settle(steps, moved, withModel)?.index).toBe(2);
  });

  it('does not auto-advance after going back to a satisfied step', () => {
    const withModel = c({ hasModel: true });
    const at2 = enter(steps, 2, withModel, 'forward', null);
    const backed = back(steps, at2, withModel);
    expect(backed.index).toBe(1);
    expect(backed.entry).toBe('back');
    expect(settle(steps, backed, withModel)).toBe(backed);
  });

  it('compares against the anchor captured on entering the flagged step', () => {
    const before = c({ hasModel: true, runCount: 3 });
    const open = enter(steps, 2, before, 'forward', null);
    expect(open.anchor).toEqual(before);
    const queued = next(steps, { ...open, entry: 'forward' }, c({ ...before, runDialogOpen: true }))!;
    expect(queued.anchor).toEqual(before);
    expect(isDone(steps[3], c({ ...before, runCount: 3 }), queued)).toBe(false);
    expect(isDone(steps[3], c({ ...before, activeJobs: 1 }), queued)).toBe(true);
  });

  it('returns null when the last step is passed (tour finished)', () => {
    const last = enter(steps, 4, ctx0, 'forward', null);
    expect(next(steps, last, ctx0)).toBeNull();
    const second = enter(steps, 3, c({ activeJobs: 1 }), 'forward', enter(steps, 2, ctx0, 'forward', null));
    expect(settle(steps, { ...second }, c({ activeJobs: 1 }))?.index).toBe(4);
  });

  it('clamps indices and resolves unknown step ids to the first step', () => {
    expect(enter(steps, 99, ctx0, 'forward', null).index).toBe(4);
    expect(enter(steps, -3, ctx0, 'back', null).index).toBe(0);
    expect(indexOfStep(steps, 'open')).toBe(2);
    expect(indexOfStep(steps, 'gone')).toBe(0);
    expect(indexOfStep(steps, null)).toBe(0);
  });
});

describe('tour script', () => {
  it('has unique ids and ends with a card that needs no action', () => {
    const ids = TOUR_STEPS.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(TOUR_STEPS[TOUR_STEPS.length - 1].done).toBeUndefined();
  });

  it('covers build, edit, run and analyse', () => {
    const tabs = TOUR_STEPS.map((s) => s.tab);
    expect(tabs).toEqual(expect.arrayContaining(['Build', 'Model', 'History', 'Analytics']));
    expect(TOUR_STEPS.some((s) => s.target === 'run-button')).toBe(true);
  });

  it('walks the whole script when the user completes each action in turn', () => {
    let state = c({});
    let run = enter(TOUR_STEPS, 0, state, 'forward', null);
    const seen: string[] = [];
    const advance = (patch: Partial<TourContext>) => {
      state = c({ ...state, ...patch });
      const settled = settle(TOUR_STEPS, run, state);
      if (settled) run = settled;
      return settled;
    };
    const manual = () => { seen.push(TOUR_STEPS[run.index].id); run = next(TOUR_STEPS, run, state)!; };
    manual();                                    // welcome
    expect(TOUR_STEPS[run.index].id).toBe('load-example');
    advance({ hasModel: true, tab: 'Build' });
    expect(TOUR_STEPS[run.index].id).toBe('build');
    manual(); manual(); manual();                // build, model-table, model-add-row
    expect(TOUR_STEPS[run.index].id).toBe('run-open');
    advance({ runDialogOpen: true });
    expect(TOUR_STEPS[run.index].id).toBe('run-submit');
    advance({ runDialogOpen: false, activeJobs: 1 });
    expect(TOUR_STEPS[run.index].id).toBe('run-wait');
    advance({ activeJobs: 0, runCount: 1 });
    expect(TOUR_STEPS[run.index].id).toBe('history-open');
    advance({ tab: 'Analytics', hasResults: true });
    expect(TOUR_STEPS[run.index].id).toBe('analytics');
  });
});

describe('persisted progress', () => {
  it('round-trips and tolerates corrupt, foreign or missing blobs', () => {
    expect(parsePersisted(serializePersisted({ status: 'paused', stepId: 'build' }))).toEqual({ status: 'paused', stepId: 'build' });
    expect(parsePersisted(null)).toEqual(UNSEEN);
    expect(parsePersisted('{not json')).toEqual(UNSEEN);
    expect(parsePersisted('{"v":9,"status":"done"}')).toEqual(UNSEEN);
    expect(parsePersisted('{"v":1,"status":"weird"}')).toEqual(UNSEEN);
    expect(parsePersisted('{"v":1,"status":"active","stepId":5}')).toEqual({ status: 'active', stepId: null });
    expect(parsePersisted('null')).toEqual(UNSEEN);
  });
});

describe('card placement', () => {
  const vp = { width: 1000, height: 700 };
  const card = { width: 340, height: 200 };

  it('centres the card when there is no target', () => {
    expect(placeCard(null, card, vp)).toEqual({ top: 250, left: 330 });
  });

  it('prefers below, flips above near the bottom, and clamps into the viewport', () => {
    expect(placeCard({ top: 100, left: 10, width: 100, height: 30 }, card, vp)).toEqual({ top: 144, left: 12 });
    expect(placeCard({ top: 640, left: 900, width: 80, height: 30 }, card, vp)).toEqual({ top: 426, left: 648 });
  });

  it('uses the side when above and below do not fit, and pins inside for a screen-sized target', () => {
    const tall = placeCard({ top: 20, left: 20, width: 200, height: 660 }, card, vp);
    expect(tall.left).toBe(234);
    const huge = placeCard({ top: 0, left: 0, width: 1000, height: 700 }, card, vp);
    expect(huge).toEqual({ top: 488, left: 648 });
  });

  it('never leaves a tiny viewport', () => {
    const p = placeCard({ top: 5, left: 5, width: 50, height: 20 }, card, { width: 300, height: 180 });
    expect(p.top).toBeGreaterThanOrEqual(12);
    expect(p.left).toBeGreaterThanOrEqual(12);
  });
});

describe('hasNetwork', () => {
  it('ignores config sheets that boot writes into an empty model', () => {
    expect(hasNetwork(null)).toBe(false);
    expect(hasNetwork({ buses: [], scenarios: [{ name: 'x' }] })).toBe(false);
    expect(hasNetwork({ buses: [{ name: 'b' }] })).toBe(true);
    expect(hasNetwork({ generators: [{ name: 'g' }] })).toBe(true);
  });
});
