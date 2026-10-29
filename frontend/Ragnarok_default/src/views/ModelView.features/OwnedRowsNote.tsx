import React from 'react';
import type { GridRow } from 'lib/types';

/**
 * One short line above a sheet that holds composite-owned rows (or above the composites sheet itself). The composite is opened from the
 * row: a click on its `plant` cell (on RAGNAROK_Composites, its `name` cell) opens the edit popup; this line only says so and links to the tab.
 */
export function OwnedRowsNote({ sheet, rows, onOpenComposite }: { sheet: string; rows: GridRow[]; onOpenComposite?: () => void }) {
  const isInstanceSheet = sheet === 'RAGNAROK_Composites';
  const owned = isInstanceSheet ? rows.length : rows.filter((r) => String(r.plant ?? '').trim()).length;
  if (owned === 0) return null;
  return (
    <p className="model-owned-note" data-testid="owned-rows-note">
      {isInstanceSheet
        ? `${owned} composite(s): click a row's name to edit it in a popup, or edit a cell and apply the sheet edits.`
        : `${owned} row(s) here belong to composites; click a row's composite name (plant column) to edit it.`}
      {onOpenComposite && <> <button type="button" className="cmp-link" onClick={onOpenComposite}>Open Composites</button></>}
    </p>
  );
}
