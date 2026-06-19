import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { SearchableOption } from './SearchableSelect';

/**
 * Multi-select sibling of {@link SearchableSelect}: a clickable control showing
 * the chosen values as pills, opening a type-to-filter checkbox menu that stays
 * open while you pick (with Select all / Clear). The menu is rendered
 * position:fixed off the control's rect so it escapes any `overflow` scroller.
 */
interface Option { value: string; label: string }

function normalize(options: SearchableOption[]): Option[] {
  return options.map((o) => (typeof o === 'string' ? { value: o, label: o } : o));
}

export function SearchableMultiSelect({
  values,
  options,
  onChange,
  placeholder = 'Any',
  disabled = false,
  className,
}: {
  values: string[];
  options: SearchableOption[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
}) {
  const opts = useMemo(() => normalize(options), [options]);
  const labelOf = useMemo(() => new Map(opts.map((o) => [o.value, o.label])), [opts]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [coords, setCoords] = useState<{ left: number; top: number; width: number } | null>(null);
  const controlRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const selected = new Set(values);
  const needle = query.trim().toLowerCase();
  const filtered = needle ? opts.filter((o) => o.label.toLowerCase().includes(needle)) : opts;

  const openMenu = () => {
    if (disabled) return;
    const r = controlRef.current?.getBoundingClientRect();
    if (r) setCoords({ left: r.left, top: r.bottom + 2, width: Math.max(r.width, 180) });
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (controlRef.current?.contains(t) || menuRef.current?.contains(t)) return;
      setOpen(false);
      setQuery('');
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setOpen(false); setQuery(''); } };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [open]);

  const toggle = (value: string) => {
    onChange(selected.has(value) ? values.filter((v) => v !== value) : [...values, value]);
  };

  return (
    <div className={['ssm-wrap', className].filter(Boolean).join(' ')}>
      <div
        ref={controlRef}
        className={`ssm-control${disabled ? ' is-disabled' : ''}`}
        onClick={() => (open ? setOpen(false) : openMenu())}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openMenu(); } }}
      >
        {values.length === 0 ? (
          <span className="ssm-placeholder">{placeholder}</span>
        ) : (
          values.map((v) => (
            <span key={v} className="ssm-pill" onClick={(e) => { e.stopPropagation(); toggle(v); }} title="Remove">
              {labelOf.get(v) ?? v}<span className="ssm-pill-x">×</span>
            </span>
          ))
        )}
      </div>

      {open && coords && createPortal(
        <div
          ref={menuRef}
          className="ssm-menu"
          style={{ position: 'fixed', left: coords.left, top: coords.top, width: coords.width }}
        >
          <input
            className="ss-input ssm-search"
            autoFocus
            placeholder="Search…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="ssm-actions">
            <button type="button" className="ssm-action" onClick={() => onChange(filtered.map((o) => o.value))}>Select all</button>
            <button type="button" className="ssm-action" onClick={() => onChange([])}>Clear</button>
          </div>
          <ul className="ss-menu ssm-list">
            {filtered.length === 0 && <li className="ss-option ssm-empty">No matches</li>}
            {filtered.map((o) => (
              <li
                key={o.value}
                className={`ss-option ssm-option${selected.has(o.value) ? ' ss-option--sel' : ''}`}
                onMouseDown={(e) => { e.preventDefault(); toggle(o.value); }}
              >
                <input type="checkbox" readOnly checked={selected.has(o.value)} className="ssm-check" />
                {o.label}
              </li>
            ))}
          </ul>
        </div>,
        document.body,
      )}
    </div>
  );
}
