import React, { useEffect, useMemo, useRef, useState } from 'react';
import ReactDOM from 'react-dom';
import { GridRow, Primitive, SheetName, TableSel, TsSheetName, WorkbookModel } from '../../shared/types';
import { ModelIssue } from '../validation/useModelIssues';
import { getAddableAttributes, getProtectedColumns, TABLE_GROUPS } from '../../constants';
import { PypsaAttribute, TableGroup } from '../../constants/pypsa_schema';
import { getColumns, getTsFirstCol, stringValue } from '../../shared/utils/helpers';
import { parseCsvToGridRows } from '../../shared/utils/workbook';
import { normalizeDateToIso } from '../../shared/utils/helpers';
import type { DateFormat } from '../settings/useSettings';
import { InputAnalyser } from './InputAnalyser';

// ── Helpers ───────────────────────────────────────────────────────────────────

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

// ── Column filter dropdown (rendered as a portal so overflow never clips it) ──

interface FilterDropdownProps {
  col: string;
  allValues: string[];
  selected: Set<string>;
  anchorRect: DOMRect;
  onToggle: (val: string) => void;
  onSelectAll: () => void;      // re-include every value (reset / no filter)
  onUncheckAll: () => void;     // empty allowed set (Excel-style hide-all)
  onClose: () => void;
}

