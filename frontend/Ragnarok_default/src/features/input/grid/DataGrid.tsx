import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import DataEditor, {
  CellClickedEventArgs,
  CompactSelection,
  EditableGridCell,
  GridCell,
  GridCellKind,
  GridColumn,
  GridMouseEventArgs,
  GridSelection,
  HeaderClickedEventArgs,
  Item,
  ProvideEditorCallback,
  TextCell,
  Theme,
} from '@glideapps/glide-data-grid';
import '@glideapps/glide-data-grid/dist/index.css';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { GridRow, Primitive } from 'lib/types';
import { stringValue } from 'lib/utils/helpers';
import { resolvePaste } from 'lib/input/range';
import { useDialog } from '../../../shared/components/Dialog';
import { FilterDropdown } from './FilterDropdown';

type Row = GridRow & { __i: number };

function inferInputValue(raw: string, current: Primitive): Primitive {
  if (raw === '') return '';
  if (typeof current === 'number') {
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : current;
  }
  if (typeof current === 'boolean') return raw.toLowerCase() === 'true';
  if (raw.toLowerCase() === 'true') return true;
  if (raw.toLowerCase() === 'false') return false;
  const parsed = Number(raw);
  if (Number.isFinite(parsed) && /^-?\d+(\.\d+)?$/.test(raw.trim())) return parsed;
  return raw;
}

function isColorColumn(col: string): boolean {
  return col.toLowerCase() === 'color' || col.toLowerCase().endsWith('_color');
}

const COL_MIN_WIDTH = 64;
const COL_MAX_WIDTH = 340;
const COL_PADDING = 26; // cell horizontal padding + sort/menu glyph room
const COL_SAMPLE_LIMIT = 250;

let measureCtx: CanvasRenderingContext2D | null = null;
/** Pixel width of `text` in the grid's cell font, via a shared offscreen canvas. */
function measureText(text: string): number {
  if (typeof document === 'undefined') return text.length * 7;
  if (!measureCtx) {
    measureCtx = document.createElement('canvas').getContext('2d');
    if (measureCtx) measureCtx.font = '13px var(--font-sans, system-ui)';
  }
  return measureCtx ? measureCtx.measureText(text).width : text.length * 7;
}

export interface DataGridProps {
  rows: GridRow[];
  cols: string[];
  frozenCol?: string | null;
  readOnly?: boolean;
  onUpdate?: (rowIndex: number, col: string, val: Primitive) => void;
  rowIssues?: Map<number, 'error' | 'warning'>;
  /** Per-cell validation issues, keyed `"${originalRowIndex}|${col}"`. Drives a
   *  per-cell tint + a hover tooltip pinpointing the offending field, on top of
   *  the whole-row tint from `rowIssues`. */
  cellIssues?: Map<string, { severity: 'error' | 'warning'; message: string }>;
  highlightRow?: number | null;
  onDeleteColumn?: (col: string) => void;
  onRenameColumn?: (oldCol: string, newCol: string) => void;
  protectedCols?: string[];
  /** Columns that stay read-only even when the grid is editable (e.g. the
   *  snapshot/time index of a temporal sheet). Their cells can't be edited or
   *  overwritten by paste. */
  readOnlyCols?: string[];
  formatDisplayValue?: (col: string, val: Primitive) => string;
  coerceEditedValue?: (col: string, raw: string, current: Primitive) => Primitive;
  getCellSuggestions?: (col: string) => string[] | null;
  /** Decorate a column header label (e.g. append unit, mark required). Falls
   *  back to the raw column name when omitted. */
  getColumnHeaderLabel?: (col: string) => string;
  onFocusRow?: (rowIndex: number) => void;
  /** Fires with the column under the active cell, or a selected column header. */
  onFocusColumn?: (col: string | null) => void;
  /** Atomic paste: apply edits and grow the table by `extraRows` in one shot. */
  onPasteEdits?: (edits: { rowIndex: number; col: string; val: Primitive }[], extraRows: number) => void;
  /** Append a blank row. Wired to the "Add row" item in the cell right-click
   *  context menu. When set, the grid stays mounted even with zero rows so the
   *  menu is reachable. */
  onAppendRow?: () => void;
  /** Delete the row at the given original (unfiltered) index. Wired to the
   *  "Delete row" item in the cell right-click context menu. */
  onDeleteRow?: (rowIndex: number) => void;
  /** Open the add-column UI; receives a screen rect to anchor it. Wired to the
   *  "Add column" item in the header right-click context menu. */
  onRequestAddColumn?: (rect: DOMRect) => void;
  /** Remove every row from the sheet. Wired to "Clear table" in both menus. */
  onClearTable?: () => void;
  /** Open the analyser, optionally focused on a single column. `col` is the
   *  column to focus, or `null` to analyse the whole table. Wired to "Analyse
   *  column" / "Analyse table" in both menus. */
  onAnalyse?: (col: string | null) => void;
  /** Stable key (typically the sheet name) under which the user's column-
   *  width overrides are persisted in localStorage. Omit to use a single
   *  shared bucket — but in practice every call site has a sheet context. */
  storageKey?: string;
}

