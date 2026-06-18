import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactDOM from 'react-dom';
import { GridRow, Primitive, SheetName, TableSel, TsSheetName, WorkbookModel } from 'lib/types';
import { ModelIssue } from '../validation/useModelIssues';
import { getAddableAttributes, getProtectedColumns, TABLE_GROUPS } from 'lib/constants';
import { getAttributeSchema, PypsaAttribute, TableGroup } from 'lib/constants/pypsa_schema';
import { ResizablePanels } from '../../layout/ResizablePanels';
import { getColumns, getTsFirstCol, stringValue } from 'lib/utils/helpers';
import { parseCsvToGridRows } from 'lib/workbook/workbook';
import { normalizeDateToIso } from 'lib/utils/helpers';
import type { DateFormat } from '../settings/useSettings';
import { PYPSA_STANDARD_LINE_TYPES, PYPSA_STANDARD_TRANSFORMER_TYPES } from 'lib/constants/pypsa_standard_types';
import { InputAnalyser } from './InputAnalyser';
import { DataGrid } from './grid/DataGrid';
import { getSheetPage, patchSheet } from 'lib/api/session';
import { useDialog } from '../../shared/components/Dialog';

// ── Helpers ───────────────────────────────────────────────────────────────────

/** User-defined `*_types` rows first (so custom types shadow standards),
 *  then the PyPSA built-in catalogue. Used to seed the `<datalist>` for
 *  `lines.type` and `transformers.type` cells. */
function mergeTypeNames(modelRows: GridRow[] | undefined, standardRows: GridRow[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const row of [...(modelRows ?? []), ...standardRows]) {
    const name = stringValue(row.name);
    if (!name || seen.has(name)) continue;
    seen.add(name);
    out.push(name);
  }
  return out;
}

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

// ── Column statistics ──────────────────────────────────────────────────────────

/** Numeric summary of one column's filled cells. `count` is how many rows held a
 *  finite number (blanks/text are skipped); the rest follow. Lets the user read
 *  e.g. total installed capacity (sum of `p_nom`) before solving. */
interface ColumnStats {
  count: number;
  sum: number;
  mean: number;
  min: number;
  max: number;
}

function computeColumnStats(rows: GridRow[], col: string): ColumnStats | null {
  let count = 0;
  let sum = 0;
  let min = Infinity;
  let max = -Infinity;
  for (const r of rows) {
    const v = r[col];
    if (v === null || v === undefined || v === '' || typeof v === 'boolean') continue;
    const n = typeof v === 'number' ? v : Number(v);
    if (!Number.isFinite(n)) continue;
    count += 1;
    sum += n;
    if (n < min) min = n;
    if (n > max) max = n;
  }
  if (count === 0) return null;
  return { count, sum, mean: sum / count, min, max };
}

/** Compact, locale-aware number for the stat chips: integers stay whole, the
 *  fraction count scales with magnitude so small ratios stay legible. */
function fmtStat(v: number): string {
  if (!Number.isFinite(v)) return '—';
  if (Number.isInteger(v)) return v.toLocaleString();
  const abs = Math.abs(v);
  const digits = abs >= 100 ? 1 : abs >= 1 ? 2 : 4;
  return v.toLocaleString(undefined, { maximumFractionDigits: digits });
}

/** Singular, human noun for an "+ Add <component>" button. Falls back to the
 *  group label when a sheet isn't listed. */
const COMPONENT_NOUN: Record<string, string> = {
  buses: 'bus',
  generators: 'generator',
  loads: 'load',
  storage_units: 'storage unit',
  stores: 'store',
  lines: 'line',
  links: 'link',
  transformers: 'transformer',
  carriers: 'carrier',
  processes: 'process',
  shunt_impedances: 'shunt impedance',
  global_constraints: 'constraint',
};

// Hidden-column sets persist per sheet so a curated view survives sheet
// switches and reloads. Mirrors the grid's column-width persistence.
const HIDDEN_COLS_PREFIX = 'pypsa.hiddenCols.';

function loadHiddenCols(sheet: string): Set<string> {
  try {
    const raw = window.localStorage.getItem(HIDDEN_COLS_PREFIX + sheet);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return new Set(Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : []);
  } catch {
    return new Set();
  }
}

