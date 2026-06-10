import React, { useEffect, useState } from 'react';

/**
 * Numeric input that NEVER fights the user's typing.
 *
 * The classic controlled-number bug: rendering straight from numeric state and
 * coercing on every change (`Number('')` → 0, often via `|| 0`) means deleting
 * the last character snaps "0" back into the field, and typing "4" then yields
 * "04". This component keeps a local STRING draft while the field is focused:
 *
 * - deleting everything leaves the field genuinely empty;
 * - every valid intermediate parse is committed immediately (the app stays as
 *   live as before), clamped to [min, max];
 * - on blur the draft snaps to the committed value; an empty/invalid draft
 *   commits `emptyValue` (default 0, clamped) so state never holds NaN;
 * - external value changes update the field only while it is NOT focused.
 *
 * Drop-in for `<input type="number">`: all other input props pass through.
 */
export function NumberDraftInput({
  value,
  onCommit,
  min,
  max,
  emptyValue = 0,
  ...rest
}: {
  value: number | null | undefined;
  onCommit: (v: number) => void;
  min?: number;
  max?: number;
  /** Committed when the field is left empty/invalid on blur (clamped). */
  emptyValue?: number;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'min' | 'max'>) {
  const asText = (v: number | null | undefined): string =>
    v === null || v === undefined || Number.isNaN(v) ? '' : String(v);
  const [draft, setDraft] = useState<string>(asText(value));
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (!focused) setDraft(asText(value));
  }, [value, focused]);

  const clamp = (v: number): number => {
    let out = v;
    if (min !== undefined) out = Math.max(min, out);
    if (max !== undefined) out = Math.min(max, out);
    return out;
  };

  return (
    <input
      type="number"
      {...rest}
      min={min}
      max={max}
      value={draft}
      onFocus={(e) => {
        setFocused(true);
        rest.onFocus?.(e);
      }}
      onChange={(e) => {
        const raw = e.target.value;
        setDraft(raw);
        if (raw.trim() === '') return; // empty stays empty while editing
        const parsed = Number(raw);
        if (Number.isFinite(parsed)) onCommit(clamp(parsed));
      }}
      onBlur={(e) => {
        setFocused(false);
        const raw = e.target.value.trim();
        const parsed = raw === '' ? Number.NaN : Number(raw);
        const next = clamp(Number.isFinite(parsed) ? parsed : emptyValue);
        onCommit(next);
        setDraft(String(next));
        rest.onBlur?.(e);
      }}
    />
  );
}
