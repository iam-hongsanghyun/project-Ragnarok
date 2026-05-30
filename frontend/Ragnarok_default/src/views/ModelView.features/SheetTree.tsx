/**
 * Sheet tree — component → attribute navigator.
 *
 * Only sheets with at least one row are shown; empty sheets and
 * temporal sheets without data are hidden. Selecting a leaf flips
 * the central table view to that sheet.
 */
import React, { useMemo, useState } from 'react';
import { GridRow, SheetName, TableSel, WorkbookModel } from '../../shared/types';
import { ModelIssue } from '../../features/validation/useModelIssues';
import { TABLE_GROUPS } from '../../constants';

interface Props {
  model: WorkbookModel;
  issues: ModelIssue[];
  sel: TableSel;
  onSelChange: (sel: TableSel) => void;
}

export function SheetTree({ model, issues, sel, onSelChange }: Props) {
  const [navSearch, setNavSearch] = useState('');
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const issueCounts = useMemo(() => {
    const counts: Record<string, { errors: number; warnings: number }> = {};
    issues.forEach((issue) => {
      if (!counts[issue.sheet]) counts[issue.sheet] = { errors: 0, warnings: 0 };
      if (issue.severity === 'error') counts[issue.sheet].errors++;
      else counts[issue.sheet].warnings++;
    });
    return counts;
  }, [issues]);

  const toggleGroup = (sheet: string) =>
    setCollapsed((s) => {
      const n = new Set(s);
      n.has(sheet) ? n.delete(sheet) : n.add(sheet);
      return n;
    });

  const matchesSearch = (haystack: string) =>
    !navSearch || haystack.toLowerCase().includes(navSearch.toLowerCase());

  // Only groups whose static sheet OR any temporal sheet has data.
  const visibleGroups = TABLE_GROUPS.filter((g) => {
    const staticRows = (model[g.sheet] ?? []) as GridRow[];
    const hasStatic = staticRows.length > 0;
    const hasAnyTs = g.temporalSheets.some(
      (ts) => (((model as unknown as Record<string, GridRow[]>)[ts.sheet]) ?? []).length > 0,
    );
    if (!hasStatic && !hasAnyTs) return false;
    if (!navSearch) return true;
    return (
      matchesSearch(g.label) ||
      matchesSearch(g.sheet) ||
      g.temporalSheets.some((ts) => matchesSearch(ts.attribute))
    );
  });

  return (
    <nav className="sheet-tree" aria-label="Component sheets">
      <div className="sheet-tree-header">
        <span className="sheet-tree-title">Model</span>
      </div>
      <div className="sheet-tree-toolbar">
        <input
          className="sheet-tree-search"
          type="text"
          placeholder="Filter…"
          value={navSearch}
          onChange={(e) => setNavSearch(e.target.value)}
          aria-label="Filter components"
        />
        <button
          className="tb-btn tb-btn--muted"
          onClick={() => setCollapsed(new Set(TABLE_GROUPS.map((g) => g.sheet)))}
          title="Collapse all"
        >
          –
        </button>
        <button
          className="tb-btn tb-btn--muted"
          onClick={() => setCollapsed(new Set())}
          title="Expand all"
        >
          +
        </button>
      </div>

      <div className="sheet-tree-body">
        {visibleGroups.length === 0 && (
          <p className="sheet-tree-empty">No components with data yet.</p>
        )}
        {visibleGroups.map((g) => {
          const staticRows = (model[g.sheet] ?? []) as GridRow[];
          const hasStatic = staticRows.length > 0;
          const open = !collapsed.has(g.sheet);
          const staticActive = sel.kind === 'static' && sel.sheet === g.sheet;

          // Only temporal sheets with data
          const tsEntries = g.temporalSheets.filter(
            (ts) => (((model as unknown as Record<string, GridRow[]>)[ts.sheet]) ?? []).length > 0,
          );

          return (
            <div key={g.sheet} className="sheet-tree-group">
              <button
                className="sheet-tree-group-header"
                onClick={() => toggleGroup(g.sheet)}
                aria-expanded={open}
              >
                <span className={`sheet-tree-chevron${open ? ' is-open' : ''}`}>›</span>
                <span className="sheet-tree-group-label">{g.label}</span>
                <span className="sheet-tree-count">{staticRows.length + tsEntries.length}</span>
              </button>
              {open && (
                <div className="sheet-tree-items">
                  {hasStatic && (
                    <button
                      className={`sheet-tree-item${staticActive ? ' is-active' : ''}`}
                      onClick={() => onSelChange({ kind: 'static', sheet: g.sheet as SheetName })}
                    >
                      <span className="sheet-tree-item-icon">≡</span>
                      <span className="sheet-tree-item-label">static</span>
                      <span className="sheet-tree-count">{staticRows.length}</span>
                      {issueCounts[g.sheet]?.errors > 0 && (
                        <span className="sheet-tree-badge is-error">{issueCounts[g.sheet].errors}</span>
                      )}
                      {!issueCounts[g.sheet]?.errors && issueCounts[g.sheet]?.warnings > 0 && (
                        <span className="sheet-tree-badge is-warning">{issueCounts[g.sheet].warnings}</span>
                      )}
                    </button>
                  )}
                  {tsEntries.map((ts) => {
                    const tsRows = ((model as unknown as Record<string, GridRow[]>)[ts.sheet]) ?? [];
                    const tsActive = sel.kind === 'ts' && sel.sheet === ts.sheet;
                    return (
                      <button
                        key={ts.sheet}
                        className={`sheet-tree-item is-ts${tsActive ? ' is-active' : ''}`}
                        onClick={() => onSelChange({ kind: 'ts', sheet: ts.sheet })}
                      >
                        <span className="sheet-tree-item-icon">t</span>
                        <span className="sheet-tree-item-label">{ts.attribute}</span>
                        <span className="sheet-tree-count">{tsRows.length}</span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </nav>
  );
}
