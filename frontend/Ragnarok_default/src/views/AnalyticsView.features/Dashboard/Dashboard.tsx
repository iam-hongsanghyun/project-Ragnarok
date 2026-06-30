/**
 * Bloomberg-style editable grid for the Analytics sub-tab.
 *
 * Rows of cards with resizable column widths and per-row heights.
 * Cards can be dragged between rows / reordered within a row. The
 * layout is persisted to localStorage and supports named layouts.
 *
 * Card content (chart / map / notes) is rendered by callbacks passed
 * in by the parent so this file knows nothing about PyPSA results;
 * its job is purely layout.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Card, DashboardLayout, DragPayload, Row } from 'lib/dashboard/types';

const MIN_ROW_HEIGHT = 120;
const MAX_ROW_HEIGHT = 1000;
const MIN_CELL_FLEX = 0.25;
const MAX_CELL_FLEX = 6;

/** Upper bound for auto-height rows. The aspect rule below scales row
 *  height with container width, which on a wide monitor (≈1900 px) drives
 *  a 2-cell row to ≈950 px — far taller than the fixed-size content in
 *  cards like merit-order / CO₂ shadow, leaving large empty bands. Capping
 *  keeps charts comfortably tall without runaway whitespace. Users can
 *  still drag any row taller (which switches it to an explicit height). */
const MAX_AUTO_ROW_HEIGHT = 500;

/** Aspect rule from the user spec:
 *    1 cell  → height = 0.5 × width  (wide chart for time series)
 *    N ≥ 2   → height =       width / N   (square cells)
 *  Returns the height in pixels for a row given the container width,
 *  clamped to [MIN_ROW_HEIGHT, MAX_AUTO_ROW_HEIGHT].
 */
function autoRowHeight(containerWidth: number, cellCount: number): number {
  if (cellCount <= 0 || containerWidth <= 0) return MIN_ROW_HEIGHT;
  const raw = cellCount === 1
    ? Math.round(containerWidth * 0.5)
    : Math.round(containerWidth / cellCount);
  return Math.max(MIN_ROW_HEIGHT, Math.min(MAX_AUTO_ROW_HEIGHT, raw));
}

function effectiveRowHeight(row: Row, containerWidth: number): number {
  if (row.autoHeight) return autoRowHeight(containerWidth, row.cells.length);
  return row.height;
}

interface Props {
  layout: DashboardLayout;
  onLayoutChange: (next: DashboardLayout) => void;
  editing: boolean;
  /** Render a card body. The card title bar is rendered by Dashboard. */
  renderCard: (card: Card) => React.ReactNode;
  /** Resolve the human label for a card, shown in its title bar. */
  cardTitle: (card: Card) => string;
  /** Optional: persist a renamed card title. When provided, the cell
   *  header offers a double-click-to-rename affordance. */
  onCardRename?: (cardId: string, title: string) => void;
  /** Card kinds offerable from an empty placeholder cell's "+" menu. */
  addableCards?: { kind: string; label: string }[];
  /** Factory the parent supplies so Dashboard (which is card-agnostic)
   *  can mint a card of the chosen kind to drop into a placeholder. */
  createCard?: (kind: string) => Card;
}

