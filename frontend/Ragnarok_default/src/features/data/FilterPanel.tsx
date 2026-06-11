/**
 * Right rail: database metadata + dynamic filter form + actions.
 *
 * The form is rendered from the active database's `filters[]` schema; each
 * `filter.kind` maps to one input component. Adding a new kind = one branch
 * here and one match on the backend `Filter` dataclass.
 */
import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { FilterSchema, PreviewSummary, Source } from 'lib/api/databases';
import { getSecret } from 'lib/api/secrets';
import type { RunPart } from 'lib/data/store';
import { SearchableSelect } from '../../shared/components/SearchableSelect';
import { DateField } from './DateField';

/**
 * Hover/focus tooltip for filter descriptions. Rendered into document.body
 * via a portal with `position: fixed` so the right rail's `overflow: hidden`
 * (needed for scrolling) doesn't clip the popup. Position is computed from
 * the icon's bounding rect each time it shows and clamped to the viewport
 * with an 8px gutter, so descriptions near the rail edge stay readable.
 */
function InfoTooltip({ text, label }: { text: string; label: string }) {
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const iconRef = useRef<HTMLSpanElement>(null);

  const show = () => {
    const el = iconRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const MAX_WIDTH = 240;
    const PAD = 8;
    // Anchor the popup so its bottom sits 8 px above the icon, centred
    // horizontally on the icon, then clamp into the viewport.
    let left = rect.left + rect.width / 2 - MAX_WIDTH / 2;
    if (left < PAD) left = PAD;
    if (left + MAX_WIDTH > window.innerWidth - PAD) {
      left = window.innerWidth - MAX_WIDTH - PAD;
    }
    const top = rect.top - 8;
    setPos({ top, left });
  };
  const hide = () => setPos(null);

  return (
    <>
      <span
        ref={iconRef}
        className="data-import-filter__info"
        role="button"
        tabIndex={0}
        aria-label={`More info about ${label}`}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onClick={(e) => {
          // Tooltips are hover/focus-only. Some icons now live inside a
          // collapsible <summary>; a click must not toggle the section.
          e.preventDefault();
          e.stopPropagation();
        }}
      >
        i
      </span>
      {pos &&
        createPortal(
          <div
            className="data-import-filter__tooltip"
            role="tooltip"
            style={{ top: pos.top, left: pos.left }}
          >
            {text}
          </div>,
          document.body,
        )}
    </>
  );
}

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

/** One database with ticked datasets: its settings section in the rail. */
export interface SourceEntry {
  source: Source;
  /** Which datasets of this source are ticked in the left rail. */
  datasetIds: string[];
  /** This source's own filter values (never shared with other sources). */
  values: Record<string, unknown>;
}

