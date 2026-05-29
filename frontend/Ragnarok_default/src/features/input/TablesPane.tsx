import React, { useEffect, useMemo, useRef, useState } from 'react';
import ReactDOM from 'react-dom';
import { GridRow, Primitive, SheetName, TableSel, TsSheetName, WorkbookModel } from '../../shared/types';
import { ModelIssue } from '../validation/useModelIssues';
import { getAddableAttributes, getProtectedColumns, TABLE_GROUPS } from '../../constants';
import { getAttributeSchema, PypsaAttribute, TableGroup } from '../../constants/pypsa_schema';
import { ResizablePanels } from '../../layout/ResizablePanels';
import { getColumns, getTsFirstCol, stringValue } from '../../shared/utils/helpers';
import { parseCsvToGridRows } from '../../shared/utils/workbook';
import { normalizeDateToIso } from '../../shared/utils/helpers';
import type { DateFormat } from '../settings/useSettings';
import { PYPSA_STANDARD_LINE_TYPES, PYPSA_STANDARD_TRANSFORMER_TYPES } from '../../constants/pypsa_standard_types';
import { InputAnalyser } from './InputAnalyser';
import { DataGrid } from './grid/DataGrid';

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

  const handleCsvFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || sel.kind !== 'ts') return;
    try {
      const imported = await parseCsvToGridRows(file);
      if (imported.length === 0) throw new Error('No rows found in the file.');
      onImportTsSheet(sel.sheet as TsSheetName, imported);
    } catch (err) {
      window.alert(`CSV import failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      e.target.value = '';
    }
  };

  const isTs = sel.kind === 'ts';
  const rows: GridRow[] = isTs
    ? ((model as any)[sel.sheet] as GridRow[]) ?? []
    : (model as any)[sel.sheet] ?? [];

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

  const parentGroup: TableGroup | undefined = isTs
    ? TABLE_GROUPS.find((g) => g.temporalSheets.some((ts) => ts.sheet === sel.sheet))
    : TABLE_GROUPS.find((g) => g.sheet === sel.sheet);
  const temporalMeta = isTs
    ? parentGroup?.temporalSheets.find((ts) => ts.sheet === sel.sheet)
    : null;

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
              accept=".csv,.tsv,.txt"
              hidden
              onChange={handleCsvFile}
            />
            <button className="ghost-button sm" onClick={() => csvInputRef.current?.click()}>
              Import CSV
            </button>
          </div>
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
            // Temporal sheets are seeded by CSV import, so an empty one shows a
            // hint instead of a grid. Static sheets always render the grid (even
            // with zero rows) so the trailing "new row" is reachable.
            <div className="grid-empty">
              {editableTs
                ? 'No temporal data — use "Import CSV" in the Temporal panel on the right, then edit values here.'
                : 'No temporal data — use "Import CSV" above to load a profile.'}
            </div>
          ) : (
            <DataGrid
              rows={rows}
              cols={cols}
              frozenCol={frozenCol}
              readOnly={isTs && !editableTs}
              onUpdate={
                isTs && !editableTs ? undefined : (ri, col, val) => onUpdate(sel.sheet as SheetName, ri, col, val)
              }
              onPasteEdits={
                (isTs && !editableTs) || !onBulkPaste ? undefined : (edits, extraRows) => onBulkPaste(sel.sheet as SheetName, edits, extraRows)
              }
              onAppendRow={isTs ? undefined : () => onAddRow(sel.sheet as SheetName)}
              onDeleteRow={isTs ? undefined : (ri) => onDeleteRow(sel.sheet as SheetName, ri)}
              onRequestAddColumn={isTs ? undefined : (rect) => { setAddColAnchor(rect); setAddColOpen(true); }}
              readOnlyCols={lockSnapshotCol && frozenCol ? [frozenCol] : undefined}
              rowIssues={isTs ? undefined : rowIssueMap}
              highlightRow={isTs ? null : jumpHighlight}
              onDeleteColumn={isTs ? undefined : (col) => onDeleteColumn(sel.sheet as SheetName, col)}
              onRenameColumn={isTs ? undefined : (old, next) => onRenameColumn(sel.sheet as SheetName, old, next)}
              onAnalyse={(col) => { setAnalyseFocusCol(col); setShowAnalyser(true); }}
              onClearTable={
                isTs
                  ? (editableTs ? () => onImportTsSheet(sel.sheet as TsSheetName, []) : undefined)
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
}

function AttributeDoc({ attr, colName }: AttributeDocProps) {
  return (
    <div className="tables-attr-doc">
      {!colName ? (
        <p className="tables-attr-doc-hint">Select a cell or a column to see its description.</p>
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
            {attr.unit && attr.unit !== 'n/a' && <span className="tables-attr-doc-unit">{attr.unit}</span>}
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
    </div>
  );
}