function FilterDropdown({
  col, allValues, selected, anchorRect,
  onToggle, onSelectAll, onUncheckAll, onClose,
}: FilterDropdownProps) {
  const [search, setSearch] = useState('');
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  const visible = search
    ? allValues.filter((v) => v.toLowerCase().includes(search.toLowerCase()))
    : allValues;

  const allChecked = allValues.every((v) => selected.has(v));

  const top = Math.min(anchorRect.bottom + 2, window.innerHeight - 320);
  const left = Math.min(anchorRect.left, window.innerWidth - 220);

  return ReactDOM.createPortal(
    <div
      ref={ref}
      className="col-filter-dropdown"
      style={{ top, left }}
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
    >
      {/* Search */}
      <div className="cfd-search-wrap">
        <input
          className="cfd-search"
          autoFocus
          placeholder="Search values…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* Select all row */}
      <label className="cfd-option cfd-select-all">
        <input
          type="checkbox"
          checked={allChecked}
          onChange={allChecked ? onUncheckAll : onSelectAll}
        />
        <span>(Select All)</span>
      </label>

      <div className="cfd-divider" />

      {/* Value list */}
      <div className="cfd-list">
        {visible.length === 0 && <div className="cfd-empty">No matches</div>}
        {visible.map((val) => (
          <label key={val} className="cfd-option">
            <input
              type="checkbox"
              checked={selected.has(val)}
              onChange={() => onToggle(val)}
            />
            <span className="cfd-val">{val === '' ? <em style={{ color: '#94a3b8' }}>(blank)</em> : val}</span>
          </label>
        ))}
      </div>

      {/* Footer */}
      <div className="cfd-footer">
        <button className="cfd-btn" onClick={() => { onSelectAll(); onClose(); }}>Reset</button>
        <button className="cfd-btn cfd-btn--primary" onClick={onClose}>OK</button>
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

// ── SpreadsheetGrid ───────────────────────────────────────────────────────────

interface SpreadsheetGridProps {
  rows: GridRow[];
  cols: string[];
  frozenCol?: string | null;
  readOnly?: boolean;
  onUpdate?: (rowIndex: number, col: string, val: Primitive) => void;
  rowIssues?: Map<number, 'error' | 'warning'>;
  highlightRow?: number | null;
  onDeleteColumn?: (col: string) => void;
  onRenameColumn?: (oldCol: string, newCol: string) => void;
  /** Columns that cannot be deleted or renamed (e.g. 'name') */
  protectedCols?: string[];
  formatDisplayValue?: (col: string, val: Primitive) => string;
  coerceEditedValue?: (col: string, raw: string, current: Primitive) => Primitive;
}

function SpreadsheetGrid({
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
}: SpreadsheetGridProps) {
  const [editCell, setEditCell] = useState<{ row: number; col: string; val: string } | null>(null);
  const [renamingCol, setRenamingCol] = useState<string | null>(null);
  const [renameVal, setRenameVal] = useState('');
  const tbodyRef = useRef<HTMLTableSectionElement>(null);

  // Scroll highlighted row into view when jumpTo fires
  useEffect(() => {
    if (highlightRow == null || !tbodyRef.current) return;
    // Find the <tr> corresponding to the original row index
    const rows = tbodyRef.current.querySelectorAll('tr');
    for (const tr of Array.from(rows)) {
      if ((tr as HTMLElement).dataset.origIdx === String(highlightRow)) {
        (tr as HTMLElement).scrollIntoView({ block: 'center', behavior: 'smooth' });
        break;
      }
    }
  }, [highlightRow]);
  // col → Set of values TO SHOW. Missing key = show all.
  const [colFilters, setColFilters] = useState<Record<string, Set<string>>>({});
  const [openCol, setOpenCol] = useState<string | null>(null);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  // Refs to <th> elements so we can read getBoundingClientRect() on click
  const thRefs = useRef<Record<string, HTMLTableCellElement | null>>({});

  // Reset filters whenever the sheet changes (cols change)
  useEffect(() => {
    setColFilters({});
    setOpenCol(null);
  }, [cols.join('|')]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Progressive rendering: rendering all 8784 rows × 217 cols ≈ 1.9 M DOM
  // nodes will crash the tab. We start with PAGE_SIZE rows and grow by
  // PAGE_SIZE each time a sentinel <tr> below the last row scrolls into view.
  // This keeps the table editable without a virtualisation library.
  const PAGE_SIZE = 500;
  const [visibleCount, setVisibleCount] = useState<number>(PAGE_SIZE);
  const sentinelRef = useRef<HTMLTableRowElement | null>(null);
  // Reset the window whenever the sheet, column set, or filter changes.
  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [cols.join('|'), JSON.stringify(colFilters)]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Unique values per column (computed from ALL rows, not filtered)
  const uniqueValues = (col: string): string[] => {
    const s = new Set(rows.map((r) => stringValue(r[col])));
    return Array.from(s).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  };

  // Resolved "selected" set — if no filter entry, all values are selected
  const selectedFor = (col: string): Set<string> =>
    colFilters[col] ?? new Set(uniqueValues(col));

  // Is the column actively filtered (a proper subset of all values)?
  const isActive = (col: string): boolean => {
    const f = colFilters[col];
    if (!f) return false;
    const all = uniqueValues(col);
    return f.size < all.length;
  };

  const hasAnyFilter = cols.some(isActive);

  // Apply filters
  const filteredRows = rows.filter((row) =>
    cols.every((col) => {
      const f = colFilters[col];
      return !f || f.has(stringValue(row[col]));
    }),
  );
  const visibleRows = filteredRows.slice(0, visibleCount);
  const hasMore = visibleRows.length < filteredRows.length;

  // Observe the sentinel <tr> and bump visibleCount when it scrolls into view.
  useEffect(() => {
    if (!hasMore) return;
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setVisibleCount((n) => n + PAGE_SIZE);
          }
        }
      },
      { rootMargin: '400px' },   // start loading before user reaches the bottom
    );
    io.observe(el);
    return () => io.disconnect();
  }, [hasMore, visibleCount]);

  const openDropdown = (col: string) => {
    if (openCol === col) { setOpenCol(null); return; }
    const thEl = thRefs.current[col];
    if (thEl) setAnchorRect(thEl.getBoundingClientRect());
    setOpenCol(col);
  };

  const toggleValue = (col: string, val: string) => {
    const all = uniqueValues(col);
    const cur = selectedFor(col);
    const next = new Set(cur);
    next.has(val) ? next.delete(val) : next.add(val);
    if (next.size >= all.length) {
      setColFilters((p) => { const n = { ...p }; delete n[col]; return n; });
    } else {
      setColFilters((p) => ({ ...p, [col]: next }));
    }
  };

  // Select-All re-includes every unique value (drops the filter entirely).
  const selectAll = (col: string) =>
    setColFilters((p) => { const n = { ...p }; delete n[col]; return n; });

  // Clear (uncheck Select-All) leaves an empty allowed-set, so the column
  // hides every row until the user picks one or more values. This matches the
  // Excel-style filter behaviour the user expects.
  const clearFilter = (col: string) =>
    setColFilters((p) => ({ ...p, [col]: new Set<string>() }));

  const clearAll = () => setColFilters({});

  if (rows.length === 0) return <div className="grid-empty">No data</div>;

  return (
    <div className="spreadsheet-scroll">
      {hasAnyFilter && (
        <div className="filter-status-bar">
          <span>
            Showing <strong>{filteredRows.length}</strong> of {rows.length} rows
          </span>
          <button className="ghost-button sm" onClick={clearAll}>Clear all filters</button>
        </div>
      )}
      {filteredRows.length > PAGE_SIZE && (
        <div className="filter-status-bar">
          <span>
            Showing <strong>{visibleRows.length}</strong> of {filteredRows.length} rows{hasMore ? ' (scroll for more)' : ''}
          </span>
        </div>
      )}
      <table className="spreadsheet-table">
        <thead>
          <tr>
            <th className="rn-col">#</th>
            {cols.map((c) => {
              const active = isActive(c);
              const frozen = c === frozenCol;
              const cls = [
                frozen ? 'col-frozen' : '',
                active ? 'col-filtered' : '',
              ].filter(Boolean).join(' ') || undefined;
              return (
                <th
                  key={c}
                  title={c}
                  className={cls}
                  ref={(el) => { thRefs.current[c] = el; }}
                >
                  <div className="col-header-inner">
                    {renamingCol === c ? (
                      <input
                        className="col-rename-input"
                        autoFocus
                        value={renameVal}
                        onChange={(e) => setRenameVal(e.target.value)}
                        onBlur={() => {
                          const trimmed = renameVal.trim();
                          if (trimmed && trimmed !== c && onRenameColumn) onRenameColumn(c, trimmed);
                          setRenamingCol(null);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.currentTarget.blur();
                          }
                          if (e.key === 'Escape') {
                            setRenamingCol(null);
                          }
                        }}
                        onClick={(e) => e.stopPropagation()}
                      />
                    ) : (
                      <span
                        className="col-header-label"
                        title={`${c}  (double-click to rename)`}
                        onDoubleClick={(e) => {
                          if (!onRenameColumn || protectedCols?.includes(c)) return;
                          e.stopPropagation();
                          setRenamingCol(c);
                          setRenameVal(c);
                        }}
                      >
                        {c}
                      </span>
                    )}
                    <button
                      className={`col-filter-btn${active ? ' col-filter-btn--active' : ''}`}
                      title={active ? 'Filter active' : 'Filter'}
                      onClick={(e) => {
                        e.stopPropagation();
                        openDropdown(c);
                      }}
                    >
                      v
                    </button>
                    {onDeleteColumn && !protectedCols?.includes(c) && (
                      <button
                        className="col-delete-btn"
                        title={`Remove column "${c}"`}
                        onClick={(e) => {
                          e.stopPropagation();
                          if (window.confirm(`Remove column "${c}" from all rows? This cannot be undone.`)) {
                            onDeleteColumn(c);
                          }
                        }}
                      >
                        x
                      </button>
                    )}
                  </div>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody ref={tbodyRef}>
          {visibleRows.map((row) => {
            const origIdx = rows.indexOf(row);
            const issueSeverity = rowIssues?.get(origIdx);
            const isHighlighted = highlightRow === origIdx;
            const rowCls = [
              issueSeverity === 'error' ? 'row-issue--error' : '',
              issueSeverity === 'warning' ? 'row-issue--warning' : '',
              isHighlighted ? 'row-jump-highlight' : '',
            ].filter(Boolean).join(' ') || undefined;
            return (
              <tr key={origIdx} className={rowCls} data-orig-idx={origIdx}>
                <td className="rn-col">{origIdx + 1}</td>
                {cols.map((c) => {
                  const isEditing = !readOnly && editCell?.row === origIdx && editCell?.col === c;
                  const frozen = c === frozenCol;
                  const baseClass = isEditing ? 'cell-editing' : readOnly ? 'cell-readonly' : 'cell-editable';
                  return (
                    <td
                      key={c}
                      className={frozen ? `${baseClass} col-frozen` : baseClass}
                      onDoubleClick={() => {
                        if (!readOnly) {
                          const display = formatDisplayValue ? formatDisplayValue(c, row[c]) : stringValue(row[c]);
                          setEditCell({ row: origIdx, col: c, val: display });
                        }
                      }}
                    >
                      {isEditing ? (
                        isColorColumn(c) ? (
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <input
                              autoFocus
                              type="color"
                              className="cell-input"
                              style={{ width: 36, padding: 2 }}
                              value={(editCell!.val || '#94a3b8').match(/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/) ? editCell!.val : '#94a3b8'}
                              onChange={(e) =>
                                setEditCell((prev) => (prev ? { ...prev, val: e.target.value } : null))
                              }
                            />
                            <input
                              className="cell-input"
                              value={editCell!.val}
                              onChange={(e) =>
                                setEditCell((prev) => (prev ? { ...prev, val: e.target.value } : null))
                              }
                              onBlur={() => {
                                if (editCell && onUpdate)
                                  onUpdate(
                                    origIdx,
                                    editCell.col,
                                    coerceEditedValue
                                      ? coerceEditedValue(editCell.col, editCell.val, row[editCell.col])
                                      : inferInputValue(editCell.val, row[editCell.col]),
                                  );
                                setEditCell(null);
                              }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === 'Tab') {
                                  if (editCell && onUpdate)
                                    onUpdate(
                                      origIdx,
                                      editCell.col,
                                      coerceEditedValue
                                        ? coerceEditedValue(editCell.col, editCell.val, row[editCell.col])
                                        : inferInputValue(editCell.val, row[editCell.col]),
                                    );
                                  setEditCell(null);
                                }
                                if (e.key === 'Escape') setEditCell(null);
                              }}
                            />
                          </div>
                        ) : (
                        <input
                          autoFocus
                          className="cell-input"
                          value={editCell!.val}
                          onChange={(e) =>
                            setEditCell((prev) => (prev ? { ...prev, val: e.target.value } : null))
                          }
                          onBlur={() => {
                            if (editCell && onUpdate)
                              onUpdate(
                                origIdx,
                                editCell.col,
                                coerceEditedValue
                                  ? coerceEditedValue(editCell.col, editCell.val, row[editCell.col])
                                  : inferInputValue(editCell.val, row[editCell.col]),
                              );
                            setEditCell(null);
                          }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === 'Tab') {
                              if (editCell && onUpdate)
                                onUpdate(
                                  origIdx,
                                  editCell.col,
                                  coerceEditedValue
                                    ? coerceEditedValue(editCell.col, editCell.val, row[editCell.col])
                                    : inferInputValue(editCell.val, row[editCell.col]),
                                );
                              setEditCell(null);
                            }
                            if (e.key === 'Escape') setEditCell(null);
                          }}
                        />
                        )
                      ) : (
                        isColorColumn(c) && stringValue(row[c]) ? (
                          <span className="cell-value" style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                            <span style={{ width: 12, height: 12, borderRadius: 999, background: stringValue(row[c]), border: '1px solid rgba(15,23,42,0.18)', flexShrink: 0 }} />
                            <span>{formatDisplayValue ? formatDisplayValue(c, row[c]) : stringValue(row[c])}</span>
                          </span>
                        ) : (
                          <span className="cell-value">{formatDisplayValue ? formatDisplayValue(c, row[c]) : stringValue(row[c])}</span>
                        )
                      )}
                    </td>
                  );
                })}
              </tr>
            );
          })}
          {hasMore && (
            <tr ref={sentinelRef} aria-hidden="true">
              <td className="rn-col" colSpan={cols.length + 1} style={{ textAlign: 'center', padding: 12, color: 'var(--text-muted, #888)' }}>
                Loading more rows…
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {/* Portal dropdown */}
      {openCol && anchorRect && (
        <FilterDropdown
          col={openCol}
          allValues={uniqueValues(openCol)}
          selected={selectedFor(openCol)}
          anchorRect={anchorRect}
          onToggle={(val) => toggleValue(openCol, val)}
          onSelectAll={() => selectAll(openCol)}
          onUncheckAll={() => clearFilter(openCol)}
          onClose={() => setOpenCol(null)}
        />
      )}
    </div>
  );
}

