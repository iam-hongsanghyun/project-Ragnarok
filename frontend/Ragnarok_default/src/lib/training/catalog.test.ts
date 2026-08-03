import { describe, test, expect } from '@jest/globals';
import { TUTORIALS, LEVEL_ORDER, findTutorial, tutorialsByLevel } from './catalog';

/**
 * Integrity gate on the catalog. Tutorials are authored one at a time, so these
 * pass vacuously today and start biting the moment content lands — which is the
 * point: the authoring rules in `catalog.ts` are checked here, not just stated.
 */
describe('catalog integrity', () => {
  test('tutorial ids are unique', () => {
    const ids = TUTORIALS.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  test('step ids are unique within each tutorial', () => {
    for (const t of TUTORIALS) {
      const ids = t.steps.map((s) => s.id);
      expect(new Set(ids).size).toBe(ids.length);
    }
  });

  test('every tutorial declares a known level and has at least one step', () => {
    for (const t of TUTORIALS) {
      expect(LEVEL_ORDER).toContain(t.level);
      expect(t.steps.length).toBeGreaterThan(0);
    }
  });

  test('every step explains itself and says how to verify it', () => {
    // A step with no `verify` leaves the learner unable to tell a working step
    // from one that silently did nothing — the failure mode this whole feature
    // exists to avoid.
    for (const t of TUTORIALS) {
      for (const s of t.steps) {
        expect(s.explain.length).toBeGreaterThan(0);
        expect(s.verify.length).toBeGreaterThan(0);
        expect(s.title.trim()).not.toBe('');
        expect(s.where.trim()).not.toBe('');
      }
    }
  });

  test('every value the user must type carries a reason', () => {
    for (const t of TUTORIALS) {
      for (const s of t.steps) {
        for (const e of s.entries ?? []) {
          expect(e.field.trim()).not.toBe('');
          expect(e.value.trim()).not.toBe('');
          expect(e.why.trim()).not.toBe('');
        }
      }
    }
  });

  // The failure mode this guards against is pointing instead of teaching: a stop
  // that says "check the bus cell" and moves on, or a `p_nom` the learner is
  // never told means capacity. Length is a crude proxy, but it catches the thin
  // one-liners that slip in when authoring at speed.
  test('a PyPSA attribute is always given a plain-English name', () => {
    for (const t of TUTORIALS) {
      for (const s of t.steps) {
        for (const e of s.entries ?? []) {
          // `sheet.column` addresses a PyPSA attribute; `View → Control` does not.
          if (!/^[a-z_]+(-[a-z_]+)?\.[a-z_]+/.test(e.field)) continue;
          expect(e.label?.trim() || '').not.toBe('');
        }
      }
    }
  });

  test('explanations say enough to be useful', () => {
    for (const t of TUTORIALS) {
      for (const s of t.steps) {
        for (const e of s.entries ?? []) {
          expect(e.why.length).toBeGreaterThan(40);
        }
        for (const sp of s.spotlights ?? []) {
          if (sp.note !== undefined) expect(sp.note.length).toBeGreaterThan(40);
        }
      }
    }
  });

  // A checkpoint whose example id is wrong loads the wrong model, or nothing,
  // and the learner has no way to tell — so the shape is checked here and the id
  // itself is checked against `/api/examples` by the backend example test.
  test('every module checkpoint names an example and says what it holds', () => {
    for (const t of TUTORIALS) {
      for (const s of t.steps) {
        if (!s.checkpoint) continue;
        expect(s.checkpoint.exampleId.trim()).not.toBe('');
        expect(s.checkpoint.note.length).toBeGreaterThan(40);
      }
    }
  });

  // The first step of a tutorial has the start-state banner; a checkpoint there
  // too would stack two banners saying different things about the same session.
  test('no checkpoint sits on a step that already carries the start state', () => {
    for (const t of TUTORIALS) {
      if (t.startState) expect(t.steps[0].checkpoint).toBeUndefined();
    }
  });

  test('every file the user must import names the control and the required shape', () => {
    for (const t of TUTORIALS) {
      for (const s of t.steps) {
        for (const f of s.files ?? []) {
          expect(f.what.trim()).not.toBe('');
          expect(f.via.trim()).not.toBe('');
          expect(f.requires.trim()).not.toBe('');
        }
      }
    }
  });
});

describe('lookup helpers', () => {
  test('findTutorial returns null for unknown and null ids', () => {
    expect(findTutorial(null)).toBeNull();
    expect(findTutorial('no-such-tutorial')).toBeNull();
  });

  test('findTutorial round-trips every catalog entry', () => {
    for (const t of TUTORIALS) expect(findTutorial(t.id)).toBe(t);
  });

  test('tutorialsByLevel drops empty levels and keeps teaching order', () => {
    const groups = tutorialsByLevel();
    const levels = groups.map((g) => g.level);
    expect(levels).toEqual(LEVEL_ORDER.filter((l) => levels.includes(l)));
    for (const g of groups) expect(g.items.length).toBeGreaterThan(0);
    expect(groups.reduce((n, g) => n + g.items.length, 0)).toBe(TUTORIALS.length);
  });
});
