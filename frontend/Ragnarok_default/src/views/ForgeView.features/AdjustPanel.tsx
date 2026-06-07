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
  Baseline,
  columnsOf,
  matchCount,
  revertAdjustments,
  uniqueValues,
} from 'lib/forge/adjust';

interface Props {
  model: WorkbookModel;
  sheetsWithRows: string[];
  onApplySheets: (partial: Record<string, GridRow[]>) => void;
  onStatus: (msg: string) => void;
}

const ACTIONS: Array<{ value: AdjustAction; label: string }> = [
  { value: 'multiply', label: 'Multiply (×%)' },
  { value: 'add', label: 'Add (+)' },
  { value: 'set', label: 'Set (=)' },
];

let counter = 0;
const newId = (): string => `adj_${(counter += 1)}_${counter}`;

const rowsOf = (model: WorkbookModel, sheet: string): GridRow[] => model[sheet] ?? [];

function blankAdjustment(sheet: string): Adjustment {
  return { id: newId(), enabled: true, sheet, filters: [], attribute: '', action: 'multiply', amount: 100 };
}

export function AdjustPanel({ model, sheetsWithRows, onApplySheets, onStatus }: Props) {
  const [adjustments, setAdjustments] = usePersistedState<Adjustment[]>('ui:forge-adjustments', []);
  // Original (pre-adjustment) cell values, so Revert restores the original, not
  // the previous step. Persisted alongside the cards so it survives tab switches.
  const [baseline, setBaseline] = usePersistedState<Baseline>('ui:forge-adjust-baseline', {});

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

  // Cards selected (checkbox on) and fully specified.
  const selected = adjustments.filter((a) => a.enabled !== false && a.sheet && a.attribute);

  const apply = () => {
    if (selected.length === 0) {
      onStatus('Select at least one adjustment (with a component and an attribute) to apply.');
      return;
    }
    const result = applyAdjustments(model, selected, baseline);
    if (result.changed === 0) {
      onStatus('No rows matched — nothing changed. Check the filters.');
      return;
    }
    onApplySheets(result.sheets);
    setBaseline(result.baseline);
    const sheetCount = Object.keys(result.sheets).length;
    onStatus(`Adjusted ${result.changed} cell${result.changed === 1 ? '' : 's'} across ${sheetCount} sheet${sheetCount === 1 ? '' : 's'}.`);
  };

  const revert = () => {
    if (selected.length === 0) {
      onStatus('Select at least one adjustment to revert.');
      return;
    }
    const result = revertAdjustments(model, selected, baseline);
    if (result.reverted === 0) {
      onStatus('Nothing to revert — these cells are already at their original values.');
      return;
    }
    onApplySheets(result.sheets);
    onStatus(`Reverted ${result.reverted} cell${result.reverted === 1 ? '' : 's'} to their original value${result.reverted === 1 ? '' : 's'}.`);
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
        <button type="button" className="primary-button" onClick={apply} disabled={selected.length === 0}>
          Apply selected{selected.length ? ` (${selected.length})` : ''}
        </button>
        <button type="button" className="tb-btn" onClick={revert} disabled={selected.length === 0} title="Restore the selected adjustments' cells to their original values.">
          Revert selected
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
    <div className={`forge-adjust-card${adj.enabled === false ? ' is-off' : ''}`}>
      {/* Spec — component · attribute · action · value, all on one line */}
      <div className="forge-adjust-row forge-adjust-spec">
        <input
          type="checkbox"
          className="forge-adjust-check"
          checked={adj.enabled !== false}
          onChange={(e) => onChange({ enabled: e.target.checked })}
          title="Include this adjustment when applying / reverting"
        />
        <SearchableSelect
          className="forge-adjust-select"
          value={adj.sheet}
          placeholder="component"
          options={sheetsWithRows.map((s) => ({ value: s, label: `${s} (${rowsOf(model, s).length})` }))}
          onChange={(v) => onChange({ sheet: v, filters: [], attribute: '' })}
        />
        <SearchableSelect
          className="forge-adjust-select"
          value={adj.attribute}
          placeholder="attribute"
          options={numCols.map((c) => ({ value: c, label: c }))}
          onChange={(v) => onChange({ attribute: v })}
        />
        <SearchableSelect
          className="forge-adjust-select forge-adjust-action"
          value={adj.action}
          options={ACTIONS}
          onChange={(v) => onChange({ action: v as AdjustAction, amount: v === 'multiply' ? 100 : 0 })}
        />
        <input
          type="number"
          className="forge-number forge-adjust-amount"
          value={Number.isFinite(adj.amount) ? adj.amount : 0}
          onChange={(e) => onChange({ amount: Number(e.target.value) })}
        />
        {adj.action === 'multiply' && <span className="forge-adjust-hint">%</span>}
        <button type="button" className="forge-adjust-remove" onClick={onRemove} aria-label="Remove adjustment">×</button>
      </div>

      {/* Filters — each "where col = val ×" on one line */}
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
    </div>
  );
}
