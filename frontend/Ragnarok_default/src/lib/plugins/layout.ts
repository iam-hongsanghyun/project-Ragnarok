/**
 * Contract v2 (X6) composite layout: an analyze output may carry a reserved
 * `layout: { rows: [[key, …], …] }` key arranging the OTHER output keys into
 * rows (keys in one row render side-by-side). The backend validates the shape;
 * this splitter is tolerant so a frontend plugin's malformed `layout` degrades
 * to the default single-column flow instead of throwing.
 */
export interface SplitOutput {
  /** Arranged rows, restricted to keys that exist in the data (empty rows dropped). */
  rows: string[][];
  /** Everything not arranged by a row and not the reserved `layout` key. */
  rest: Record<string, unknown>;
}

export function splitOutputLayout(data: Record<string, unknown>): SplitOutput {
  const layout = data.layout as { rows?: unknown } | undefined;
  const rawRows = layout && typeof layout === 'object' && Array.isArray(layout.rows) ? layout.rows : [];
  const placed = new Set<string>();
  const rows: string[][] = [];
  for (const raw of rawRows) {
    if (!Array.isArray(raw)) continue;
    const row = raw.filter(
      (k): k is string => typeof k === 'string' && k !== 'layout' && k in data && !placed.has(k),
    );
    row.forEach((k) => placed.add(k));
    if (row.length > 0) rows.push(row);
  }
  const rest: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(data)) {
    if (k !== 'layout' && !placed.has(k)) rest[k] = v;
  }
  return { rows, rest };
}
