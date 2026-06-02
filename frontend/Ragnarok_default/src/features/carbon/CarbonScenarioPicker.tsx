/**
 * Searchable scenario dropdown for the carbon schedule.
 *
 * One control replaces the saved-schedules list: click a scenario's NAME to
 * make it active (it loads onto the chart to edit and is applied to the run);
 * tick its CHECKBOX to overlay it for comparison. Rename inline, delete, add
 * "New from current", and a "Scalar (no schedule)" option are all inside.
 *
 * Closes on click-outside or Escape; stays open while ticking / renaming.
 */
import React, { useEffect, useRef, useState } from 'react';
import type { CarbonScheduleProfile } from 'lib/types';

interface Props {
  library: CarbonScheduleProfile[];
  /** The active (selected/edited/applied) profile, or null for scalar/custom. */
  activeId: string | null;
  /** Active curve is a non-empty, unsaved scratch (no scenario selected). */
  isCustom: boolean;
  overlayIds: Set<string>;
  colorOf: (i: number) => string;
  onSelect: (id: string | null) => void;
  onToggleCompare: (id: string) => void;
  onRename: (id: string, name: string) => void;
  onDelete: (id: string) => void;
  onNewFromCurrent: () => void;
  canSaveNew: boolean;
}

export function CarbonScenarioPicker({
  library, activeId, isCustom, overlayIds, colorOf,
  onSelect, onToggleCompare, onRename, onDelete, onNewFromCurrent, canSaveNew,
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) { setOpen(false); setRenamingId(null); }
    };
    const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') { setOpen(false); setRenamingId(null); } };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onEsc);
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onEsc); };
  }, [open]);

  const activeProfile = activeId ? library.find((p) => p.id === activeId) ?? null : null;
  const triggerLabel = activeProfile
    ? activeProfile.name
    : (isCustom ? 'Custom (unsaved)' : 'Scalar price (no schedule)');

  const needle = query.trim().toLowerCase();
  const filtered = needle ? library.filter((p) => p.name.toLowerCase().includes(needle)) : library;

  const select = (id: string | null) => { onSelect(id); setOpen(false); setQuery(''); setRenamingId(null); };

  return (
    <div className="carbon-picker" ref={wrapRef}>
      <span className="carbon-picker-prefix">Scenario</span>
      <button type="button" className="carbon-picker-trigger" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="carbon-picker-value">{triggerLabel}</span>
        <span className="carbon-picker-caret">▾</span>
      </button>
      {open && (
        <div className="carbon-picker-menu">
          {library.length > 4 && (
            <input
              className="carbon-picker-search"
              placeholder="Search scenarios…"
              value={query}
              autoFocus
              onChange={(e) => setQuery(e.target.value)}
            />
          )}
          <button
            type="button"
            className={`carbon-picker-scalar${activeId === null && !isCustom ? ' is-active' : ''}`}
            onClick={() => select(null)}
          >
            Scalar price (no schedule)
          </button>
          <ul className="carbon-picker-list">
            {filtered.map((p) => {
              const i = library.indexOf(p);
              return (
                <li key={p.id} className={`carbon-picker-row${activeId === p.id ? ' is-active' : ''}`}>
                  <label className="carbon-show" title="Overlay on the chart to compare">
                    <input type="checkbox" checked={overlayIds.has(p.id)} onChange={() => onToggleCompare(p.id)} />
                    <span className="carbon-swatch" style={{ background: overlayIds.has(p.id) ? colorOf(i) : 'transparent', borderColor: colorOf(i) }} />
                  </label>
                  {renamingId === p.id ? (
                    <input
                      className="carbon-picker-rename"
                      value={p.name}
                      autoFocus
                      onChange={(e) => onRename(p.id, e.target.value)}
                      onBlur={() => setRenamingId(null)}
                      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === 'Escape') setRenamingId(null); }}
                    />
                  ) : (
                    <button
                      type="button"
                      className="carbon-picker-name"
                      onClick={() => select(p.id)}
                      title="Select — load on the chart to edit, and apply to the run"
                    >
                      {p.name}
                    </button>
                  )}
                  <button type="button" className="carbon-picker-icon" title="Rename" onClick={() => setRenamingId((r) => (r === p.id ? null : p.id))}>✎</button>
                  <button type="button" className="carbon-picker-icon carbon-picker-del" title="Delete" onClick={() => onDelete(p.id)}>×</button>
                </li>
              );
            })}
            {filtered.length === 0 && <li className="carbon-picker-nomatch">No matches</li>}
          </ul>
          {canSaveNew && (
            <button type="button" className="carbon-picker-new" onClick={() => { onNewFromCurrent(); setOpen(false); }}>
              + New from current curve
            </button>
          )}
        </div>
      )}
    </div>
  );
}
