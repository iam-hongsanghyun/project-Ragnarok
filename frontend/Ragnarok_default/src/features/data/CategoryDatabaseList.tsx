/**
 * Left rail of the Data view — Country → Database → Datasets selector.
 *
 * Uses the project's canonical `.sheet-tree-*` classes (same primitive as
 * ModelView's component tree). The tree is two levels:
 *
 *   ▾ Database (source)            e.g. "KPG193 — Korean reference grid"   2/4
 *       ☑ Network                  ← multi-select checkboxes
 *       ☑ Renewable capacity
 *       ☐ Demand profile
 *       ☑ Renewable profile
 *
 * Ticking datasets decides what gets fetched; clicking a source focuses it so
 * its settings render in the right rail. A source with one dataset (OSM, WRI,
 * EIA, …) is just the degenerate case. Selecting a source's datasets and
 * fetching produces one aligned, PyPSA-ready bundle.
 *
 * Stage 1 (no country): a short prompt. Stage 2 (country picked): the tree of
 * sources that cover the country. Collapse + filter state persist.
 */
import React, { useMemo, useState } from 'react';
import { CountryMeta, Source } from 'lib/api/databases';
import { usePersistedState } from 'shared/hooks/usePersistedState';

interface Props {
  sources: Source[];
  selectedCountry: CountryMeta | null;
  focusedSourceId: string | null;
  selectionBySource: Record<string, string[]>;
  onFocusSource: (sourceId: string) => void;
  onToggleDataset: (sourceId: string, datasetId: string) => void;
}

const COLLAPSE_KEY = 'ragnarok:data-import:tree-collapsed';

const CATEGORY_LABEL: Record<string, string> = {
  transmission: 'Transmission',
  generation: 'Generation',
  demand: 'Demand',
  costs: 'Costs',
};

/** True iff this source has data for the selected ISO-A3 country. */
function coversCountry(source: Source, iso: string): boolean {
  const cov = source.country_coverage;
  if (cov === undefined || cov === 'global') return true;
  if (Array.isArray(cov)) return cov.includes(iso);
  return true;
}

function matchesQuery(text: string, query: string): boolean {
  return !query || text.toLowerCase().includes(query.toLowerCase());
}

/** Selected dataset ids for a source — absent means none ticked (the user
 *  chooses what to fetch). */
function selectedIdsFor(source: Source, selectionBySource: Record<string, string[]>): string[] {
  return selectionBySource[source.source_id] ?? [];
}

export function CategoryDatabaseList({
  sources,
  selectedCountry,
  focusedSourceId,
  selectionBySource,
  onFocusSource,
  onToggleDataset,
}: Props) {
  const visibleSources = useMemo(() => {
    if (!selectedCountry) return sources;
    return sources.filter((s) => coversCountry(s, selectedCountry.iso));
  }, [sources, selectedCountry]);
  const [collapsed, setCollapsed] = usePersistedState<Record<string, boolean>>(COLLAPSE_KEY, {});
  const [query, setQuery] = useState('');

  const isCollapsed = (key: string): boolean => collapsed[key] === true;
  const toggleCollapse = (key: string) => setCollapsed({ ...collapsed, [key]: !isCollapsed(key) });
  const collapseAll = () => {
    const next: Record<string, boolean> = {};
    for (const s of visibleSources) next[s.source_id] = true;
    setCollapsed(next);
  };
  const expandAll = () => setCollapsed({});

  const header = (
    <div className="view-rail-header">
      <span>Data import</span>
    </div>
  );

  if (!selectedCountry) {
    return (
      <aside className="view-rail view-rail--left data-import-rail">
        {header}
        <div className="view-rail-body data-import-rail__body">
          <p className="data-import-rail__hint">
            Pick a country on the map to begin. Click a country shape, or type its
            name in the search box at the top of the map.
          </p>
        </div>
      </aside>
    );
  }

  const queryActive = query.trim().length > 0;

  return (
    <aside className="view-rail view-rail--left data-import-rail">
      {header}
      <div className="data-import-rail__country">
        <div className="data-import-rail__country-name">{selectedCountry.name}</div>
        <div className="data-import-rail__country-iso">{selectedCountry.iso}</div>
      </div>
      <nav className="sheet-tree" aria-label="Database tree">
        <div className="sheet-tree-toolbar">
          <input
            className="sheet-tree-search"
            type="text"
            placeholder="Filter…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Filter databases"
          />
          <button type="button" className="tb-btn tb-btn--muted" onClick={collapseAll} title="Collapse all">
            –
          </button>
          <button type="button" className="tb-btn tb-btn--muted" onClick={expandAll} title="Expand all">
            +
          </button>
        </div>
        <div className="sheet-tree-body">
          {visibleSources.map((source) => {
            const datasets = source.datasets.filter(
              (d) => !queryActive
                || matchesQuery(source.source_label, query)
                || matchesQuery(d.short_name || d.name, query),
            );
            if (queryActive && datasets.length === 0 && !matchesQuery(source.source_label, query)) {
              return null;
            }
            const open = queryActive ? true : !isCollapsed(source.source_id);
            const selected = selectedIdsFor(source, selectionBySource);
            const selectedCount = source.datasets.filter((d) => selected.includes(d.id)).length;
            const isFocused = source.source_id === focusedSourceId;
            const renderDatasets = datasets.length > 0 ? datasets : source.datasets;
            return (
              <div key={source.source_id} className="sheet-tree-group">
                <button
                  type="button"
                  className={`sheet-tree-group-header${isFocused ? ' is-active' : ''}`}
                  onClick={() => {
                    // Focusing an unfocused source opens it (so its datasets
                    // show); clicking the already-focused source toggles
                    // collapse. So focusing never hides the datasets.
                    if (isFocused) {
                      toggleCollapse(source.source_id);
                    } else {
                      onFocusSource(source.source_id);
                      if (isCollapsed(source.source_id)) toggleCollapse(source.source_id);
                    }
                  }}
                  aria-expanded={open}
                  title={source.source_label}
                >
                  <span className={`sheet-tree-chevron${open ? ' is-open' : ''}`}>›</span>
                  <span className="sheet-tree-group-label">{source.source_label}</span>
                  <span className="sheet-tree-count">
                    {selectedCount}/{source.datasets.length}
                  </span>
                </button>
                {open && (
                  <div className="sheet-tree-items">
                    {renderDatasets.map((db) => {
                      const checked = selected.includes(db.id);
                      const catLabel = CATEGORY_LABEL[db.category] || db.category;
                      return (
                        <label
                          key={db.id}
                          className={`sheet-tree-item data-import-dataset${db.available ? '' : ' is-disabled'}`}
                          style={{ paddingLeft: 28 }}
                          title={db.unavailable_reason || db.description || db.name}
                        >
                          <input
                            type="checkbox"
                            className="data-import-dataset__check"
                            checked={checked}
                            disabled={!db.available}
                            onChange={() => onToggleDataset(source.source_id, db.id)}
                          />
                          <span className="sheet-tree-item-label">{db.short_name || db.name}</span>
                          {source.datasets.length > 1 && (
                            <span className="data-import-dataset__tag">{catLabel}</span>
                          )}
                        </label>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </nav>
    </aside>
  );
}