function saveHiddenCols(sheet: string, hidden: Set<string>): void {
  try {
    if (hidden.size === 0) window.localStorage.removeItem(HIDDEN_COLS_PREFIX + sheet);
    else window.localStorage.setItem(HIDDEN_COLS_PREFIX + sheet, JSON.stringify(Array.from(hidden)));
  } catch {
    /* storage unavailable */
  }
}

// ── ColumnsDropdown ────────────────────────────────────────────────────────────

interface ColumnsDropdownProps {
  cols: string[];
  frozenCol: string | null;
  hidden: Set<string>;
  anchorRect: DOMRect;
  onToggle: (col: string) => void;
  onEssentials: () => void;
  onShowAll: () => void;
  onClose: () => void;
}

function ColumnsDropdown({ cols, frozenCol, hidden, anchorRect, onToggle, onEssentials, onShowAll, onClose }: ColumnsDropdownProps) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handler = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) onClose(); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  const top = Math.min(anchorRect.bottom + 4, window.innerHeight - 420);
  const left = Math.min(anchorRect.left, window.innerWidth - 280);

  return ReactDOM.createPortal(
    <div ref={ref} className="add-col-dropdown" style={{ top, left }} onKeyDown={(e) => e.key === 'Escape' && onClose()}>
      <div className="add-col-header">Show columns</div>
      <div className="section-toolbar" style={{ padding: '6px 10px', gap: 6 }}>
        <button className="ghost-button sm" onClick={onEssentials}>Essentials only</button>
        <button className="ghost-button sm" onClick={onShowAll}>Show all</button>
      </div>
      <div className="add-col-list">
        {cols.map((col) => {
          const locked = col === frozenCol;
          return (
            <label key={col} className="add-col-item" style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: locked ? 'default' : 'pointer' }}>
              <input
                type="checkbox"
                checked={!hidden.has(col)}
                disabled={locked}
                onChange={() => onToggle(col)}
              />
              <span className="add-col-name">{col}{locked ? ' (pinned)' : ''}</span>
            </label>
          );
        })}
      </div>
    </div>,
    document.body,
  );
}

// ── AddColumnDropdown ─────────────────────────────────────────────────────────

interface AddColumnDropdownProps {
  sheet: string;
  existingCols: string[];
  anchorRect: DOMRect;
  onAdd: (attr: PypsaAttribute) => void;
  onClose: () => void;
}

function AddColumnDropdown({ sheet, existingCols, anchorRect, onAdd, onClose }: AddColumnDropdownProps) {
  const [search, setSearch] = useState('');
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  const allAttrs: PypsaAttribute[] = getAddableAttributes(sheet);
  const available = allAttrs.filter(
    (a) =>
      !existingCols.includes(a.attribute) &&
      (!search || a.attribute.toLowerCase().includes(search.toLowerCase()) || a.description.toLowerCase().includes(search.toLowerCase())),
  );

  const top = Math.min(anchorRect.bottom + 4, window.innerHeight - 420);
  const left = Math.min(anchorRect.left, window.innerWidth - 300);

  return ReactDOM.createPortal(
    <div
      ref={ref}
      className="add-col-dropdown"
      style={{ top, left }}
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
    >
      <div className="add-col-header">Add column to <strong>{sheet}</strong></div>
      <div className="cfd-search-wrap">
        <input
          className="cfd-search"
          autoFocus
          placeholder="Search attributes…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <div className="add-col-list">
        {available.length === 0 && (
          <div className="cfd-empty">
            {allAttrs.length === 0
              ? 'No optional attributes defined for this sheet.'
              : 'All known attributes are already present.'}
          </div>
        )}
        {available.map((attr) => (
          <button
            key={attr.attribute}
            className="add-col-item"
            onClick={() => { onAdd(attr); onClose(); }}
          >
            <div className="add-col-item-top">
              <span className="add-col-name">{attr.attribute}</span>
              {attr.unit && attr.unit !== 'n/a' && <span className="add-col-unit">{attr.unit}</span>}
              <span className={`add-col-type add-col-type--${attr.type}`}>{attr.type}</span>
            </div>
            <div className="add-col-desc">{attr.description}</div>
          </button>
        ))}
      </div>
    </div>,
    document.body,
  );
}

