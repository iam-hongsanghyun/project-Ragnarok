/**
 * Building blocks for run-option editors whose labels, units and help text come from the run-options reference
 * (`GET /api/run-options?key=...`) rather than being retyped here.
 */
import React from 'react';
import { getRunOptionFields, type RunOptionField, type RunOptionFields } from 'lib/api/runOptions';
import { useAsync } from '../../shared/hooks/useAsync';

/** The reference's fields for one key, by path; `{}` until loaded or when the reference is unreachable. */
export function useOptionFields(key: string): RunOptionFields {
  const state = useAsync<RunOptionFields>(key, () => getRunOptionFields(key));
  return state.data ?? {};
}

export interface OptionRowProps {
  label: string;
  /** The reference entry for this input: supplies the unit and the help text. */
  field?: RunOptionField;
  htmlFor?: string;
  /** Replaces the reference's unit in the label (e.g. "%" when the input edits a fraction in percent). */
  unit?: string;
  children: React.ReactNode;
}

export function OptionRow({ label, field, htmlFor, unit, children }: OptionRowProps) {
  const shownUnit = unit ?? field?.unit;
  return (
    <div className="sg-setting-row">
      <label className="sg-setting-label" htmlFor={htmlFor}>
        {label}{shownUnit ? ` (${shownUnit})` : ''}
      </label>
      <div className="sg-btn-row">{children}</div>
      {field && <p className="sg-setting-hint">{field.meaning}</p>}
    </div>
  );
}

/** A number input where blank means "not set" (`null`); never coerces blank to 0. */
export function NullableNumberInput({
  value, onChange, min, max, step, id, placeholder, ariaLabel, disabled,
}: {
  value: number | null | undefined;
  onChange: (v: number | null) => void;
  min?: number;
  max?: number;
  step?: number;
  id?: string;
  placeholder?: string;
  ariaLabel?: string;
  disabled?: boolean;
}) {
  return (
    <input
      id={id}
      type="number"
      className="sg-num-input"
      min={min}
      max={max}
      step={step}
      placeholder={placeholder}
      aria-label={ariaLabel}
      disabled={disabled}
      value={value ?? ''}
      onChange={(e) => {
        if (e.target.value.trim() === '') { onChange(null); return; }
        const n = Number(e.target.value);
        if (Number.isFinite(n)) onChange(n);
      }}
    />
  );
}

/** Off / On buttons; renders only the buttons, so place it inside an {@link OptionRow} (or an `sg-btn-row`). */
export function OnOff({ value, onChange, offLabel = 'Off', onLabel = 'On' }: {
  value: boolean; onChange: (v: boolean) => void; offLabel?: string; onLabel?: string;
}) {
  return (
    <>
      <button type="button" className={`tb-btn sg-solver-btn${!value ? '' : ' tb-btn--muted'}`} onClick={() => onChange(false)}>{offLabel}</button>
      <button type="button" className={`tb-btn sg-solver-btn${value ? '' : ' tb-btn--muted'}`} onClick={() => onChange(true)}>{onLabel}</button>
    </>
  );
}
