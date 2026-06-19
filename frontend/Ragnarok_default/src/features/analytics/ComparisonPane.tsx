import React, { useEffect, useMemo, useRef, useState } from 'react';
import { API_BASE } from 'lib/constants';
import { BackendRunMeta, MixItem, RunResults, SummaryItem } from 'lib/types';
import { carrierColor, numberValue, stringValue } from 'lib/utils/helpers';
import { ComparisonMatrix, ComparisonScenario, topicNeedsFull } from './ComparisonMatrix';

interface CapacityInfo {
  /** Installed nameplate (input p_nom) by carrier — the energy-carrierMix analogue. */
  mix: MixItem[];
  /** Total installed generator nameplate (Σ generators.p_nom). */
  genCap: number;
  /** Total installed storage nameplate (Σ storage_units.p_nom). */
  storCap: number;
}

/** Derive installed nameplate capacity from a run's input model (modelStatic),
 *  so it's available for any stored run without re-solving. */
function capacityInfoFromModel(modelStatic: unknown): CapacityInfo {
  const root = modelStatic as {
    generators?: Array<Record<string, unknown>>;
    storage_units?: Array<Record<string, unknown>>;
  } | null;
  const byCarrier = new Map<string, number>();
  let genCap = 0;
  for (const r of root?.generators ?? []) {
    const name = stringValue(r.name as string | number | undefined);
    if (!name || name.startsWith('load_shedding_')) continue;
    const p = numberValue(r.p_nom as string | number | undefined);
    genCap += p;
    const carrier = stringValue(r.carrier as string | number | undefined) || 'Other';
    byCarrier.set(carrier, (byCarrier.get(carrier) ?? 0) + p);
  }
  let storCap = 0;
  for (const r of root?.storage_units ?? []) {
    if (!stringValue(r.name as string | number | undefined)) continue;
    storCap += numberValue(r.p_nom as string | number | undefined);
  }
  const mix = Array.from(byCarrier.entries())
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([label, value]) => ({ label, value, color: carrierColor(label) }));
  return { mix, genCap, storCap };
}

/** Replace the stored single "Installed capacity" / "Reserve position" KPIs with
 *  the Generator + Storage split (matching the result view), once the run's model
 *  has been fetched. Newer runs already carry the split, so there's nothing to
 *  replace. */
function splitCapacitySummary(base: SummaryItem[], info: CapacityInfo | undefined): SummaryItem[] {
  if (!info) return base;
  const mw = (n: number) => `${Math.round(n).toLocaleString()} MW`;
  const peakItem = base.find((s) => /^peak demand$/i.test(s.label.trim()));
  const peak = peakItem ? Number(peakItem.value.replace(/[^\d.-]/g, '')) || 0 : 0;
  const out: SummaryItem[] = [];
  for (const item of base) {
    if (/^installed capacity$/i.test(item.label.trim())) {
      out.push({ label: 'Generator capacity', value: mw(info.genCap), detail: 'installed nameplate' });
      out.push({ label: 'Storage capacity', value: mw(info.storCap), detail: 'installed nameplate' });
    } else if (/^reserve position$/i.test(item.label.trim())) {
      out.push({ label: 'Generator reserve', value: mw(info.genCap - peak), detail: 'generator capacity vs peak demand' });
      out.push({ label: 'Storage reserve', value: mw(info.storCap - peak), detail: 'storage capacity vs peak demand' });
    } else {
      out.push(item);
    }
  }
  return out;
}

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
  // Installed capacity (input p_nom: per-carrier mix + gen/storage totals),
  // derived from the same fetch.
  const [capacityCache, setCapacityCache] = useState<Record<string, CapacityInfo>>({});
  const needFull = enabled.some(topicNeedsFull);

  useEffect(() => {
    if (!needFull) return;
    const fetchOne = async (name: string) => {
      try {
        const resp = await fetch(`${API_BASE}/api/runs/${encodeURIComponent(name)}/analytics`);
        if (!resp.ok) throw new Error('fetch failed');
        const bundle = await resp.json();
        setFullCache((c) => ({ ...c, [name]: (bundle.result ?? {}) as RunResults }));
        setCapacityCache((c) => ({ ...c, [name]: capacityInfoFromModel(bundle.modelStatic) }));
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
    const capInfo = capacityCache[name];
    return [{
      name,
      label: m.label,
      carrierMix: m.carrierMix ?? [],
      capacityMix: capInfo?.mix ?? [],
      summary: splitCapacitySummary(m.summary ?? [], capInfo),
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
