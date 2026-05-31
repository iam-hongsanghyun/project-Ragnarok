/**
 * Popover-style date picker built on `react-calendar`.
 *
 * Wraps the canonical `.ss-*` input chrome so the trigger looks identical
 * to every other dropdown in the app (mono font, square border, chevron).
 * The popover renders react-calendar with restyled tiles to match the
 * project's monochrome palette — no react-calendar default colours bleed
 * through.
 *
 * Value contract: ISO `YYYY-MM-DD` strings, both in and out. `min` / `max`
 * are optional bounds (same string format).
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import Calendar from 'react-calendar';

interface Props {
  value: string;
  onChange: (iso: string) => void;
  min?: string;
  max?: string;
  /** Placeholder shown in the trigger when value is empty. */
  placeholder?: string;
}

/** Format a Date as ISO YYYY-MM-DD (local-time, no UTC drift). */
function formatISO(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/** Parse a YYYY-MM-DD string into a local-time Date (UTC drift-free). */
function parseISO(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  if (!y || !mo || !d) return null;
  return new Date(y, mo - 1, d);
}

export function DateField({ value, onChange, min, max, placeholder }: Props) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const selected = useMemo(() => parseISO(value), [value]);
  const minDate = useMemo(() => parseISO(min) || undefined, [min]);
  const maxDate = useMemo(() => parseISO(max) || undefined, [max]);

  const handleCalendarChange: (value: unknown) => void = (next) => {
    // react-calendar can hand us Date | [Date, Date] | null depending on
    // selectRange — we use single-date mode so it's always Date or null.
    if (next instanceof Date) {
      onChange(formatISO(next));
      setOpen(false);
    } else if (Array.isArray(next) && next[0] instanceof Date) {
      onChange(formatISO(next[0] as Date));
      setOpen(false);
    }
  };

  return (
    <div ref={wrapRef} className="ss-wrap data-import-date">
      <button
        type="button"
        className="ss-input data-import-date__trigger"
        onClick={() => setOpen((s) => !s)}
        aria-expanded={open}
      >
        {value || placeholder || 'YYYY-MM-DD'}
      </button>
      {open && (
        <div className="data-import-date__popover" role="dialog">
          <Calendar
            onChange={handleCalendarChange}
            value={selected ?? undefined}
            minDate={minDate}
            maxDate={maxDate}
            locale="en-CA"
            formatDay={(_locale, date) => String(date.getDate())}
            calendarType="iso8601"
            showFixedNumberOfWeeks={false}
          />
        </div>
      )}
    </div>
  );
}