const COL_WIDTH_STORAGE_PREFIX = 'pypsa.gridColumnWidths.';

function loadColumnWidths(key: string | undefined): Record<string, number> {
  if (!key) return {};
  try {
    const raw = window.localStorage.getItem(COL_WIDTH_STORAGE_PREFIX + key);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return {};
    const out: Record<string, number> = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof v === 'number' && Number.isFinite(v) && v > 0) out[k] = v;
    }
    return out;
  } catch {
    return {};
  }
}

function saveColumnWidths(key: string | undefined, widths: Record<string, number>): void {
  if (!key) return;
  try {
    window.localStorage.setItem(COL_WIDTH_STORAGE_PREFIX + key, JSON.stringify(widths));
  } catch {
    /* storage unavailable */
  }
}

/** Glide overlay editors mount into a fixed `#portal` element. Create it once. */
function ensurePortal(): void {
  if (typeof document === 'undefined') return;
  if (document.getElementById('portal')) return;
  const el = document.createElement('div');
  el.id = 'portal';
  el.style.position = 'fixed';
  el.style.left = '0';
  el.style.top = '0';
  el.style.zIndex = '9999';
  document.body.appendChild(el);
}

export function DataGrid({
  rows,
  cols,
  frozenCol,
  readOnly = false,
  onUpdate,
  rowIssues,
  cellIssues,
  highlightRow,
  onDeleteColumn,
  onRenameColumn,
  protectedCols,
  readOnlyCols,
  formatDisplayValue,
  coerceEditedValue,
  getCellSuggestions,
  getColumnHeaderLabel,
  onFocusRow,
  onFocusColumn,
  onPasteEdits,
  onAppendRow,
  onDeleteRow,
  onRequestAddColumn,
  onClearTable,
  onAnalyse,
  storageKey,
}: DataGridProps) {
  const gridRef = useRef<any>(null);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const { confirm } = useDialog();
  useEffect(() => { ensurePortal(); }, []);

  // User-overridden column widths persist per storageKey (sheet name).
  // Re-load whenever the key changes so switching sheets shows that
  // sheet's saved widths, not the previous sheet's.
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>(
    () => loadColumnWidths(storageKey),
  );
  useEffect(() => {
    setColumnWidths(loadColumnWidths(storageKey));
  }, [storageKey]);
  const onColumnResize = useCallback(
    (col: GridColumn, newSize: number) => {
      if (!col.id || col.id === '__add_col__') return;
      setColumnWidths((prev) => {
        const next = { ...prev, [col.id as string]: Math.round(newSize) };
        saveColumnWidths(storageKey, next);
        return next;
      });
    },
    [storageKey],
  );

  // Right-click a body cell → context menu (screen-positioned). Column actions
  // (filter / rename / delete) live in the header ▾ menu, not here.
  const [ctxMenu, setCtxMenu] = useState<
    | { origIndex: number | null; col: string; x: number; y: number }
    | null
  >(null);

  const display = useCallback(
    (col: string, v: Primitive): string => (formatDisplayValue ? formatDisplayValue(col, v) : stringValue(v)),
    [formatDisplayValue],
  );

  // Hover tooltip for a cell that has a validation issue (item 1). Screen-
  // positioned (glide bounds are client coords, same basis as the ctx menu).
  const [cellTip, setCellTip] = useState<
    { x: number; y: number; msg: string; sev: 'error' | 'warning' } | null
  >(null);

  // ── Column filters (Excel-style) ──────────────────────────────────────────
  const [colFilters, setColFilters] = useState<Record<string, Set<string>>>({});
  const [menuCol, setMenuCol] = useState<string | null>(null);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  useEffect(() => { setColFilters({}); setMenuCol(null); }, [cols.join('|')]); // eslint-disable-line react-hooks/exhaustive-deps

  const uniqueValues = useCallback((col: string): string[] => {
    const s = new Set(rows.map((r) => display(col, r[col])));
    return Array.from(s).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  }, [rows, display]);
  const selectedFor = (col: string): Set<string> => colFilters[col] ?? new Set(uniqueValues(col));
  const isActive = useCallback((col: string): boolean => {
    const f = colFilters[col];
    return !!f && f.size < uniqueValues(col).length;
  }, [colFilters, uniqueValues]);

  // ── Tag + filter rows (preserve original index) ───────────────────────────
  const filtered = useMemo(
    () => rows.map((r, i) => ({ r, i })).filter(({ r }) => cols.every((col) => {
      const f = colFilters[col];
      return !f || f.has(display(col, r[col]));
    })),
    [rows, cols, colFilters, display],
  );
  const gridRows: Row[] = useMemo(() => filtered.map(({ r, i }) => ({ ...r, __i: i })), [filtered]);
  const displayToOrig = useMemo(() => filtered.map(({ i }) => i), [filtered]);
  const origToDisplay = useMemo(() => {
    const m = new Map<number, number>();
    displayToOrig.forEach((orig, disp) => m.set(orig, disp));
    return m;
  }, [displayToOrig]);

  // ── Selection ─────────────────────────────────────────────────────────────
  const [selection, setSelection] = useState<GridSelection>({
    columns: CompactSelection.empty(),
    rows: CompactSelection.empty(),
  });
  const activeColRef = useRef<number | null>(null);

  const onGridSelectionChange = useCallback((sel: GridSelection) => {
    setSelection(sel);
    if (sel.current) {
      const [c, r] = sel.current.cell;
      activeColRef.current = c;
      const orig = displayToOrig[r];
      if (orig != null) onFocusRow?.(orig);
      onFocusColumn?.(cols[c] ?? null);
    } else if (sel.columns.length > 0) {
      const c = sel.columns.last();
      onFocusColumn?.(c != null ? cols[c] ?? null : null);
    }
  }, [displayToOrig, onFocusRow, onFocusColumn, cols]);

  // ── Columns ───────────────────────────────────────────────────────────────
  // User-overridden widths win over the auto-measured default so a dragged
  // column stays where the user put it across re-renders / tab switches.
  const columns: GridColumn[] = useMemo(
    () => cols.map((col) => {
      const label = getColumnHeaderLabel ? getColumnHeaderLabel(col) : col;
      const title = label + (isActive(col) ? ' ▾' : '');
      let width: number;
      if (columnWidths[col]) {
        width = columnWidths[col];
      } else {
        let max = measureText(title);
        const limit = Math.min(rows.length, COL_SAMPLE_LIMIT);
        for (let i = 0; i < limit; i += 1) {
          const w = measureText(display(col, rows[i][col]));
          if (w > max) max = w;
        }
        width = Math.round(Math.max(COL_MIN_WIDTH, Math.min(COL_MAX_WIDTH, max + COL_PADDING)));
      }
      // The header ▾ menu opens the Excel-style filter (+ rename / delete).
      return { title, id: col, hasMenu: true, width };
    }),
    [cols, isActive, rows, display, columnWidths, getColumnHeaderLabel],
  );
  const freezeColumns = frozenCol && cols[0] === frozenCol ? 1 : 0;

  // Trailing "+" column at the right edge: clicking its header opens the
  // add-column UI. Indexed at `cols.length`, it carries no data.
  const addColEnabled = !!onRequestAddColumn && !readOnly;
  const addColIndex = addColEnabled ? cols.length : -1;
  const displayColumns: GridColumn[] = useMemo(
    () => (addColEnabled
      ? [...columns, { title: '+', id: '__add_col__', hasMenu: false, width: 44 } as GridColumn]
      : columns),
    [columns, addColEnabled],
  );

  // ── Cell content ──────────────────────────────────────────────────────────
  const getCellContent = useCallback(([c, r]: Item): GridCell => {
    if (c >= cols.length) {
      // Trailing "+" column — blank, non-editable filler.
      return { kind: GridCellKind.Text, data: '', displayData: '', allowOverlay: false, readonly: true };
    }
    const col = cols[c];
    const row = gridRows[r];
    const text = row ? display(col, row[col]) : '';
    let themeOverride: Partial<Theme> | undefined =
      isColorColumn(col) && text ? { bgCell: text } : undefined;
    // Per-cell validation tint — a stronger shade than the whole-row tint so the
    // exact offending field stands out. Skip color cells (their bg is the value).
    if (!themeOverride) {
      const orig = displayToOrig[r];
      const issue = orig != null ? cellIssues?.get(`${orig}|${col}`) : undefined;
      if (issue) {
        themeOverride = issue.severity === 'error'
          ? { bgCell: '#fee2e2', textDark: '#b91c1c' }
          : { bgCell: '#fef3c7', textDark: '#b45309' };
      }
    }
    const cellReadOnly = readOnly || (readOnlyCols?.includes(col) ?? false);
    return {
      kind: GridCellKind.Text,
      data: text,
      displayData: text,
      allowOverlay: !cellReadOnly,
      readonly: cellReadOnly,
      themeOverride,
    };
  }, [cols, gridRows, display, readOnly, readOnlyCols, displayToOrig, cellIssues]);

  const onCellEdited = useCallback(([c, r]: Item, newVal: EditableGridCell) => {
    if (readOnly || !onUpdate) return;
    if (c >= cols.length) return; // trailing "+" column
    if (newVal.kind !== GridCellKind.Text) return;
    const col = cols[c];
    if (readOnlyCols?.includes(col)) return;
    const orig = displayToOrig[r];
    if (orig == null) return;
    const raw = newVal.data ?? '';
    const current = rows[orig]?.[col];
    const val = coerceEditedValue ? coerceEditedValue(col, raw, current) : inferInputValue(raw, current);
    onUpdate(orig, col, val);
  }, [readOnly, onUpdate, cols, displayToOrig, rows, coerceEditedValue, readOnlyCols]);

  // ── Paste (auto-grows the table) ──────────────────────────────────────────
  const onPaste = useCallback((target: Item, values: readonly (readonly string[])[]): boolean => {
    if (readOnly) return false;
    const [startCol, startRow] = target;
    const matrix = values.map((row) => [...row]);
    const { edits, extraRows } = resolvePaste(matrix, startRow, startCol, cols, displayToOrig, rows.length);
    const coerce = (rowIndex: number, col: string, raw: string): Primitive => {
      const current = rowIndex < rows.length ? rows[rowIndex][col] : '';
      return coerceEditedValue ? coerceEditedValue(col, raw, current) : inferInputValue(raw, current);
    };
    const resolved = edits
      .filter((e) => !readOnlyCols?.includes(e.col))
      .map((e) => ({ rowIndex: e.rowIndex, col: e.col, val: coerce(e.rowIndex, e.col, e.raw) }));
    if (onPasteEdits) {
      onPasteEdits(resolved, extraRows);
    } else if (onUpdate) {
      resolved.filter((e) => e.rowIndex < rows.length).forEach((e) => onUpdate(e.rowIndex, e.col, e.val));
    }
    return false; // we applied it ourselves
  }, [readOnly, cols, displayToOrig, rows, coerceEditedValue, onPasteEdits, onUpdate, readOnlyCols]);

  // ── Combobox editor for suggestion columns ────────────────────────────────
  const provideEditor: ProvideEditorCallback<GridCell> = useCallback((cell) => {
    if (readOnly || cell.kind !== GridCellKind.Text) return undefined;
    const c = activeColRef.current;
    if (c == null) return undefined;
    const suggestions = getCellSuggestions?.(cols[c]) ?? null;
    if (!suggestions || suggestions.length === 0) return undefined;
    const Editor: React.FC<{
      value: GridCell;
      onChange: (v: GridCell) => void;
      onFinishedEditing: (v?: GridCell, movement?: readonly [-1 | 0 | 1, -1 | 0 | 1]) => void;
    }> = ({ value, onChange, onFinishedEditing }) => {
      const tc = value as TextCell;
      const [v, setV] = useState(tc.data ?? '');
      const listId = useMemo(() => 'dl-' + Math.random().toString(36).slice(2), []);
      const commit = (mv?: readonly [-1 | 0 | 1, -1 | 0 | 1]) =>
        onFinishedEditing({ ...tc, data: v, displayData: v }, mv);
      // Soft guidance only — free text is allowed (a name may be created later,
      // and paste/CSV import must keep working); we just flag an unknown value.
      const known = useMemo(() => new Set(suggestions), []); // eslint-disable-line react-hooks/exhaustive-deps
      const unknown = v.trim() !== '' && !known.has(v);
      return (
        <div className="rdg-combobox">
          <input
            className="rdg-combobox-input"
            autoFocus
            list={listId}
            value={v}
            onChange={(e) => { setV(e.target.value); onChange({ ...tc, data: e.target.value, displayData: e.target.value }); }}
            onBlur={() => commit()}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); commit([0, 1]); }
              if (e.key === 'Escape') { e.preventDefault(); onFinishedEditing(undefined); }
            }}
          />
          <datalist id={listId}>
            {suggestions.map((s) => <option key={s} value={s} />)}
          </datalist>
          {unknown && (
            <div className="rdg-combobox-hint">Not in the list yet — pick an existing value, or keep it if you’ll add it.</div>
          )}
        </div>
      );
    };
    return { editor: Editor, disablePadding: true };
  }, [readOnly, getCellSuggestions, cols]);

  // ── Row-issue tint ────────────────────────────────────────────────────────
  const getRowThemeOverride = useCallback((row: number): Partial<Theme> | undefined => {
    const orig = displayToOrig[row];
    if (orig == null) return undefined;
    const sev = rowIssues?.get(orig);
    if (sev === 'error') return { bgCell: '#fef2f2', accentColor: '#dc2626' };
    if (sev === 'warning') return { bgCell: '#fffbeb', accentColor: '#d97706' };
    return undefined;
  }, [displayToOrig, rowIssues]);

  // ── Hover a cell with a validation issue → message tooltip ────────────────
  const onItemHovered = useCallback((args: GridMouseEventArgs) => {
    if (!cellIssues || cellIssues.size === 0) { if (cellTip) setCellTip(null); return; }
    if (args.kind !== 'cell') { setCellTip(null); return; }
    const [c, r] = args.location;
    if (c < 0 || r < 0 || c >= cols.length) { setCellTip(null); return; }
    const orig = displayToOrig[r];
    const issue = orig != null ? cellIssues.get(`${orig}|${cols[c]}`) : undefined;
    if (!issue) { setCellTip(null); return; }
    const b = args.bounds;
    setCellTip({ x: b.x + b.width / 2, y: b.y, msg: issue.message, sev: issue.severity });
  }, [cellIssues, cellTip, cols, displayToOrig]);

  // ── Right-click a body cell → cell context menu ───────────────────────────
  const onCellContextMenu = useCallback(([c, r]: Item, e: CellClickedEventArgs) => {
    if (c >= cols.length) return; // trailing "+" column
    e.preventDefault();
    const orig = displayToOrig[r] ?? null;
    setCtxMenu({ origIndex: orig, col: cols[c] ?? '', x: e.bounds.x + e.localEventX, y: e.bounds.y + e.localEventY });
  }, [displayToOrig, cols]);

  // ── Header ▾ menu → Excel-style filter (+ rename / delete) ─────────────────
  const onHeaderMenuClick = useCallback((c: number, screenPosition: { x: number; y: number; width: number; height: number }) => {
    setAnchorRect(new DOMRect(screenPosition.x, screenPosition.y, screenPosition.width, screenPosition.height));
    setMenuCol(cols[c] ?? null);
  }, [cols]);

  // ── Click the trailing "+" header → open the add-column UI ─────────────────
  const onHeaderClicked = useCallback((c: number, e: HeaderClickedEventArgs) => {
    if (c !== addColIndex || !onRequestAddColumn) return;
    const b = e.bounds;
    onRequestAddColumn(new DOMRect(b.x, b.y, b.width, b.height));
  }, [addColIndex, onRequestAddColumn]);

  // ── Scroll the highlighted (jump-to) row into view ────────────────────────
  useEffect(() => {
    if (highlightRow == null) return;
    const disp = origToDisplay.get(highlightRow);
    if (disp != null) gridRef.current?.scrollTo?.(0, disp);
  }, [highlightRow, origToDisplay]);

  // With an append handler the grid stays mounted at zero rows so the trailing
  // "new row" affordance is reachable; otherwise show a plain empty state.
  if (rows.length === 0 && !onAppendRow) return <div className="grid-empty">No data</div>;

  const hasAnyFilter = cols.some(isActive);

  // Which cell right-click actions are reachable (column actions + filter live
  // in the header ▾ menu, not the cell menu).
  const hasCellMenu = !!onAnalyse || (!readOnly && (!!onAppendRow || !!onRequestAddColumn || !!onDeleteRow || !!onClearTable));
  const menuProtected = menuCol ? protectedCols?.includes(menuCol) ?? false : false;

  return (
    <div className="rdg-wrap">
      {hasAnyFilter && (
        <div className="filter-status-bar">
          <span>Showing <strong>{filtered.length}</strong> of {rows.length} rows</span>
          <button className="ghost-button sm" onClick={() => setColFilters({})}>Clear all filters</button>
        </div>
      )}
      <div className="rdg-grid-host" ref={hostRef}>
        <DataEditor
          ref={gridRef}
          columns={displayColumns}
          rows={gridRows.length}
          getCellContent={getCellContent}
          onCellEdited={readOnly ? undefined : onCellEdited}
          onPaste={readOnly ? undefined : onPaste}
          onColumnResize={onColumnResize}
          getCellsForSelection={true}
          fillHandle={!readOnly}
          rowMarkers="number"
          freezeColumns={freezeColumns}
          gridSelection={selection}
          onGridSelectionChange={onGridSelectionChange}
          getRowThemeOverride={getRowThemeOverride}
          provideEditor={provideEditor}
          onHeaderMenuClick={onHeaderMenuClick}
          onHeaderClicked={addColEnabled ? onHeaderClicked : undefined}
          onCellContextMenu={hasCellMenu ? onCellContextMenu : undefined}
          onItemHovered={cellIssues && cellIssues.size > 0 ? onItemHovered : undefined}
          onRowAppended={onAppendRow ? () => { onAppendRow(); } : undefined}
          trailingRowOptions={onAppendRow ? { sticky: false, tint: true, hint: 'New row…' } : undefined}
          width="100%"
          height="100%"
          smoothScrollX
          smoothScrollY
        />
      </div>
      {/* Right-click cell menu — Radix DropdownMenu anchored at the cursor.
          Keyed by position so each right-click re-anchors the content; Radix
          handles outside-click / Escape / keyboard navigation / ARIA. */}
      <DropdownMenu.Root
        key={ctxMenu ? `${ctxMenu.x}:${ctxMenu.y}` : 'closed'}
        open={!!ctxMenu}
        onOpenChange={(o) => { if (!o) setCtxMenu(null); }}
      >
        <DropdownMenu.Trigger asChild>
          <span aria-hidden style={{ position: 'fixed', left: ctxMenu?.x ?? 0, top: ctxMenu?.y ?? 0, width: 0, height: 0 }} />
        </DropdownMenu.Trigger>
        {ctxMenu && (
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              className="grid-ctxmenu"
              align="start"
              sideOffset={2}
              collisionPadding={8}
              onCloseAutoFocus={(e) => e.preventDefault()}
            >
              {!readOnly && onAppendRow && (
                <DropdownMenu.Item className="grid-ctxmenu-item" onSelect={() => onAppendRow()}>
                  Add row
                </DropdownMenu.Item>
              )}
              {!readOnly && onRequestAddColumn && (
                <DropdownMenu.Item className="grid-ctxmenu-item"
                  onSelect={() => onRequestAddColumn(new DOMRect(ctxMenu.x, ctxMenu.y, 0, 0))}>
                  Add column
                </DropdownMenu.Item>
              )}
              {!readOnly && onDeleteRow && ctxMenu.origIndex != null && (
                <DropdownMenu.Item className="grid-ctxmenu-item danger"
                  onSelect={() => onDeleteRow(ctxMenu.origIndex as number)}>
                  Delete row
                </DropdownMenu.Item>
              )}
              {onAnalyse && (
                <>
                  <DropdownMenu.Separator className="grid-ctxmenu-sep" />
                  {ctxMenu.col && (
                    <DropdownMenu.Item className="grid-ctxmenu-item" onSelect={() => onAnalyse(ctxMenu.col)}>
                      Analyse column
                    </DropdownMenu.Item>
                  )}
                  <DropdownMenu.Item className="grid-ctxmenu-item" onSelect={() => onAnalyse(null)}>
                    Analyse table
                  </DropdownMenu.Item>
                </>
              )}
              {!readOnly && onClearTable && (
                <>
                  <DropdownMenu.Separator className="grid-ctxmenu-sep" />
                  <DropdownMenu.Item className="grid-ctxmenu-item danger"
                    onSelect={() => { void confirm('Remove every row from this table?', { title: 'Clear table', confirmText: 'Clear table', danger: true }).then((ok) => { if (ok) onClearTable(); }); }}>
                    Clear table
                  </DropdownMenu.Item>
                </>
              )}
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        )}
      </DropdownMenu.Root>
      {menuCol && anchorRect && (
        <FilterDropdown
          col={menuCol}
          allValues={uniqueValues(menuCol)}
          selected={selectedFor(menuCol)}
          anchorRect={anchorRect}
          onToggle={(val) => {
            const all = uniqueValues(menuCol);
            const cur = selectedFor(menuCol);
            const next = new Set(cur);
            next.has(val) ? next.delete(val) : next.add(val);
            setColFilters((p) => {
              const n = { ...p };
              if (next.size >= all.length) delete n[menuCol];
              else n[menuCol] = next;
              return n;
            });
          }}
          onSelectAll={() => setColFilters((p) => { const n = { ...p }; delete n[menuCol]; return n; })}
          onUncheckAll={() => setColFilters((p) => ({ ...p, [menuCol]: new Set<string>() }))}
          onRename={onRenameColumn && !menuProtected ? (newName) => onRenameColumn(menuCol, newName) : undefined}
          onDelete={onDeleteColumn && !menuProtected ? () => onDeleteColumn(menuCol) : undefined}
          onClose={() => setMenuCol(null)}
        />
      )}
      {cellTip && (
        <div
          className="grid-cell-tip"
          data-sev={cellTip.sev}
          style={{ position: 'fixed', left: cellTip.x, top: cellTip.y - 6 }}
          role="tooltip"
        >
          {cellTip.msg}
        </div>
      )}
    </div>
  );
}
