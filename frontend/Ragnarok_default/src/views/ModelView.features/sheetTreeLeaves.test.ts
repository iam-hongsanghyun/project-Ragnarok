import { describe, it, expect } from '@jest/globals';
import { temporalLeaves, TemporalLeaf } from './sheetTreeLeaves';

const leaf = (attribute: string): TemporalLeaf => ({
  sheet: `loads-${attribute}`,
  attribute,
  label: attribute,
});

const LEAVES = [leaf('p_set'), leaf('q_set')];
const counts = (map: Record<string, number>) => (sheet: string) => map[sheet] ?? 0;
const HAS_STATIC = true;
const NO_STATIC = false;

describe('temporalLeaves', () => {
  it('makes an EMPTY profile reachable once the component exists — the whole point', () => {
    // A model with loads but no temporal data at all. Selecting a leaf is the only
    // route to its pane, and that pane holds the CSV importer, so if nothing is
    // shown here a profile cannot be created from the Model tab at all.
    const { shown } = temporalLeaves(LEAVES, counts({}), HAS_STATIC);
    expect(shown.map((l) => l.sheet)).toEqual(['loads-p_set', 'loads-q_set']);
  });

  it('hides empty profiles when the component itself has no rows', () => {
    // No load ⇒ nothing to profile, so the placeholders would be noise.
    const { shown } = temporalLeaves(LEAVES, counts({}), NO_STATIC);
    expect(shown).toEqual([]);
  });

  it('still shows a populated profile when the component has no static rows', () => {
    // An imported results file can carry a series whose component sheet is absent;
    // that data must stay reachable.
    const { shown, populated } = temporalLeaves(LEAVES, counts({ 'loads-p_set': 24 }), NO_STATIC);
    expect(shown.map((l) => l.attribute)).toEqual(['p_set']);
    expect(populated.map((l) => l.attribute)).toEqual(['p_set']);
  });

  it('counts only profiles that hold data, so placeholders cannot inflate the badge', () => {
    const { shown, populated } = temporalLeaves(
      [leaf('p_set'), leaf('q_set'), leaf('p_max_pu')],
      counts({ 'loads-q_set': 8760 }),
      HAS_STATIC,
    );
    expect(shown).toHaveLength(3);
    expect(populated.map((l) => l.attribute)).toEqual(['q_set']);
  });

  it('keeps the schema declaration order so leaves do not jump as rows arrive', () => {
    const order = [leaf('p_set'), leaf('q_set'), leaf('p_max_pu')];
    const before = temporalLeaves(order, counts({}), HAS_STATIC).shown.map((l) => l.attribute);
    const after = temporalLeaves(order, counts({ 'loads-q_set': 10 }), HAS_STATIC).shown
      .map((l) => l.attribute);
    expect(before).toEqual(['p_set', 'q_set', 'p_max_pu']);
    expect(after).toEqual(before);
  });

  it('treats a zero-row sheet as empty, not as present', () => {
    // The session keeps a created-then-emptied sheet at rowCount 0; it must stay
    // reachable for a refill and out of the badge.
    const { shown, populated } = temporalLeaves(LEAVES, counts({ 'loads-p_set': 0 }), HAS_STATIC);
    expect(shown).toHaveLength(2);
    expect(populated).toEqual([]);
  });
});
