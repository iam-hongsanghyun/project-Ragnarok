/**
 * Forge — Query & Edit (database-query-like bulk edit).
 *
 * Pick a component + attribute (static or temporal), narrow rows with ANDed
 * filters — each on the component itself OR on a one-hop-linked component
 * (e.g. filter `buses` by `province`, edit the `generators` on those buses) —
 * and edit: set / add / multiply, or derive a static value from another
 * attribute (`p_nom_max = 3 × p_nom`). Preview runs a server-side dry run
 * (match count + before/after); Apply writes through the session.
 *
 * All resolution (filters, joins, temporal series-column selection) happens on
 * the backend, which holds the full model — the thin client can't see series
 * or join across the whole model. This panel only builds the request.
 */
import React, { useEffect, useMemo, useState } from 'react';
import type { WorkbookModel } from 'lib/types';
import { usePersistedState } from 'shared/hooks/usePersistedState';
import { SearchableSelect } from 'shared/components/SearchableSelect';
import { NumberDraftInput } from 'shared/components/NumberDraftInput';
import {
  getComponentSchema,
  PYPSA_COMPONENTS,
  PypsaComponentSchema,
} from 'lib/constants/pypsa_schema';
import { getSheetDistinct } from 'lib/api/session';
import {
  buildRequest,
  DeriveState,
  EditOp,
  EQUALITY_OPS,
  FilterOp,
  FILTER_OPS,
  NUMERIC_OPS,
  QueryApplyResult,
  QueryEditRequest,
  QueryFilterState,
  QueryPreview,
} from 'lib/forge/queryEdit';

interface Props {
  model: WorkbookModel;
  sheetsWithRows: string[];
  onPreview: (req: QueryEditRequest) => Promise<QueryPreview>;
  onApply: (req: QueryEditRequest) => Promise<QueryApplyResult>;
  onStatus: (msg: string) => void;
}

const EDIT_OPS: Array<{ value: EditOp; label: string }> = [
  { value: 'set', label: 'Set (=)' },
  { value: 'add', label: 'Add (+)' },
  { value: 'multiply', label: 'Multiply (×%)' },
  { value: 'derive', label: 'Derive (coef × attr + const)' },
];

const BUS_REFS = ['bus', 'bus0', 'bus1', 'bus2', 'bus3', 'bus4'];

let counter = 0;
const newId = (): string => `qf_${(counter += 1)}`;

/** Attribute names that can be edited on a component (input, static or temporal). */
function editableAttrs(comp: PypsaComponentSchema | null): string[] {
  if (!comp) return [];
  return Array.from(new Set([...comp.input_static_attributes, ...comp.input_temporal_attributes]));
}

/** All column-name options for filtering a component: schema input attributes +
 *  `name`. Free text is allowed (SearchableSelect on string options), so custom
 *  columns like `province` that aren't in the schema can still be typed. */
function filterColumns(comp: PypsaComponentSchema | null): string[] {
  if (!comp) return ['name'];
  return Array.from(new Set(['name', ...comp.input_attributes, ...comp.static_attributes]));
}

interface Spec {
  target: string;
  attribute: string;
  temporalPref: boolean;
  filters: QueryFilterState[];
  op: EditOp;
  amount: string;
  derive: DeriveState;
}

const BLANK_SPEC: Spec = {
  target: '',
  attribute: '',
  temporalPref: false,
  filters: [],
  op: 'multiply',
  amount: '100',
  derive: { source_attr: '', coefficient: 1, constant: 0 },
};

