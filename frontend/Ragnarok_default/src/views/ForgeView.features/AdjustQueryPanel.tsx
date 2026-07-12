/**
 * Forge — Adjust values (the merged Adjust + Query & Edit tool).
 *
 * Pick a component + attribute (static or temporal), narrow rows with ANDed
 * filters, and edit. The filter column dropdown lists the component's own
 * columns AND the columns of its linked bus(es) — `province (via bus)` — so
 * filtering loads by a user-defined bus column needs no join wiring; the
 * one-hop join is built silently. Values are a multi-select of the column's
 * distinct values (union within a filter, AND across filters).
 *
 * Static edits: set / add / multiply / derive. Temporal edits are series
 * transforms: multiply, set (constant MW), and add with explicit semantics —
 * MW at every snapshot or MWh over the period, applied to each matched load
 * or divided across them (equally / proportionally to current demand).
 * Preview runs a server-side dry run; temporal previews report period energy
 * (MWh) before → after per load plus the group total. Apply writes through
 * the session.
 */
import React, { useEffect, useMemo, useState } from 'react';
import type { GridRow, WorkbookModel } from 'lib/types';
import { usePersistedState } from 'shared/hooks/usePersistedState';
import { SearchableSelect } from 'shared/components/SearchableSelect';
import { SearchableMultiSelect } from 'shared/components/SearchableMultiSelect';
import { NumberDraftInput } from 'shared/components/NumberDraftInput';
import {
  getComponentSchema,
  PYPSA_COMPONENTS,
  PypsaComponentSchema,
} from 'lib/constants/pypsa_schema';
import { getSheetDistinct } from 'lib/api/session';
import {
  AddScope,
  AddSplit,
  AddUnit,
  buildRequest,
  DeriveState,
  EditOp,
  MULTI_OPS,
  NUMERIC_OPS,
  PANEL_FILTER_OPS,
  PanelFilterOp,
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

const STATIC_EDIT_OPS: Array<{ value: EditOp; label: string }> = [
  { value: 'set', label: 'Set (=)' },
  { value: 'add', label: 'Add (+)' },
  { value: 'multiply', label: 'Multiply (×%)' },
  { value: 'derive', label: 'Derive (coef × attr + const)' },
];

const TEMPORAL_EDIT_OPS: Array<{ value: EditOp; label: string }> = [
  { value: 'multiply', label: 'Multiply (×%)' },
  { value: 'add', label: 'Add' },
  { value: 'set', label: 'Set constant (MW)' },
];

const ADD_UNITS: Array<{ value: AddUnit; label: string }> = [
  { value: 'mw', label: 'MW at every snapshot' },
  { value: 'mwh', label: 'MWh over the period' },
];

const ADD_SCOPES: Array<{ value: AddScope; label: string }> = [
  { value: 'each', label: 'to each matched load' },
  { value: 'total', label: 'in total, divided across matches' },
];

const ADD_SPLITS: Array<{ value: AddSplit; label: string }> = [
  { value: 'proportional', label: 'proportionally to current demand' },
  { value: 'equal', label: 'equally' },
];

const BUS_REFS = ['bus', 'bus0', 'bus1', 'bus2', 'bus3', 'bus4'];
/** Encodes a linked-bus filter column option; own columns are the bare name. */
const VIA_SEP = '::';

let counter = 0;
const newId = (): string => `qf_${(counter += 1)}`;

const rowsOf = (model: WorkbookModel, sheet: string): GridRow[] => model[sheet] ?? [];

/** Columns actually present on the sheet's rows (data-aware — includes
 *  user-defined columns like `province` that no schema knows about). */
function dataColumns(rows: GridRow[]): string[] {
  const cols = new Set<string>();
  for (const r of rows.slice(0, 200)) Object.keys(r).forEach((c) => cols.add(c));
  return Array.from(cols);
}

/** Attribute names that can be edited on a component (input, static or temporal). */
function editableAttrs(comp: PypsaComponentSchema | null): string[] {
  if (!comp) return [];
  return Array.from(new Set([...comp.input_static_attributes, ...comp.input_temporal_attributes]));
}

interface Spec {
  target: string;
  attribute: string;
  temporalPref: boolean;
  filters: QueryFilterState[];
  op: EditOp;
  amount: string;
  unit: AddUnit;
  scope: AddScope;
  split: AddSplit;
  derive: DeriveState;
}

const BLANK_SPEC: Spec = {
  target: '',
  attribute: '',
  temporalPref: false,
  filters: [],
  op: 'multiply',
  amount: '100',
  unit: 'mw',
  scope: 'each',
  split: 'proportional',
  derive: { source_attr: '', coefficient: 1, constant: 0 },
};

export function AdjustQueryPanel({ model, sheetsWithRows, onPreview, onApply, onStatus }: Props) {
  const [spec, setSpec] = usePersistedState<Spec>('ui:forge-adjust-query', BLANK_SPEC);
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
  const seriesSheet = spec.target && spec.attribute ? `${spec.target}-${spec.attribute}` : '';
  const seriesVisible = !!seriesSheet && sheetsWithRows.includes(seriesSheet);

  // Filter column options: the target's own columns (schema + actual data,
  // covering user-defined ones), then each linked bus's columns as
  // `col (via bus)` — picking one silently builds the one-hop join.
  const filterColumnOptions = useMemo(() => {
    const own = new Set<string>(['name']);
    (targetComp?.input_attributes ?? []).forEach((a) => own.add(a));
    (targetComp?.static_attributes ?? []).forEach((a) => own.add(a));
    dataColumns(rowsOf(model, spec.target)).forEach((c) => own.add(c));
    const options = Array.from(own).map((c) => ({ value: c, label: c }));
    const refsPresent = BUS_REFS.filter((r) => own.has(r));
    const busCols = dataColumns(rowsOf(model, 'buses'));
    for (const ref of refsPresent) {
      for (const col of busCols) {
        options.push({ value: `${ref}${VIA_SEP}${col}`, label: `${col} (via ${ref})` });
      }
    }
    return options;
  }, [targetComp, model, spec.target]);

  // Numeric static attributes usable as a derive source.
  const deriveSources = useMemo(
    () => (targetComp ? targetComp.input_static_attributes : []),
    [targetComp],
  );

  // The op list forks on static vs temporal; keep the selection valid across
  // the switch (temporal has no derive; both share set/add/multiply).
  const opChoices = temporal ? TEMPORAL_EDIT_OPS : STATIC_EDIT_OPS;
  const effectiveOp: EditOp = opChoices.some((o) => o.value === spec.op) ? spec.op : 'multiply';

  const setFilter = (id: string, p: Partial<QueryFilterState>) =>
    patch({ filters: spec.filters.map((f) => (f.id === id ? { ...f, ...p } : f)) });
  const addFilter = () =>
    patch({
      filters: [
        ...spec.filters,
        { id: newId(), via: '', column: '', op: 'any', values: [], text: '' },
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
      unit: spec.unit,
      scope: spec.scope,
      split: spec.split,
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
      onStatus(`Adjusted ${r.changed} ${r.temporal ? 'series column' : 'cell'}${r.changed === 1 ? '' : 's'} in ${where} (${r.matched} matched).`);
      setPreview(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Apply failed.');
    } finally { setBusy(false); }
  };

  const energySample = preview?.sampleKind === 'energyMwh';

  return (
    <section className="forge-section">
      <header className="forge-section-header">
        <h3>Adjust values</h3>
        <p>
          Pick a component and attribute, narrow the rows with filters — a
          filter column can live on the component itself or on its bus
          (<code>province (via bus)</code>), matching <em>any</em> of the
          selected values — then edit. Temporal attributes are adjusted as
          series: multiply, set a constant, or add MW / MWh to each matched
          load or divided across them. Preview runs server-side before you
          apply.
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
          onChange={(v) => {
            // Default to the temporal side when the series sheet is visibly
            // populated (e.g. loads_t-p_set exists) — the common intent.
            const series = `${spec.target}-${v}`;
            patch({ attribute: v, temporalPref: sheetsWithRows.includes(series) });
            setPreview(null);
          }}
        />
        {both && (
          <div className="sg-btn-row" style={{ marginLeft: 8 }}>
            <button className={`tb-btn sg-solver-btn${!temporal ? '' : ' tb-btn--muted'}`} onClick={() => patch({ temporalPref: false })}>Static</button>
            <button className={`tb-btn sg-solver-btn${temporal ? '' : ' tb-btn--muted'}`} onClick={() => patch({ temporalPref: true })}>Temporal</button>
          </div>
        )}
        {spec.attribute && (
          <span className="sg-setting-hint" style={{ marginLeft: 8 }}>
            {temporal
              ? `temporal (per-snapshot series${seriesVisible ? `, ${seriesSheet} present` : ''})`
              : 'static (single value)'}
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
            columnOptions={filterColumnOptions}
            onChange={(p) => { setFilter(f.id, p); setPreview(null); }}
            onRemove={() => { removeFilter(f.id); setPreview(null); }}
          />
        ))}
        <div>
          <button className="tb-btn tb-btn--muted" onClick={addFilter} disabled={!spec.target}>+ Add filter</button>
        </div>
      </div>

      {/* Edit */}
      <div className="sg-setting-row" style={{ flexWrap: 'wrap' }}>
        <label className="sg-setting-label">Edit</label>
        <SearchableSelect
          className="forge-adjust-select forge-adjust-action"
          value={effectiveOp}
          options={opChoices}
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
            {temporal && effectiveOp === 'set' && <span className="forge-adjust-hint">MW at every snapshot</span>}
            {temporal && effectiveOp === 'add' && (
              <>
                <SearchableSelect
                  className="forge-adjust-select"
                  value={spec.unit}
                  options={ADD_UNITS}
                  onChange={(v) => { patch({ unit: v as AddUnit }); setPreview(null); }}
                />
                <SearchableSelect
                  className="forge-adjust-select"
                  value={spec.scope}
                  options={ADD_SCOPES}
                  onChange={(v) => { patch({ scope: v as AddScope }); setPreview(null); }}
                />
                {spec.scope === 'total' && (
                  <SearchableSelect
                    className="forge-adjust-select"
                    value={spec.split}
                    options={ADD_SPLITS}
                    onChange={(v) => { patch({ split: v as AddSplit }); setPreview(null); }}
                  />
                )}
              </>
            )}
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
            {energySample && preview.energyBeforeMwh != null && preview.energyAfterMwh != null && (
              <> · total <b>{fmt(preview.energyBeforeMwh)}</b> → <b>{fmt(preview.energyAfterMwh)}</b> MWh</>
            )}
          </p>
          {preview.warnings.map((w, i) => <p key={i} className="forge-status" style={{ color: 'var(--warn, #b45309)' }}>{w}</p>)}
          {preview.sample.length > 0 && (
            <table className="forge-preview-table" style={{ width: '100%', fontSize: 12 }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left' }}>name</th>
                  <th style={{ textAlign: 'right' }}>{energySample ? 'MWh before' : 'before'}</th>
                  <th style={{ textAlign: 'right' }}>{energySample ? 'MWh after' : 'after'}</th>
                </tr>
              </thead>
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
  index, filter, target, columnOptions, onChange, onRemove,
}: {
  index: number;
  filter: QueryFilterState;
  target: string;
  columnOptions: Array<{ value: string; label: string }>;
  onChange: (p: Partial<QueryFilterState>) => void;
  onRemove: () => void;
}) {
  // The sheet the filter's column lives on: buses when linked, else the target.
  const filterSheet = filter.via ? 'buses' : target;

  // Distinct values for the multi-select (server-side DISTINCT, on demand).
  const [distinct, setDistinct] = useState<string[]>([]);
  const wantsValues = MULTI_OPS.includes(filter.op);
  useEffect(() => {
    let live = true;
    if (!filterSheet || !filter.column || !wantsValues) { setDistinct([]); return; }
    getSheetDistinct(filterSheet, filter.column).then((v) => { if (live) setDistinct(v); }).catch(() => { if (live) setDistinct([]); });
    return () => { live = false; };
  }, [filterSheet, filter.column, wantsValues]);

  const encoded = filter.via ? `${filter.via}${VIA_SEP}${filter.column}` : filter.column;

  return (
    <div className="forge-adjust-card">
      <div className="forge-adjust-row forge-adjust-filter" style={{ flexWrap: 'wrap', gap: 6 }}>
        <span className="forge-adjust-and">{index === 0 ? 'where' : 'and'}</span>
        <SearchableSelect
          className="forge-adjust-select"
          value={encoded}
          placeholder="column"
          options={columnOptions}
          onChange={(v) => {
            const sep = v.indexOf(VIA_SEP);
            const via = sep > 0 ? v.slice(0, sep) : '';
            const column = sep > 0 ? v.slice(sep + VIA_SEP.length) : v;
            onChange({ via, column, values: [], text: '' });
          }}
        />
        <SearchableSelect
          className="forge-adjust-select forge-adjust-action"
          value={filter.op}
          options={PANEL_FILTER_OPS}
          onChange={(v) => onChange({ op: v as PanelFilterOp, values: [], text: '' })}
        />
        {wantsValues ? (
          <SearchableMultiSelect
            className="forge-adjust-select"
            values={filter.values}
            placeholder="values"
            options={distinct}
            onChange={(values) => onChange({ values })}
          />
        ) : (
          <input
            className="forge-number"
            type={NUMERIC_OPS.includes(filter.op) ? 'number' : 'text'}
            value={filter.text}
            placeholder="value"
            onChange={(e) => onChange({ text: e.target.value })}
          />
        )}
        <button type="button" className="forge-adjust-remove" onClick={onRemove} aria-label="Remove filter">×</button>
      </div>
    </div>
  );
}
