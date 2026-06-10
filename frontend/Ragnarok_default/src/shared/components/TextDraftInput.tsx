import React, { useEffect, useState } from 'react';

/**
 * Text input that NEVER fights the user's typing (string twin of
 * `NumberDraftInput`).
 *
 * For fields whose committed state is NORMALIZED (e.g. a scenario label that
 * falls back to its previous value when empty: `label.trim() || old`), a plain
 * controlled input re-renders the normalized value on every keystroke — so the
 * user cannot delete the last character; the old text snaps straight back.
 *
 * This keeps a local draft while the field is focused: it can be completely
 * empty mid-edit. Every keystroke still commits (the app stays live; the
 * normalization applies to STATE, not to what's displayed). On blur the field
 * snaps to the committed (normalized) value. External changes update the field
 * only while it is not focused.
 */
export function TextDraftInput({
  value,
  onCommit,
  ...rest
}: {
  value: string | null | undefined;
  onCommit: (v: string) => void;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'>) {
  const [draft, setDraft] = useState<string>(value ?? '');
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (!focused) setDraft(value ?? '');
  }, [value, focused]);

  return (
    <input
      type="text"
      {...rest}
      value={draft}
      onFocus={(e) => {
        setFocused(true);
        rest.onFocus?.(e);
      }}
      onChange={(e) => {
        setDraft(e.target.value);
        onCommit(e.target.value);
      }}
      onBlur={(e) => {
        setFocused(false); // the effect snaps the draft to the committed value
        rest.onBlur?.(e);
      }}
    />
  );
}
