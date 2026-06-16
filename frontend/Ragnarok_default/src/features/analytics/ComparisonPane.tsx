import React, { useEffect, useMemo, useRef, useState } from 'react';
import { API_BASE } from 'lib/constants';
import { BackendRunMeta, RunResults } from 'lib/types';
import { ComparisonMatrix, ComparisonScenario, topicNeedsFull } from './ComparisonMatrix';

// How many scenarios can sit side by side. The matrix fills the width with this
// many 1fr columns (+ a legend column), so the cap keeps each chart readable.
const MAX_SCENARIOS = 5;
// Light topics on by default; the heavier (full-data) ones are added on demand.
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
  // Column order = chosen run names. Light topics render from the in-memory run
  // meta (carrierMix + summary). FULL topics lazily fetch each selected run's
  // analytics — only once such a topic is switched on (see the effect below).
  const [selected, setSelected] = useState<string[]>(() => (activeRunName ? [activeRunName] : []));
  const [enabled, setEnabled] = useState<string[]>(DEFAULT_TOPICS);

  useEffect(() => {
    setSelected((prev) => {
      const next = prev.filter((n) => backendRuns.some((r) => r.name === n));
      return next.length === prev.length ? prev : next;
    });
  }, [backendRuns]);

  const metaByName = useMemo(() => new Map(backendRuns.map((r) => [r.name, r])), [backendRuns]);

  // Lazy full-results cache, populated only when a FULL topic is active.
  const [fullCache, setFullCache] = useState<Record<string, RunResults | 'loading' | 'error'>>({});
  const needFull = enabled.some(topicNeedsFull);

  useEffect(() => {
    if (!needFull) return;
    const fetchOne = async (name: string) => {
      try {
        const resp = await fetch(`${API_BASE}/api/runs/${encodeURIComponent(name)}/analytics`);
        if (!resp.ok) throw new Error('fetch failed');
        const bundle = await resp.json();
        setFullCache((c) => ({ ...c, [name]: (bundle.result ?? {}) as RunResults }));
      } catch {
        setFullCache((c) => ({ ...c, [name]: 'error' }));
      }
    };
    for (const name of selected) {
      if (fullCache[name]) continue; // loading / loaded / errored
      setFullCache((c) => ({ ...c, [name]: 'loading' }));
      void fetchOne(name);
    }
  }, [selected, needFull]); // eslint-disable-line react-hooks/exhaustive-deps -- fullCache read but not a trigger

  const scenarios: ComparisonScenario[] = selected.flatMap((name) => {
    const m = metaByName.get(name);
    if (!m) return [];
    return [{
      name,
      label: m.label,
      carrierMix: m.carrierMix ?? [],
      summary: m.summary ?? [],
      full: needFull ? (fullCache[name] ?? 'loading') : undefined,
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
