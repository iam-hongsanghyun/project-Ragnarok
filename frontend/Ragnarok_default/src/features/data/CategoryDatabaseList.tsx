/**
 * Left rail of the Data view — file-tree-style database selector.
 *
 * Uses the project's canonical `.sheet-tree-*` classes (same primitive as
 * ModelView's component tree) so every tree in the app shares look and
 * behaviour: chevron + label + count for branch rows, icon + label + count
 * for leaves, filter search + collapse-all / expand-all in the toolbar.
 *
 * Stage 1 (no country selected): a short prompt + the recently-used
 * countries list, so the rail isn't empty before the user clicks the map.
 *
 * Stage 2 (country picked): country header, then a recursive tree
 *
 *   ▾ Category
 *     ▾ Subcategory
 *       • Database 1
 *       • Database 2
 *
 * Every branch is collapsable; the open/closed state and the filter query
 * persist to localStorage so the user's view sticks across reloads.
 * Designed to scale to ~100 databases — collapsed subtrees render nothing.
 */
import React, { useMemo, useState } from 'react';
import { CountryMeta, DatabaseMeta, ImporterCategory } from '../../shared/api/databases';
import { usePersistedState } from '../../shared/utils/usePersistedState';

interface Props {
  databases: DatabaseMeta[];
  selectedCountry: CountryMeta | null;
  selectedDatabaseId: string | null;
  onSelectDatabase: (id: string) => void;
}

/** True iff this database has data for the selected ISO-A3 country. */
function coversCountry(db: DatabaseMeta, iso: string): boolean {
  const cov = db.country_coverage;
  if (cov === undefined || cov === 'global') return true;
  if (Array.isArray(cov)) return cov.includes(iso);
  return true;
}

const CATEGORY_ORDER: ImporterCategory[] = ['transmission', 'generation', 'demand', 'costs'];
const CATEGORY_LABEL: Record<string, string> = {
  transmission: 'Transmission',
  generation: 'Generation',
  demand: 'Demand',
  costs: 'Costs & parameters',
};
const UNCATEGORISED = '(uncategorised)';
const COLLAPSE_KEY = 'ragnarok:data-import:tree-collapsed';

interface CategoryNode {
  category: ImporterCategory;
  subcategories: Map<string, DatabaseMeta[]>;
}

function buildTree(databases: DatabaseMeta[]): CategoryNode[] {
  const byCategory = new Map<ImporterCategory, Map<string, DatabaseMeta[]>>();
  for (const db of databases) {
    const cat = (db.category || UNCATEGORISED) as ImporterCategory;
    const sub = db.subcategory && db.subcategory.length > 0 ? db.subcategory : UNCATEGORISED;
    if (!byCategory.has(cat)) byCategory.set(cat, new Map());
    const subMap = byCategory.get(cat)!;
    if (!subMap.has(sub)) subMap.set(sub, []);
    subMap.get(sub)!.push(db);
  }
  const ordered: CategoryNode[] = [];
  const seen = new Set<string>();
  for (const cat of CATEGORY_ORDER) {
    if (byCategory.has(cat)) {
      ordered.push({ category: cat, subcategories: byCategory.get(cat)! });
      seen.add(cat);
    }
  }
  const extras = Array.from(byCategory.keys()).filter((c) => !seen.has(c)).sort();
  for (const cat of extras) ordered.push({ category: cat, subcategories: byCategory.get(cat)! });
  return ordered;
}

function nodeKey(parts: string[]): string {
  return parts.join('/');
}

function matchesQuery(text: string, query: string): boolean {
  return !query || text.toLowerCase().includes(query.toLowerCase());
}

