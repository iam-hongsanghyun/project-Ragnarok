/**
 * Left rail of the Data view — file-tree-style database selector.
 *
 * Stage 1 (no country selected): a short prompt + the recently-used
 * countries list (so the rail isn't empty before the user clicks the map).
 *
 * Stage 2 (country picked): country header, then a recursive tree
 *
 *   ▾ Category
 *     ▾ Subcategory
 *       • Database 1
 *       • Database 2
 *
 * Every node is collapsable; the open/closed state persists to localStorage
 * so the user's preferred view sticks across reloads. Designed to scale to
 * ~100 databases — each node renders independently so collapsed subtrees
 * cost nothing to keep on screen.
 */
import React, { useMemo } from 'react';
import { CountryMeta, DatabaseMeta, ImporterCategory } from '../../shared/api/databases';
import { usePersistedState } from '../../shared/utils/usePersistedState';

interface Props {
  databases: DatabaseMeta[];
  selectedCountry: CountryMeta | null;
  recentCountries: CountryMeta[];
  onClearCountry: () => void;
  onChooseRecent: (iso: string) => void;
  selectedDatabaseId: string | null;
  onSelectDatabase: (id: string) => void;
}

const CATEGORY_ORDER: ImporterCategory[] = ['transmission', 'generation', 'demand'];
const CATEGORY_LABEL: Record<string, string> = {
  transmission: 'Transmission',
  generation: 'Generation',
  demand: 'Demand',
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
  // Append any extra categories not in the canonical order (alphabetical).
  const extras = Array.from(byCategory.keys()).filter((c) => !seen.has(c)).sort();
  for (const cat of extras) ordered.push({ category: cat, subcategories: byCategory.get(cat)! });
  return ordered;
}

function nodeKey(parts: string[]): string {
  return parts.join('/');
}

/**
 * Tree-node row primitive — chevron + label + optional right-aligned count.
 * Indented by `depth` (one level = 12px). The chevron rotates when open.
 */
function TreeRow({
  depth,
  open,
  hasChildren,
  selected,
  label,
  count,
  onClick,
  title,
  trailing,
  disabled,
}: {
  depth: number;
  open?: boolean;
  hasChildren: boolean;
  selected?: boolean;
  label: string;
  count?: number;
  onClick: () => void;
  title?: string;
  trailing?: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className={
        'data-tree__row' +
        (selected ? ' data-tree__row--active' : '') +
        (disabled ? ' data-tree__row--disabled' : '')
      }
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{ paddingLeft: 8 + depth * 12 }}
    >
      <span
        className={
          'data-tree__chevron' +
          (hasChildren ? '' : ' data-tree__chevron--leaf') +
          (open ? ' data-tree__chevron--open' : '')
        }
        aria-hidden="true"
      >
        {hasChildren ? '›' : '•'}
      </span>
      <span className="data-tree__label">{label}</span>
      {count !== undefined && <span className="data-tree__count">{count}</span>}
      {trailing}
    </button>
  );
}

export function CategoryDatabaseList({
  databases,
  selectedCountry,
  recentCountries,
  onClearCountry,
  onChooseRecent,
  selectedDatabaseId,
  onSelectDatabase,
}: Props) {
  const tree = useMemo(() => buildTree(databases), [databases]);
  const [collapsed, setCollapsed] = usePersistedState<Record<string, boolean>>(COLLAPSE_KEY, {});

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

  if (!selectedCountry) {
    return (
      <aside className="view-rail view-rail--left data-import-rail">
        <div className="view-rail-header">
          <span>Data import</span>
        </div>
        <div className="view-rail-body data-import-rail__body">
          <p className="data-import-rail__hint">
            Pick a country on the map to begin. Click a country shape, or type its
            name in the search box at the top of the map.
          </p>
          {recentCountries.length > 0 && (
            <section>
              <h4 className="data-import-rail__section-label">Recently used</h4>
              <ul className="data-import-rail__list">
                {recentCountries.map((c) => (
                  <li key={c.iso}>
                    <button
                      type="button"
                      className="data-import-rail__country-item"
                      onClick={() => onChooseRecent(c.iso)}
                    >
                      <span>{c.name}</span>
                      <span className="data-import-rail__country-iso">{c.iso}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </aside>
    );
  }

  return (
    <aside className="view-rail view-rail--left data-import-rail">
      <div className="view-rail-header">
        <span>Data import</span>
        <button
          type="button"
          className="data-import-rail__country-clear"
          onClick={onClearCountry}
          title="Clear country selection"
        >
          Clear
        </button>
      </div>
      <div className="data-import-rail__country">
        <div className="data-import-rail__country-name">{selectedCountry.name}</div>
        <div className="data-import-rail__country-iso">{selectedCountry.iso}</div>
      </div>
      <div className="data-import-rail__tree-toolbar">
        <span className="data-import-rail__section-label">Databases</span>
        <span className="data-import-rail__tree-actions">
          <button type="button" onClick={collapseAll} title="Collapse all">–</button>
          <button type="button" onClick={expandAll} title="Expand all">+</button>
        </span>
      </div>
      <div className="view-rail-body data-tree">
        {tree.map((node) => {
          const catKey = nodeKey([node.category]);
          const catOpen = !isCollapsed(catKey);
          const dbCount = Array.from(node.subcategories.values()).reduce((n, list) => n + list.length, 0);
          return (
            <div key={node.category} className="data-tree__group">
              <TreeRow
                depth={0}
                open={catOpen}
                hasChildren
                label={CATEGORY_LABEL[node.category] || node.category}
                count={dbCount}
                onClick={() => toggle(catKey)}
              />
              {catOpen && (
                <div className="data-tree__children">
                  {Array.from(node.subcategories.entries()).map(([sub, dbs]) => {
                    const subKey = nodeKey([node.category, sub]);
                    const subOpen = !isCollapsed(subKey);
                    // When the subcategory is empty (UNCATEGORISED), flatten:
                    // render databases directly under the category at depth 1.
                    if (sub === UNCATEGORISED) {
                      return dbs.map((db) => (
                        <TreeRow
                          key={db.id}
                          depth={1}
                          hasChildren={false}
                          selected={db.id === selectedDatabaseId}
                          disabled={!db.available}
                          label={db.name}
                          onClick={() => db.available && onSelectDatabase(db.id)}
                          title={db.unavailable_reason || db.description || db.name}
                          trailing={
                            <span className="data-tree__hint" title={db.license}>{db.license}</span>
                          }
                        />
                      ));
                    }
                    return (
                      <div key={sub} className="data-tree__group">
                        <TreeRow
                          depth={1}
                          open={subOpen}
                          hasChildren
                          label={sub}
                          count={dbs.length}
                          onClick={() => toggle(subKey)}
                        />
                        {subOpen && (
                          <div className="data-tree__children">
                            {dbs.map((db) => (
                              <TreeRow
                                key={db.id}
                                depth={2}
                                hasChildren={false}
                                selected={db.id === selectedDatabaseId}
                                disabled={!db.available}
                                label={db.name}
                                onClick={() => db.available && onSelectDatabase(db.id)}
                                title={db.unavailable_reason || db.description || db.name}
                                trailing={
                                  <span className="data-tree__hint" title={db.license}>{db.license}</span>
                                }
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
    </aside>
  );
}