// ── TablesPane ────────────────────────────────────────────────────────────────

interface TablesPaneProps {
  model: WorkbookModel;
  sel: TableSel;
  onSelChange: (sel: TableSel) => void;
  onUpdate: (sheet: SheetName, rowIndex: number, col: string, val: Primitive) => void;
  onAddRow: (sheet: SheetName) => void;
  onDeleteRow: (sheet: SheetName, rowIndex: number) => void;
  onAddColumn: (sheet: SheetName, col: string, defaultValue: string | number | boolean) => void;
  onDeleteColumn: (sheet: SheetName, col: string) => void;
  onRenameColumn: (sheet: SheetName, oldCol: string, newCol: string) => void;
  onClearTable: (sheet: SheetName) => void;
  onImportTsSheet: (sheet: TsSheetName, rows: GridRow[]) => void;
  issues?: ModelIssue[];
  jumpTo?: { sheet: string; rowIndex: number } | null;
  currencySymbol?: string;
  dateFormat?: DateFormat;
  /** Forwarded to the grid — fires when the user clicks a row. */
  onFocusRow?: (rowIndex: number) => void;
  /** Show the resizable attribute-description panel below the grid. */
  showAttrDoc?: boolean;
  /** Hide the sheet title header (eyebrow + name + stats). Build supplies its
   *  own step context, so the redundant title block is dropped there. */
  compact?: boolean;
  /** Allow inline editing of temporal (_t) sheets. The Model tab keeps these
   *  read-only; Build opts in so users can populate profiles while building.
   *  The snapshot/time index column stays locked regardless. */
  editableTs?: boolean;
  /** Atomic paste: apply many cell edits and grow the sheet by `extraRows`. */
  onBulkPaste?: (
    sheet: SheetName,
    edits: { rowIndex: number; col: string; val: Primitive }[],
    extraRows: number,
  ) => void;
}

