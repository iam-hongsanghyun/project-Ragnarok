import React, { useRef, useState } from 'react';

/**
 * A dropdown that doubles as a type-to-filter search box. Click to see every
 * option; type to narrow the list; pick one to set the value. Free text is
 * still allowed (so comma-separated carriers or a custom attribute can be
 * typed), but the visible list makes the valid choices discoverable.
 *
 * The menu is rendered position:fixed off the input's bounding rect so it
 * escapes the table's `overflow-x: auto` scroll container instead of being
 * clipped. It closes on blur, scroll, or Escape.
 */
export function SearchableSelect({
  value,
  options,
  onChange,
  placeholder,
  className,
}: {
  value: string;
  options: string[];
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<{ left: number; top: number; width: number } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const blurTimer = useRef<number | null>(null);

  const needle = value.trim().toLowerCase();
  const exact = options.some((o) => o.toLowerCase() === needle);
  // Empty or already-selected → show the full list so the user can re-pick;
  // partial text → filter by substring.
  const filtered = !needle || exact ? options : options.filter((o) => o.toLowerCase().includes(needle));

  const openMenu = () => {
    const r = inputRef.current?.getBoundingClientRect();
    if (r) setCoords({ left: r.left, top: r.bottom + 2, width: r.width });
    setOpen(true);
  };

  const closeSoon = () => {
    blurTimer.current = window.setTimeout(() => setOpen(false), 120);
  };

  const pick = (v: string) => {
    if (blurTimer.current) window.clearTimeout(blurTimer.current);
    onChange(v);
    setOpen(false);
  };

  return (
    <div className="ss-wrap">
      <input
        ref={inputRef}
        className={className}
        value={value}
        placeholder={placeholder}
        onFocus={openMenu}
        onClick={openMenu}
        onChange={(e) => { onChange(e.target.value); if (!open) openMenu(); }}
        onBlur={closeSoon}
        onScroll={() => setOpen(false)}
        onKeyDown={(e) => { if (e.key === 'Escape') { setOpen(false); (e.target as HTMLInputElement).blur(); } }}
      />
      {open && coords && filtered.length > 0 && (
        <ul
          className="ss-menu"
          style={{ position: 'fixed', left: coords.left, top: coords.top, width: coords.width }}
          onScroll={(e) => e.stopPropagation()}
        >
          {filtered.map((o) => (
            <li
              key={o}
              className={`ss-option${o.toLowerCase() === needle ? ' ss-option--sel' : ''}`}
              onMouseDown={(e) => { e.preventDefault(); pick(o); }}
            >
              {o}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
