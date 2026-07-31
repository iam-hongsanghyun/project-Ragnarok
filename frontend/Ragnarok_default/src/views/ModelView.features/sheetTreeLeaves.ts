/**
 * Which temporal leaves the sheet tree renders for one component group.
 *
 * Extracted as a pure function because it encodes a rule that was wrong in a way
 * no type could catch: leaves were filtered to `count > 0`, which made an empty
 * temporal sheet unreachable. The CSV importer for a profile lives on that
 * sheet's own pane, so you needed rows to reach the UI that adds rows — and with
 * no temporal sheet in the session there was no way in from the Model tab at all.
 *
 * The rule matches upstream Ragnarok (`e6a7241`): list the profiles a component
 * supports but has no rows for, once the component itself exists. No static row
 * means nothing to profile, so those stay hidden.
 */

/** A group's temporal sheet as `TABLE_GROUPS` declares it. */
export interface TemporalLeaf {
  sheet: string;
  attribute: string;
  label: string;
}

export interface TemporalLeaves<T extends TemporalLeaf> {
  /** Leaves carrying rows. The group badge counts these — the empty ones are
   *  affordances, not content, and must not inflate it. */
  populated: T[];
  /** What to render, in order. */
  shown: T[];
}

/**
 * Split a group's temporal sheets into what to show and what holds data.
 *
 * @param leaves - the group's schema-declared temporal sheets.
 * @param count - rows currently in a sheet (session count, else in-memory).
 * @param hasStatic - whether the component has any rows of its own.
 */
export function temporalLeaves<T extends TemporalLeaf>(
  leaves: readonly T[],
  count: (sheet: string) => number,
  hasStatic: boolean,
): TemporalLeaves<T> {
  const shown: T[] = [];
  const populated: T[] = [];
  for (const leaf of leaves) {
    const rows = count(leaf.sheet);
    if (rows > 0) {
      populated.push(leaf);
      shown.push(leaf);
    } else if (hasStatic) {
      // Empty, but the component exists — so it can be opened and imported into.
      shown.push(leaf);
    }
  }
  return { populated, shown };
}