export function CategoryDatabaseList({
  databases,
  selectedCountry,
  selectedDatabaseId,
  onSelectDatabase,
}: Props) {
  // Filter to only databases that have coverage for the selected country.
  // Before a country is picked we don't render the tree at all (stage-1
  // copy block), so the full list is fine there.
  const visibleDatabases = useMemo(() => {
    if (!selectedCountry) return databases;
    return databases.filter((db) => coversCountry(db, selectedCountry.iso));
  }, [databases, selectedCountry]);
  const tree = useMemo(() => buildTree(visibleDatabases), [visibleDatabases]);
  const [collapsed, setCollapsed] = usePersistedState<Record<string, boolean>>(COLLAPSE_KEY, {});
  const [query, setQuery] = useState('');

  const isCollapsed = (key: string): boolean => collapsed[key] === true;
  const toggle = (key: string) =>
    setCollapsed({ ...collapsed, [key]: !isCollapsed(key) });

  const collapseAll = () => {
    const next: Record<string, boolean> = {};
    for (const node of tree) {
      next[nodeKey([node.category])] = true;
      Array.from(node.subcategories.keys()).forEach((sub) => {
        next[nodeKey([node.category, sub])] = true;
      });
    }
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

  // When the user has typed a query, force-open every branch that contains
  // a matching leaf so they can see results without having to expand by hand.
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
          <button
            type="button"
            className="tb-btn tb-btn--muted"
            onClick={collapseAll}
            title="Collapse all"
          >
            –
          </button>
          <button
            type="button"
            className="tb-btn tb-btn--muted"
            onClick={expandAll}
            title="Expand all"
          >
            +
          </button>
        </div>
        <div className="sheet-tree-body">
          {tree.map((node) => {
            const catKey = nodeKey([node.category]);
            const catLabel = CATEGORY_LABEL[node.category] || node.category;
            const subEntries = Array.from(node.subcategories.entries());
            // Apply the filter to leaves; a branch is visible if its label
            // matches or any descendant leaf does.
            const filteredSubEntries = subEntries
              .map(([sub, dbs]) => {
                const subMatches = matchesQuery(sub, query);
                const dbMatches = dbs.filter((d) => matchesQuery(d.name, query));
                if (!queryActive) return [sub, dbs] as const;
                if (subMatches) return [sub, dbs] as const;
                if (dbMatches.length > 0) return [sub, dbMatches] as const;
                return null;
              })
              .filter((entry): entry is readonly [string, DatabaseMeta[]] => entry !== null);
            const catMatches = matchesQuery(catLabel, query);
            if (queryActive && !catMatches && filteredSubEntries.length === 0) return null;
            const catOpen = queryActive ? true : !isCollapsed(catKey);
            const dbCount = filteredSubEntries.reduce((n, [, list]) => n + list.length, 0);
            return (
              <div key={node.category} className="sheet-tree-group">
                <button
                  type="button"
                  className="sheet-tree-group-header"
                  onClick={() => toggle(catKey)}
                  aria-expanded={catOpen}
                >
                  <span className={`sheet-tree-chevron${catOpen ? ' is-open' : ''}`}>›</span>
                  <span className="sheet-tree-group-label">{catLabel}</span>
                  <span className="sheet-tree-count">{dbCount}</span>
                </button>
                {catOpen && (
                  <div className="sheet-tree-items">
                    {filteredSubEntries.map(([sub, dbs]) => {
                      // Uncategorised buckets render their databases inline at
                      // the same depth as the category's leaves; we skip the
                      // intermediate subcategory branch row.
                      if (sub === UNCATEGORISED) {
                        return dbs.map((db) => (
                          <DatabaseLeaf
                            key={db.id}
                            db={db}
                            depth={1}
                            active={db.id === selectedDatabaseId}
                            onSelect={onSelectDatabase}
                          />
                        ));
                      }
                      const subKey = nodeKey([node.category, sub]);
                      const subOpen = queryActive ? true : !isCollapsed(subKey);
                      return (
                        <div key={sub} className="sheet-tree-group">
                          <button
                            type="button"
                            className="sheet-tree-group-header"
                            onClick={() => toggle(subKey)}
                            aria-expanded={subOpen}
                            style={{ paddingLeft: 28 }}
                          >
                            <span className={`sheet-tree-chevron${subOpen ? ' is-open' : ''}`}>›</span>
                            <span className="sheet-tree-group-label">{sub}</span>
                            <span className="sheet-tree-count">{dbs.length}</span>
                          </button>
                          {subOpen && (
                            <div className="sheet-tree-items">
                              {dbs.map((db) => (
                                <DatabaseLeaf
                                  key={db.id}
                                  db={db}
                                  depth={2}
                                  active={db.id === selectedDatabaseId}
                                  onSelect={onSelectDatabase}
                                />
                              ))}
                            </div>
                          )}
                        </div>
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

/**
 * Leaf row — one database. Uses the same `.sheet-tree-item` class as the
 * Model's per-sheet rows so the Data and Model trees read identically.
 * The icon column is a small carrier-style glyph (≡) for the database.
 */
function DatabaseLeaf({
  db,
  depth,
  active,
  onSelect,
}: {
  db: DatabaseMeta;
  depth: number;
  active: boolean;
  onSelect: (id: string) => void;
}) {
  // depth 1 = direct under category (uncategorised) → default 28px left;
  // depth 2 = under subcategory → 44px left.
  const paddingLeft = depth >= 2 ? 44 : undefined;
  return (
    <button
      type="button"
      className={`sheet-tree-item${active ? ' is-active' : ''}`}
      onClick={() => db.available && onSelect(db.id)}
      disabled={!db.available}
      title={db.unavailable_reason || db.description || db.name}
      style={paddingLeft !== undefined ? { paddingLeft } : undefined}
    >
      <span className="sheet-tree-item-icon">≡</span>
      <span className="sheet-tree-item-label">{db.name}</span>
      <span className="sheet-tree-count">{db.license || '—'}</span>
    </button>
  );
}
