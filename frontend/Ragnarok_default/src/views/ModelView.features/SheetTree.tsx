/**
 * Sheet tree — component → attribute navigator.
 *
 * Only sheets with at least one row are shown; empty sheets are hidden.
 * Temporal (time-series) sheets are stripped from the in-memory model (they
 * live in the backend session and are paged into the grid on demand), so their
 * presence + row count come from `seriesSheetCounts` — the session's series
 * sheets. Selecting a temporal leaf flips the central table to it, which then
 * lazy-loads its rows from the session.
 */
import React, { useMemo, useState } from 'react';
import { GridRow, SheetName, TableSel, WorkbookModel } from 'lib/types';
import { ModelIssue } from '../../features/validation/useModelIssues';
import { TABLE_GROUPS } from 'lib/constants';

/** The shared time axis every temporal sheet is indexed by. */
const SNAPSHOTS_SHEET = 'snapshots';

interface Props {
  model: WorkbookModel;
  issues: ModelIssue[];
  sel: TableSel;
  onSelChange: (sel: TableSel) => void;
  /** Temporal sheet name → row count in the backend session. Series sheets are
   *  not held in the in-memory model, so this is what makes them visible and
   *  selectable in the tree (the table loads the rows on demand when selected). */
  seriesSheetCounts?: Record<string, number>;
}

export function SheetTree({ model, issues, sel, onSelChange, seriesSheetCounts }: Props) {
  // Row count for a temporal sheet: the session's count (source of truth, since
  // series aren't kept in the in-memory model), else any in-memory rows.
  const tsCount = (sheet: string): number =>
    seriesSheetCounts?.[sheet] ?? ((model as unknown as Record<string, GridRow[]>)[sheet]?.length ?? 0);
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

  // Only groups whose static sheet OR any temporal sheet has data — plus
  // `snapshots`, which is ALWAYS listed. Snapshots are the one shared time axis
  // every temporal sheet is indexed by, so an empty one has to be reachable or a
  // from-scratch model can never get a time axis (and then no profile can be
  // written or imported either).
  const visibleGroups = TABLE_GROUPS.filter((g) => {
    const staticRows = (model[g.sheet] ?? []) as GridRow[];
    const hasStatic = staticRows.length > 0 || g.sheet === SNAPSHOTS_SHEET;
    const hasAnyTs = g.temporalSheets.some((ts) => tsCount(ts.sheet) > 0);
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
          // `snapshots` keeps its leaf even at zero rows — that empty sheet is
          // where the time axis gets authored (see `visibleGroups`).
          const hasStatic = staticRows.length > 0 || g.sheet === SNAPSHOTS_SHEET;
          const open = !collapsed.has(g.sheet);
          const staticActive = sel.kind === 'static' && sel.sheet === g.sheet;

          // Temporal sheets that hold rows — PLUS, once the component itself
          // exists, the ones that are still empty.
          //
          // An empty profile has to be reachable: the CSV importer for a
          // temporal sheet lives on that sheet's own pane, so hiding it until it
          // had rows made it impossible to create — you needed rows to reach the
          // UI that adds rows (Build's Temporal panel was the only way in).
          // With no static row there is nothing to profile, so those stay hidden.
          const tsEntries = g.temporalSheets.filter((ts) => tsCount(ts.sheet) > 0 || hasStatic);
          // The header badge stays a count of sheets that actually hold data —
          // the empty placeholders above are affordances, not content.
          const tsWithRows = tsEntries.filter((ts) => tsCount(ts.sheet) > 0);

          return (
            <div key={g.sheet} className="sheet-tree-group">
              <button
                className="sheet-tree-group-header"
                onClick={() => toggleGroup(g.sheet)}
                aria-expanded={open}
              >
                <span className={`sheet-tree-chevron${open ? ' is-open' : ''}`}>›</span>
                <span className="sheet-tree-group-label">{g.label}</span>
                <span className="sheet-tree-count">{staticRows.length + tsWithRows.length}</span>
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
                    const tsActive = sel.kind === 'ts' && sel.sheet === ts.sheet;
                    const tsRows = tsCount(ts.sheet);
                    return (
                      <button
                        key={ts.sheet}
                        className={`sheet-tree-item is-ts${tsActive ? ' is-active' : ''}${tsRows === 0 ? ' is-empty' : ''}`}
                        onClick={() => onSelChange({ kind: 'ts', sheet: ts.sheet })}
                        title={tsRows === 0
                          ? `No ${ts.attribute} profile yet — open it to import a CSV`
                          : `${ts.attribute}: ${tsRows} rows`}
                      >
                        <span className="sheet-tree-item-icon">t</span>
                        <span className="sheet-tree-item-label">{ts.attribute}</span>
                        <span className="sheet-tree-count">{tsRows}</span>
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