export function QueryEditPanel({ sheetsWithRows, onPreview, onApply, onStatus }: Props) {
  const [spec, setSpec] = usePersistedState<Spec>('ui:forge-query', BLANK_SPEC);
  const [preview, setPreview] = useState<QueryPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const patch = (p: Partial<Spec>) => setSpec({ ...spec, ...p });

  // Target components come from the SCHEMA (not just sheets-with-rows) so a
  // temporal target whose series sheet isn't in the thin client still appears.
  // Prefer components that actually have rows by listing them first.
  const targetOptions = useMemo(() => {
    const withRows = new Set(sheetsWithRows);
    return PYPSA_COMPONENTS
      .filter((c) => c.sheet_name !== 'snapshots')
      .map((c) => ({
        value: c.sheet_name,
        label: `${c.component_name} (${c.sheet_name})${withRows.has(c.sheet_name) ? '' : ' · empty'}`,
        has: withRows.has(c.sheet_name),
      }))
      .sort((a, b) => Number(b.has) - Number(a.has))
      .map(({ value, label }) => ({ value, label }));
  }, [sheetsWithRows]);

  const targetComp = useMemo(() => getComponentSchema(spec.target), [spec.target]);
  const attrOptions = useMemo(() => editableAttrs(targetComp), [targetComp]);

  // Static / temporal capability of the chosen attribute (from its schema storage).
  const storage = useMemo(
    () => targetComp?.attributes.find((a) => a.attribute === spec.attribute)?.storage,
    [targetComp, spec.attribute],
  );
  const canStatic = storage === 'static' || storage === 'static_or_series';
  const canTemporal = storage === 'series' || storage === 'static_or_series';
  const both = canStatic && canTemporal;
  const temporal = both ? spec.temporalPref : canTemporal;

  // Numeric static attributes usable as a derive source.
  const deriveSources = useMemo(
    () => (targetComp ? targetComp.input_static_attributes : []),
    [targetComp],
  );

  // Derive isn't supported for temporal targets (backend rejects it) — fall back.
  const effectiveOp: EditOp = temporal && spec.op === 'derive' ? 'set' : spec.op;

  const setFilter = (id: string, p: Partial<QueryFilterState>) =>
    patch({ filters: spec.filters.map((f) => (f.id === id ? { ...f, ...p } : f)) });
  const addFilter = () =>
    patch({
      filters: [
        ...spec.filters,
        { id: newId(), join: false, joinComponent: '', refColumn: 'bus', column: '', op: 'eq', value: '' },
      ],
    });
  const removeFilter = (id: string) => patch({ filters: spec.filters.filter((f) => f.id !== id) });

  const request = (): QueryEditRequest =>
    buildRequest({
      target: spec.target,
      attribute: spec.attribute,
      temporal,
      filters: spec.filters,
      op: effectiveOp,
      amount: spec.amount,
      derive: spec.derive,
    });

  const ready = !!spec.target && !!spec.attribute
    && (effectiveOp !== 'derive' || !!spec.derive.source_attr);

  const runPreview = async () => {
    setBusy(true); setError(null);
    try {
      setPreview(await onPreview(request()));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Preview failed.');
      setPreview(null);
    } finally { setBusy(false); }
  };

  const runApply = async () => {
    setBusy(true); setError(null);
    try {
      const r = await onApply(request());
      const where = r.temporal ? r.seriesSheet : r.sheet;
      onStatus(`Query applied: ${r.changed} ${r.temporal ? 'series column' : 'cell'}${r.changed === 1 ? '' : 's'} changed in ${where} (${r.matched} matched).`);
      setPreview(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Apply failed.');
    } finally { setBusy(false); }
  };

  return (
    <section className="forge-section">
      <header className="forge-section-header">
        <h3>Query &amp; edit</h3>
        <p>
          Select a component and attribute, filter rows (on the component itself
          or a linked one — e.g. filter <code>buses</code> by <code>province</code>,
          edit the <code>generators</code> on those buses), then set / add / multiply,
          or derive a value from another attribute. Works on static and temporal
          data. Preview runs server-side before you apply.
        </p>
      </header>

      {/* Target + attribute */}
      <div className="sg-setting-row">
        <label className="sg-setting-label">Component</label>
        <SearchableSelect
          className="forge-adjust-select"
          value={spec.target}
          placeholder="component"
          options={targetOptions}
          onChange={(v) => { patch({ target: v, attribute: '', filters: [], derive: { ...spec.derive, source_attr: '' } }); setPreview(null); }}
        />
      </div>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Attribute</label>
        <SearchableSelect
          className="forge-adjust-select"
          value={spec.attribute}
          placeholder="attribute"
          disabled={!spec.target}
          options={attrOptions.map((a) => ({ value: a, label: a }))}
          onChange={(v) => { patch({ attribute: v }); setPreview(null); }}
        />
        {both && (
          <div className="sg-btn-row" style={{ marginLeft: 8 }}>
            <button className={`tb-btn sg-solver-btn${!temporal ? '' : ' tb-btn--muted'}`} onClick={() => patch({ temporalPref: false })}>Static</button>
            <button className={`tb-btn sg-solver-btn${temporal ? '' : ' tb-btn--muted'}`} onClick={() => patch({ temporalPref: true })}>Temporal</button>
          </div>
        )}
        {spec.attribute && (
          <span className="sg-setting-hint" style={{ marginLeft: 8 }}>
            {temporal ? 'temporal (per-snapshot series)' : 'static (single value)'}
          </span>
        )}
      </div>

      {/* Filters */}
      <div className="sg-setting-row" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
        <label className="sg-setting-label">Filters</label>
        {spec.filters.length === 0 && <p className="sg-setting-hint">No filters — the edit applies to every row. Add one to narrow it.</p>}
        {spec.filters.map((f, i) => (
          <FilterRow
            key={f.id}
            index={i}
            filter={f}
            target={spec.target}
            targetComp={targetComp}
            onChange={(p) => { setFilter(f.id, p); setPreview(null); }}
            onRemove={() => { removeFilter(f.id); setPreview(null); }}
          />
        ))}
        <div>
          <button className="tb-btn tb-btn--muted" onClick={addFilter} disabled={!spec.target}>+ Add filter</button>
        </div>
      </div>

      {/* Edit */}
      <div className="sg-setting-row">
        <label className="sg-setting-label">Edit</label>
        <SearchableSelect
          className="forge-adjust-select forge-adjust-action"
          value={effectiveOp}
          options={EDIT_OPS.filter((o) => o.value !== 'derive' || !temporal)}
          onChange={(v) => { patch({ op: v as EditOp, amount: v === 'multiply' ? '100' : '0' }); setPreview(null); }}
        />
        {effectiveOp === 'derive' ? (
          <div className="sg-btn-row" style={{ gap: 6, alignItems: 'center' }}>
            <NumberDraftInput className="forge-number forge-adjust-amount" value={spec.derive.coefficient} onCommit={(v) => { patch({ derive: { ...spec.derive, coefficient: v } }); setPreview(null); }} />
            <span className="forge-adjust-hint">×</span>
            <SearchableSelect
              className="forge-adjust-select"
              value={spec.derive.source_attr}
              placeholder="source attr"
              options={deriveSources.map((a) => ({ value: a, label: a }))}
              onChange={(v) => { patch({ derive: { ...spec.derive, source_attr: v } }); setPreview(null); }}
            />
            <span className="forge-adjust-hint">+</span>
            <NumberDraftInput className="forge-number forge-adjust-amount" value={spec.derive.constant} onCommit={(v) => { patch({ derive: { ...spec.derive, constant: v } }); setPreview(null); }} />
          </div>
        ) : (
          <>
            <NumberDraftInput
              className="forge-number forge-adjust-amount"
              value={Number.isFinite(Number(spec.amount)) ? Number(spec.amount) : 0}
              onCommit={(v) => { patch({ amount: String(v) }); setPreview(null); }}
            />
            {effectiveOp === 'multiply' && <span className="forge-adjust-hint">%</span>}
          </>
        )}
      </div>

      {/* Actions */}
      <div className="forge-actions">
        <button className="tb-btn" onClick={runPreview} disabled={!ready || busy}>{busy ? 'Working…' : 'Preview'}</button>
        <button className="run-button" onClick={runApply} disabled={!ready || busy}>Apply</button>
      </div>

      {error && <p className="forge-status" style={{ color: 'var(--danger, #dc2626)' }}>{error}</p>}

      {preview && (
        <div className="forge-report">
          <p className="forge-report-line">
            <b>{preview.matched}</b> of {preview.targetTotal} {spec.target} match
            {preview.temporal && preview.seriesColumnsPresent != null && (
              <> · <b>{preview.seriesColumnsPresent}</b> have a column in <code>{preview.seriesSheet}</code></>
            )}
          </p>
          {preview.warnings.map((w, i) => <p key={i} className="forge-status" style={{ color: 'var(--warn, #b45309)' }}>{w}</p>)}
          {preview.sample.length > 0 && (
            <table className="forge-preview-table" style={{ width: '100%', fontSize: 12 }}>
              <thead><tr><th style={{ textAlign: 'left' }}>name</th><th style={{ textAlign: 'right' }}>before</th><th style={{ textAlign: 'right' }}>after</th></tr></thead>
              <tbody>
                {preview.sample.map((s) => (
                  <tr key={s.name}>
                    <td>{s.name}</td>
                    <td style={{ textAlign: 'right' }}>{fmt(s.before)}</td>
                    <td style={{ textAlign: 'right' }}>{fmt(s.after)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </section>
  );
}

function fmt(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  return Number.isFinite(n) ? String(Math.round(n * 1000) / 1000) : String(v);
}

// ── one filter row ──────────────────────────────────────────────────────────────

function FilterRow({
  index, filter, target, targetComp, onChange, onRemove,
}: {
  index: number;
  filter: QueryFilterState;
  target: string;
  targetComp: PypsaComponentSchema | null;
  onChange: (p: Partial<QueryFilterState>) => void;
  onRemove: () => void;
}) {
  // The sheet the filter's column lives on: the linked component when joining,
  // else the target. Determines the schema columns + distinct-value lookups.
  const filterSheet = filter.join ? filter.joinComponent : target;
  const filterComp = useMemo(() => getComponentSchema(filterSheet), [filterSheet]);
  const columns = useMemo(() => filterColumns(filterComp), [filterComp]);

  // Bus-reference columns present on the TARGET, for the join's ref column.
  const refCols = useMemo(() => {
    const attrs = new Set([...(targetComp?.input_attributes ?? []), ...(targetComp?.static_attributes ?? [])]);
    const present = BUS_REFS.filter((b) => attrs.has(b));
    return present.length ? present : BUS_REFS;
  }, [targetComp]);

  const componentOptions = useMemo(
    () => PYPSA_COMPONENTS.filter((c) => c.sheet_name !== 'snapshots').map((c) => ({ value: c.sheet_name, label: c.sheet_name })),
    [],
  );

  // Distinct values for the value dropdown (equality ops on a real sheet+column).
  const [distinct, setDistinct] = useState<string[]>([]);
  useEffect(() => {
    let live = true;
    if (!filterSheet || !filter.column || !EQUALITY_OPS.includes(filter.op)) { setDistinct([]); return; }
    getSheetDistinct(filterSheet, filter.column).then((v) => { if (live) setDistinct(v); }).catch(() => { if (live) setDistinct([]); });
    return () => { live = false; };
  }, [filterSheet, filter.column, filter.op]);

  const showValueDropdown = EQUALITY_OPS.includes(filter.op) && distinct.length > 0;

  return (
    <div className="forge-adjust-card">
      <div className="forge-adjust-row forge-adjust-filter" style={{ flexWrap: 'wrap', gap: 6 }}>
        <span className="forge-adjust-and">{index === 0 ? 'where' : 'and'}</span>
        <label className="forge-check" title="Evaluate this filter on a linked component and match through a reference column">
          <input type="checkbox" checked={filter.join} onChange={(e) => onChange({ join: e.target.checked })} /> linked
        </label>
        {filter.join && (
          <>
            <SearchableSelect
              className="forge-adjust-select"
              value={filter.joinComponent}
              placeholder="linked component"
              options={componentOptions}
              onChange={(v) => onChange({ joinComponent: v, column: '' })}
            />
            <span className="forge-adjust-hint">via</span>
            <SearchableSelect
              className="forge-adjust-select"
              value={filter.refColumn}
              placeholder="ref column"
              options={refCols.map((c) => ({ value: c, label: c }))}
              onChange={(v) => onChange({ refColumn: v })}
            />
            <span className="forge-adjust-hint">where</span>
          </>
        )}
        <SearchableSelect
          className="forge-adjust-select"
          value={filter.column}
          placeholder="column"
          options={columns}
          onChange={(v) => onChange({ column: v, value: '' })}
        />
        <SearchableSelect
          className="forge-adjust-select forge-adjust-action"
          value={filter.op}
          options={FILTER_OPS}
          onChange={(v) => onChange({ op: v as FilterOp, value: '' })}
        />
        {showValueDropdown ? (
          <SearchableSelect
            className="forge-adjust-select"
            value={filter.value}
            placeholder="value"
            options={distinct}
            onChange={(v) => onChange({ value: v })}
          />
        ) : (
          <input
            className="forge-number"
            type={NUMERIC_OPS.includes(filter.op) ? 'number' : 'text'}
            value={filter.value}
            placeholder={filter.op === 'in' ? 'a, b, c' : 'value'}
            onChange={(e) => onChange({ value: e.target.value })}
          />
        )}
        <button type="button" className="forge-adjust-remove" onClick={onRemove} aria-label="Remove filter">×</button>
      </div>
    </div>
  );
}
