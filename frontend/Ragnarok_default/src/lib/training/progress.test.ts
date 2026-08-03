import { describe, test, expect } from '@jest/globals';
import {
  clearGuideStop,
  completeAndAdvance,
  completedCount,
  emptyProgress,
  firstIncompleteStepId,
  guideStopFor,
  isCheckpointLoaded,
  isTutorialComplete,
  liveCompleted,
  moveBy,
  percentComplete,
  resolveCurrentStepId,
  setCheckpointLoaded,
  setGuideStop,
  stepIndex,
  toggleStep,
} from './progress';
import { Tutorial, TutorialStep } from './types';

const step = (id: string): TutorialStep => ({
  id,
  title: id,
  tab: 'Model',
  where: 'Model view',
  explain: ['…'],
  verify: ['…'],
});

const tutorial = (ids: string[]): Tutorial => ({
  id: 't',
  title: 'T',
  level: 'Beginner',
  minutes: 1,
  summary: '…',
  outcomes: [],
  prerequisites: [],
  steps: ids.map(step),
});

const T = tutorial(['a', 'b', 'c', 'd']);

describe('completion arithmetic', () => {
  test('an untouched tutorial is 0%', () => {
    expect(percentComplete(T, emptyProgress())).toBe(0);
    expect(isTutorialComplete(T, emptyProgress())).toBe(false);
  });

  test('percent rounds to whole numbers', () => {
    expect(percentComplete(T, { completed: ['a'], currentStepId: null })).toBe(25);
    expect(percentComplete(tutorial(['a', 'b', 'c']), { completed: ['a'], currentStepId: null })).toBe(33);
  });

  test('all steps ticked is 100% and complete', () => {
    const done = { completed: ['a', 'b', 'c', 'd'], currentStepId: null };
    expect(percentComplete(T, done)).toBe(100);
    expect(isTutorialComplete(T, done)).toBe(true);
  });

  test('an empty tutorial is 0% and never complete', () => {
    const empty = tutorial([]);
    expect(percentComplete(empty, emptyProgress())).toBe(0);
    expect(isTutorialComplete(empty, emptyProgress())).toBe(false);
  });
});

describe('stale ids', () => {
  // Progress survives catalog edits: a step id that no longer exists must not
  // inflate the count, and duplicates must not double-count.
  test('ids the catalog no longer defines are ignored', () => {
    const progress = { completed: ['a', 'removed-step'], currentStepId: null };
    expect(liveCompleted(T, progress)).toEqual(['a']);
    expect(completedCount(T, progress)).toBe(1);
    expect(percentComplete(T, progress)).toBe(25);
  });

  test('duplicates count once', () => {
    expect(completedCount(T, { completed: ['a', 'a', 'b'], currentStepId: null })).toBe(2);
  });
});

describe('current step resolution', () => {
  test('resolves to the first incomplete step when nothing is stored', () => {
    expect(resolveCurrentStepId(T, { completed: ['a'], currentStepId: null })).toBe('b');
  });

  test('a stored step wins over the first incomplete one', () => {
    expect(resolveCurrentStepId(T, { completed: [], currentStepId: 'd' })).toBe('d');
  });

  test('a stored step the catalog dropped falls back to the first incomplete one', () => {
    expect(resolveCurrentStepId(T, { completed: ['a', 'b'], currentStepId: 'gone' })).toBe('c');
  });

  test('a fully complete tutorial parks on the last step', () => {
    expect(firstIncompleteStepId(T, { completed: ['a', 'b', 'c', 'd'], currentStepId: null })).toBe('d');
  });

  test('an empty tutorial has no current step', () => {
    expect(resolveCurrentStepId(tutorial([]), emptyProgress())).toBeNull();
  });
});

