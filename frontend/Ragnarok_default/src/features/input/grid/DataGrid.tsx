import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import DataEditor, {
  CompactSelection,
  EditableGridCell,
  GridCell,
  GridCellKind,
  GridColumn,
  GridSelection,
  Item,
  ProvideEditorCallback,
  TextCell,
  Theme,
} from '@glideapps/glide-data-grid';
import '@glideapps/glide-data-grid/dist/index.css';
import { GridRow, Primitive } from '../../../shared/types';
import { stringValue } from '../../../shared/utils/helpers';
import { resolvePaste } from './range';
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
  highlightRow?: number | null;
  onDeleteColumn?: (col: string) => void;
  onRenameColumn?: (oldCol: string, newCol: string) => void;
  protectedCols?: string[];
  formatDisplayValue?: (col: string, val: Primitive) => string;
  coerceEditedValue?: (col: string, raw: string, current: Primitive) => Primitive;
  getCellSuggestions?: (col: string) => string[] | null;
  onFocusRow?: (rowIndex: number) => void;
  /** Fires with the column under the active cell, or a selected column header. */
  onFocusColumn?: (col: string | null) => void;
  /** Atomic paste: apply edits and grow the table by `extraRows` in one shot. */
  onPasteEdits?: (edits: { rowIndex: number; col: string; val: Primitive }[], extraRows: number) => void;
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
  highlightRow,
  onDeleteColumn,
  onRenameColumn,
  protectedCols,
  formatDisplayValue,
  coerceEditedValue,
  getCellSuggestions,
  onFocusRow,
  onFocusColumn,
  onPasteEdits,
}: DataGridProps) {
  const gridRef = useRef<any>(null);
  useEffect(() => { ensurePortal(); }, []);

  const display = useCallback(
    (col: string, v: Primitive): string => (formatDisplayValue ? formatDisplayValue(col, v) : stringValue(v)),
    [formatDisplayValue],
  );

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
  const columns: GridColumn[] = useMemo(
    () => cols.map((col) => {
      const title = col + (isActive(col) ? ' ▾' : '');
      let max = measureText(title);
      const limit = Math.min(rows.length, COL_SAMPLE_LIMIT);
      for (let i = 0; i < limit; i += 1) {
        const w = measureText(display(col, rows[i][col]));
        if (w > max) max = w;
      }
      const width = Math.round(Math.max(COL_MIN_WIDTH, Math.min(COL_MAX_WIDTH, max + COL_PADDING)));
      return { title, id: col, hasMenu: true, width };
    }),
    [cols, isActive, rows, display],
  );
  const freezeColumns = frozenCol && cols[0] === frozenCol ? 1 : 0;

  // ── Cell content ──────────────────────────────────────────────────────────
  const getCellContent = useCallback(([c, r]: Item): GridCell => {
    const col = cols[c];
    const row = gridRows[r];
    const text = row ? display(col, row[col]) : '';
    const themeOverride: Partial<Theme> | undefined =
      isColorColumn(col) && text ? { bgCell: text } : undefined;
    return {
      kind: GridCellKind.Text,
      data: text,
      displayData: text,
      allowOverlay: !readOnly,
      readonly: readOnly,
      themeOverride,
    };
  }, [cols, gridRows, display, readOnly]);

  const onCellEdited = useCallback(([c, r]: Item, newVal: EditableGridCell) => {
    if (readOnly || !onUpdate) return;
    if (newVal.kind !== GridCellKind.Text) return;
    const col = cols[c];
    const orig = displayToOrig[r];
    if (orig == null) return;
    const raw = newVal.data ?? '';
    const current = rows[orig]?.[col];
    const val = coerceEditedValue ? coerceEditedValue(col, raw, current) : inferInputValue(raw, current);
    onUpdate(orig, col, val);
  }, [readOnly, onUpdate, cols, displayToOrig, rows, coerceEditedValue]);

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
    const resolved = edits.map((e) => ({ rowIndex: e.rowIndex, col: e.col, val: coerce(e.rowIndex, e.col, e.raw) }));
    if (onPasteEdits) {
      onPasteEdits(resolved, extraRows);
    } else if (onUpdate) {
      resolved.filter((e) => e.rowIndex < rows.length).forEach((e) => onUpdate(e.rowIndex, e.col, e.val));
    }
    return false; // we applied it ourselves
  }, [readOnly, cols, displayToOrig, rows, coerceEditedValue, onPasteEdits, onUpdate]);

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

  // ── Header menu (filter + rename + delete) ────────────────────────────────
  const onHeaderMenuClick = useCallback((c: number, bounds: { x: number; y: number; width: number; height: number }) => {
    const col = cols[c];
    if (menuCol === col) { setMenuCol(null); return; }
    setAnchorRect(new DOMRect(bounds.x, bounds.y, bounds.width, bounds.height));
    setMenuCol(col);
  }, [cols, menuCol]);

  // ── Scroll the highlighted (jump-to) row into view ────────────────────────
  useEffect(() => {
    if (highlightRow == null) return;
    const disp = origToDisplay.get(highlightRow);
    if (disp != null) gridRef.current?.scrollTo?.(0, disp);
  }, [highlightRow, origToDisplay]);

  if (rows.length === 0) return <div className="grid-empty">No data</div>;

  const hasAnyFilter = cols.some(isActive);
  const menuProtected = menuCol ? protectedCols?.includes(menuCol) : false;

  return (
    <div className="rdg-wrap">
      {hasAnyFilter && (
        <div className="filter-status-bar">
          <span>Showing <strong>{filtered.length}</strong> of {rows.length} rows</span>
          <button className="ghost-button sm" onClick={() => setColFilters({})}>Clear all filters</button>
        </div>
      )}
      <div className="rdg-grid-host">
        <DataEditor
          ref={gridRef}
          columns={columns}
          rows={gridRows.length}
          getCellContent={getCellContent}
          onCellEdited={readOnly ? undefined : onCellEdited}
          onPaste={readOnly ? undefined : onPaste}
          getCellsForSelection={true}
          fillHandle={!readOnly}
          rowMarkers="number"
          freezeColumns={freezeColumns}
          gridSelection={selection}
          onGridSelectionChange={onGridSelectionChange}
          getRowThemeOverride={getRowThemeOverride}
          provideEditor={provideEditor}
          onHeaderMenuClick={onHeaderMenuClick}
          width="100%"
          height="100%"
          smoothScrollX
          smoothScrollY
        />
      </div>
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
          onClose={() => setMenuCol(null)}
          onRename={onRenameColumn && !menuProtected ? (newName) => onRenameColumn(menuCol, newName) : undefined}
          onDelete={onDeleteColumn && !menuProtected ? () => onDeleteColumn(menuCol) : undefined}
        />
      )}
    </div>
  );
}
