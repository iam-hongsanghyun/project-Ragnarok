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

  // Optional numeric filter (e.g. build_year >= a sibling field's value).
  const filter = spec.filter;
  let threshold = Number.NaN;
  if (filter) {
    const raw = filter.valueFrom !== undefined ? ctx.formValues?.[filter.valueFrom] : filter.value;
    threshold = Number(raw);
  }
  const passesFilter = (row: Record<string, unknown>): boolean => {
    if (!filter || !Number.isFinite(threshold)) return true; // no-op when no threshold
    const cell = Number(row[filter.column]);
    if (!Number.isFinite(cell)) return false; // non-numeric cell can't satisfy a numeric filter
    switch (filter.op ?? '>=') {
      case '>': return cell > threshold;
      case '<': return cell < threshold;
      case '<=': return cell <= threshold;
      case '==': return cell === threshold;
      case '!=': return cell !== threshold;
      case '>=':
      default: return cell >= threshold;
    }
  };

  const seen = new Set<string>();
  const out: ResolvedOption[] = [];
  for (const row of rows) {
    if (!row || typeof row !== 'object') continue;
    if (!passesFilter(row)) continue;
    const value = String(row[valueKey] ?? '');
    if (!value || seen.has(value)) continue;
    seen.add(value);
    const labelRaw = row[labelKey];
    let label = labelRaw === undefined || labelRaw === null || labelRaw === '' ? value : String(labelRaw);
    if (spec.labelSuffixColumn) {
      const suffix = row[spec.labelSuffixColumn];
      if (suffix !== undefined && suffix !== null && suffix !== '') label = `${label} (${String(suffix)})`;
    }
    out.push({ value, label });
  }
  return out;
}
