/**
 * Forge — bulk value adjustment.
 *
 * Each adjustment: pick a component (sheet), narrow rows with one or more
 * equality filters (column + value, ANDed), pick a numeric attribute, and
 * rescale it (multiply by %, add a delta, or set absolute). Multiple
 * adjustments stack and apply together. All dropdowns are searchable.
 */
import React, { useMemo } from 'react';
import type { GridRow, WorkbookModel } from 'lib/types';
import { usePersistedState } from 'shared/hooks/usePersistedState';
import { SearchableSelect } from 'shared/components/SearchableSelect';
import { numericColumns } from 'lib/forge/transforms';
import {
  Adjustment,
  AdjustAction,
  AdjustFilter,
  applyAdjustments,
  columnsOf,
  matchCount,
  uniqueValues,
} from 'lib/forge/adjust';

interface Props {
  model: WorkbookModel;
  sheetsWithRows: string[];
  onApplySheets: (partial: Record<string, GridRow[]>) => void;
  onStatus: (msg: string) => void;
}

const ACTIONS: Array<{ value: AdjustAction; label: string }> = [
  { value: 'multiply', label: 'Multiply (current × %)' },
  { value: 'add', label: 'Add (current + value)' },
  { value: 'set', label: 'Set (= value)' },
];

const amountHint = (action: AdjustAction): string =>
  action === 'multiply' ? '% (100 = unchanged)' : action === 'add' ? 'amount to add' : 'new value';

let counter = 0;
const newId = (): string => `adj_${(counter += 1)}_${counter}`;

const rowsOf = (model: WorkbookModel, sheet: string): GridRow[] => model[sheet] ?? [];

function blankAdjustment(sheet: string): Adjustment {
  return { id: newId(), sheet, filters: [], attribute: '', action: 'multiply', amount: 100 };
}

export function AdjustPanel({ model, sheetsWithRows, onApplySheets, onStatus }: Props) {
  const [adjustments, setAdjustments] = usePersistedState<Adjustment[]>('ui:forge-adjustments', []);

  // usePersistedState's setter takes a value (no functional updater), so each
  // mutator derives the next array from the current `adjustments`.
  const update = (id: string, patch: Partial<Adjustment>) =>
    setAdjustments(adjustments.map((a) => (a.id === id ? { ...a, ...patch } : a)));

  const addAdjustment = () =>
    setAdjustments([...adjustments, blankAdjustment(sheetsWithRows[0] ?? '')]);

  const removeAdjustment = (id: string) =>
    setAdjustments(adjustments.filter((a) => a.id !== id));

  const mapFilters = (id: string, fn: (filters: AdjustFilter[]) => AdjustFilter[]) =>
    setAdjustments(adjustments.map((a) => (a.id === id ? { ...a, filters: fn(a.filters) } : a)));

  const addFilter = (id: string) =>
    mapFilters(id, (filters) => [...filters, { column: '', value: '' }]);

  const setFilter = (id: string, idx: number, patch: Partial<AdjustFilter>) =>
    mapFilters(id, (filters) => filters.map((f, i) => (i === idx ? { ...f, ...patch } : f)));

  const removeFilter = (id: string, idx: number) =>
    mapFilters(id, (filters) => filters.filter((_, i) => i !== idx));

  const apply = () => {
    const ready = adjustments.filter((a) => a.sheet && a.attribute);
    if (ready.length === 0) {
      onStatus('Add at least one adjustment with a component and an attribute.');
      return;
    }
    const result = applyAdjustments(model, ready);
    if (result.changed === 0) {
      onStatus('No rows matched — nothing changed. Check the filters.');
      return;
    }
    onApplySheets(result.sheets);
    const sheetCount = Object.keys(result.sheets).length;
    onStatus(`Adjusted ${result.changed} cell${result.changed === 1 ? '' : 's'} across ${sheetCount} sheet${sheetCount === 1 ? '' : 's'}.`);
  };

  return (
    <section className="forge-section">
      <header className="forge-section-header">
        <h3>Adjust values</h3>
        <p>
          Rescale a numeric attribute for a filtered subset of components — e.g. multiply
          generators where carrier = gas and province = 경상남도 by 80%. Stack several
          adjustments, then Apply.
        </p>
      </header>

      {adjustments.length === 0 && (
        <p className="sg-setting-hint">No adjustments yet — add one to start.</p>
      )}

      {adjustments.map((adj) => (
        <AdjustmentCard
          key={adj.id}
          adj={adj}
          model={model}
          sheetsWithRows={sheetsWithRows}
          onChange={(patch) => update(adj.id, patch)}
          onAddFilter={() => addFilter(adj.id)}
          onSetFilter={(idx, patch) => setFilter(adj.id, idx, patch)}
          onRemoveFilter={(idx) => removeFilter(adj.id, idx)}
          onRemove={() => removeAdjustment(adj.id)}
        />
      ))}

      <div className="forge-adjust-actions">
        <button type="button" className="tb-btn" onClick={addAdjustment} disabled={sheetsWithRows.length === 0}>
          + Add adjustment
        </button>
        <button type="button" className="primary-button" onClick={apply} disabled={adjustments.length === 0}>
          Apply {adjustments.length || ''} adjustment{adjustments.length === 1 ? '' : 's'}
        </button>
      </div>
    </section>
  );
}