interface Props {
  /** Every database with ≥1 ticked dataset — each renders its own section. */
  entries: SourceEntry[];
  onChange: (sourceId: string, filterId: string, value: unknown) => void;
  onFetch: () => void;
  onApply: () => void;
  fetching: boolean;
  /** Reserved — true while the merge is in progress. With the one-trip
   *  endpoint the merge is synchronous, so this is currently always false. */
  applying: boolean;
  /** The held run's per-source slices (status / preview / error), if any. */
  parts: RunPart[] | null;
  /** True iff ≥1 fetched fragment is ready to merge. */
  canApply: boolean;
  errors: string[];
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
      // Unreachable: toggles are rendered inline by the outer map so they
      // can share their row with the (i) tooltip icon. Kept here as a
      // defensive fallback if a toggle ever ends up routed through
      // FilterInput.
      return (
        <label className="data-import-filter__toggle">
          <input
            type="checkbox"
            checked={!!value}
            onChange={(e) => onChange(e.target.checked)}
          />
          <span>{filter.label}</span>
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

function formatCount(value: number): string {
  return value.toLocaleString();
}

/** Sort voltage keys ("145 kV", "1100 kV", …) ascending numerically. */
function compareVoltageKey(a: string, b: string): number {
  const na = parseFloat(a);
  const nb = parseFloat(b);
  if (Number.isFinite(na) && Number.isFinite(nb)) return na - nb;
  return a.localeCompare(b);
}

function PreviewBody({ summary }: { summary: PreviewSummary }) {
  // Split the count map into rows + breakdowns. The renderer below shows
  // a single right-aligned column for the headline counts, then optional
  // carrier / voltage breakdowns as compact two-column lists.
  const numeric = Object.entries(summary.counts).filter(
    ([k]) => !k.startsWith('carrier:') && !k.startsWith('voltage:'),
  );
  const carriers = Object.entries(summary.counts)
    .filter(([k]) => k.startsWith('carrier:'))
    .map(([k, v]) => [k.slice('carrier:'.length), v] as const);
  const voltages = Object.entries(summary.counts)
    .filter(([k]) => k.startsWith('voltage:'))
    .map(([k, v]) => [k.slice('voltage:'.length), v] as const)
    .sort(([a], [b]) => compareVoltageKey(a, b));

  return (
    <div className="data-import-preview">
      {summary.notes.length > 0 && (
        <p className="data-import-preview__note">{summary.notes[0]}</p>
      )}
      {numeric.length > 0 && (
        <dl className="data-import-preview__counts">
          {numeric.map(([k, v]) => (
            <React.Fragment key={k}>
              <dt>{k.replace(/_/g, ' ')}</dt>
              <dd>{formatCount(Number(v) || 0)}</dd>
            </React.Fragment>
          ))}
        </dl>
      )}
      {carriers.length > 0 && (
        <section className="data-import-preview__group">
          <h5>By carrier</h5>
          <dl className="data-import-preview__counts">
            {carriers.map(([name, v]) => (
              <React.Fragment key={name}>
                <dt>{name}</dt>
                <dd>{formatCount(Number(v) || 0)}</dd>
              </React.Fragment>
            ))}
          </dl>
        </section>
      )}
      {voltages.length > 0 && (
        <section className="data-import-preview__group">
          <h5>By voltage</h5>
          <dl className="data-import-preview__counts">
            {voltages.map(([name, v]) => (
              <React.Fragment key={name}>
                <dt>{name}</dt>
                <dd>{formatCount(Number(v) || 0)}</dd>
              </React.Fragment>
            ))}
          </dl>
        </section>
      )}
    </div>
  );
}

/** One filter row — toggles render inline (checkbox + label + ⓘ); everything
 *  else as label + input. Shared by the Common group and per-dataset groups. */
function FilterRow({
  filter,
  value,
  onChange,
}: {
  filter: FilterSchema;
  value: unknown;
  onChange: (id: string, value: unknown) => void;
}) {
  if (filter.kind === 'toggle') {
    return (
      <div className="data-import-filter data-import-filter--toggle">
        <label className="data-import-filter__toggle">
          <input
            type="checkbox"
            checked={!!value}
            onChange={(e) => onChange(filter.id, e.target.checked)}
          />
          <span>{filter.label}</span>
        </label>
        {filter.description && <InfoTooltip text={filter.description} label={filter.label} />}
      </div>
    );
  }
  return (
    <div className="data-import-filter">
      <label className="data-import-filter__label">
        <span>{filter.label}</span>
        {filter.unit ? <span className="data-import-filter__unit"> ({filter.unit})</span> : null}
        {filter.description && <InfoTooltip text={filter.description} label={filter.label} />}
      </label>
      <FilterInput filter={filter} value={value} onChange={(v) => onChange(filter.id, v)} />
    </div>
  );
}

/** Missing BYOK key names for one entry's ticked datasets. */
function missingSecretsFor(entry: SourceEntry): string[] {
  const selected = entry.source.datasets.filter((d) => entry.datasetIds.includes(d.id));
  return Array.from(new Set(selected.flatMap((d) => d.requires_secrets ?? []))).filter(
    (name) => !getSecret(name),
  );
}

/** One database's settings block: meta line + Common group + per-dataset groups. */
function SourceSection({
  entry,
  onChange,
}: {
  entry: SourceEntry;
  onChange: (sourceId: string, filterId: string, value: unknown) => void;
}) {
  const { source, datasetIds, values } = entry;
  const selectedDatasets = source.datasets.filter((d) => datasetIds.includes(d.id));
  const missingSecrets = missingSecretsFor(entry);

  // Common settings render once, but only when ≥1 selected dataset declares
  // them. Per-dataset groups carry each dataset's remaining (own) filters.
  const commonIds = new Set(source.common_filter_ids);
  const selectedFilterIds = new Set(selectedDatasets.flatMap((d) => d.filters.map((f) => f.id)));
  const commonFilters = source.common_filters.filter((f) => selectedFilterIds.has(f.id));
  const primary = selectedDatasets[0] ?? source.datasets[0];
  const change = (filterId: string, value: unknown) => onChange(source.source_id, filterId, value);

  return (
    <details className="data-import-filters__source" open>
      <summary className="data-import-filters__source-title">{source.source_label}</summary>
      <div className="data-import-filters__source-body">
        {missingSecrets.length > 0 && (
          <p className="data-import-filters__keynotice">
            This source needs an API key: <b>{missingSecrets.join(', ')}</b>.
            Add it in <b>Settings → API keys</b>, then come back and fetch.
          </p>
        )}

        <section className="data-import-filters__meta">
          {primary && (
            <>
              <p className="data-import-filters__line">
                <b>License:</b> {primary.license}
              </p>
              <p className="data-import-filters__line">
                <b>Source:</b>{' '}
                <a href={primary.homepage} target="_blank" rel="noreferrer">
                  {primary.homepage}
                </a>
              </p>
            </>
          )}
          <p className="data-import-filters__line">
            <b>Datasets:</b> {selectedDatasets.map((d) => d.short_name || d.name).join(', ')}
          </p>
        </section>

        {commonFilters.length > 0 && (
          <details className="data-import-filters__group" open>
            <summary className="data-import-filters__group-title">Common settings</summary>
            <div className="data-import-filters__group-body">
              {commonFilters.map((f) => (
                <FilterRow key={f.id} filter={f} value={values[f.id]} onChange={change} />
              ))}
            </div>
          </details>
        )}

        {selectedDatasets.map((ds) => {
          const ownFilters = ds.filters.filter((f) => !commonIds.has(f.id));
          if (ownFilters.length === 0) return null;
          return (
            <details key={ds.id} className="data-import-filters__group" open>
              <summary className="data-import-filters__group-title">
                {ds.short_name || ds.name}
                {ds.description && <InfoTooltip text={ds.description} label={ds.short_name || ds.name} />}
              </summary>
              <div className="data-import-filters__group-body">
                {ownFilters.map((f) => (
                  <FilterRow key={f.id} filter={f} value={values[f.id]} onChange={change} />
                ))}
              </div>
            </details>
          );
        })}
      </div>
    </details>
  );
}

export function FilterPanel({
  entries,
  onChange,
  onFetch,
  onApply,
  fetching,
  applying,
  parts,
  canApply,
  errors,
}: Props) {
  if (entries.length === 0) {
    return (
      <aside className="view-rail view-rail--right data-import-filters">
        <div className="view-rail-header"><span>Settings</span></div>
        <div className="view-rail-body data-import-filters__empty">
          <p>Pick a database in the left rail, then tick the datasets to fetch — across as many databases as you need.</p>
        </div>
      </aside>
    );
  }

  // BYOK: any entry missing a key blocks the (single) fetch.
  const blockedOnSecrets = entries.some((e) => missingSecretsFor(e).length > 0);
  const headerLabel =
    entries.length === 1 ? entries[0].source.source_label : `${entries.length} databases`;
  const readyPreviews = (parts ?? []).filter((p) => p.status === 'ready' && p.preview);

  return (
    <aside className="view-rail view-rail--right data-import-filters">
      <div className="view-rail-header"><span>{headerLabel}</span></div>
      <div className="view-rail-body data-import-filters__body">
        {entries.map((entry) => (
          <SourceSection key={entry.source.source_id} entry={entry} onChange={onChange} />
        ))}

        <section className="data-import-filters__actions">
          <button
            type="button"
            className="primary"
            onClick={onFetch}
            disabled={fetching || applying || blockedOnSecrets}
            title={blockedOnSecrets ? 'Add the required API key in Settings first' : undefined}
          >
            {fetching ? 'Fetching…' : entries.length > 1 ? `Fetch preview (${entries.length} databases)` : 'Fetch preview'}
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
        {errors.map((err) => (
          <p key={err} className="data-import-filters__error">{err}</p>
        ))}
        {readyPreviews.map((p) =>
          readyPreviews.length > 1 ? (
            <details key={p.sourceId} className="data-import-filters__group" open>
              <summary className="data-import-filters__group-title">{p.sourceLabel}</summary>
              <div className="data-import-filters__group-body">
                <PreviewBody summary={p.preview as PreviewSummary} />
              </div>
            </details>
          ) : (
            <section key={p.sourceId} className="data-import-filters__group">
              <PreviewBody summary={p.preview as PreviewSummary} />
            </section>
          ),
        )}
      </div>
    </aside>
  );
}