let _newId = 0;
const newId = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${(_newId++).toString(36)}`;

export function Dashboard({ layout, onLayoutChange, editing, renderCard, cardTitle, onCardRename, addableCards = [], createCard }: Props) {
  const cardById = new Map(layout.cards.map((c) => [c.id, c]));

  // Which empty placeholder cell currently has its "+" menu open.
  const [addMenuCellId, setAddMenuCellId] = useState<string | null>(null);
  // Which existing card currently has its type-switcher menu open.
  const [kindMenuCellId, setKindMenuCellId] = useState<string | null>(null);

  // Container-width observer so auto-height rows can compute their
  // pixel height from the current dashboard width on every layout pass.
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      setContainerWidth(w);
    });
    ro.observe(el);
    setContainerWidth(el.getBoundingClientRect().width);
    return () => ro.disconnect();
  }, []);

  // ── Mutation helpers ──────────────────────────────────────────────────────
  const removeCell = (rowId: string, cellId: string) => {
    const next = {
      ...layout,
      rows: layout.rows
        .map((r) => (r.id === rowId ? { ...r, cells: r.cells.filter((c) => c.id !== cellId) } : r))
        // Drop a row that has no cells left after the removal.
        .filter((r) => r.cells.length > 0),
    };
    onLayoutChange(next);
  };

  const removeRow = (rowId: string) =>
    onLayoutChange({ ...layout, rows: layout.rows.filter((r) => r.id !== rowId) });

  // A fresh row arrives as one full-width placeholder cell the user fills
  // via its "+". Columns are then added with the per-row "+ Add column".
  const addRow = () =>
    onLayoutChange({
      ...layout,
      rows: [...layout.rows, { id: newId('row'), height: 280, autoHeight: true, cells: [{ id: newId('cell'), flex: 1 }] }],
    });

  // Append an empty placeholder column to a row and re-even the widths so
  // the row's full width splits equally across all columns.
  const addColumn = (rowId: string) =>
    onLayoutChange({
      ...layout,
      rows: layout.rows.map((r) =>
        r.id === rowId
          ? { ...r, cells: [...r.cells, { id: newId('cell'), flex: 1 }].map((c) => ({ ...c, flex: 1 })) }
          : r,
      ),
    });

  // Fill a placeholder cell with a freshly-minted card of the chosen kind.
  const fillCell = (rowId: string, cellId: string, kind: string) => {
    if (!createCard) return;
    const card = createCard(kind);
    setAddMenuCellId(null);
    onLayoutChange({
      cards: [...layout.cards, card],
      rows: layout.rows.map((r) =>
        r.id === rowId
          ? { ...r, cells: r.cells.map((c) => (c.id === cellId ? { ...c, cardId: card.id } : c)) }
          : r,
      ),
    });
  };

  // Swap an existing card's kind in place — keeps the same id so the cell's
  // cardId reference stays valid, replacing config with the new kind's default.
  const changeCardKind = (cardId: string, kind: string) => {
    if (!createCard) return;
    setKindMenuCellId(null);
    const fresh = createCard(kind);
    const replaced = { ...fresh, id: cardId } as Card;
    onLayoutChange({
      ...layout,
      cards: layout.cards.map((c) => (c.id === cardId ? replaced : c)),
    });
  };

  const moveCell = (from: DragPayload, toRowId: string, toIndex: number) => {
    if (from.rowId === toRowId) {
      // Reorder inside the same row.
      onLayoutChange({
        ...layout,
        rows: layout.rows.map((r) => {
          if (r.id !== toRowId) return r;
          const idx = r.cells.findIndex((c) => c.id === from.cellId);
          if (idx < 0) return r;
          const next = [...r.cells];
          const [moved] = next.splice(idx, 1);
          const insertAt = idx < toIndex ? toIndex - 1 : toIndex;
          next.splice(Math.max(0, Math.min(next.length, insertAt)), 0, moved);
          return { ...r, cells: next };
        }),
      });
      return;
    }
    // Move across rows.
    const fromRow = layout.rows.find((r) => r.id === from.rowId);
    const cell = fromRow?.cells.find((c) => c.id === from.cellId);
    if (!cell) return;
    onLayoutChange({
      ...layout,
      rows: layout.rows
        .map((r) => {
          if (r.id === from.rowId) return { ...r, cells: r.cells.filter((c) => c.id !== from.cellId) };
          if (r.id === toRowId) {
            const next = [...r.cells];
            next.splice(Math.max(0, Math.min(next.length, toIndex)), 0, cell);
            return { ...r, cells: next };
          }
          return r;
        })
        .filter((r) => r.cells.length > 0),
    });
  };

  // ── Resize handlers (no React state during drag) ─────────────────────────
  const dragState = useRef<null | {
    type: 'row-height' | 'cell-width';
    rowId: string;
    cellId?: string;
    startY: number;
    startX: number;
    startHeight?: number;
    startFlex?: number;
    rightFlex?: number;
    rightCellId?: string;
  }>(null);

  const onRowHeightHandleDown = (rowId: string, e: React.MouseEvent) => {
    e.preventDefault();
    const row = layout.rows.find((r) => r.id === rowId);
    if (!row) return;
    dragState.current = {
      type: 'row-height',
      rowId,
      startY: e.clientY,
      startX: e.clientX,
      // Start from the currently-rendered height so dragging picks up the
      // auto-computed value if the row was in auto mode.
      startHeight: effectiveRowHeight(row, containerWidth),
    };
    window.addEventListener('mousemove', onDragMove);
    window.addEventListener('mouseup', onDragUp);
  };

  const onCellWidthHandleDown = (rowId: string, cellId: string, e: React.MouseEvent) => {
    e.preventDefault();
    const row = layout.rows.find((r) => r.id === rowId);
    if (!row) return;
    const idx = row.cells.findIndex((c) => c.id === cellId);
    if (idx < 0 || idx >= row.cells.length - 1) return;
    dragState.current = {
      type: 'cell-width',
      rowId,
      cellId,
      startX: e.clientX,
      startY: e.clientY,
      startFlex: row.cells[idx].flex,
    };
    window.addEventListener('mousemove', onDragMove);
    window.addEventListener('mouseup', onDragUp);
  };

  const dragLatest = useRef<DashboardLayout>(layout);
  dragLatest.current = layout;

  const onDragMove = useCallback((e: MouseEvent) => {
    const s = dragState.current;
    if (!s) return;
    const cur = dragLatest.current;
    if (s.type === 'row-height' && s.startHeight !== undefined) {
      const dy = e.clientY - s.startY;
      const next = Math.max(MIN_ROW_HEIGHT, Math.min(MAX_ROW_HEIGHT, s.startHeight + dy));
      const updated: DashboardLayout = {
        ...cur,
        rows: cur.rows.map((r) => (r.id === s.rowId ? { ...r, height: next, autoHeight: false } : r)),
      };
      dragLatest.current = updated;
      onLayoutChange(updated);
    } else if (s.type === 'cell-width' && s.startFlex !== undefined && s.cellId) {
      const dx = e.clientX - s.startX;
      // Treat 200 px ≈ 1.0 flex unit shift. Only the dragged cell's flex
      // changes; flexbox redistributes the rest of the row proportionally,
      // so every following cell reflows.
      const delta = dx / 200;
      const next = Math.max(MIN_CELL_FLEX, Math.min(MAX_CELL_FLEX, s.startFlex + delta));
      const cellId = s.cellId;
      const updated: DashboardLayout = {
        ...cur,
        rows: cur.rows.map((r) =>
          r.id === s.rowId
            ? { ...r, cells: r.cells.map((c) => (c.id === cellId ? { ...c, flex: next } : c)) }
            : r,
        ),
      };
      dragLatest.current = updated;
      onLayoutChange(updated);
    }
  }, [onLayoutChange]);

  const onDragUp = useCallback(() => {
    dragState.current = null;
    window.removeEventListener('mousemove', onDragMove);
    window.removeEventListener('mouseup', onDragUp);
  }, [onDragMove]);

  // ── Drag-and-drop between rows / cells ───────────────────────────────────
  const [dropHint, setDropHint] = useState<{ rowId: string; index: number } | null>(null);

  const onCellDragStart = (rowId: string, cellId: string) => (e: React.DragEvent) => {
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', JSON.stringify({ rowId, cellId } as DragPayload));
  };

  const onCellDragOver = (rowId: string, index: number) => (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDropHint({ rowId, index });
  };

  const onCellDrop = (toRowId: string, toIndex: number) => (e: React.DragEvent) => {
    e.preventDefault();
    setDropHint(null);
    try {
      const payload = JSON.parse(e.dataTransfer.getData('text/plain')) as DragPayload;
      moveCell(payload, toRowId, toIndex);
    } catch { /* ignore malformed drops */ }
  };

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div ref={containerRef} className={`dashboard${editing ? ' is-editing' : ''}`}>
      {layout.rows.length === 0 && (
        <div className="dashboard-empty">
          <p>Empty layout. Turn on Edit and add a row.</p>
        </div>
      )}

      {layout.rows.map((row) => (
        <div
          key={row.id}
          className="db-row"
          style={{ height: effectiveRowHeight(row, containerWidth) }}
        >
          {row.cells.map((cell, index) => {
            const card = cell.cardId ? cardById.get(cell.cardId) : undefined;
            const isDropTarget = editing && dropHint?.rowId === row.id && dropHint.index === index;
            return (
              <React.Fragment key={cell.id}>
                {editing && (
                  <div
                    className={`dashboard-drop-zone${isDropTarget ? ' is-active' : ''}`}
                    onDragOver={onCellDragOver(row.id, index)}
                    onDragLeave={() => setDropHint(null)}
                    onDrop={onCellDrop(row.id, index)}
                  />
                )}
                <div
                  className={`dashboard-cell${!card ? ' is-placeholder' : ''}`}
                  style={{ flexGrow: cell.flex, flexBasis: 0, minWidth: 0 }}
                >
                  {card ? (
                    <>
                      <div
                        className="dashboard-cell-header"
                        draggable={editing}
                        onDragStart={editing ? onCellDragStart(row.id, cell.id) : undefined}
                      >
                        {onCardRename ? (
                          <CellTitle
                            title={cardTitle(card)}
                            onRename={(next) => onCardRename(card.id, next)}
                          />
                        ) : (
                          <span className="dashboard-cell-title">{cardTitle(card)}</span>
                        )}
                        {editing && (
                          <div className="dashboard-cell-actions">
                            {createCard && addableCards.length > 0 && (
                              <div className="dashboard-cell-kind">
                                <button
                                  className="dashboard-cell-kind-btn"
                                  onClick={() => setKindMenuCellId(kindMenuCellId === cell.id ? null : cell.id)}
                                  title="Change card type"
                                  aria-label="Change card type"
                                >
                                  ⇄
                                </button>
                                {kindMenuCellId === cell.id && (
                                  <div className="dashboard-cell-add-menu dashboard-cell-kind-menu">
                                    {addableCards.map((opt) => (
                                      <button
                                        key={opt.kind}
                                        className={`tb-btn${card.kind === opt.kind ? ' tb-btn--active' : ''}`}
                                        onClick={() => changeCardKind(card.id, opt.kind)}
                                      >
                                        {opt.label}
                                      </button>
                                    ))}
                                  </div>
                                )}
                              </div>
                            )}
                            <button
                              className="dashboard-cell-remove"
                              onClick={() => removeCell(row.id, cell.id)}
                              title="Remove card"
                              aria-label="Remove card"
                            >
                              ×
                            </button>
                          </div>
                        )}
                      </div>
                      <div className="dashboard-cell-body">{renderCard(card)}</div>
                    </>
                  ) : (
                    // Empty placeholder: a centered "+" opens a kind picker.
                    <div className="dashboard-cell-placeholder">
                      {editing ? (
                        <div className="dashboard-cell-add">
                          <button
                            className="dashboard-cell-add-btn"
                            onClick={() => setAddMenuCellId(addMenuCellId === cell.id ? null : cell.id)}
                            title="Add a card here"
                            aria-label="Add a card here"
                          >
                            +
                          </button>
                          {addMenuCellId === cell.id && (
                            <div className="dashboard-cell-add-menu">
                              {addableCards.map((opt) => (
                                <button
                                  key={opt.kind}
                                  className="tb-btn"
                                  onClick={() => fillCell(row.id, cell.id, opt.kind)}
                                >
                                  {opt.label}
                                </button>
                              ))}
                            </div>
                          )}
                          <button
                            className="dashboard-cell-remove dashboard-cell-remove--placeholder"
                            onClick={() => removeCell(row.id, cell.id)}
                            title="Remove column"
                            aria-label="Remove column"
                          >
                            ×
                          </button>
                        </div>
                      ) : (
                        <span className="dashboard-cell-placeholder-hint">Empty</span>
                      )}
                    </div>
                  )}
                  {editing && index < row.cells.length - 1 && (
                    <div
                      className="dashboard-cell-resize"
                      draggable={false}
                      onMouseDown={(e) => { e.stopPropagation(); onCellWidthHandleDown(row.id, cell.id, e); }}
                      title="Drag to resize"
                    />
                  )}
                </div>
              </React.Fragment>
            );
          })}

          {editing && (
            <div
              className={`dashboard-drop-zone is-tail${dropHint?.rowId === row.id && dropHint.index === row.cells.length ? ' is-active' : ''}`}
              onDragOver={onCellDragOver(row.id, row.cells.length)}
              onDragLeave={() => setDropHint(null)}
              onDrop={onCellDrop(row.id, row.cells.length)}
            />
          )}

          {editing && (
            <button
              className="dashboard-add-col"
              onClick={() => addColumn(row.id)}
              title="Add a column to this row"
              aria-label="Add column"
            >
              + Add column
            </button>
          )}

          {editing && (
            <div className="dashboard-row-edge">
              <button
                className="dashboard-row-remove"
                onClick={() => removeRow(row.id)}
                title="Remove row"
                aria-label="Remove row"
              >
                ×
              </button>
            </div>
          )}

          {editing && (
            <div
              className="dashboard-row-resize"
              draggable={false}
              onMouseDown={(e) => { e.stopPropagation(); onRowHeightHandleDown(row.id, e); }}
              title="Drag to resize row height"
            />
          )}
        </div>
      ))}

      {editing && (
        <div className="dashboard-add-row">
          <button className="tb-btn" onClick={addRow}>+ Add row</button>
        </div>
      )}
    </div>
  );
}

// ── Layout mutation utilities (used by the parent toolbar) ─────────────────

export function addCard(layout: DashboardLayout, rowId: string | null, card: Card): DashboardLayout {
  const nextCards = [...layout.cards, card];
  const cell = { id: newId('cell'), flex: 1, cardId: card.id };
  if (rowId === null) {
    // No row chosen — append a new row with this single cell.
    return {
      cards: nextCards,
      rows: [...layout.rows, { id: newId('row'), height: 280, autoHeight: true, cells: [cell] }],
    };
  }
  const exists = layout.rows.some((r) => r.id === rowId);
  if (!exists) {
    return {
      cards: nextCards,
      rows: [...layout.rows, { id: newId('row'), height: 280, autoHeight: true, cells: [cell] }],
    };
  }
  return {
    cards: nextCards,
    rows: layout.rows.map((r) => (r.id === rowId ? { ...r, cells: [...r.cells, cell] } : r)),
  };
}

export { newId };

// ── Inline rename input for cell titles ─────────────────────────────────

interface CellTitleProps {
  title: string;
  onRename: (next: string) => void;
}

function CellTitle({ title, onRename }: CellTitleProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);

  const commit = () => {
    const trimmed = draft.trim();
    onRename(trimmed === title ? title : trimmed);
    setEditing(false);
  };

  if (!editing) {
    return (
      <span
        className="dashboard-cell-title"
        title="Double-click to rename"
        onDoubleClick={(e) => {
          e.stopPropagation();
          setDraft(title);
          setEditing(true);
        }}
      >
        {title}
      </span>
    );
  }
  return (
    <input
      className="dashboard-cell-title-input"
      type="text"
      autoFocus
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') commit();
        if (e.key === 'Escape') { setDraft(title); setEditing(false); }
      }}
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
    />
  );
}
