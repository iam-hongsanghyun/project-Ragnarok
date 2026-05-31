/**
 * Right rail: database metadata + dynamic filter form + actions.
 *
 * The form is rendered from the active database's `filters[]` schema; each
 * `filter.kind` maps to one input component. Adding a new kind = one branch
 * here and one match on the backend `Filter` dataclass.
 */
import React, { useEffect, useRef, useState } from 'react';
import { DatabaseMeta, FilterSchema, PreviewSummary } from '../../shared/api/databases';
import { SearchableSelect } from '../../shared/components/SearchableSelect';
import { DateField } from './DateField';

/**
 * Dropdown-style multiselect — keeps the right rail compact when the
 * options list is long. Trigger shows a one-line summary; clicking opens
 * a panel below it with a Select all / Clear header and one checkbox per
 * option. Closes on outside click or Escape.
 */
function MultiselectDropdown({
  filter,
  selected,
  onChange,
}: {
  filter: FilterSchema;
  selected: unknown[];
  onChange: (v: unknown[]) => void;
}) {
  const options = filter.options || [];
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const allSelected = options.length > 0 && options.every((o) => selected.includes(o.value));
  const noneSelected = selected.length === 0;
  const summary = noneSelected
    ? `All (${options.length})`
    : allSelected
      ? `All (${options.length})`
      : selected.length <= 3
        ? options
            .filter((o) => selected.includes(o.value))
            .map((o) => o.label)
            .join(', ')
        : `${selected.length} selected`;

  const toggle = (v: string | number | boolean) =>
    onChange(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]);

  return (
    <div ref={rootRef} className="ss-wrap data-import-multiselect">
      <button
        type="button"
        className="ss-input data-import-multiselect__trigger"
        onClick={() => setOpen((s) => !s)}
        aria-expanded={open}
      >
        {summary}
      </button>
      {open && (
        <ul
          className="ss-menu data-import-multiselect__panel"
          role="listbox"
          aria-multiselectable="true"
        >
          <li className="data-import-multiselect__head">
            <button
              type="button"
              className="data-import-multiselect__head-btn"
              onClick={() => onChange(options.map((o) => o.value))}
              disabled={allSelected}
            >
              Select all
            </button>
            <button
              type="button"
              className="data-import-multiselect__head-btn"
              onClick={() => onChange([])}
              disabled={noneSelected}
            >
              Clear
            </button>
          </li>
          {options.map((opt) => {
            const checked = selected.includes(opt.value);
            return (
              <li key={String(opt.value)} className="ss-option data-import-multiselect__option">
                <label>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(opt.value)}
                  />
                  <span>{opt.label}</span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

interface Props {
  database: DatabaseMeta | null;
  values: Record<string, unknown>;
  onChange: (id: string, value: unknown) => void;
  onFetch: () => void;
  onApply: () => void;
  fetching: boolean;
  /** Reserved — true while the merge is in progress. With the one-trip
   *  endpoint the merge is synchronous, so this is currently always false. */
  applying: boolean;
  preview: PreviewSummary | null;
  /** True iff a fetch has succeeded and the held fragment is ready to merge. */
  canApply: boolean;
  error: string | null;
}

function FilterInput({
  filter,
  value,
  onChange,
}: {
  filter: FilterSchema;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  switch (filter.kind) {
    case 'number': {
      const v = value === null || value === undefined ? '' : String(value);
      return (
        <input
          type="number"
          value={v}
          min={typeof filter.min === 'number' ? filter.min : undefined}
          max={typeof filter.max === 'number' ? filter.max : undefined}
          step={filter.step}
          onChange={(e) => {
            const raw = e.target.value;
            onChange(raw === '' ? null : Number(raw));
          }}
        />
      );
    }
    case 'toggle': {
      return (
        <label className="data-import-filter__toggle">
          <input
            type="checkbox"
            checked={!!value}
            onChange={(e) => onChange(e.target.checked)}
          />
          <span>{filter.description || filter.label}</span>
        </label>
      );
    }
    case 'select': {
      const v = typeof value === 'string' || typeof value === 'number' ? String(value) : '';
      const options = (filter.options || []).map((opt) => ({
        value: String(opt.value),
        label: opt.label,
      }));
      return (
        <SearchableSelect
          value={v}
          options={options}
          onChange={(next) => onChange(next)}
          placeholder="—"
        />
      );
    }
    case 'multiselect': {
      const selected: unknown[] = Array.isArray(value) ? value : [];
      return <MultiselectDropdown filter={filter} selected={selected} onChange={onChange} />;
    }
    case 'date': {
      // Popover-style date picker built on react-calendar; renders with
      // the same ss-* chrome as every other dropdown so the trigger lines
      // up visually. Stored value is always ISO YYYY-MM-DD.
      const v = typeof value === 'string' ? value : '';
      const minISO = typeof filter.min === 'string' ? filter.min : undefined;
      const maxISO = typeof filter.max === 'string' ? filter.max : undefined;
      return <DateField value={v} onChange={onChange} min={minISO} max={maxISO} />;
    }
    default:
      return (
        <input
          type="text"
          value={value === null || value === undefined ? '' : String(value)}
          onChange={(e) => onChange(e.target.value)}
        />
      );
  }
}

function PreviewBody({ summary }: { summary: PreviewSummary }) {
  const numeric = Object.entries(summary.counts).filter(([k]) => !k.startsWith('carrier:') && !k.startsWith('voltage:'));
  const carriers = Object.entries(summary.counts).filter(([k]) => k.startsWith('carrier:'));
  const voltages = Object.entries(summary.counts).filter(([k]) => k.startsWith('voltage:'));
  return (
    <div className="data-import-preview">
      <h4>Preview</h4>
      {summary.notes.map((n, idx) => (
        <p key={idx} className="data-import-preview__note">{n}</p>
      ))}
      {numeric.length > 0 && (
        <dl className="data-import-preview__counts">
          {numeric.map(([k, v]) => (
            <div key={k}>
              <dt>{k.replace(/_/g, ' ')}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {carriers.length > 0 && (
        <section>
          <h5>By carrier</h5>
          <ul className="data-import-preview__chips">
            {carriers.map(([k, v]) => (
              <li key={k}><span>{k.slice('carrier:'.length)}</span><b>{v}</b></li>
            ))}
          </ul>
        </section>
      )}
      {voltages.length > 0 && (
        <section>
          <h5>By voltage</h5>
          <ul className="data-import-preview__chips">
            {voltages.map(([k, v]) => (
              <li key={k}><span>{k.slice('voltage:'.length)}</span><b>{v}</b></li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

export function FilterPanel({
  database,
  values,
  onChange,
  onFetch,
  onApply,
  fetching,
  applying,
  preview,
  canApply,
  error,
}: Props) {
  if (!database) {
    return (
      <aside className="view-rail view-rail--right data-import-filters">
        <div className="view-rail-header"><span>Filters</span></div>
        <div className="view-rail-body data-import-filters__empty">
          <p>Select a database from the left rail to set filters.</p>
        </div>
      </aside>
    );
  }
  return (
    <aside className="view-rail view-rail--right data-import-filters">
      <div className="view-rail-header"><span>{database.name}</span></div>
      <div className="view-rail-body data-import-filters__body">
        <section className="data-import-filters__meta">
          {database.description && (
            <p className="data-import-filters__desc">{database.description}</p>
          )}
          <p className="data-import-filters__line">
            <b>License:</b> {database.license}
          </p>
          <p className="data-import-filters__line">
            <b>Source:</b>{' '}
            <a href={database.homepage} target="_blank" rel="noreferrer">
              {database.homepage}
            </a>
          </p>
          <p className="data-import-filters__line">
            <b>Targets:</b> {database.targets.join(', ')}
          </p>
        </section>
        <section className="data-import-filters__form">
          {database.filters.map((filter) => (
            <div key={filter.id} className="data-import-filter">
              <label className="data-import-filter__label">
                {filter.label}
                {filter.unit ? <span className="data-import-filter__unit"> ({filter.unit})</span> : null}
              </label>
              <FilterInput
                filter={filter}
                value={values[filter.id]}
                onChange={(v) => onChange(filter.id, v)}
              />
              {filter.description && filter.kind !== 'toggle' && (
                <p className="data-import-filter__hint">{filter.description}</p>
              )}
            </div>
          ))}
        </section>
        <section className="data-import-filters__actions">
          <button
            type="button"
            className="primary"
            onClick={onFetch}
            disabled={fetching || applying}
          >
            {fetching ? 'Fetching…' : 'Fetch preview'}
          </button>
          <button
            type="button"
            onClick={onApply}
            disabled={!canApply || fetching || applying}
            title={!canApply ? 'Run a preview first' : 'Merge the fetched rows into the current workbook'}
          >
            {applying ? 'Adding…' : 'Add to workbook'}
          </button>
        </section>
        {error && <p className="data-import-filters__error">{error}</p>}
        {preview && <PreviewBody summary={preview} />}
      </div>
    </aside>
  );
}
