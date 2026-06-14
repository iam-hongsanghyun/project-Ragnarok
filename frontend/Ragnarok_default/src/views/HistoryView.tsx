/**
 * History view — browse and manage persisted past runs.
 *
 * The backend is the single source of truth for run history: every successful
 * solve is stored server-side (see backend/app/run_store.py) and listed here as
 * a lightweight meta sidecar, so a full-year result never has to be downloaded
 * just to enumerate runs. Each row offers a select checkbox (drives bulk
 * delete), name + metadata, and inline actions: View results (fetches the full
 * bundle into the viewer), Download Excel, Delete.
 */
import React, { useMemo, useState } from 'react';
import { BackendRunMeta } from 'lib/types';
import { formatRelTime } from 'lib/utils/formatRelTime';
import { usePersistedState } from 'shared/hooks/usePersistedState';

/** localStorage key for the user's manual drag-and-drop ordering of runs (by name). */
const ORDER_KEY = 'ragnarok.history.manualOrder';

interface HistoryViewProps {
  backendRuns: BackendRunMeta[];
  /** View the current selection: 1 → its Result, 2+ → side-by-side Comparison. */
  onViewSelected: (names: string[]) => void;
  /** Import the run's model into the editable session for edit + re-run (heavy). */
  onImportBackendRun: (name: string) => void;
  /** Import an external Excel results file as a new persistent History entry. */
  onImportResult: () => void;
  /** Filenames of result imports currently converting — shown as placeholder
   *  rows so a slow (tens-of-seconds) import doesn't read as "nothing happened". */
  convertingImports?: string[];
  /** Per-run in-flight activity (name → "Importing" / "Exporting" / "Deleting"),
   *  shown as a spinner + label on that row. */
  runActivity?: Record<string, string>;
  /** Explicit Excel export; `parts` ⊆ ['metadata','model','result'] selects sheet groups. */
  onDownloadBackendXlsx: (name: string, parts: string[]) => void;
  /** Download the full project package (.zip of bundle JSON + meta JSON + xlsx). */
  onExportBackendProject: (name: string) => void;
  onDeleteBackendRuns: (names: string[]) => void;
  /** Rename a stored run — click the row label to edit it in place. */
  onRenameBackendRun: (name: string, newName: string) => void;
  /** Manually re-fetch the run list from the backend. */
  onReload?: () => void;
}

/**
 * Reorder a list of run names after a drag-and-drop: lift `names[fromIndex]`
 * out and reinsert it relative to `names[toIndex]` — below the target when the
 * drag moved downward, above it when the drag moved upward. Returns a new array
 * (the input is not mutated). A no-op `fromIndex === toIndex` returns a copy.
 */
export function reorderNames(names: string[], fromIndex: number, toIndex: number): string[] {
  if (fromIndex === toIndex) return [...names];
  const dragged = names[fromIndex];
  const without = names.filter((n) => n !== dragged);
  let insertAt = without.indexOf(names[toIndex]);
  if (fromIndex < toIndex) insertAt += 1;
  without.splice(insertAt, 0, dragged);
  return without;
}

/** Case-insensitive match for a backend run's meta. */
export function matchesBackendQuery(meta: BackendRunMeta, query: string): boolean {
  if (!query) return true;
  const needle = query.toLowerCase();
  const haystack = [
    meta.label,
    meta.name,
    meta.filename,
    meta.savedAt,
    new Date(meta.savedAt).toLocaleString(),
  ]
    .join(' ')
    .toLowerCase();
  return haystack.includes(needle);
}

