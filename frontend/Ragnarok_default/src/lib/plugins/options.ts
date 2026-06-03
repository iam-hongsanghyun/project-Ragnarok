import { ModuleConfigOptionsFrom, WorkbookModel } from 'lib/types';

export interface ResolvedOption {
  value: string;
  label: string;
}

export interface OptionsContext {
  /** The current workbook model, for `source: 'model'`. */
  model?: WorkbookModel;
  /** Sibling config field values, for `source: 'config'`. */
  formValues?: Record<string, unknown>;
}

/**
 * Resolve a `ModuleConfigOptionsFrom` spec to a distinct option list.
 *
 * - `source: 'model'`  reads rows from `model[sheet]`.
 * - `source: 'config'` reads rows from `formValues[field]` (a sibling `table`
 *   field's current value).
 *
 * Each row contributes `{ value: row[column], label: row[labelColumn] }`,
 * with `column` defaulting to `'name'` and `labelColumn` to `column`. Blank
 * values are dropped and duplicates collapse to the first occurrence (so the
 * label of the first row wins). Returns `[]` when the source is unavailable —
 * callers fall back to any static `options`.
 */
export function resolveOptionsFrom(spec: ModuleConfigOptionsFrom, ctx: OptionsContext): ResolvedOption[] {
  let rows: Array<Record<string, unknown>> = [];
  if (spec.source === 'model') {
    const sheet = spec.sheet ? ctx.model?.[spec.sheet] : undefined;
    if (Array.isArray(sheet)) rows = sheet as Array<Record<string, unknown>>;
  } else if (spec.source === 'config') {
    const raw = spec.field ? ctx.formValues?.[spec.field] : undefined;
    if (Array.isArray(raw)) rows = raw as Array<Record<string, unknown>>;
  }

  const valueKey = spec.column ?? 'name';
  const labelKey = spec.labelColumn ?? valueKey;

  const seen = new Set<string>();
  const out: ResolvedOption[] = [];
  for (const row of rows) {
    if (!row || typeof row !== 'object') continue;
    const value = String(row[valueKey] ?? '');
    if (!value || seen.has(value)) continue;
    seen.add(value);
    const labelRaw = row[labelKey];
    out.push({ value, label: labelRaw === undefined || labelRaw === null || labelRaw === '' ? value : String(labelRaw) });
  }
  return out;
}
