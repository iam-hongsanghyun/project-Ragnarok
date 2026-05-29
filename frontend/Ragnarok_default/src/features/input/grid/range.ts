/**
 * Pure geometry + clipboard helpers for the spreadsheet grid.
 *
 * Kept free of any react-data-grid import so it can be unit-tested under Jest
 * (the grid library ships ESM-only and is awkward to transform in CRA's Jest).
 */

export interface CellRef {
  /** Display row index (position within the rows currently shown). */
  row: number;
  /** Column index within the visible column order. */
  col: number;
}

export interface RangeBox {
  r0: number;
  r1: number;
  c0: number;
  c1: number;
}

/** Normalise an anchor/focus pair into an inclusive bounding box. */
export function boxFromCells(anchor: CellRef, focus: CellRef): RangeBox {
  return {
    r0: Math.min(anchor.row, focus.row),
    r1: Math.max(anchor.row, focus.row),
    c0: Math.min(anchor.col, focus.col),
    c1: Math.max(anchor.col, focus.col),
  };
}

export function isInBox(box: RangeBox | null, row: number, col: number): boolean {
  if (!box) return false;
  return row >= box.r0 && row <= box.r1 && col >= box.c0 && col <= box.c1;
}

/** A single cell edit to apply against the underlying model. */
export interface CellEdit {
  /** Original row index in the unfiltered model rows. */
  rowIndex: number;
  col: string;
  raw: string;
}

/**
 * Resolve a pasted TSV matrix into a flat list of edits, given the top-left
 * landing cell. `displayToOrig` maps a display row index to the model's
 * original row index; rows past the current table length get a synthetic
 * original index of (rowCount + overflowOffset) so the caller can grow the
 * table by `extraRows`.
 */
export function resolvePaste(
  matrix: string[][],
  startDisplayRow: number,
  startColIndex: number,
  cols: string[],
  displayToOrig: number[],
  rowCount: number,
): { edits: CellEdit[]; extraRows: number } {
  const edits: CellEdit[] = [];
  let extraRows = 0;
  for (let i = 0; i < matrix.length; i += 1) {
    const displayRow = startDisplayRow + i;
    let origIndex: number;
    if (displayRow < displayToOrig.length) {
      origIndex = displayToOrig[displayRow];
    } else {
      // Beyond the current rows — append. New rows land at the end of the model.
      origIndex = rowCount + extraRows;
      extraRows += 1;
    }
    const cells = matrix[i];
    for (let j = 0; j < cells.length; j += 1) {
      const colIdx = startColIndex + j;
      if (colIdx >= cols.length) break;
      edits.push({ rowIndex: origIndex, col: cols[colIdx], raw: cells[j] });
    }
  }
  return { edits, extraRows };
}
