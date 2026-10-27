import React, { useEffect, useMemo, useRef, useState } from 'react';
import { BackendRunMeta } from 'lib/types';
import { ComparisonResponse, fetchRunComparison } from 'lib/api/resultsDerived';
import { useAsync } from '../../shared/hooks/useAsync';
import { ComparisonMatrix, ComparisonScenario, ComparisonStatus } from './ComparisonMatrix';

// How many scenarios can sit side by side. The matrix fills the width with this
// many 1fr columns (+ a legend column), so the cap keeps each chart readable.
const MAX_SCENARIOS = 5;
// Topics shown by default; the others are switched on from the "Show" chips.
const DEFAULT_TOPICS = ['kpi', 'generation-mix'];

interface Props {
  /** Every backend-stored run meta (the single source of truth for history). */
  backendRuns: BackendRunMeta[];
  /** Name of the run currently shown in the viewer (highlighted as "active"). */
  activeRunName: string | null;
  currencySymbol?: string;
}

// ── Searchable multi-select scenario picker ───────────────────────────────────

function ScenarioPicker({ available, selected, max, onAdd, onRemove }: {
  available: BackendRunMeta[];
  selected: string[];
  max: number;
  onAdd: (name: string) => void;
  onRemove: (name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocMouseDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDocMouseDown);
    return () => document.removeEventListener('mousedown', onDocMouseDown);
  }, [open]);

  const byName = useMemo(() => new Map(available.map((r) => [r.name, r])), [available]);
  const full = selected.length >= max;
  const q = query.trim().toLowerCase();
  const candidates = available.filter(
    (r) => !selected.includes(r.name) && (q === '' || r.label.toLowerCase().includes(q)),
  );

  return (
    <div className="cmp-picker">
      <span className="cmp-toolbar-label">Scenarios <em>({selected.length}/{max})</em></span>

      {selected.map((name) => (
        <span key={name} className="cmp-sel-chip" title={byName.get(name)?.label || name}>
          <span className="cmp-sel-label">{byName.get(name)?.label || name}</span>
          <button type="button" className="cmp-sel-x" aria-label="Remove scenario" onClick={() => onRemove(name)}>×</button>
        </span>
      ))}

      <div className="cmp-dropdown" ref={ref}>
        <button
          type="button"
          className="cmp-add-btn"
          disabled={full}
          title={full ? `Remove a scenario to add another (max ${max})` : 'Add a scenario'}
          onClick={() => setOpen((o) => !o)}
        >
          + Add scenario
        </button>
        {open && !full && (
          <div className="cmp-dropdown-panel">
            <input
              autoFocus
              className="cmp-dropdown-search"
              placeholder="Search runs…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <div className="cmp-dropdown-list">
              {candidates.length === 0 ? (
                <div className="cmp-dropdown-empty">No matching runs</div>
              ) : (
                candidates.map((r) => (
                  <button key={r.name} type="button" className="cmp-dropdown-item" onClick={() => onAdd(r.name)}>
                    <span className="cmp-dropdown-item-label">{r.label}</span>
                    {r.scenarioYear ? <span className="cmp-dropdown-item-meta">{r.scenarioYear}</span> : null}
                  </button>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Comparison pane ───────────────────────────────────────────────────────────

export function ComparisonPane({ backendRuns, activeRunName, currencySymbol = '$' }: Props) {
  // Column order = chosen run names. The matrix data is one server request
  // (`GET /api/results/compare`) for the selected runs and the shown topics.
  const [selected, setSelected] = useState<string[]>(() => (activeRunName ? [activeRunName] : []));
  const [enabled, setEnabled] = useState<string[]>(DEFAULT_TOPICS);

  useEffect(() => {
    setSelected((prev) => {
      const next = prev.filter((n) => backendRuns.some((r) => r.name === n));
      return next.length === prev.length ? prev : next;
    });
  }, [backendRuns]);

  const metaByName = useMemo(() => new Map(backendRuns.map((r) => [r.name, r])), [backendRuns]);

  const request = selected.length >= 2 && enabled.length > 0
    ? `${selected.join(',')}|${[...enabled].sort().join(',')}`
    : null;
  const { data, loading, error } = useAsync<ComparisonResponse>(
    request,
    () => fetchRunComparison(selected, enabled),
  );
  const status: ComparisonStatus = error
    ? { state: 'error', message: error }
    : loading ? { state: 'loading' } : { state: 'ready' };

  const scenarios: ComparisonScenario[] = selected.flatMap((name) => {
    const m = metaByName.get(name);
    if (!m) return [];
    return [{
      name,
      label: m.label,
      entry: data?.items.find((it) => it.name === name),
      carrierColors: Object.fromEntries((m.carrierMix ?? []).map((c) => [c.label, c.color])),
    }];
  });

  const add = (name: string) =>
    setSelected((prev) => (prev.includes(name) || prev.length >= MAX_SCENARIOS ? prev : [...prev, name]));
  const remove = (name: string) => setSelected((prev) => prev.filter((n) => n !== name));
  const toggleTopic = (id: string) =>
    setEnabled((prev) => (prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]));

  if (backendRuns.length < 2) {
    return (
      <div className="analytics-empty">
        <h3>No runs to compare yet</h3>
        <p>Run the model at least twice. Every run is stored automatically and can be picked here.</p>
      </div>
    );
  }

  return (
    <div className="cmp-root">
      <ScenarioPicker available={backendRuns} selected={selected} max={MAX_SCENARIOS} onAdd={add} onRemove={remove} />

      {scenarios.length < 2 ? (
        <div className="analytics-empty">
          <h3>Pick at least two scenarios</h3>
          <p>Use “Add scenario” above to choose runs to compare side by side (up to {MAX_SCENARIOS}).</p>
        </div>
      ) : (
        <ComparisonMatrix
          scenarios={scenarios}
          status={status}
          activeRunName={activeRunName}
          currencySymbol={currencySymbol}
          enabled={enabled}
          onToggleTopic={toggleTopic}
          onReorder={setSelected}
        />
      )}
    </div>
  );
}
