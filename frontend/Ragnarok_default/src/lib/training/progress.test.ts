import { describe, test, expect } from '@jest/globals';
import {
  clearEntries,
  clearGuideStop,
  completeAndAdvance,
  completedCount,
  emptyProgress,
  entriesDoneFor,
  firstIncompleteStepId,
  guideStopFor,
  isEntryDone,
  isTutorialComplete,
  liveCompleted,
  moveBy,
  percentComplete,
  resolveCurrentStepId,
  setGuideStop,
  stepIndex,
  toggleEntry,
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

describe('within-step entry progress', () => {
  // A step can list twenty values entered a few at a time. Without this, a
  // learner returning mid-step has to re-find their place in the list.
  test('an untouched step has no entries done', () => {
    expect(entriesDoneFor(emptyProgress(), 'a')).toEqual([]);
    expect(isEntryDone(emptyProgress(), 'a', 'generators.p_nom')).toBe(false);
  });

  test('toggling an entry records and clears it', () => {
    const once = toggleEntry(emptyProgress(), 'a', 'generators.p_nom');
    expect(isEntryDone(once, 'a', 'generators.p_nom')).toBe(true);
    expect(isEntryDone(toggleEntry(once, 'a', 'generators.p_nom'), 'a', 'generators.p_nom')).toBe(false);
  });

  test('entries are scoped per step', () => {
    const p = toggleEntry(emptyProgress(), 'a', 'buses.name');
    expect(isEntryDone(p, 'a', 'buses.name')).toBe(true);
    expect(isEntryDone(p, 'b', 'buses.name')).toBe(false);
  });

  test('toggling an entry leaves step completion and cursor alone', () => {
    const base = { completed: ['a'], currentStepId: 'b' };
    const next = toggleEntry(base, 'b', 'loads.p_set');
    expect(next.completed).toEqual(['a']);
    expect(next.currentStepId).toBe('b');
  });

  test('clearEntries drops one step without touching others', () => {
    let p = toggleEntry(emptyProgress(), 'a', 'x');
    p = toggleEntry(p, 'b', 'y');
    const cleared = clearEntries(p, 'a');
    expect(entriesDoneFor(cleared, 'a')).toEqual([]);
    expect(entriesDoneFor(cleared, 'b')).toEqual(['y']);
  });

  test('clearEntries on progress that has none is a no-op', () => {
    expect(clearEntries(emptyProgress(), 'a')).toEqual(emptyProgress());
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
