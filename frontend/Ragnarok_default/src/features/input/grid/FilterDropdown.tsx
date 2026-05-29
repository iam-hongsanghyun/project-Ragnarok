import React, { useEffect, useRef, useState } from 'react';
import ReactDOM from 'react-dom';

interface FilterDropdownProps {
  col: string;
  allValues: string[];
  selected: Set<string>;
  anchorRect: DOMRect;
  onToggle: (val: string) => void;
  onSelectAll: () => void;
  onUncheckAll: () => void;
  onClose: () => void;
  onRename?: (newName: string) => void;
  onDelete?: () => void;
}

/** Excel-style column value filter, rendered as a portal so grid overflow
 *  never clips it. Optionally hosts column rename / delete controls. */
export function FilterDropdown({
  col, allValues, selected, anchorRect,
  onToggle, onSelectAll, onUncheckAll, onClose, onRename, onDelete,
}: FilterDropdownProps) {
  const [search, setSearch] = useState('');
  const [rename, setRename] = useState(col);
  const ref = useRef<HTMLDivElement>(null);

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
      {(onRename || onDelete) && (
        <div className="cfd-colops">
          {onRename && (
            <input
              className="cfd-rename"
              value={rename}
              onChange={(e) => setRename(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  const t = rename.trim();
                  if (t && t !== col) onRename(t);
                  onClose();
                }
              }}
              title="Rename column (Enter to apply)"
            />
          )}
          {onDelete && (
            <button
              className="cfd-delete"
              title={`Remove column "${col}"`}
              onClick={() => {
                if (window.confirm(`Remove column "${col}" from all rows? This cannot be undone.`)) {
                  onDelete();
                  onClose();
                }
              }}
            >
              Delete
            </button>
          )}
        </div>
      )}
      <div className="cfd-search-wrap">
        <input
          className="cfd-search"
          autoFocus
          placeholder="Search values…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <label className="cfd-option cfd-select-all">
        <input type="checkbox" checked={allChecked} onChange={allChecked ? onUncheckAll : onSelectAll} />
        <span>(Select All)</span>
      </label>
      <div className="cfd-divider" />
      <div className="cfd-list">
        {visible.length === 0 && <div className="cfd-empty">No matches</div>}
        {visible.map((val) => (
          <label key={val} className="cfd-option">
            <input type="checkbox" checked={selected.has(val)} onChange={() => onToggle(val)} />
            <span className="cfd-val">{val === '' ? <em style={{ color: '#94a3b8' }}>(blank)</em> : val}</span>
          </label>
        ))}
      </div>
      <div className="cfd-footer">
        <button className="cfd-btn" onClick={() => { onSelectAll(); onClose(); }}>Reset</button>
        <button className="cfd-btn cfd-btn--primary" onClick={onClose}>OK</button>
      </div>
    </div>,
    document.body,
  );
}