export function HistoryView({
  backendRuns,
  onViewSelected,
  onImportBackendRun,
  onImportResult,
  convertingImports,
  runActivity,
  onDownloadBackendXlsx,
  onExportBackendProject,
  onDeleteBackendRuns,
  onRenameBackendRun,
  onReload,
}: HistoryViewProps) {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  // Manual drag-and-drop order, persisted by run name. Empty → fall back to the
  // default newest-first (savedAt) sort. Once the user drags a row, the whole
  // visible order is captured here and from then on the list follows it; brand
  // new runs (not yet placed) surface at the top so they're never hidden.
  const [manualOrder, setManualOrder] = usePersistedState<string[]>(ORDER_KEY, []);
  // Index of the row being dragged and the row currently hovered, for the live
  // drop indicator. Both null when no drag is in progress.
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);
  // Export dialog: which run is being exported (null = closed) + the three
  // sheet-group checkboxes. All on by default so the file is a complete,
  // PyPSA-import-ready workbook with the Result included.
  const [exportFor, setExportFor] = useState<string | null>(null);
  const [exportParts, setExportParts] = useState({ metadata: true, model: true, result: true });

  const filtered = useMemo(
    () => backendRuns.filter((meta) => matchesBackendQuery(meta, query)),
    [backendRuns, query],
  );

  // Default order: newest first. The manual order (if any) then takes over —
  // placed runs follow it; anything not yet placed stays newest-first on top.
  const sorted = useMemo(() => {
    const byDate = [...filtered].sort((a, b) =>
      a.savedAt < b.savedAt ? 1 : a.savedAt > b.savedAt ? -1 : 0,
    );
    if (manualOrder.length === 0) return byDate;
    const rank = new Map(manualOrder.map((name, i) => [name, i]));
    const placed = byDate.filter((m) => rank.has(m.name)).sort((a, b) => rank.get(a.name)! - rank.get(b.name)!);
    const unplaced = byDate.filter((m) => !rank.has(m.name));
    return [...unplaced, ...placed];
  }, [filtered, manualOrder]);

  const visibleNames = useMemo(() => sorted.map((m) => m.name), [sorted]);

  // Reordering only makes sense over the full, unfiltered list — a drag within
  // a search-filtered subset would silently rearrange hidden rows. So the drag
  // handles are live only when no search query is active.
  const reorderable = query.trim() === '';

  const onRowDragStart = (index: number) => (e: React.DragEvent) => {
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', String(index));
    setDragIndex(index);
  };
  const onRowDragOver = (index: number) => (e: React.DragEvent) => {
    if (dragIndex === null) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setOverIndex(index);
  };
  const endDrag = () => { setDragIndex(null); setOverIndex(null); };
  const onRowDrop = (index: number) => (e: React.DragEvent) => {
    e.preventDefault();
    if (dragIndex === null || dragIndex === index) { endDrag(); return; }
    // Capture the current visible order and reinsert the dragged run relative to
    // the hovered row; this "freezes" the merged order into the explicit one.
    setManualOrder(reorderNames(visibleNames, dragIndex, index));
    endDrag();
  };
  const visibleSelected = useMemo(
    () => selected.filter((n) => visibleNames.includes(n)),
    [selected, visibleNames],
  );
  const allVisibleSelected = visibleNames.length > 0 && visibleSelected.length === visibleNames.length;

  const toggleName = (name: string, checked: boolean) =>
    setSelected((prev) => (checked ? (prev.includes(name) ? prev : [...prev, name]) : prev.filter((n) => n !== name)));

  const toggleSelectAll = (checked: boolean) => setSelected(checked ? visibleNames : []);

  const deleteSelected = () => {
    if (visibleSelected.length === 0) return;
    onDeleteBackendRuns(visibleSelected);
    setSelected([]);
  };

  // Actions live at the top and act on the selection: Import needs exactly one
  // model; View shows one run's Result, or several side-by-side in Comparison.
  const single = visibleSelected.length === 1 ? visibleSelected[0] : null;
  const n = visibleSelected.length;

  return (
    <div className="history-view">
      <div className="history-toolbar">
        <input
          className="history-search"
          type="text"
          placeholder="Search runs by name, file, or date"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label className="history-select-all">
          <input
            type="checkbox"
            checked={allVisibleSelected}
            onChange={(e) => toggleSelectAll(e.target.checked)}
            disabled={visibleNames.length === 0}
          />
          Select all
        </label>
        <button
          className="tb-btn tb-btn--primary"
          onClick={() => onViewSelected(visibleSelected)}
          disabled={n === 0}
          title={n > 1 ? 'Compare the selected runs side by side' : 'View this run’s results'}
        >
          {n > 1 ? `Compare results (${n})` : 'View result'}
        </button>
        <button
          className="tb-btn"
          onClick={() => single && onImportBackendRun(single)}
          disabled={!single}
          title={single ? 'Load this run’s model into the editor to edit and re-run' : 'Select exactly one run to import'}
        >
          Import project
        </button>
        <button
          className="tb-btn"
          onClick={() => single && onExportBackendProject(single)}
          disabled={!single}
          title="Download the full project package (.zip of bundle + meta + workbook)"
        >
          Project .zip
        </button>
        <button
          className="tb-btn"
          onClick={() => single && setExportFor(single)}
          disabled={!single}
          title="Export an Excel workbook (choose Metadata / Model / Result)"
        >
          Excel .xlsx
        </button>
        <span className="history-toolbar-spacer" />
        <button
          className="tb-btn"
          onClick={onImportResult}
          title="Import a project .zip (model + results) or a results .xlsx as a new, permanent History entry"
        >
          Import result
        </button>
        <button className="tb-btn" onClick={deleteSelected} disabled={n === 0}>
          Delete ({n})
        </button>
        {manualOrder.length > 0 && (
          <button
            className="tb-btn"
            onClick={() => setManualOrder([])}
            title="Discard the custom drag order and sort newest-first again"
          >
            Reset order
          </button>
        )}
        {onReload && (
          <button className="tb-btn" onClick={onReload} title="Re-fetch run history from the backend">
            Reload
          </button>
        )}
      </div>

      {sorted.length === 0 && (convertingImports?.length ?? 0) === 0 ? (
        <div className="history-empty">
          {backendRuns.length === 0
            ? 'No saved runs yet — run the model to populate history.'
            : 'No runs match your search.'}
        </div>
      ) : (
        <div className="history-list">
          {(convertingImports ?? []).map((filename) => (
            <div key={`converting:${filename}`} className="history-row history-row--converting">
              <span className="history-row-spinner" aria-hidden="true" />
              <span className="history-row-name">{filename}</span>
              <span className="history-row-chip history-row-chip--converting">Converting…</span>
              <span className="history-row-spacer" />
            </div>
          ))}
          {sorted.map((meta, index) => (
            <BackendHistoryRow
              key={meta.name}
              meta={meta}
              selected={visibleSelected.includes(meta.name)}
              activity={runActivity?.[meta.name]}
              reorderable={reorderable}
              dragging={dragIndex === index}
              dropEdge={
                overIndex === index && dragIndex !== null && dragIndex !== index
                  ? dragIndex < index ? 'after' : 'before'
                  : null
              }
              onGripDragStart={onRowDragStart(index)}
              onRowDragOver={onRowDragOver(index)}
              onRowDrop={onRowDrop(index)}
              onDragEnd={endDrag}
              onSelect={(checked) => toggleName(meta.name, checked)}
              onActivate={() => onViewSelected([meta.name])}
              onRename={(newName) => onRenameBackendRun(meta.name, newName)}
            />
          ))}
        </div>
      )}

      {exportFor && (
        <div className="modal-backdrop" onClick={() => setExportFor(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="validation-report">
              <span className="validation-eyebrow">Export</span>
              <h2>Export Excel</h2>
              <p className="sg-setting-hint">
                Builds one workbook on demand from <b>{exportFor}</b> — nothing is
                stored server-side. With all three parts selected the file is
                PyPSA-import-ready.
              </p>
              <div className="validation-section">
                <h3>Include</h3>
                {([
                  ['model', 'Model', 'PyPSA component sheets, input time-series, snapshots'],
                  ['result', 'Result', 'Solved outputs: optimal capacities, dispatch series, result meta'],
                  ['metadata', 'Metadata', 'Ragnarok config: scenarios, constraints, run state, settings'],
                ] as const).map(([key, label, hint]) => (
                  <label key={key} className="modal-check-row">
                    <input
                      type="checkbox"
                      checked={exportParts[key]}
                      onChange={(e) => setExportParts((p) => ({ ...p, [key]: e.target.checked }))}
                    />
                    <span><b>{label}</b> — {hint}</span>
                  </label>
                ))}
              </div>
              <div className="modal-actions" style={{ gap: 8 }}>
                <button className="tb-btn" onClick={() => setExportFor(null)}>Cancel</button>
                <button
                  className="tb-btn tb-btn--primary"
                  disabled={!exportParts.metadata && !exportParts.model && !exportParts.result}
                  onClick={() => {
                    const parts = (['metadata', 'model', 'result'] as const).filter((k) => exportParts[k]);
                    onDownloadBackendXlsx(exportFor, parts);
                    setExportFor(null);
                  }}
                >
                  Download .xlsx
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** Annual energy demand (MWh) → a compact TWh / GWh / MWh label. */
function formatDemand(mwh: number | null | undefined): string | null {
  if (mwh == null || !Number.isFinite(mwh) || mwh <= 0) return null;
  if (mwh >= 1e6) return `${(mwh / 1e6).toLocaleString(undefined, { maximumFractionDigits: 1 })} TWh`;
  if (mwh >= 1e3) return `${(mwh / 1e3).toLocaleString(undefined, { maximumFractionDigits: 1 })} GWh`;
  return `${Math.round(mwh).toLocaleString()} MWh`;
}

// ── Backend (server-stored) run row ─────────────────────────────────────────

function BackendHistoryRow({
  meta, selected, activity, reorderable, dragging, dropEdge,
  onGripDragStart, onRowDragOver, onRowDrop, onDragEnd,
  onSelect, onActivate, onRename,
}: {
  meta: BackendRunMeta;
  selected: boolean;
  /** In-flight action on this run ("Importing" / "Exporting" / "Deleting"), or undefined. */
  activity?: string;
  /** Whether the drag handle is live (false while a search query is filtering rows). */
  reorderable: boolean;
  /** This row is the one currently being dragged. */
  dragging: boolean;
  /** Show a drop indicator on this row's top ('before') or bottom ('after') edge. */
  dropEdge: 'before' | 'after' | null;
  onGripDragStart: (e: React.DragEvent) => void;
  onRowDragOver: (e: React.DragEvent) => void;
  onRowDrop: (e: React.DragEvent) => void;
  onDragEnd: () => void;
  onSelect: (checked: boolean) => void;
  /** Double-click / Enter on the row → view this single run (toolbar handles the rest). */
  onActivate: () => void;
  /** Commit an in-place rename (Enter / blur); the backend renames identity + labels together. */
  onRename: (newName: string) => void;
}) {
  // The run's display name IS the scenario name (falls back to the stored label).
  const name = meta.scenarioLabel || meta.label || meta.name;

  // Click the label to rename in place (same affordance as scenario labels in
  // Settings). Editing starts from the CANONICAL run name — the filesystem/API
  // identity — not the display label; after a rename the backend sets both.
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(meta.name);
  const commit = () => {
    setEditing(false);
    const next = draft.trim();
    if (next && next !== meta.name) onRename(next);
  };

  // Rows are otherwise display-only: select with the checkbox (or click the
  // row), then use the toolbar actions at the top. This keeps every row a
  // clean, aligned line instead of a ragged strip of buttons.
  const rowClass =
    `history-row${selected ? ' is-selected' : ''}${dragging ? ' is-dragging' : ''}` +
    (dropEdge ? ` is-drop-${dropEdge}` : '');

  return (
    <div
      className={rowClass}
      onDoubleClick={onActivate}
      onDragOver={reorderable ? onRowDragOver : undefined}
      onDrop={reorderable ? onRowDrop : undefined}
    >
      {reorderable && (
        <span
          className="history-row-grip"
          draggable
          onDragStart={onGripDragStart}
          onDragEnd={onDragEnd}
          onClick={(e) => e.stopPropagation()}
          onDoubleClick={(e) => e.stopPropagation()}
          title="Drag to reorder"
          aria-label={`Reorder ${name}`}
          role="button"
        >
          ⠿
        </span>
      )}
      <input
        type="checkbox"
        className="history-row-select"
        checked={selected}
        onChange={(e) => onSelect(e.target.checked)}
        aria-label={`Select ${name}`}
      />

      {editing ? (
        <input
          className="history-row-name-input"
          value={draft}
          autoFocus
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit();
            if (e.key === 'Escape') { setEditing(false); setDraft(meta.name); }
          }}
          onClick={(e) => e.stopPropagation()}
          onDoubleClick={(e) => e.stopPropagation()}
          aria-label={`Rename ${meta.name}`}
        />
      ) : (
        <span
          className="history-row-name history-row-name--editable"
          title={`${meta.name} — click to rename`}
          onClick={(e) => { e.stopPropagation(); setDraft(meta.name); setEditing(true); }}
          onDoubleClick={(e) => e.stopPropagation()}
        >
          {name}
        </span>
      )}

      <span className="history-row-time" title={new Date(meta.savedAt).toLocaleString()}>
        {formatRelTime(meta.savedAt)}
      </span>
      {meta.origin === 'xlsx_import' && (
        <span
          className="history-row-chip history-row-chip--imported"
          title="Imported from an external Excel results file (not a solve)"
        >
          imported
        </span>
      )}
      {meta.scenarioYear != null && <span className="history-row-chip">{meta.scenarioYear}</span>}
      {meta.resolutionHours != null && <span className="history-row-chip">{meta.resolutionHours}h res</span>}
      {meta.windowCount != null && meta.windowCount > 0 && (
        <span className="history-row-chip">{meta.windowCount} batches</span>
      )}
      {formatDemand(meta.totalDemandMwh) && (
        <span className="history-row-kpi"><b>{formatDemand(meta.totalDemandMwh)}</b> demand</span>
      )}
      {(meta.tags ?? []).map((t) => (
        <span key={t} className="history-row-chip history-row-chip--tag">{t}</span>
      ))}

      <span className="history-row-spacer" />
      {activity && (
        <span className="history-row-activity" role="status">
          <span className="topbar-spinner" aria-hidden="true" />
          {activity}…
        </span>
      )}
    </div>
  );
}
