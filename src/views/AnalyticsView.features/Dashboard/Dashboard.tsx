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
import React, { useCallback, useRef, useState } from 'react';
import { Card, DashboardLayout, DragPayload } from './types';

const MIN_ROW_HEIGHT = 120;
const MAX_ROW_HEIGHT = 1000;
const MIN_CELL_FLEX = 0.25;
const MAX_CELL_FLEX = 6;

interface Props {
  layout: DashboardLayout;
  onLayoutChange: (next: DashboardLayout) => void;
  editing: boolean;
  /** Render a card body. The card title bar is rendered by Dashboard. */
  renderCard: (card: Card) => React.ReactNode;
  /** Resolve the human label for a card, shown in its title bar. */
  cardTitle: (card: Card) => string;
}

let _newId = 0;
const newId = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${(_newId++).toString(36)}`;

export function Dashboard({ layout, onLayoutChange, editing, renderCard, cardTitle }: Props) {
  const cardById = new Map(layout.cards.map((c) => [c.id, c]));

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

  const addRow = () =>
    onLayoutChange({ ...layout, rows: [...layout.rows, { id: newId('row'), height: 280, cells: [] }] });

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
      startHeight: row.height,
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
      rightFlex: row.cells[idx + 1].flex,
      rightCellId: row.cells[idx + 1].id,
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
        rows: cur.rows.map((r) => (r.id === s.rowId ? { ...r, height: next } : r)),
      };
      dragLatest.current = updated;
      onLayoutChange(updated);
    } else if (s.type === 'cell-width' && s.startFlex !== undefined && s.rightFlex !== undefined && s.cellId && s.rightCellId) {
      const dx = e.clientX - s.startX;
      // Treat 200 px ≈ 1.0 flex unit shift.
      const delta = dx / 200;
      const total = s.startFlex + s.rightFlex;
      const next = Math.max(MIN_CELL_FLEX, Math.min(total - MIN_CELL_FLEX, s.startFlex + delta));
      const right = Math.max(MIN_CELL_FLEX, Math.min(MAX_CELL_FLEX, total - next));
      const cellId = s.cellId;
      const rightCellId = s.rightCellId;
      const updated: DashboardLayout = {
        ...cur,
        rows: cur.rows.map((r) =>
          r.id === s.rowId
            ? {
                ...r,
                cells: r.cells.map((c) =>
                  c.id === cellId ? { ...c, flex: next } :
                  c.id === rightCellId ? { ...c, flex: right } :
                  c,
                ),
              }
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
    <div className={`dashboard${editing ? ' is-editing' : ''}`}>
      {layout.rows.length === 0 && (
        <div className="dashboard-empty">
          <p>Empty layout. Turn on Edit and add a row.</p>
        </div>
      )}

      {layout.rows.map((row) => (
        <div
          key={row.id}
          className="dashboard-row"
          style={{ height: row.height }}
        >
          {row.cells.map((cell, index) => {
            const card = cardById.get(cell.cardId);
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
                  className="dashboard-cell"
                  style={{ flexGrow: cell.flex, flexBasis: 0, minWidth: 0 }}
                  draggable={editing}
                  onDragStart={editing ? onCellDragStart(row.id, cell.id) : undefined}
                >
                  <div className="dashboard-cell-header">
                    <span className="dashboard-cell-title">
                      {card ? cardTitle(card) : 'Missing card'}
                    </span>
                    {editing && (
                      <button
                        className="dashboard-cell-remove"
                        onClick={() => removeCell(row.id, cell.id)}
                        title="Remove card"
                        aria-label="Remove card"
                      >
                        ×
                      </button>
                    )}
                  </div>
                  <div className="dashboard-cell-body">
                    {card ? renderCard(card) : <p className="dashboard-cell-missing">Missing card.</p>}
                  </div>
                  {editing && index < row.cells.length - 1 && (
                    <div
                      className="dashboard-cell-resize"
                      onMouseDown={(e) => onCellWidthHandleDown(row.id, cell.id, e)}
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
              onMouseDown={(e) => onRowHeightHandleDown(row.id, e)}
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
      rows: [...layout.rows, { id: newId('row'), height: 280, cells: [cell] }],
    };
  }
  const exists = layout.rows.some((r) => r.id === rowId);
  if (!exists) {
    return {
      cards: nextCards,
      rows: [...layout.rows, { id: newId('row'), height: 280, cells: [cell] }],
    };
  }
  return {
    cards: nextCards,
    rows: layout.rows.map((r) => (r.id === rowId ? { ...r, cells: [...r.cells, cell] } : r)),
  };
}

export { newId };