export function TablesPane({
  model,
  sel,
  onSelChange,
  onUpdate,
  onAddRow,
  onDeleteRow,
  onAddColumn,
  onDeleteColumn,
  onRenameColumn,
  onClearTable,
  onImportTsSheet,
  issues = [],
  jumpTo,
  currencySymbol = '$',
  dateFormat = 'auto',
  onFocusRow,
  onBulkPaste,
  showAttrDoc = false,
  compact = false,
  editableTs = false,
}: TablesPaneProps) {
  const [jumpHighlight, setJumpHighlight] = useState<number | null>(null);
  const [focusedCol, setFocusedCol] = useState<string | null>(null);
  const { alert: alertDialog } = useDialog();

  // The selected attribute is only meaningful within the current sheet.
  useEffect(() => { setFocusedCol(null); }, [sel.sheet]);

  // When jumpTo changes: switch to the target sheet and flash the row
  useEffect(() => {
    if (!jumpTo) return;
    onSelChange({ kind: 'static', sheet: jumpTo.sheet as SheetName });
    setJumpHighlight(jumpTo.rowIndex);
    const t = setTimeout(() => setJumpHighlight(null), 2500);
    return () => clearTimeout(t);
  }, [jumpTo, onSelChange]);
  const [addColOpen, setAddColOpen] = useState(false);
  const [addColAnchor, setAddColAnchor] = useState<DOMRect | null>(null);
  const [showAnalyser, setShowAnalyser] = useState(false);
  // Column the analyser opens focused on (from "Analyse column"); null = whole
  // table (from "Analyse table"). Both are triggered from the grid right-click.
  const [analyseFocusCol, setAnalyseFocusCol] = useState<string | null>(null);
  const csvInputRef = useRef<HTMLInputElement | null>(null);

  // Per-sheet hidden columns (column picker). Reload when the sheet changes so
  // each sheet shows its own curated set.
  const [hiddenCols, setHiddenCols] = useState<Set<string>>(() => loadHiddenCols(String(sel.sheet)));
  const [colsMenuOpen, setColsMenuOpen] = useState(false);
  const [colsMenuAnchor, setColsMenuAnchor] = useState<DOMRect | null>(null);
  useEffect(() => { setHiddenCols(loadHiddenCols(String(sel.sheet))); setColsMenuOpen(false); }, [sel.sheet]);
  const persistHidden = useCallback((next: Set<string>) => {
    setHiddenCols(next);
    saveHiddenCols(String(sel.sheet), next);
  }, [sel.sheet]);

  // Row issue map for the currently visible sheet
  const rowIssueMap = useMemo(() => {
    const map = new Map<number, 'error' | 'warning'>();
    issues
      .filter((i) => i.sheet === sel.sheet)
      .forEach((issue) => {
        const existing = map.get(issue.rowIndex);
        if (!existing || issue.severity === 'error') {
          map.set(issue.rowIndex, issue.severity);
        }
      });
    return map;
  }, [issues, sel.sheet]);

  // Per-cell issue map: pinpoints the offending field within a tinted row, with
  // its message for the hover tooltip. Only issues that name a column qualify;
  // errors win over warnings on the same cell.
  const cellIssueMap = useMemo(() => {
    const map = new Map<string, { severity: 'error' | 'warning'; message: string }>();
    issues
      .filter((i) => i.sheet === sel.sheet && i.col)
      .forEach((issue) => {
        const key = `${issue.rowIndex}|${issue.col}`;
        const existing = map.get(key);
        if (!existing || issue.severity === 'error') {
          map.set(key, { severity: issue.severity, message: issue.message });
        }
      });
    return map;
  }, [issues, sel.sheet]);

  const handleCsvFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || sel.kind !== 'ts') return;
    try {
      const imported = await parseCsvToGridRows(file);
      if (imported.length === 0) throw new Error('No rows found in the file.');
      // ts sheets live in the backend session — replace the sheet there (clear
      // current rows, then add the imported ones) and mirror locally.
      const current = tsRows?.length ?? 0;
      const ops = [
        ...(current ? [{ op: 'deleteRows' as const, rows: Array.from({ length: current }, (_, i) => i) }] : []),
        ...imported.map((r) => ({ op: 'addRow' as const, values: r as Record<string, unknown> })),
      ];
      setTsRows(imported);
      await patchSheet(String(sel.sheet), ops);
    } catch (err) {
      void alertDialog(`${err instanceof Error ? err.message : String(err)}`, { title: 'CSV import failed' });
    } finally {
      e.target.value = '';
    }
  };

  const isTs = sel.kind === 'ts';
  // Time-series (ts) sheets are NOT kept in the React model (they're the heavy
  // part). Fetch the selected ts sheet's rows from the backend session on
  // demand; edits below go straight to the backend via PATCH. Static sheets
  // still come from the in-memory model.
  const [tsRows, setTsRows] = useState<GridRow[] | null>(null);
  const [tsLoading, setTsLoading] = useState(false);
  useEffect(() => {
    if (!isTs) { setTsRows(null); return undefined; }
    let cancelled = false;
    setTsLoading(true);
    // Fetch the whole sheet (one ts sheet at a time is bounded; the persistent
    // win is that ALL ts sheets no longer live in the browser model).
    void getSheetPage(String(sel.sheet), { offset: 0, limit: 1_000_000 })
      .then((page) => { if (!cancelled) setTsRows(page.rows); })
      .catch(() => { if (!cancelled) setTsRows([]); })
      .finally(() => { if (!cancelled) setTsLoading(false); });
    return () => { cancelled = true; };
  }, [isTs, sel.sheet]);

  const rows: GridRow[] = isTs
    ? (tsRows ?? [])
    : (model as any)[sel.sheet] ?? [];

  // Edit a ts cell: update the fetched rows locally (responsive) and persist to
  // the backend session via PATCH. Static-sheet edits keep using the prop
  // handlers (which update the React model).
  const patchTsCell = (rowIndex: number, col: string, val: Primitive) => {
    setTsRows((prev) => (prev ? prev.map((r, i) => (i === rowIndex ? { ...r, [col]: val } : r)) : prev));
    void patchSheet(String(sel.sheet), [{ op: 'set', row: rowIndex, column: col, value: val }]).catch(() => { /* best-effort */ });
  };
  const patchTsPaste = (edits: { rowIndex: number; col: string; val: Primitive }[], extraRows: number) => {
    setTsRows((prev) => {
      if (!prev) return prev;
      const next = prev.map((r) => ({ ...r }));
      for (let k = 0; k < extraRows; k += 1) next.push({});
      for (const e of edits) { if (next[e.rowIndex]) next[e.rowIndex][e.col] = e.val; }
      return next;
    });
    const ops = [
      ...Array.from({ length: extraRows }, () => ({ op: 'addRow' as const, values: {} })),
      ...edits.map((e) => ({ op: 'set' as const, row: e.rowIndex, column: e.col, value: e.val })),
    ];
    void patchSheet(String(sel.sheet), ops).catch(() => { /* best-effort */ });
  };
  const patchTsClear = () => {
    const count = tsRows?.length ?? 0;
    if (count === 0) return;
    setTsRows([]);
    void patchSheet(
      String(sel.sheet),
      [{ op: 'deleteRows', rows: Array.from({ length: count }, (_, i) => i) }],
    ).catch(() => { /* best-effort */ });
  };

  // Build ordered column list with pinned first column
  const rawCols: string[] =
    rows.length > 0
      ? isTs
        ? (() => {
            // Union all keys to avoid first-row integer-like key reordering issues.
            // JS engines float numeric-string keys (e.g. '1', '2', '216' — common
            // for bus IDs in loads-p_set) ahead of non-numeric keys when iterating
            // an object. We rebuild the column order explicitly so PyPSA-style
            // `period?` and `snapshot` lead the table regardless of how the
            // upstream rows were constructed.
            const seen = new Set<string>();
            rows.forEach((row) => Object.keys(row).forEach((key) => seen.add(key)));
            const out: string[] = [];
            if (seen.has('period')) out.push('period');
            if (seen.has('snapshot')) out.push('snapshot');
            seen.forEach((key) => {
              if (key !== 'period' && key !== 'snapshot') out.push(key);
            });
            return out;
          })()
        : getColumns(rows, sel.sheet as SheetName)
      : isTs
        ? []
        : getColumns([], sel.sheet as SheetName);

  // For temporal sheets, ensure snapshot/timestamp is first
  let cols = rawCols;
  if (isTs && rawCols.length > 0) {
    const tsFirst = getTsFirstCol(rows);
    const idx = rawCols.indexOf(tsFirst);
    if (idx > 0) {
      cols = [tsFirst, ...rawCols.filter((c) => c !== tsFirst)];
    }
  }

  // The first data column is always frozen (sticky)
  const frozenCol = cols[0] ?? null;

  // Column picker (static sheets only): hide columns the user has tucked away,
  // but never the frozen first column. Temporal sheets show all columns.
  const visibleCols = isTs ? cols : cols.filter((c) => c === frozenCol || !hiddenCols.has(c));

  // Decorate static-sheet headers with the attribute's unit + a required mark,
  // so users don't need the attribute-doc panel to read them.
  const getColumnHeaderLabel = useCallback((col: string): string => {
    if (isTs) return col;
    const attr = getAttributeSchema(sel.sheet, col);
    if (!attr) return col;
    const unit = attr.unit && attr.unit !== 'n/a' ? ` (${attr.unit})` : '';
    return `${col}${unit}${attr.required ? ' *' : ''}`;
  }, [isTs, sel.sheet]);

  // "Essentials only" = required columns + the frozen col + any column that
  // actually holds data; hide the rest. Reuses the schema's protected set.
  const showEssentialsOnly = () => {
    const keep = new Set<string>([frozenCol ?? '', ...getProtectedColumns(sel.sheet)]);
    cols.forEach((c) => {
      if (rows.some((r) => { const v = r[c]; return v !== undefined && v !== null && v !== ''; })) keep.add(c);
    });
    persistHidden(new Set(cols.filter((c) => !keep.has(c))));
  };
  const toggleColumn = (col: string) => {
    const next = new Set(hiddenCols);
    next.has(col) ? next.delete(col) : next.add(col);
    next.delete(frozenCol ?? ''); // never hide the pinned column
    persistHidden(next);
  };

  // Add a component row and scroll/flash it into view (focus-after-add).
  const handleAddComponent = () => {
    const newIndex = rows.length;
    onAddRow(sel.sheet as SheetName);
    setJumpHighlight(newIndex);
    setTimeout(() => setJumpHighlight((cur) => (cur === newIndex ? null : cur)), 2500);
  };

  const parentGroup: TableGroup | undefined = isTs
    ? TABLE_GROUPS.find((g) => g.temporalSheets.some((ts) => ts.sheet === sel.sheet))
    : TABLE_GROUPS.find((g) => g.sheet === sel.sheet);
  const temporalMeta = isTs
    ? parentGroup?.temporalSheets.find((ts) => ts.sheet === sel.sheet)
    : null;
  const componentNoun = COMPONENT_NOUN[String(sel.sheet)] ?? (parentGroup?.label ?? String(sel.sheet));

  // Temporal data is loaded by CSV import (right-hand Temporal panel in Build);
  // value cells are editable inline, but the snapshot/time index column stays
  // locked so the imported time axis can't be corrupted.
  const lockSnapshotCol = isTs && editableTs;

  const protectedCols = isTs
    ? (lockSnapshotCol && frozenCol ? [frozenCol] : [])
    : getProtectedColumns(sel.sheet);
  const temporalLabelCols = new Set(['snapshot', 'datetime', 'name', 'index', 'timestep']);
  const normalizeTemporalDisplay = (raw: string): string => {
    const iso = normalizeDateToIso(raw, dateFormat);
    return /^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00` : iso;
  };
  const formatDisplayValue = (col: string, val: Primitive): string => {
    const s = stringValue(val);
    return isTs && temporalLabelCols.has(col.toLowerCase()) ? normalizeTemporalDisplay(s) : s;
  };
  const coerceEditedValue = (col: string, raw: string, current: Primitive): Primitive => {
    if (isTs && temporalLabelCols.has(col.toLowerCase())) return normalizeTemporalDisplay(raw);
    return inferInputValue(raw, current);
  };

  const header = (
    <>
        {!compact && (
        <div className="tables-content-header">
          <div>
            <p className="eyebrow">{isTs ? 'Temporal (_t)' : 'Static'}</p>
            <h2>
              {parentGroup?.label ?? sel.sheet}{isTs && temporalMeta ? ` · ${temporalMeta.attribute}` : ''}
            </h2>
          </div>
          <div className="inline-stats">
            <span>{rows.length} rows</span>
            {cols.length > 0 && <span>{cols.length} cols</span>}
            {isTs && <span className="ts-chip">time-series</span>}
          </div>
        </div>
        )}

        {/* All table actions (add/delete row & column, rename, analyse, clear,
            filter) live in the grid right-click menu. The Model tab keeps an
            inline CSV import for temporal sheets since it has no side panel;
            Build (editableTs) imports from the right-hand Temporal panel. */}
        {isTs && !editableTs && (
          <div className="section-toolbar">
            <input
              ref={csvInputRef}
              type="file"
              accept=".csv,.tsv,.txt,text/csv,text/tab-separated-values,text/plain"
              hidden
              onChange={handleCsvFile}
            />
            <button className="ghost-button sm" onClick={() => csvInputRef.current?.click()}>
              Import CSV
            </button>
          </div>
        )}
        {/* Static-sheet quick actions: add a component without learning the
            grid, and curate which columns are shown (40+ on some sheets). */}
        {!isTs && (
          <div className="section-toolbar">
            <button className="ghost-button sm" onClick={handleAddComponent}>
              + Add {componentNoun}
            </button>
            <button
              className="ghost-button sm"
              onClick={(e) => {
                const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
                setColsMenuAnchor(new DOMRect(r.left, r.top, r.width, r.height));
                setColsMenuOpen((v) => !v);
              }}
            >
              Columns{hiddenCols.size > 0 ? ` (${cols.length - hiddenCols.size}/${cols.length})` : ''}
            </button>
          </div>
        )}
        {colsMenuOpen && colsMenuAnchor && !isTs && (
          <ColumnsDropdown
            cols={cols}
            frozenCol={frozenCol}
            hidden={hiddenCols}
            anchorRect={colsMenuAnchor}
            onToggle={toggleColumn}
            onEssentials={() => { showEssentialsOnly(); setColsMenuOpen(false); }}
            onShowAll={() => { persistHidden(new Set()); setColsMenuOpen(false); }}
            onClose={() => setColsMenuOpen(false)}
          />
        )}
        {addColOpen && addColAnchor && !isTs && (
          <AddColumnDropdown
            sheet={sel.sheet as SheetName}
            existingCols={cols}
            anchorRect={addColAnchor}
            onAdd={(attr) => onAddColumn(sel.sheet as SheetName, attr.attribute, inferInputValue(String(attr.default ?? ''), '') ?? '')}
            onClose={() => setAddColOpen(false)}
          />
        )}

        {showAnalyser && rows.length > 0 && (
          <div className="ia-wrap">
            <div className="ia-wrap-head">
              <span className="eyebrow">Analyser{analyseFocusCol ? ` · ${analyseFocusCol}` : ''}</span>
              <button className="ghost-button sm" onClick={() => setShowAnalyser(false)}>Close</button>
            </div>
            <InputAnalyser
              rows={rows}
              cols={cols}
              isTs={isTs}
              frozenCol={frozenCol}
              currencySymbol={currencySymbol}
              focusCol={analyseFocusCol}
            />
          </div>
        )}
    </>
  );

  const grid = (
        <div className="tables-grid-wrap">
          {isTs && rows.length === 0 ? (
            // Temporal sheets are fetched from the backend session on demand;
            // show a loading note while that's in flight, otherwise the empty
            // hint. Static sheets always render the grid (even with zero rows).
            <div className="grid-empty">
              {tsLoading
                ? 'Loading time-series from the backend…'
                : editableTs
                  ? 'No temporal data — use "Import CSV" in the Temporal panel on the right, then edit values here.'
                  : 'No temporal data — use "Import CSV" above to load a profile.'}
            </div>
          ) : (
            <DataGrid
              rows={rows}
              cols={visibleCols}
              frozenCol={frozenCol}
              storageKey={`${sel.kind}:${String(sel.sheet)}`}
              getColumnHeaderLabel={getColumnHeaderLabel}
              readOnly={isTs && !editableTs}
              onUpdate={
                isTs
                  ? (editableTs ? patchTsCell : undefined)
                  : (ri, col, val) => onUpdate(sel.sheet as SheetName, ri, col, val)
              }
              onPasteEdits={
                isTs
                  ? (editableTs ? patchTsPaste : undefined)
                  : (!onBulkPaste ? undefined : (edits, extraRows) => onBulkPaste(sel.sheet as SheetName, edits, extraRows))
              }
              onAppendRow={isTs ? undefined : () => onAddRow(sel.sheet as SheetName)}
              onDeleteRow={isTs ? undefined : (ri) => onDeleteRow(sel.sheet as SheetName, ri)}
              onRequestAddColumn={isTs ? undefined : (rect) => { setAddColAnchor(rect); setAddColOpen(true); }}
              readOnlyCols={lockSnapshotCol && frozenCol ? [frozenCol] : undefined}
              rowIssues={isTs ? undefined : rowIssueMap}
              cellIssues={isTs ? undefined : cellIssueMap}
              highlightRow={isTs ? null : jumpHighlight}
              onDeleteColumn={isTs ? undefined : (col) => onDeleteColumn(sel.sheet as SheetName, col)}
              onRenameColumn={isTs ? undefined : (old, next) => onRenameColumn(sel.sheet as SheetName, old, next)}
              onAnalyse={(col) => { setAnalyseFocusCol(col); setShowAnalyser(true); }}
              onClearTable={
                isTs
                  ? (editableTs ? patchTsClear : undefined)
                  : () => onClearTable(sel.sheet as SheetName)
              }
              protectedCols={protectedCols}
              formatDisplayValue={formatDisplayValue}
              coerceEditedValue={coerceEditedValue}
              getCellSuggestions={(col) => {
                if (col === 'type') {
                  if (sel.sheet === 'lines') {
                    return mergeTypeNames(model.line_types, PYPSA_STANDARD_LINE_TYPES);
                  }
                  if (sel.sheet === 'transformers') {
                    return mergeTypeNames(model.transformer_types, PYPSA_STANDARD_TRANSFORMER_TYPES);
                  }
                }
                // bus references → list of bus names defined in the workbook.
                if (col === 'bus' || col === 'bus0' || col === 'bus1' || col === 'bus2') {
                  return (model.buses ?? []).map((r) => stringValue(r.name)).filter(Boolean);
                }
                // carrier references → defined carriers.
                if (col === 'carrier') {
                  return (model.carriers ?? []).map((r) => stringValue(r.name)).filter(Boolean);
                }
                return null;
              }}
              onFocusRow={onFocusRow}
              onFocusColumn={setFocusedCol}
            />
          )}
        </div>
  );

  const docPanel = (
    <AttributeDoc
      attr={focusedCol ? getAttributeSchema(sel.sheet, focusedCol) : null}
      colName={focusedCol}
      stats={focusedCol ? computeColumnStats(rows, focusedCol) : null}
    />
  );

  return (
    <div className="tables-content">
      {header}
      {showAttrDoc && !isTs ? (
        <ResizablePanels
          id="model-attr-doc"
          direction="vertical"
          className="tables-doc-split"
          initialSizes={[76, 24]}
          minSize={90}
        >
          {grid}
          {docPanel}
        </ResizablePanels>
      ) : (
        grid
      )}
    </div>
  );
}

interface AttributeDocProps {
  attr: PypsaAttribute | null;
  colName: string | null;
  /** Numeric summary of the focused column (null when not numeric / no column). */
  stats: ColumnStats | null;
}

function AttributeDoc({ attr, colName, stats }: AttributeDocProps) {
  const unit = attr?.unit && attr.unit !== 'n/a' ? attr.unit : '';
  return (
    <div className="tables-attr-doc">
      {!colName ? (
        <p className="tables-attr-doc-hint">Select a cell or a column to see its description and statistics.</p>
      ) : !attr ? (
        <>
          <div className="tables-attr-doc-head">
            <span className="tables-attr-doc-name">{colName}</span>
            <span className="tables-attr-doc-custom">custom column</span>
          </div>
          <p className="tables-attr-doc-hint">No PyPSA schema description for this column.</p>
        </>
      ) : (
        <>
          <div className="tables-attr-doc-head">
            <span className="tables-attr-doc-name">{attr.attribute}</span>
            {unit && <span className="tables-attr-doc-unit">{unit}</span>}
            <span className={`tables-attr-doc-type tables-attr-doc-type--${attr.type}`}>{attr.type}</span>
            {attr.required && <span className="tables-attr-doc-required">required</span>}
            {attr.status === 'output' && <span className="tables-attr-doc-output">output</span>}
            {attr.default && attr.default !== 'n/a' && (
              <span className="tables-attr-doc-default">default <code>{attr.default}</code></span>
            )}
          </div>
          <p className="tables-attr-doc-desc">{attr.description || 'No description available.'}</p>
        </>
      )}

      {colName && (
        stats ? <ColumnStatsBlock stats={stats} unit={unit} /> : (
          <p className="tables-attr-doc-hint">No numeric values in this column to summarise.</p>
        )
      )}
    </div>
  );
}

/** Five-up stat grid (count / sum / average / min / max) for the focused column.
 *  Sum/min/max carry the column unit so totals like installed capacity read in
 *  context; count and average stay unit-free. */
function ColumnStatsBlock({ stats, unit }: { stats: ColumnStats; unit: string }) {
  const items: { label: string; value: string }[] = [
    { label: 'Count', value: fmtStat(stats.count) },
    { label: 'Sum', value: `${fmtStat(stats.sum)}${unit ? ` ${unit}` : ''}` },
    { label: 'Average', value: `${fmtStat(stats.mean)}${unit ? ` ${unit}` : ''}` },
    { label: 'Min', value: `${fmtStat(stats.min)}${unit ? ` ${unit}` : ''}` },
    { label: 'Max', value: `${fmtStat(stats.max)}${unit ? ` ${unit}` : ''}` },
  ];
  return (
    <div className="tables-attr-doc-stats">
      {items.map((s) => (
        <div key={s.label} className="tables-attr-doc-stat">
          <span className="tables-attr-doc-stat-label">{s.label}</span>
          <span className="tables-attr-doc-stat-value">{s.value}</span>
        </div>
      ))}
    </div>
  );
}