describe('mutations', () => {
  test('toggleStep flips a step without moving the cursor', () => {
    const once = toggleStep({ completed: [], currentStepId: 'b' }, 'a');
    expect(once).toEqual({ completed: ['a'], currentStepId: 'b' });
    expect(toggleStep(once, 'a').completed).toEqual([]);
  });

  test('completeAndAdvance ticks the step and moves to the next', () => {
    const next = completeAndAdvance(T, emptyProgress(), 'a');
    expect(next.completed).toEqual(['a']);
    expect(next.currentStepId).toBe('b');
  });

  test('completeAndAdvance on the last step ticks it and stays put', () => {
    const next = completeAndAdvance(T, { completed: ['a', 'b', 'c'], currentStepId: 'd' }, 'd');
    expect(isTutorialComplete(T, next)).toBe(true);
    expect(next.currentStepId).toBe('d');
  });

  test('moveBy clamps at both ends', () => {
    expect(moveBy(T, { completed: [], currentStepId: 'a' }, -1).currentStepId).toBe('a');
    expect(moveBy(T, { completed: [], currentStepId: 'd' }, 1).currentStepId).toBe('d');
    expect(moveBy(T, { completed: [], currentStepId: 'b' }, 2).currentStepId).toBe('d');
  });

  test('stepIndex reports -1 for an unknown or null id', () => {
    expect(stepIndex(T, 'c')).toBe(2);
    expect(stepIndex(T, 'gone')).toBe(-1);
    expect(stepIndex(T, null)).toBe(-1);
  });
});

describe('walkthrough stage', () => {
  // Closing a walkthrough to do the work must not lose the stage — "Back to
  // tutorial" resumes at the stop the learner was on.
  test('an untouched step has stage 0', () => {
    expect(guideStopFor(emptyProgress(), 'a')).toBe(0);
  });

  test('setGuideStop records per step and does not disturb the rest', () => {
    const base = { completed: ['a'], currentStepId: 'b' };
    const p = setGuideStop(base, 'b', 4);
    expect(guideStopFor(p, 'b')).toBe(4);
    expect(guideStopFor(p, 'a')).toBe(0);
    expect(p.completed).toEqual(['a']);
    expect(p.currentStepId).toBe('b');
  });

  test('negative stops clamp to 0', () => {
    expect(guideStopFor(setGuideStop(emptyProgress(), 'a', -3), 'a')).toBe(0);
  });

  test('clearGuideStop forgets one step only', () => {
    let p = setGuideStop(emptyProgress(), 'a', 2);
    p = setGuideStop(p, 'b', 5);
    const cleared = clearGuideStop(p, 'a');
    expect(guideStopFor(cleared, 'a')).toBe(0);
    expect(guideStopFor(cleared, 'b')).toBe(5);
  });

  test('clearGuideStop without a record is a no-op', () => {
    expect(clearGuideStop(emptyProgress(), 'a')).toEqual(emptyProgress());
  });
});

describe('module prebuilt-data tick', () => {
  // One checkbox per module, and it has to survive the remount that loading an
  // example causes — which is why it lives in progress, not component state.
  test('an untouched module opener is unticked', () => {
    expect(isCheckpointLoaded(emptyProgress(), 'm2-merit-order')).toBe(false);
  });

  test('the tick is recorded and cleared per module', () => {
    const on = setCheckpointLoaded(emptyProgress(), 'm2-merit-order', true);
    expect(isCheckpointLoaded(on, 'm2-merit-order')).toBe(true);
    expect(isCheckpointLoaded(setCheckpointLoaded(on, 'm2-merit-order', false), 'm2-merit-order')).toBe(false);
  });

  test('modules do not share a tick', () => {
    const on = setCheckpointLoaded(emptyProgress(), 'm2-merit-order', true);
    expect(isCheckpointLoaded(on, 'm3-two-buses')).toBe(false);
  });

  test('ticking leaves step completion and the cursor alone', () => {
    const next = setCheckpointLoaded({ completed: ['a'], currentStepId: 'b' }, 'b', true);
    expect(next.completed).toEqual(['a']);
    expect(next.currentStepId).toBe('b');
  });
});