// ── Single adjustment card ─────────────────────────────────────────────────

function AdjustmentCard({
  adj, model, sheetsWithRows, onChange, onAddFilter, onSetFilter, onRemoveFilter, onRemove,
}: {
  adj: Adjustment;
  model: WorkbookModel;
  sheetsWithRows: string[];
  onChange: (patch: Partial<Adjustment>) => void;
  onAddFilter: () => void;
  onSetFilter: (idx: number, patch: Partial<{ column: string; value: string }>) => void;
  onRemoveFilter: (idx: number) => void;
  onRemove: () => void;
}) {
  const rows = useMemo(() => rowsOf(model, adj.sheet), [model, adj.sheet]);
  const columns = useMemo(() => columnsOf(rows), [rows]);
  const numCols = useMemo(() => numericColumns(rows), [rows]);
  const matches = useMemo(() => matchCount(model, adj.sheet, adj.filters), [model, adj.sheet, adj.filters]);

  return (
    <div className="forge-adjust-card">
      <div className="forge-adjust-row">
        <label className="sg-setting-label">Component</label>
        <SearchableSelect
          className="forge-adjust-select"
          value={adj.sheet}
          options={sheetsWithRows.map((s) => ({ value: s, label: `${s} (${rowsOf(model, s).length})` }))}
          onChange={(v) => onChange({ sheet: v, filters: [], attribute: '' })}
        />
        <button type="button" className="forge-adjust-remove" onClick={onRemove} aria-label="Remove adjustment">×</button>
      </div>

      {/* Filters (AND) */}
      {adj.filters.map((f, idx) => (
        <div className="forge-adjust-row forge-adjust-filter" key={idx}>
          <span className="forge-adjust-and">{idx === 0 ? 'where' : 'and'}</span>
          <SearchableSelect
            className="forge-adjust-select"
            value={f.column}
            placeholder="column"
            options={columns.map((c) => ({ value: c, label: c }))}
            onChange={(v) => onSetFilter(idx, { column: v, value: '' })}
          />
          <span className="forge-adjust-eq">=</span>
          <SearchableSelect
            className="forge-adjust-select"
            value={f.value}
            placeholder="value"
            disabled={!f.column}
            options={uniqueValues(rows, f.column).map((v) => ({ value: v, label: v }))}
            onChange={(v) => onSetFilter(idx, { value: v })}
          />
          <button type="button" className="forge-adjust-remove" onClick={() => onRemoveFilter(idx)} aria-label="Remove filter">×</button>
        </div>
      ))}

      <div className="forge-adjust-row">
        <button type="button" className="tb-btn tb-btn--muted forge-adjust-addfilter" onClick={onAddFilter} disabled={!adj.sheet}>
          + Add filter
        </button>
        <span className="forge-adjust-match">{matches} row{matches === 1 ? '' : 's'} match</span>
      </div>

      {/* Attribute + action + amount */}
      <div className="forge-adjust-row">
        <label className="sg-setting-label">Attribute</label>
        <SearchableSelect
          className="forge-adjust-select"
          value={adj.attribute}
          placeholder="numeric attribute"
          options={numCols.map((c) => ({ value: c, label: c }))}
          onChange={(v) => onChange({ attribute: v })}
        />
      </div>
      <div className="forge-adjust-row">
        <label className="sg-setting-label">Action</label>
        <SearchableSelect
          className="forge-adjust-select"
          value={adj.action}
          options={ACTIONS}
          onChange={(v) => onChange({ action: v as AdjustAction, amount: v === 'multiply' ? 100 : 0 })}
        />
        <input
          type="number"
          className="forge-number"
          value={Number.isFinite(adj.amount) ? adj.amount : 0}
          onChange={(e) => onChange({ amount: Number(e.target.value) })}
        />
        <span className="forge-adjust-hint">{amountHint(adj.action)}</span>
      </div>
    </div>
  );
}
