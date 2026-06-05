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
  // 'server' rows are fetched asynchronously by the caller (TableEditor) and
  // passed to optionsFromRows directly; resolveOptionsFrom yields [] for it.
  return optionsFromRows(spec, rows, ctx.formValues);
}

/**
 * Transform rows into options: dedup by value, apply the optional numeric
 * `filter` (threshold from a literal or a sibling field), and append a
 * `labelSuffixColumn` value to each label. Shared by the model/config path and
 * the async `source: 'server'` path.
 */
export function optionsFromRows(
  spec: ModuleConfigOptionsFrom,
  rows: Array<Record<string, unknown>>,
  formValues?: Record<string, unknown>,
): ResolvedOption[] {
  const valueKey = spec.column ?? 'name';
  const labelKey = spec.labelColumn ?? valueKey;

  // Optional numeric filter (e.g. build_year >= a sibling field's value).
  const filter = spec.filter;
  let threshold = Number.NaN;
  if (filter) {
    const raw = filter.valueFrom !== undefined ? formValues?.[filter.valueFrom] : filter.value;
    threshold = Number(raw);
  }
  const passesFilter = (row: Record<string, unknown>): boolean => {
    // No-op when blank / 0 / non-numeric (Number('') === 0), so an unset year
    // shows all rows. A real year threshold is always positive.
    if (!filter || !Number.isFinite(threshold) || threshold <= 0) return true;
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