// ── TablesPane ────────────────────────────────────────────────────────────────

interface TablesPaneProps {
  model: WorkbookModel;
  onUpdate: (sheet: SheetName, rowIndex: number, col: string, val: Primitive) => void;
  onAddRow: (sheet: SheetName) => void;
  onDeleteRow: (sheet: SheetName, rowIndex: number) => void;
  onAddColumn: (sheet: SheetName, col: string, defaultValue: string | number | boolean) => void;
  onDeleteColumn: (sheet: SheetName, col: string) => void;
  onRenameColumn: (sheet: SheetName, oldCol: string, newCol: string) => void;
  onImportTsSheet: (sheet: TsSheetName, rows: GridRow[]) => void;
  issues?: ModelIssue[];
  jumpTo?: { sheet: string; rowIndex: number } | null;
  currencySymbol?: string;
  dateFormat?: DateFormat;
}

export function TablesPane({
  model,
  onUpdate,
  onAddRow,
  onDeleteRow,
  onAddColumn,
  onDeleteColumn,
  onRenameColumn,
  onImportTsSheet,
  issues = [],
  jumpTo,
  currencySymbol = '$',
  dateFormat = 'auto',
}: TablesPaneProps) {
  const [sel, setSel] = useState<TableSel>({ kind: 'static', sheet: 'buses' });
  const [jumpHighlight, setJumpHighlight] = useState<number | null>(null);

  // When jumpTo changes: switch to the target sheet and flash the row
  useEffect(() => {
    if (!jumpTo) return;
    setSel({ kind: 'static', sheet: jumpTo.sheet as SheetName });
    setJumpHighlight(jumpTo.rowIndex);
    // Clear the flash after 2.5 s
    const t = setTimeout(() => setJumpHighlight(null), 2500);
    return () => clearTimeout(t);
  }, [jumpTo]);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [navSearch, setNavSearch] = useState('');
  const [addColOpen, setAddColOpen] = useState(false);
  const [addColAnchor, setAddColAnchor] = useState<DOMRect | null>(null);
  const [showAnalyser, setShowAnalyser] = useState(false);
  const addColBtnRef = useRef<HTMLButtonElement | null>(null);
  const csvInputRef = useRef<HTMLInputElement | null>(null);

  // Per-sheet issue counts for nav badges
  const issueCounts = useMemo(() => {
    const counts: Record<string, { errors: number; warnings: number }> = {};
    issues.forEach((issue) => {
      if (!counts[issue.sheet]) counts[issue.sheet] = { errors: 0, warnings: 0 };
      if (issue.severity === 'error') counts[issue.sheet].errors++;
      else counts[issue.sheet].warnings++;
    });
    return counts;
  }, [issues]);

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

  const toggleGroup = (sheet: string) =>
    setCollapsed((s) => {
      const n = new Set(s);
      n.has(sheet) ? n.delete(sheet) : n.add(sheet);
      return n;
    });

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
  const protectedCols = isTs ? [] : getProtectedColumns(sel.sheet);
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

  return (
    <div className="tables-layout">
      <nav className="tables-nav">
        <div className="nav-search-wrap">
          <input
            className="nav-search"
            type="text"
            placeholder="Filter sheets…"
            value={navSearch}
            onChange={(e) => setNavSearch(e.target.value)}
            aria-label="Filter sheets"
          />
          {navSearch && (
            <button className="nav-search-clear" onClick={() => setNavSearch('')} aria-label="Clear filter">
              ×
            </button>
          )}
        </div>
        <div className="nav-toolbar">
          <button
            className="tb-btn"
            onClick={() => setCollapsed(new Set(TABLE_GROUPS.map((g) => g.sheet)))}
          >
            Collapse all
          </button>
          <button className="tb-btn" onClick={() => setCollapsed(new Set())}>
            Expand all
          </button>
        </div>
        {TABLE_GROUPS.filter(
          (g) =>
            !navSearch ||
            g.label.toLowerCase().includes(navSearch.toLowerCase()) ||
            g.sheet.toLowerCase().includes(navSearch.toLowerCase()) ||
            g.temporalSheets.some((ts) => ts.attribute.toLowerCase().includes(navSearch.toLowerCase())),
        ).map((g) => {
          const open = !collapsed.has(g.sheet);
          const staticActive = sel.kind === 'static' && sel.sheet === g.sheet;
          return (
            <div key={g.sheet} className="nav-group">
              <div className="nav-group-header" onClick={() => toggleGroup(g.sheet)}>
                <span className={`nav-chevron${open ? ' open' : ''}`}>›</span>
                <span className="nav-group-label">{g.label}</span>
                <span className="nav-count">{(model[g.sheet] ?? []).length}</span>
              </div>
              {open && (
                <div className="nav-items">
                  <button
                    className={`nav-item${staticActive ? ' active' : ''}`}
                    onClick={() => { setSel({ kind: 'static', sheet: g.sheet }); setAddColOpen(false); }}
                  >
                    <span className="nav-item-icon">≡</span>
                    <span className="nav-item-label">static</span>
                    <span className="nav-count">{(model[g.sheet] ?? []).length}</span>
                    {issueCounts[g.sheet]?.errors > 0 && (
                      <span className="nav-issue-badge nav-issue-badge--error">{issueCounts[g.sheet].errors}</span>
                    )}
                    {!issueCounts[g.sheet]?.errors && issueCounts[g.sheet]?.warnings > 0 && (
                      <span className="nav-issue-badge nav-issue-badge--warning">{issueCounts[g.sheet].warnings}</span>
                    )}
                  </button>
                  {g.temporalSheets.map((ts) => {
                    const tsRows: GridRow[] = ((model as any)[ts.sheet] as GridRow[]) ?? [];
                    const tsActive = sel.kind === 'ts' && sel.sheet === ts.sheet;
                    return (
                    <button
                      key={ts.sheet}
                      className={`nav-item ts-item${tsActive ? ' active' : ''}`}
                      onClick={() => setSel({ kind: 'ts', sheet: ts.sheet })}
                    >
                      <span className="nav-item-icon">t</span>
                      <span className="nav-item-label">{ts.attribute}</span>
                      <span className={`nav-count${tsRows.length > 0 ? ' has-data' : ''}`}>
                        {tsRows.length > 0 ? `${tsRows.length}t` : '—'}
                      </span>
                    </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      <div className="tables-content">
        <div className="tables-content-header">
          <div>
            <p className="eyebrow">{isTs ? 'Temporal (_t)' : 'Static'}</p>
            <h2>
              {parentGroup?.label ?? sel.sheet}{isTs && temporalMeta ? ` · ${temporalMeta.attribute}` : ''}{' '}
              <span className="sheet-name-chip">{sel.sheet}</span>
            </h2>
          </div>
          <div className="inline-stats">
            <span>{rows.length} rows</span>
            {cols.length > 0 && <span>{cols.length} cols</span>}
            {isTs && <span className="ts-chip">time-series</span>}
          </div>
        </div>

        {isTs ? (
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
            {rows.length > 0 && (
              <button
                className="ghost-button sm danger"
                title="Remove all rows from this time-series sheet"
                onClick={() => onImportTsSheet(sel.sheet as TsSheetName, [])}
              >
                Clear
              </button>
            )}
            {rows.length > 0 && (
              <button
                className={`ghost-button sm${showAnalyser ? ' ghost-button--active' : ''}`}
                onClick={() => setShowAnalyser((v) => !v)}
                title="Toggle input data analyser"
              >
                Analyse
              </button>
            )}
          </div>
        ) : (
          <div className="section-toolbar">
            <button className="ghost-button sm" onClick={() => onAddRow(sel.sheet as SheetName)}>
              + Row
            </button>
            {rows.length > 0 && (
              <button
                className="ghost-button sm danger"
                onClick={() => onDeleteRow(sel.sheet as SheetName, rows.length - 1)}
              >
                − Last row
              </button>
            )}
            <button
              ref={addColBtnRef}
              className="ghost-button sm"
              onClick={() => {
                if (addColOpen) { setAddColOpen(false); return; }
                const rect = addColBtnRef.current?.getBoundingClientRect();
                if (rect) setAddColAnchor(rect);
                setAddColOpen(true);
              }}
            >
              + Column
            </button>
            {rows.length > 0 && (
              <button
                className={`ghost-button sm${showAnalyser ? ' ghost-button--active' : ''}`}
                onClick={() => setShowAnalyser((v) => !v)}
                title="Toggle input data analyser"
              >
                Analyse
              </button>
            )}
          </div>
        )}
        {addColOpen && addColAnchor && (
          <AddColumnDropdown
            sheet={sel.sheet as SheetName}
            existingCols={cols}
            anchorRect={addColAnchor}
            onAdd={(attr) => onAddColumn(sel.sheet as SheetName, attr.attribute, inferInputValue(String(attr.default ?? ''), '') ?? '')}
            onClose={() => setAddColOpen(false)}
          />
        )}

        {showAnalyser && rows.length > 0 && (
          <InputAnalyser
            rows={rows}
            cols={cols}
            isTs={isTs}
            frozenCol={frozenCol}
            currencySymbol={currencySymbol}
          />
        )}

        <div className="tables-grid-wrap">
          {rows.length === 0 ? (
            <div className="grid-empty">
              {isTs ? 'No temporal data — use "Import CSV" above to load a profile.' : 'No rows yet — use "+ Row" to add one.'}
            </div>
          ) : (
            <SpreadsheetGrid
              rows={rows}
              cols={cols}
              frozenCol={frozenCol}
              readOnly={isTs}
              onUpdate={
                isTs ? undefined : (ri, col, val) => onUpdate(sel.sheet as SheetName, ri, col, val)
              }
              rowIssues={isTs ? undefined : rowIssueMap}
              highlightRow={isTs ? null : jumpHighlight}
              onDeleteColumn={isTs ? undefined : (col) => onDeleteColumn(sel.sheet as SheetName, col)}
              onRenameColumn={isTs ? undefined : (old, next) => onRenameColumn(sel.sheet as SheetName, old, next)}
              protectedCols={protectedCols}
              formatDisplayValue={formatDisplayValue}
              coerceEditedValue={coerceEditedValue}
            />
          )}
        </div>
      </div>
    </div>
  );
}
