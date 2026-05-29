import React, { useMemo, useRef, useState } from 'react';

/**
 * A dropdown that doubles as a type-to-filter search box. Click to open the
 * list, type to narrow it, pick one to set the value. The menu is rendered
 * position:fixed off the input's bounding rect so it escapes any
 * `overflow` scroll container instead of being clipped; it closes on blur,
 * scroll, or Escape.
 *
 * Options may be plain strings (value === label, and free text is allowed —
 * typing stores the typed value) or `{ value, label }` objects (the input
 * shows the label but stores the value, and typing only filters — unmatched
 * text reverts on blur so an invalid code is never stored).
 */
export type SearchableOption = string | { value: string; label: string };

interface Option { value: string; label: string }

function normalize(options: SearchableOption[]): Option[] {
  return options.map((o) => (typeof o === 'string' ? { value: o, label: o } : o));
}

export function SearchableSelect({
  value,
  options,
  onChange,
  placeholder,
  className,
  disabled = false,
}: {
  value: string;
  options: SearchableOption[];
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  disabled?: boolean;
}) {
  const opts = useMemo(() => normalize(options), [options]);
  // Plain-string option sets accept free text; mapped {value,label} sets do not.
  const freeText = useMemo(() => options.every((o) => typeof o === 'string'), [options]);
  const currentLabel = opts.find((o) => o.value === value)?.label ?? value;

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState<string | null>(null); // null ⇒ not editing; show currentLabel
  const [coords, setCoords] = useState<{ left: number; top: number; width: number } | null>(null);
  const [hi, setHi] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const blurTimer = useRef<number | null>(null);

  const needle = (query ?? '').trim().toLowerCase();
  const filtered = query === null || needle === ''
    ? opts
    : opts.filter((o) => o.label.toLowerCase().includes(needle));

  const display = query !== null ? query : currentLabel;

  const openMenu = () => {
    if (disabled) return;
    const r = inputRef.current?.getBoundingClientRect();
    if (r) setCoords({ left: r.left, top: r.bottom + 2, width: r.width });
    setHi(Math.max(0, opts.findIndex((o) => o.value === value)));
    setOpen(true);
  };

  const closeAndReset = () => { setOpen(false); setQuery(null); };

  const closeSoon = () => {
    blurTimer.current = window.setTimeout(closeAndReset, 120);
  };

  const pick = (opt: Option) => {
    if (blurTimer.current) window.clearTimeout(blurTimer.current);
    onChange(opt.value);
    closeAndReset();
  };

  const onType = (text: string) => {
    setQuery(text);
    setHi(0);
    if (!open) openMenu();
    if (freeText) onChange(text); // store live for free-text fields
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') { closeAndReset(); inputRef.current?.blur(); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); if (!open) openMenu(); setHi((h) => Math.min(h + 1, filtered.length - 1)); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); return; }
    if (e.key === 'Enter' && open && filtered[hi]) { e.preventDefault(); pick(filtered[hi]); }
  };

  return (
    <div className="ss-wrap">
      <input
        ref={inputRef}
        className={className}
        value={display}
        placeholder={placeholder}
        disabled={disabled}
        onFocus={(e) => { openMenu(); e.target.select(); }}
        onClick={openMenu}
        onChange={(e) => onType(e.target.value)}
        onBlur={closeSoon}
        onScroll={() => closeAndReset()}
        onKeyDown={onKeyDown}
      />
      {open && coords && filtered.length > 0 && (
        <ul
          className="ss-menu"
          style={{ position: 'fixed', left: coords.left, top: coords.top, width: coords.width }}
        >
          {filtered.map((o, idx) => (
            <li
              key={o.value}
              className={`ss-option${o.value === value ? ' ss-option--sel' : ''}${idx === hi ? ' ss-option--active' : ''}`}
              onMouseDown={(e) => { e.preventDefault(); pick(o); }}
              onMouseEnter={() => setHi(idx)}
            >
              {o.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
