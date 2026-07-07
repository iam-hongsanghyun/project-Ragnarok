/**
 * Forge — data-handling workspace.
 *
 * Bulk operations that shape the imported model into solver-ready form,
 * sitting between Data (import) and Build/Model (edit):
 *
 *   1. Round / Ceil / Floor selected numeric attributes.
 *   2. Snap components to their nearest bus by great-circle distance,
 *      within a km buffer (sets bus / bus0 / bus1).
 *
 * The view is presentation + orchestration only; the numeric and spatial
 * logic lives in `lib/forge/*` so it is unit-tested independently.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import type { GridRow, WorkbookModel } from 'lib/types';
import { usePersistedState } from 'shared/hooks/usePersistedState';
import { FORGE_CONFIG, VALIDATION_CONFIG } from 'lib/constants';
import { LeftRail, ViewPanel } from 'shared/components/primitives';
import { NumberDraftInput } from 'shared/components/NumberDraftInput';
import { applyRounding, busColumns, numericColumns, type RoundOp, type ClusterResult } from 'lib/forge/transforms';
import {
  buildTargets,
  sheetSnappable,
  snapSheet,
  type OutsideEntry,
  type SnapResult,
} from 'lib/forge/snap';
import { nonEmptySheets, roundFindings, snapFindings, type ForgeFinding } from 'lib/forge/validate';
import { AdjustPanel } from './ForgeView.features/AdjustPanel';
import { CostCurvePanel } from './ForgeView.features/CostCurvePanel';
import { QueryEditPanel } from './ForgeView.features/QueryEditPanel';
import type { QueryApplyResult, QueryEditRequest, QueryPreview } from 'lib/forge/queryEdit';

interface Props {
  model: WorkbookModel;
  /** Merge transformed sheets back into the model (keeps everything else). */
  onApplySheets: (partial: Record<string, GridRow[]>) => void;
  /** Query & edit — server-side bulk edit (filters + one-hop joins, static or
   *  temporal). Preview is a dry run; apply writes through the session. */
  onQueryEditPreview?: (req: QueryEditRequest) => Promise<QueryPreview>;
  onQueryEditApply?: (req: QueryEditRequest) => Promise<QueryApplyResult>;
  /** Reduce the session model to fewer clustered buses; returns the reduced
   *  model for preview (no mutation). Absent ⇒ the cluster tool is read-only.
   *  `groupByColumn` groups buses by a workbook column instead of nClusters;
   *  `aggregateComponents` additionally collapses those one-ports by carrier. */
  onClusterPreview?: (opts: {
    nClusters: number;
    method: string;
    resolveConflicts: boolean;
    conflictStrategy: string;
    groupByColumn?: string;
    aggregateComponents?: string[];
  }) => Promise<ClusterResult>;
  /** Replace the working model with a previewed clustered model. */
  onClusterApply?: (model: WorkbookModel) => void;
  /** Attach Open-Meteo weather profiles to the existing renewable fleet by
   *  coordinate; applies server-side + merges, returns a summary. */
  onAttachRenewableProfiles?: (opts: {
    dateFrom: string;
    dateTo: string;
    performanceRatio: number;
    source: string;
    utcOffset?: number;
    solarCarriers?: string[];
    windCarriers?: string[];
  }) => Promise<AttachProfilesResult>;
  /** T1(a) — retarget the snapshot window + reindex all temporal sheets. */
  onRetargetSnapshots?: (opts: {
    start: string; end: string; stepHours: number; fill: string;
  }) => Promise<{ snapshots: number; retargeted: string[] }>;
  /** T1(b) — project the series to a future year (grow demand, re-date). */
  onForecastSnapshots?: (opts: {
    fromYear: number; toYear: number; growthPct: number; method: string;
  }) => Promise<{ toYear: number; growthFactor: number; grown: string[]; note?: string }>;
  /** I3 — driver-based demand forecast (evolve the demand SHAPE from drivers). */
  onDriverForecast?: (opts: {
    fromYear: number; toYear: number; popGrowthPct: number; gdpGrowthPct: number;
    gdpElasticity: number; heatAddedGWh: number; evAddedGWh: number;
  }) => Promise<{ snapshots: number; macroFactor: number; heatAddedMwh: number; evAddedMwh: number }>;
  /** M4 — EV-fleet demand reshaping (home overnight / work daytime charging). */
  onEvDemand?: (opts: {
    fleetSize: number; kwhPerVehicleDay: number; homeChargingShare: number;
  }) => Promise<{ rows: number; addedMwh: number; homeMwh: number; workMwh: number }>;
  /** I4 — attach GloFAS discharge-shaped hydro inflow to storage units. */
  onAttachHydroInflow?: (opts: {
    dateFrom: string; dateTo: string; targetCapacityFactor: number; utcOffset: number;
    hydroCarriers?: string[];
  }) => Promise<{ attached: string[]; skipped: string[]; sites: number; notes: string[] }>;
}

export interface AttachProfilesResult {
  attached: string[];
  skipped: string[];
  sites: number;
}

type Operation = 'round' | 'adjust' | 'query' | 'costcurve' | 'snap' | 'cluster' | 'renewable' | 'hydroInflow' | 'retarget' | 'forecast' | 'driverForecast' | 'evDemand';
type OpGroup = 'Numeric' | 'Economics' | 'Geospatial' | 'Topology' | 'Temporal';

/** Catalog of Forge tools, grouped. Add a new tool by adding an entry here
 *  (and its panel + findings wiring) — the rail renders groups from this. */
const OPERATIONS: Array<{ id: Operation; label: string; group: OpGroup }> = [
  { id: 'round', label: 'Round / Ceil / Floor', group: 'Numeric' },
  { id: 'adjust', label: 'Adjust values', group: 'Numeric' },
  { id: 'query', label: 'Query & edit', group: 'Numeric' },
  { id: 'costcurve', label: 'Marginal cost curve', group: 'Economics' },
  { id: 'snap', label: 'Snap to nearest bus', group: 'Geospatial' },
  { id: 'renewable', label: 'Attach renewable profiles', group: 'Geospatial' },
  { id: 'hydroInflow', label: 'Attach hydro inflow', group: 'Geospatial' },
  { id: 'cluster', label: 'Reduce / cluster network', group: 'Topology' },
  { id: 'retarget', label: 'Retarget snapshot window', group: 'Temporal' },
  { id: 'forecast', label: 'Forecast to future year', group: 'Temporal' },
  { id: 'driverForecast', label: 'Driver-based demand forecast', group: 'Temporal' },
  { id: 'evDemand', label: 'EV fleet demand', group: 'Temporal' },
];
const OP_GROUPS: OpGroup[] = ['Numeric', 'Economics', 'Geospatial', 'Topology', 'Temporal'];

const ROUND_OPS: Array<{ value: RoundOp; label: string }> = [
  { value: 'round', label: 'Round' },
  { value: 'ceil', label: 'Ceiling' },
  { value: 'floor', label: 'Floor' },
];

const rowsOf = (model: WorkbookModel, sheet: string): GridRow[] => model[sheet] ?? [];

/** One-port components the reduction can collapse by carrier per merged bus.
 *  `id` is the PyPSA component name the backend expects. */
const AGGREGATABLE_COMPONENTS: Array<{ id: string; label: string }> = [
  { id: 'Generator', label: 'Generators' },
  { id: 'StorageUnit', label: 'Storage units' },
  { id: 'Store', label: 'Stores' },
  { id: 'Load', label: 'Loads' },
  { id: 'ShuntImpedance', label: 'Shunt impedances' },
];

const CLUSTER_PALETTE = [
  '#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f',
  '#edc948', '#b07aa1', '#ff9da7', '#9c755f', '#bab0ab',
];

/** Dependency-free SVG scatter of the busmap: each original bus plotted at its
 *  x/y and coloured by the cluster it merges into, with a ring at each cluster
 *  centroid. Returns null when buses carry no coordinates (e.g. a modularity
 *  clustering on a coordinate-less network) — the counts preview still shows. */
function ClusterScatter({ model, busmap }: { model: WorkbookModel; busmap: Record<string, string> }) {
  const buses = rowsOf(model, 'buses')
    .map((r) => ({ name: String(r.name ?? ''), x: Number(r.x), y: Number(r.y) }))
    .filter((b) => b.name && Number.isFinite(b.x) && Number.isFinite(b.y));
  if (buses.length < 2) return null;
  const xs = buses.map((b) => b.x);
  const ys = buses.map((b) => b.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const W = 320, H = 200, pad = 12;
  const sx = (x: number) => pad + ((x - minX) / ((maxX - minX) || 1)) * (W - 2 * pad);
  const sy = (y: number) => H - pad - ((y - minY) / ((maxY - minY) || 1)) * (H - 2 * pad); // north up
  const clusters = Array.from(new Set(Object.values(busmap)));
  const colorOf = (c: string) => CLUSTER_PALETTE[Math.max(0, clusters.indexOf(c)) % CLUSTER_PALETTE.length];
  const cent: Record<string, { x: number; y: number; n: number }> = {};
  for (const b of buses) {
    const c = busmap[b.name];
    if (!c) continue;
    const e = (cent[c] ??= { x: 0, y: 0, n: 0 });
    e.x += b.x; e.y += b.y; e.n += 1;
  }
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', maxWidth: '100%' }} role="img" aria-label="Cluster map">
      {buses.map((b) => (
        <circle key={b.name} cx={sx(b.x)} cy={sy(b.y)} r={2.5} fill={colorOf(busmap[b.name])} fillOpacity={0.7} />
      ))}
      {Object.entries(cent).map(([c, e]) => (
        <circle key={c} cx={sx(e.x / e.n)} cy={sy(e.y / e.n)} r={6} fill="none" stroke={colorOf(c)} strokeWidth={2} />
      ))}
    </svg>
  );
}

/**
 * Searchable multi-select for a (potentially large) list of string options —
 * e.g. picking which carriers are solar vs wind without one row per carrier.
 * Trigger shows a summary; the panel has a search box + checkboxes and closes
 * on outside click or Escape.
 */
function SearchableMultiSelect({
  options, selected, onChange, placeholder = 'None selected',
}: {
  options: string[];
  selected: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (!rootRef.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey); };
  }, [open]);
  const selectedSet = new Set(selected);
  const shown = query.trim()
    ? options.filter((o) => o.toLowerCase().includes(query.trim().toLowerCase()))
    : options;
  const summary = selected.length === 0
    ? placeholder
    : selected.length <= 3 ? selected.join(', ') : `${selected.length} selected`;
  const toggle = (o: string) =>
    onChange(selectedSet.has(o) ? selected.filter((x) => x !== o) : [...selected, o]);
  return (
    <div ref={rootRef} className="ss-wrap forge-msel">
      <button type="button" className="ss-input forge-msel__trigger" onClick={() => setOpen((s) => !s)} aria-expanded={open}>
        {summary}
      </button>
      {open && (
        <div className="ss-menu forge-msel__panel">
          <input
            className="forge-msel__search"
            placeholder="Search…"
            value={query}
            autoFocus
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="forge-msel__head">
            <button type="button" className="data-import-multiselect__head-btn" onClick={() => onChange(Array.from(new Set([...selected, ...shown])))}>Select shown</button>
            <button type="button" className="data-import-multiselect__head-btn" onClick={() => onChange(selected.filter((s) => !shown.includes(s)))}>Clear shown</button>
          </div>
          <ul className="forge-msel__list" role="listbox" aria-multiselectable="true">
            {shown.length === 0 && <li className="forge-msel__empty">No matches</li>}
            {shown.map((o) => (
              <li key={o} className="ss-option forge-msel__option">
                <label>
                  <input type="checkbox" checked={selectedSet.has(o)} onChange={() => toggle(o)} />
                  <span>{o}</span>
                </label>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function ForgeView({ model, onApplySheets, onQueryEditPreview, onQueryEditApply, onClusterPreview, onClusterApply, onAttachRenewableProfiles, onRetargetSnapshots, onForecastSnapshots, onDriverForecast, onEvDemand, onAttachHydroInflow }: Props) {
  // Persisted so the chosen tool + validation result survive leaving and
  // returning to the Forge tab (the view unmounts on tab switch). The findings
  // scan the whole model, so these three drivers fully restore the result.
  const [operation, setOperation] = usePersistedState<Operation>('ui:forge-operation', 'round');
  const [validated, setValidated] = usePersistedState<boolean>('ui:forge-validated', false);
  const [status, setStatus] = useState<string | null>(null);

  // Read any model that holds rows, regardless of how it was loaded (project
  // import, plugin "Send model", build editor, …) — not just a fixed sheet list.
  const sheetsWithRows = useMemo(() => nonEmptySheets(model), [model]);

  // ── Operation 1: Round / Ceil / Floor ──────────────────────────────────
  const [roundSheet, setRoundSheet] = useState<string>('');
  const [roundAttrs, setRoundAttrs] = useState<string[]>([]);
  const [roundOp, setRoundOp] = useState<RoundOp>('round');
  const [decimals, setDecimals] = usePersistedState<number>('ui:forge-decimals', FORGE_CONFIG.defaultRoundDecimals);

  const activeRoundSheet = roundSheet && sheetsWithRows.includes(roundSheet) ? roundSheet : (sheetsWithRows[0] ?? '');
  const roundCols = useMemo(
    () => numericColumns(rowsOf(model, activeRoundSheet)),
    [model, activeRoundSheet],
  );
  const selectedRoundAttrs = roundAttrs.filter((a) => roundCols.includes(a));
  const roundPreview = useMemo(() => {
    if (!activeRoundSheet || selectedRoundAttrs.length === 0) return 0;
    return applyRounding(rowsOf(model, activeRoundSheet), selectedRoundAttrs, roundOp, decimals).changed;
  }, [model, activeRoundSheet, selectedRoundAttrs, roundOp, decimals]);

  const toggleRoundAttr = (col: string) =>
    setRoundAttrs((prev) => (prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col]));

  const applyRound = () => {
    const { rows, changed } = applyRounding(rowsOf(model, activeRoundSheet), selectedRoundAttrs, roundOp, decimals);
    onApplySheets({ [activeRoundSheet]: rows });
    const opLabel = ROUND_OPS.find((o) => o.value === roundOp)?.label ?? roundOp;
    setStatus(`${opLabel}: changed ${changed} cell${changed === 1 ? '' : 's'} across ${selectedRoundAttrs.length} attribute${selectedRoundAttrs.length === 1 ? '' : 's'} in ${activeRoundSheet}.`);
  };

  // ── Operation 2: Snap to nearest bus ────────────────────────────────────
  const [overlaySel, setOverlaySel] = useState<string[]>([]);
  const [bufferKm, setBufferKm] = useState<number>(FORGE_CONFIG.defaultBufferKm);
  const [snapReport, setSnapReport] = useState<
    { assigned: number; outside: OutsideEntry[]; noCoords: number; perSheet: Array<{ sheet: string; anchors: string[]; assigned: number }> } | null
  >(null);

  const targets = useMemo(() => buildTargets(rowsOf(model, 'buses')), [model]);
  const overlayCandidates = useMemo(
    () => sheetsWithRows.filter((sheet) => sheet !== 'buses' && sheetSnappable(rowsOf(model, sheet))),
    [model, sheetsWithRows],
  );
  const selectedOverlays = overlaySel.filter((s) => overlayCandidates.includes(s));

  const toggleOverlay = (sheet: string) =>
    setOverlaySel((prev) => (prev.includes(sheet) ? prev.filter((s) => s !== sheet) : [...prev, sheet]));

  const applySnap = () => {
    const partial: Record<string, GridRow[]> = {};
    const outside: OutsideEntry[] = [];
    const perSheet: Array<{ sheet: string; anchors: string[]; assigned: number }> = [];
    let assigned = 0;
    let noCoords = 0;
    for (const sheet of selectedOverlays) {
      const result: SnapResult = snapSheet(rowsOf(model, sheet), targets, bufferKm);
      partial[sheet] = result.rows;
      assigned += result.assigned;
      noCoords += result.noCoords;
      outside.push(...result.outside.map((o) => ({ ...o, name: `${sheet}: ${o.name}` })));
      perSheet.push({ sheet, anchors: result.anchors, assigned: result.assigned });
    }
    onApplySheets(partial);
    setSnapReport({ assigned, outside, noCoords, perSheet });
    setStatus(`Snapped ${assigned} connection${assigned === 1 ? '' : 's'} to nearest bus${outside.length ? `, ${outside.length} beyond ${bufferKm} km` : ''}.`);
  };

  // ── Operation 4: Reduce / cluster network ───────────────────────────────
  const busCount = rowsOf(model, 'buses').length;
  const defaultClusterN = Math.max(1, Math.min(Math.max(busCount - 1, 1), Math.round(busCount / 2)));
  const [clusterN, setClusterN] = useState<number | null>(null);
  const [clusterMethod, setClusterMethod] = useState<'modularity' | 'kmeans' | 'column'>('modularity');
  const [clusterResolveConflicts, setClusterResolveConflicts] = useState(true);
  const [clusterConflictStrategy, setClusterConflictStrategy] = useState<'mean' | 'max' | 'min' | 'zero' | 'default'>('mean');
  const [clusterBusy, setClusterBusy] = useState(false);
  const [clusterResult, setClusterResult] = useState<ClusterResult | null>(null);
  const [clusterError, setClusterError] = useState<string | null>(null);
  const effClusterN = clusterN ?? defaultClusterN;
  // Aggregate-by-column: which bus column to group on.
  const busCols = busColumns(rowsOf(model, 'buses'));
  const [clusterColumn, setClusterColumn] = useState<string>('');
  const effClusterColumn = clusterColumn || busCols[0] || '';
  // Aggregate one-port components by carrier per merged bus (off by default).
  const [aggComponents, setAggComponents] = useState(false);
  const [aggSelected, setAggSelected] = useState<Set<string>>(() => new Set(AGGREGATABLE_COMPONENTS.map((c) => c.id)));
  const toggleAggComponent = (id: string) =>
    setAggSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const runClusterPreview = async () => {
    if (!onClusterPreview) return;
    if (clusterMethod === 'column' && !effClusterColumn) {
      setClusterError('Pick a bus column to group by.');
      return;
    }
    setClusterBusy(true);
    setClusterError(null);
    setClusterResult(null);
    try {
      const aggregateComponents = aggComponents ? Array.from(aggSelected) : [];
      setClusterResult(
        await onClusterPreview({
          nClusters: effClusterN,
          method: clusterMethod === 'column' ? 'modularity' : clusterMethod,
          resolveConflicts: clusterResolveConflicts,
          conflictStrategy: clusterConflictStrategy,
          groupByColumn: clusterMethod === 'column' ? effClusterColumn : undefined,
          aggregateComponents,
        }),
      );
    } catch (e) {
      setClusterError(e instanceof Error ? e.message : 'Clustering failed.');
    } finally {
      setClusterBusy(false);
    }
  };

  const applyCluster = () => {
    if (!clusterResult || !onClusterApply) return;
    onClusterApply(clusterResult.model);
    setStatus(`Reduced ${clusterResult.before.buses} → ${clusterResult.after.buses} buses; working model replaced.`);
    setClusterResult(null);
  };

  // ── Operation 5: Attach renewable profiles (Open-Meteo, by coordinate) ────
  // Mirrors the backend's carrier classifier: name a generator's tech by its
  // carrier, wind hints taking priority over solar.
  const autoClassify = (carrier: string): 'solar' | 'wind' | null => {
    const c = carrier.toLowerCase();
    if (/wind|onwind|offwind/.test(c)) return 'wind';
    if (/solar|pv/.test(c)) return 'solar';
    return null;
  };
  // Distinct generator carriers + how many generators carry each — the user can
  // override the auto guess per carrier (answers "which is wind, which is PV?").
  const genCarriers = useMemo(() => {
    const counts = new Map<string, number>();
    for (const g of rowsOf(model, 'generators')) {
      const c = String(g.carrier ?? '').trim();
      if (c) counts.set(c, (counts.get(c) ?? 0) + 1);
    }
    return Array.from(counts.entries())
      .map(([carrier, count]) => ({ carrier, count, auto: autoClassify(carrier) }))
      .sort((a, b) => a.carrier.localeCompare(b.carrier));
  }, [model]);
  const carrierNames = useMemo(() => genCarriers.map((c) => c.carrier), [genCarriers]);
  const countByCarrier = useMemo(
    () => new Map(genCarriers.map((c) => [c.carrier, c.count])),
    [genCarriers],
  );
  // Representative fleet longitude → a suggested UTC offset (≈ lon / 15), so
  // snapshots default to local time instead of UTC.
  const fleetLon = useMemo(() => {
    const buses = new Map(rowsOf(model, 'buses').map((b) => [String(b.name), b]));
    const lons: number[] = [];
    for (const g of rowsOf(model, 'generators')) {
      const gx = Number(g.x);
      if (Number.isFinite(gx)) { lons.push(gx); continue; }
      const bx = Number(buses.get(String(g.bus))?.x);
      if (Number.isFinite(bx)) lons.push(bx);
    }
    return lons.length ? lons.reduce((a, b) => a + b, 0) / lons.length : null;
  }, [model]);
  const suggestedOffset = fleetLon == null ? 0 : Math.max(-12, Math.min(14, Math.round(fleetLon / 15)));

  const [renewSource, setRenewSource] = useState<'open-meteo' | 'pvgis' | 'nasa-power'>('open-meteo');
  const [renewFrom, setRenewFrom] = useState('2019-01-01');
  const [renewTo, setRenewTo] = useState('2019-01-31');
  const [renewPr, setRenewPr] = useState(0.9);
  const [renewOffset, setRenewOffset] = useState(0);
  const [renewBusy, setRenewBusy] = useState(false);
  const [renewResult, setRenewResult] = useState<AttachProfilesResult | null>(null);
  const [renewError, setRenewError] = useState<string | null>(null);
  // Which carriers are solar / which are wind — seeded from the auto guess, then
  // freely editable via the searchable multi-selects. Reseed when the model's
  // carrier set changes.
  const [solarCarriers, setSolarCarriers] = useState<string[]>([]);
  const [windCarriers, setWindCarriers] = useState<string[]>([]);
  const carrierKey = carrierNames.join('|');
  useEffect(() => {
    setSolarCarriers(genCarriers.filter((c) => c.auto === 'solar').map((c) => c.carrier));
    setWindCarriers(genCarriers.filter((c) => c.auto === 'wind').map((c) => c.carrier));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [carrierKey]);
  useEffect(() => { setRenewOffset(suggestedOffset); }, [suggestedOffset]);

  const renewableGenCount = useMemo(() => {
    const picked = new Set([...solarCarriers, ...windCarriers]);
    let n = 0;
    picked.forEach((c) => { n += countByCarrier.get(c) ?? 0; });
    return n;
  }, [solarCarriers, windCarriers, countByCarrier]);

  const runAttachProfiles = async () => {
    if (!onAttachRenewableProfiles) return;
    setRenewBusy(true);
    setRenewError(null);
    setRenewResult(null);
    try {
      const res = await onAttachRenewableProfiles({
        dateFrom: renewFrom, dateTo: renewTo, performanceRatio: renewPr, source: renewSource,
        utcOffset: renewOffset, solarCarriers, windCarriers,
      });
      setRenewResult(res);
      setStatus(`Attached weather profiles to ${res.attached.length} generator(s) from ${res.sites} site(s).`);
    } catch (e) {
      setRenewError(e instanceof Error ? e.message : 'Attaching profiles failed.');
    } finally {
      setRenewBusy(false);
    }
  };

  // ── Operation 6/7: Temporal — retarget window + forecast to a future year ──
  const [tStart, setTStart] = useState('2025-01-01');
  const [tEnd, setTEnd] = useState('2025-12-31 23:00');
  const [tStep, setTStep] = useState(1);
  const [tFill, setTFill] = useState<'tile' | 'pad'>('tile');
  const [fFrom, setFFrom] = useState(2025);
  const [fTo, setFTo] = useState(2035);
  const [fGrowth, setFGrowth] = useState(2);
  const [fMethod, setFMethod] = useState<'cagr' | 'linear' | 'regression' | 'arima' | 'prophet'>('cagr');
  const [tempBusy, setTempBusy] = useState(false);
  const [tempError, setTempError] = useState<string | null>(null);
  // I3 driver-forecast inputs.
  const [dPop, setDPop] = useState(0.5);
  const [dGdp, setDGdp] = useState(2.0);
  const [dElas, setDElas] = useState(0.5);
  const [dHeat, setDHeat] = useState(0);
  const [dEv, setDEv] = useState(0);

  // I4 hydro-inflow inputs.
  const [hiFrom, setHiFrom] = useState('2019-01-01');
  const [hiTo, setHiTo] = useState('2019-12-31');
  const [hiCf, setHiCf] = useState(0.35);
  const [hiUtc, setHiUtc] = useState(0);
  const [hiResult, setHiResult] = useState<string | null>(null);
  // Distinct carriers present on the storage_units sheet — the picker options.
  const storageCarriers = useMemo(() => {
    const set = new Set<string>();
    for (const s of rowsOf(model, 'storage_units')) {
      const c = String(s.carrier ?? '').trim();
      if (c) set.add(c);
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [model]);
  // The user picks which storage carriers count as hydro (the name-hint
  // classifier misses non-English / custom names). Seeded with the obvious
  // hydro-like ones; PHS/pumped excluded from the seed.
  const [hydroCarriers, setHydroCarriers] = useState<string[]>([]);
  const storageCarrierKey = storageCarriers.join('|');
  useEffect(() => {
    setHydroCarriers(storageCarriers.filter((c) => {
      const cl = c.toLowerCase();
      if (cl.includes('phs') || cl.includes('pump')) return false;
      return ['hydro', 'ror', 'reservoir', 'water'].some((h) => cl.includes(h));
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageCarrierKey]);

  const runHydroInflow = async () => {
    if (!onAttachHydroInflow) return;
    setTempBusy(true); setTempError(null); setHiResult(null);
    try {
      const r = await onAttachHydroInflow({
        dateFrom: hiFrom, dateTo: hiTo, targetCapacityFactor: hiCf, utcOffset: hiUtc,
        hydroCarriers: hydroCarriers.length ? hydroCarriers : undefined,
      });
      setHiResult(`Attached inflow to ${r.attached.length} unit(s) from ${r.sites} site(s)` +
        (r.skipped.length ? `; skipped ${r.skipped.length} without coordinates` : '') +
        (r.notes.length ? `. ${r.notes[0]}` : '.'));
    } catch (e) {
      setTempError(e instanceof Error ? e.message : 'Hydro inflow failed.');
    } finally { setTempBusy(false); }
  };

  // M4 EV-demand inputs.
  const [evFleet, setEvFleet] = useState(100000);
  const [evKwh, setEvKwh] = useState(7);
  const [evHome, setEvHome] = useState(0.7);

  const runEvDemand = async () => {
    if (!onEvDemand) return;
    setTempBusy(true); setTempError(null);
    try {
      await onEvDemand({ fleetSize: evFleet, kwhPerVehicleDay: evKwh, homeChargingShare: evHome });
    } catch (e) {
      setTempError(e instanceof Error ? e.message : 'EV demand failed.');
    } finally { setTempBusy(false); }
  };

  const runDriverForecast = async () => {
    if (!onDriverForecast) return;
    setTempBusy(true); setTempError(null);
    try {
      await onDriverForecast({
        fromYear: fFrom, toYear: fTo, popGrowthPct: dPop, gdpGrowthPct: dGdp,
        gdpElasticity: dElas, heatAddedGWh: dHeat, evAddedGWh: dEv,
      });
    } catch (e) {
      setTempError(e instanceof Error ? e.message : 'Driver forecast failed.');
    } finally { setTempBusy(false); }
  };

  const runRetarget = async () => {
    if (!onRetargetSnapshots) return;
    setTempBusy(true); setTempError(null);
    try {
      const r = await onRetargetSnapshots({ start: tStart, end: tEnd, stepHours: tStep, fill: tFill });
      setStatus(`Snapshots retargeted to ${r.snapshots} steps; ${r.retargeted.length} series reindexed.`);
    } catch (e) {
      setTempError(e instanceof Error ? e.message : 'Retarget failed.');
    } finally { setTempBusy(false); }
  };

  const runForecast = async () => {
    if (!onForecastSnapshots) return;
    setTempBusy(true); setTempError(null);
    try {
      const r = await onForecastSnapshots({ fromYear: fFrom, toYear: fTo, growthPct: fGrowth, method: fMethod });
      const how = r.note ? ` (${r.note})` : '';
      setStatus(`Projected to ${r.toYear}: demand ×${r.growthFactor} on ${r.grown.length} sheet(s)${how}.`);
    } catch (e) {
      setTempError(e instanceof Error ? e.message : 'Forecast failed.');
    } finally { setTempBusy(false); }
  };

  // Context-aware "what needs handling" for the active tool. Recomputes when
  // the tool or model changes, so switching tools re-reports automatically.
  const findings = useMemo<ForgeFinding[] | null>(() => {
    // 'adjust' / 'costcurve' have no pre-scan; their preview is the match count.
    if (!validated || operation === 'adjust' || operation === 'costcurve') return null;
    return operation === 'round'
      ? roundFindings(model, decimals, VALIDATION_CONFIG.magnitudeMax, VALIDATION_CONFIG.magnitudeMin)
      : snapFindings(model);
  }, [validated, operation, model, decimals]);

  const activeOpLabel = OPERATIONS.find((op) => op.id === operation)?.label ?? operation;

  return (
    <ViewPanel name="forge">
      <LeftRail title="Forge">
        <button
          type="button"
          className="tb-btn forge-validate-btn"
          aria-pressed={validated}
          onClick={() => setValidated(!validated)}
        >
          {validated ? 'Validation on' : 'Validate'}
        </button>
        <div className="forge-rail-divider" />
        {OP_GROUPS.map((group) => (
          <div key={group} className="forge-group">
            <div className="forge-group-title">{group}</div>
            {OPERATIONS.filter((op) => op.group === group).map((op) => (
              <button
                key={op.id}
                className={`settings-nav-item${operation === op.id ? ' settings-nav-item--active' : ''}`}
                onClick={() => setOperation(op.id)}
              >
                {op.label}
              </button>
            ))}
          </div>
        ))}
      </LeftRail>

      <main className="view-main forge-main">
        {sheetsWithRows.length > 0 && findings && (
          <div className="forge-findings">
            <p className="forge-findings-title">
              {activeOpLabel} —{' '}
              {findings.length === 0
                ? 'nothing needs handling for this tool'
                : `${findings.length} item${findings.length === 1 ? '' : 's'} need attention`}
            </p>
            {findings.length > 0 && (
              <ul className="forge-findings-list">
                {findings.map((f, i) => (
                  <li key={i}><b>{f.sheet}</b> — {f.message}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        {sheetsWithRows.length === 0 ? (
          <div className="view-empty">
            <p>No model loaded. Import data first, then return to Forge to clean it up.</p>
          </div>
        ) : operation === 'round' ? (
          <section className="forge-section">
            <header className="forge-section-header">
              <h3>Round / Ceiling / Floor</h3>
              <p>Apply a rounding operation to selected numeric attributes. Empty and non-numeric cells are left untouched.</p>
            </header>

            <div className="sg-setting-row">
              <label className="sg-setting-label">Sheet</label>
              <select
                className="forge-select"
                value={activeRoundSheet}
                onChange={(e) => { setRoundSheet(e.target.value); setRoundAttrs([]); }}
              >
                {sheetsWithRows.map((sheet) => (
                  <option key={sheet} value={sheet}>{sheet} ({rowsOf(model, sheet).length})</option>
                ))}
              </select>
            </div>

            <div className="sg-setting-row">
              <label className="sg-setting-label">Attributes</label>
              {roundCols.length === 0 ? (
                <p className="sg-setting-hint">No numeric attributes in this sheet.</p>
              ) : (
                <div className="forge-checklist">
                  {roundCols.map((col) => (
                    <label key={col} className="forge-check">
                      <input
                        type="checkbox"
                        checked={selectedRoundAttrs.includes(col)}
                        onChange={() => toggleRoundAttr(col)}
                      />
                      {col}
                    </label>
                  ))}
                </div>
              )}
            </div>

            <div className="sg-setting-row">
              <label className="sg-setting-label">Operation</label>
              <div className="sg-btn-row">
                {ROUND_OPS.map(({ value, label }) => (
                  <button
                    key={value}
                    className={`tb-btn sg-solver-btn${roundOp === value ? '' : ' tb-btn--muted'}`}
                    onClick={() => setRoundOp(value)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="sg-setting-row">
              <label className="sg-setting-label">Decimals</label>
              <NumberDraftInput
                className="forge-number"
                min={0}
                max={12}
                value={decimals}
                onCommit={(v) => setDecimals(Math.trunc(v))}
              />
              <p className="sg-setting-hint">0 = whole numbers. Applies to all three operations.</p>
            </div>

            <div className="forge-actions">
              <button
                className="run-button"
                disabled={selectedRoundAttrs.length === 0}
                onClick={applyRound}
              >
                Apply
              </button>
              <span className="sg-setting-hint">
                {selectedRoundAttrs.length === 0
                  ? 'Select at least one attribute.'
                  : `${roundPreview} cell${roundPreview === 1 ? '' : 's'} will change.`}
              </span>
            </div>
          </section>
        ) : operation === 'adjust' ? (
          <AdjustPanel
            model={model}
            sheetsWithRows={sheetsWithRows}
            onApplySheets={onApplySheets}
            onStatus={setStatus}
          />
        ) : operation === 'query' ? (
          onQueryEditPreview && onQueryEditApply ? (
            <QueryEditPanel
              model={model}
              sheetsWithRows={sheetsWithRows}
              onPreview={onQueryEditPreview}
              onApply={onQueryEditApply}
              onStatus={setStatus}
            />
          ) : (
            <div className="view-empty"><p>Query &amp; edit needs a live backend session.</p></div>
          )
        ) : operation === 'costcurve' ? (
          <CostCurvePanel
            model={model}
            sheetsWithRows={sheetsWithRows}
            onApplySheets={onApplySheets}
            onStatus={setStatus}
          />
        ) : operation === 'snap' ? (
          <section className="forge-section">
            <header className="forge-section-header">
              <h3>Snap to nearest bus</h3>
              <p>Connect each selected component to the nearest bus by great-circle distance. Sets <code>bus</code> (point components) or <code>bus0</code>/<code>bus1</code> (branch endpoints). Components beyond the buffer are left unchanged and reported.</p>
            </header>

            <div className="sg-setting-row">
              <label className="sg-setting-label">Target</label>
              <p className="sg-setting-hint">
                buses — <b>{targets.length}</b> of {rowsOf(model, 'buses').length} have coordinates.
                {targets.length === 0 && ' No buses carry x/y, so there is nothing to snap to.'}
              </p>
            </div>

            <div className="sg-setting-row">
              <label className="sg-setting-label">Connect</label>
              {overlayCandidates.length === 0 ? (
                <p className="sg-setting-hint">No other components carry coordinates (x/y, x0/y0, x1/y1) to snap.</p>
              ) : (
                <div className="forge-checklist">
                  {overlayCandidates.map((sheet) => (
                    <label key={sheet} className="forge-check">
                      <input
                        type="checkbox"
                        checked={selectedOverlays.includes(sheet)}
                        onChange={() => toggleOverlay(sheet)}
                      />
                      {sheet} ({rowsOf(model, sheet).length})
                    </label>
                  ))}
                </div>
              )}
            </div>

            <div className="sg-setting-row">
              <label className="sg-setting-label">Buffer (km)</label>
              <NumberDraftInput
                className="forge-number"
                min={0}
                value={bufferKm}
                onCommit={setBufferKm}
              />
              <p className="sg-setting-hint">A component whose nearest bus is farther than this is left unchanged and warned.</p>
            </div>

            <div className="forge-actions">
              <button
                className="run-button"
                disabled={selectedOverlays.length === 0 || targets.length === 0}
                onClick={applySnap}
              >
                Connect to nearest
              </button>
            </div>

            {snapReport && (
              <div className="forge-report">
                <p className="forge-report-line">
                  Connected <b>{snapReport.assigned}</b>
                  {snapReport.outside.length > 0 && <> · <span className="forge-warn">{snapReport.outside.length} beyond buffer</span></>}
                  {snapReport.noCoords > 0 && <> · {snapReport.noCoords} without coordinates</>}
                </p>
                {snapReport.outside.length > 0 && (
                  <ul className="forge-outside">
                    {snapReport.outside.slice(0, 30).map((o, i) => (
                      <li key={i}>
                        {o.name} → nearest <b>{o.nearest}</b> ({o.field}) is {o.km.toFixed(1)} km away
                      </li>
                    ))}
                    {snapReport.outside.length > 30 && <li>… and {snapReport.outside.length - 30} more</li>}
                  </ul>
                )}
              </div>
            )}
          </section>
        ) : operation === 'renewable' ? (
          <section className="forge-section">
            <header className="forge-section-header">
              <h3>Attach renewable profiles</h3>
              <p>Fetch hourly wind/solar capacity factors (keyless reanalysis) for each renewable generator's location — its own x/y, else its bus's — and attach them as <code>generators-p_max_pu</code>. Weather is fetched once per 0.1° grid cell and cached. Match the window to your run snapshots (or realign with the snapshot editor).</p>
            </header>

            <div className="sg-setting-row">
              <label className="sg-setting-label" htmlFor="forge-renew-source">Weather source</label>
              <select
                id="forge-renew-source"
                className="forge-select"
                value={renewSource}
                onChange={(e) => setRenewSource(e.target.value as typeof renewSource)}
              >
                <option value="open-meteo">Open-Meteo (ERA5, global)</option>
                <option value="pvgis">PVGIS (EU JRC — Europe/Africa/Asia)</option>
                <option value="nasa-power">NASA POWER (global)</option>
              </select>
              <p className="sg-setting-hint">All keyless. PVGIS is strongest over Europe/Africa/Asia; the others are global.</p>
            </div>

            <div className="sg-setting-row">
              <label className="sg-setting-label" htmlFor="forge-renew-from">Weather window</label>
              <div className="sg-btn-row" style={{ gap: 8 }}>
                <input id="forge-renew-from" type="date" className="forge-number" value={renewFrom} onChange={(e) => setRenewFrom(e.target.value)} />
                <input type="date" className="forge-number" value={renewTo} onChange={(e) => setRenewTo(e.target.value)} />
              </div>
              <p className="sg-setting-hint">Reanalyses lag by days and recent dates can miss irradiance; PVGIS covers 2005–2020. 2019 is a safe default.</p>
            </div>

            <div className="sg-setting-row">
              <label className="sg-setting-label">Local UTC offset (hours)</label>
              <NumberDraftInput
                className="forge-number"
                min={-12}
                max={14}
                step={1}
                value={renewOffset}
                onCommit={(v) => setRenewOffset(Math.max(-12, Math.min(14, Math.trunc(v))))}
              />
              <p className="sg-setting-hint">
                Weather is fetched in UTC; this shifts snapshots to local time so the diurnal profile lines up with local demand.
                {fleetLon != null && ` Suggested from the fleet: ${suggestedOffset >= 0 ? '+' : ''}${suggestedOffset}.`}
              </p>
            </div>

            <div className="sg-setting-row">
              <label className="sg-setting-label">Solar performance ratio</label>
              <NumberDraftInput
                className="forge-number"
                min={0.1}
                max={1}
                value={renewPr}
                onCommit={(v) => setRenewPr(Math.max(0.1, Math.min(1, v)))}
              />
              <p className="sg-setting-hint">Flat derate on solar CF (inverter / soiling / temperature).</p>
            </div>

            {carrierNames.length > 0 && (
              <div className="sg-setting-row">
                <label className="sg-setting-label">Carrier → technology</label>
                <p className="sg-setting-hint">
                  Pick which carriers are solar and which are wind (pre-filled from a guess:
                  <code> wind/onwind/offwind</code> → wind, <code>solar/pv</code> → solar). Carriers in neither list are skipped.
                </p>
                <div className="forge-carrier-picker">
                  <div className="forge-carrier-picker__row">
                    <span className="forge-carrier-picker__label">Solar</span>
                    <SearchableMultiSelect options={carrierNames} selected={solarCarriers} onChange={setSolarCarriers} placeholder="No solar carriers" />
                  </div>
                  <div className="forge-carrier-picker__row">
                    <span className="forge-carrier-picker__label">Wind</span>
                    <SearchableMultiSelect options={carrierNames} selected={windCarriers} onChange={setWindCarriers} placeholder="No wind carriers" />
                  </div>
                </div>
              </div>
            )}

            <div className="forge-actions">
              <button
                className="run-button"
                disabled={renewableGenCount < 1 || renewBusy || !onAttachRenewableProfiles}
                onClick={runAttachProfiles}
              >
                {renewBusy ? 'Fetching weather…' : `Attach to ${renewableGenCount} renewable generator${renewableGenCount === 1 ? '' : 's'}`}
              </button>
              {renewableGenCount < 1 && <span className="sg-setting-hint">No generators classified as solar/wind. Set a carrier above.</span>}
            </div>

            {renewError && <p className="forge-status" style={{ color: 'var(--danger, #dc2626)' }}>{renewError}</p>}

            {renewResult && (
              <div className="forge-report">
                <p className="forge-report-line">
                  Attached profiles to <b>{renewResult.attached.length}</b> generator(s) from <b>{renewResult.sites}</b> weather site(s).
                  {renewResult.skipped.length > 0 && (
                    <span style={{ color: 'var(--muted)', marginLeft: 6 }}>
                      Skipped {renewResult.skipped.length} without a coordinate: {renewResult.skipped.slice(0, 6).join(', ')}{renewResult.skipped.length > 6 ? '…' : ''}
                    </span>
                  )}
                </p>
              </div>
            )}
          </section>
        ) : operation === 'retarget' ? (
          <section className="forge-section">
            <header className="forge-section-header">
              <h3>Retarget snapshot window</h3>
              <p>Regenerate the snapshot index over a new start/end at a chosen step, and reindex every temporal sheet onto it. A longer window <b>tiles</b> the source (reuse a base year to fill more time) or <b>pads</b> the last value; a shorter one clips. Use this to re-aim an imported profile onto the window you want to run.</p>
            </header>
            <div className="sg-setting-row">
              <label className="sg-setting-label">Window</label>
              <div className="sg-btn-row" style={{ gap: 8 }}>
                <input type="datetime-local" className="forge-number" value={tStart.replace(' ', 'T')} onChange={(e) => setTStart(e.target.value.replace('T', ' '))} />
                <input type="datetime-local" className="forge-number" value={tEnd.replace(' ', 'T')} onChange={(e) => setTEnd(e.target.value.replace('T', ' '))} />
              </div>
            </div>
            <div className="sg-setting-row">
              <label className="sg-setting-label">Step (hours)</label>
              <NumberDraftInput className="forge-number" min={1} value={tStep} onCommit={(v) => setTStep(Math.max(1, Math.trunc(v)))} />
            </div>
            <div className="sg-setting-row">
              <label className="sg-setting-label">Fill longer windows</label>
              <div className="sg-btn-row">
                <button className={`tb-btn sg-solver-btn${tFill === 'tile' ? '' : ' tb-btn--muted'}`} onClick={() => setTFill('tile')}>Tile (cycle)</button>
                <button className={`tb-btn sg-solver-btn${tFill === 'pad' ? '' : ' tb-btn--muted'}`} onClick={() => setTFill('pad')}>Pad (repeat last)</button>
              </div>
            </div>
            <div className="forge-actions">
              <button className="run-button" disabled={tempBusy || !onRetargetSnapshots} onClick={runRetarget}>
                {tempBusy ? 'Retargeting…' : 'Retarget snapshots'}
              </button>
            </div>
            {tempError && <p className="forge-status" style={{ color: 'var(--danger, #dc2626)' }}>{tempError}</p>}
          </section>
        ) : operation === 'hydroInflow' ? (
          <section className="forge-section">
            <header className="forge-section-header">
              <h3>Attach hydro inflow</h3>
              <p>Fetch GloFAS river discharge (keyless Open-Meteo Flood API) at each hydro storage unit's coordinate and land it as <code>storage_units-inflow</code>. The discharge provides the seasonal <em>shape</em>; you set the <em>level</em> as a target capacity factor (window-mean inflow = cf × p_nom). PHS/pumped units are excluded (no natural inflow).</p>
            </header>
            <div className="sg-setting-row">
              <label className="sg-setting-label">Hydro carriers</label>
              {storageCarriers.length === 0 ? (
                <p className="sg-setting-hint">No storage units in the model.</p>
              ) : (
                <>
                  <SearchableMultiSelect
                    options={storageCarriers}
                    selected={hydroCarriers}
                    onChange={setHydroCarriers}
                    placeholder="No hydro carriers selected"
                  />
                  <p className="sg-setting-hint">
                    Storage units with these carriers get inflow. Auto-seeded from hydro-like names — add yours if it was missed.
                  </p>
                </>
              )}
            </div>
            <div className="sg-setting-row">
              <label className="sg-setting-label">From → to (daily discharge)</label>
              <div className="sg-btn-row" style={{ gap: 8 }}>
                <input type="date" className="forge-select" value={hiFrom} onChange={(e) => setHiFrom(e.target.value)} />
                <input type="date" className="forge-select" value={hiTo} onChange={(e) => setHiTo(e.target.value)} />
              </div>
            </div>
            <div className="sg-setting-row">
              <label className="sg-setting-label">Target capacity factor · UTC offset (h)</label>
              <div className="sg-btn-row" style={{ gap: 8 }}>
                <NumberDraftInput className="forge-number" min={0} max={1} step={0.05} value={hiCf} onCommit={(v) => setHiCf(Math.min(1, Math.max(0, v)))} />
                <NumberDraftInput className="forge-number" min={-12} max={14} step={1} value={hiUtc} onCommit={(v) => setHiUtc(Math.trunc(v))} />
              </div>
              <p className="sg-setting-hint">Hydro CF is typically 0.3–0.5. Daily values repeat across each day's hours.</p>
            </div>
            <div className="forge-actions">
              <button className="run-button" disabled={tempBusy || !onAttachHydroInflow} onClick={runHydroInflow}>
                {tempBusy ? 'Attaching…' : 'Attach hydro inflow'}
              </button>
            </div>
            {hiResult && <p className="forge-status">{hiResult}</p>}
            {tempError && <p className="forge-status" style={{ color: 'var(--danger, #dc2626)' }}>{tempError}</p>}
          </section>
        ) : operation === 'evDemand' ? (
          <section className="forge-section">
            <header className="forge-section-header">
              <h3>EV fleet demand</h3>
              <p>Add an EV fleet's charging load onto the demand series, region-aware: the home-charging share lands <em>overnight</em> on home-heavy regions, workplace charging lands in <em>office hours</em> — the energy follows the fleet's location by time of day. Region home/work shares default to each load's size (per-region shares via the API).</p>
            </header>
            <div className="sg-setting-row">
              <label className="sg-setting-label">Fleet size · kWh/vehicle/day · home-charging share</label>
              <div className="sg-btn-row" style={{ gap: 8 }}>
                <NumberDraftInput className="forge-number" min={0} step={10000} value={evFleet} onCommit={(v) => setEvFleet(Math.max(0, Math.trunc(v)))} />
                <NumberDraftInput className="forge-number" min={0} step={0.5} value={evKwh} onCommit={(v) => setEvKwh(Math.max(0, v))} />
                <NumberDraftInput className="forge-number" min={0} max={1} step={0.05} value={evHome} onCommit={(v) => setEvHome(Math.min(1, Math.max(0, v)))} />
              </div>
              <p className="sg-setting-hint">
                ≈{Math.round((evFleet * evKwh) / 1000).toLocaleString()} MWh/day of charging; {Math.round(evHome * 100)}% overnight at home, the rest at work.
              </p>
            </div>
            <div className="forge-actions">
              <button className="run-button" disabled={tempBusy || !onEvDemand} onClick={runEvDemand}>
                {tempBusy ? 'Applying…' : 'Add EV fleet load'}
              </button>
            </div>
            {tempError && <p className="forge-status" style={{ color: 'var(--danger, #dc2626)' }}>{tempError}</p>}
          </section>
        ) : operation === 'driverForecast' ? (
          <section className="forge-section">
            <header className="forge-section-header">
              <h3>Driver-based demand forecast</h3>
              <p>Evolve the demand <em>shape</em>, not just its level: population and GDP scale the base profile, while electrified heat (winter-peaking, morning/evening) and EV charging (overnight + midday work) add load with their own hourly patterns. A decade out the peak can move to a winter evening — which uniform growth can't produce.</p>
            </header>
            <div className="sg-setting-row">
              <label className="sg-setting-label">From year → to year</label>
              <div className="sg-btn-row" style={{ gap: 8 }}>
                <NumberDraftInput className="forge-number" min={1900} max={2100} value={fFrom} onCommit={(v) => setFFrom(Math.trunc(v))} />
                <NumberDraftInput className="forge-number" min={1900} max={2100} value={fTo} onCommit={(v) => setFTo(Math.trunc(v))} />
              </div>
            </div>
            <div className="sg-setting-row">
              <label className="sg-setting-label">Population %/yr · GDP %/yr · GDP elasticity</label>
              <div className="sg-btn-row" style={{ gap: 8 }}>
                <NumberDraftInput className="forge-number" step={0.1} value={dPop} onCommit={setDPop} />
                <NumberDraftInput className="forge-number" step={0.1} value={dGdp} onCommit={setDGdp} />
                <NumberDraftInput className="forge-number" min={0} max={1} step={0.1} value={dElas} onCommit={setDElas} />
              </div>
              <p className="sg-setting-hint">
                Macro factor ×{(((1 + dPop / 100) ** Math.max(0, fTo - fFrom)) * ((1 + (dElas * dGdp) / 100) ** Math.max(0, fTo - fFrom))).toFixed(3)} by {fTo} (scales the base profile, shape unchanged).
              </p>
            </div>
            <div className="sg-setting-row">
              <label className="sg-setting-label">Electrified heat · EV charging (GWh/yr added by {fTo})</label>
              <div className="sg-btn-row" style={{ gap: 8 }}>
                <NumberDraftInput className="forge-number" min={0} step={10} value={dHeat} onCommit={setDHeat} />
                <NumberDraftInput className="forge-number" min={0} step={10} value={dEv} onCommit={setDEv} />
              </div>
              <p className="sg-setting-hint">Heat lands winter-heavy on morning/evening hours; EV lands overnight with a midday work bump — split across loads by their size.</p>
            </div>
            <div className="forge-actions">
              <button className="run-button" disabled={tempBusy || fTo < fFrom || !onDriverForecast} onClick={runDriverForecast}>
                {tempBusy ? 'Evolving…' : `Evolve demand to ${fTo}`}
              </button>
            </div>
            {tempError && <p className="forge-status" style={{ color: 'var(--danger, #dc2626)' }}>{tempError}</p>}
          </section>
        ) : operation === 'forecast' ? (
          <section className="forge-section">
            <header className="forge-section-header">
              <h3>Forecast to future year</h3>
              <p>Project demand to a future year. <strong>CAGR / Linear</strong> grow the current window by a rate you set. <strong>Regression / ARIMA / Prophet</strong> instead fit the trend from your series' own annual history (needs ≥3 years) and project the base-year window forward. Availability profiles (p_max_pu) are re-dated but not grown.</p>
            </header>
            <div className="sg-setting-row">
              <label className="sg-setting-label">From year → to year</label>
              <div className="sg-btn-row" style={{ gap: 8 }}>
                <NumberDraftInput className="forge-number" min={1900} max={2100} value={fFrom} onCommit={(v) => setFFrom(Math.trunc(v))} />
                <NumberDraftInput className="forge-number" min={1900} max={2100} value={fTo} onCommit={(v) => setFTo(Math.trunc(v))} />
              </div>
              <p className="sg-setting-hint">Snapshots move by {fTo - fFrom} year(s).</p>
            </div>
            <div className="sg-setting-row">
              <label className="sg-setting-label">Method</label>
              <div className="sg-btn-row" style={{ flexWrap: 'wrap' }}>
                {([['cagr', 'Compound (CAGR)'], ['linear', 'Linear'], ['regression', 'Trend fit'], ['arima', 'ARIMA'], ['prophet', 'Prophet']] as const).map(([id, label]) => (
                  <button key={id} className={`tb-btn sg-solver-btn${fMethod === id ? '' : ' tb-btn--muted'}`} onClick={() => setFMethod(id)}>{label}</button>
                ))}
              </div>
              <p className="sg-setting-hint">
                {fMethod === 'cagr' || fMethod === 'linear'
                  ? 'You set the growth rate below.'
                  : 'Growth is estimated from your series’ annual history — no rate needed.'}
              </p>
            </div>
            {(fMethod === 'cagr' || fMethod === 'linear') && (
              <div className="sg-setting-row">
                <label className="sg-setting-label">Demand growth (%/yr)</label>
                <NumberDraftInput className="forge-number" step={0.5} value={fGrowth} onCommit={setFGrowth} />
                <p className="sg-setting-hint">
                  {fMethod === 'cagr'
                    ? `Demand ×${(((1 + fGrowth / 100) ** Math.max(0, fTo - fFrom))).toFixed(3)} by ${fTo}.`
                    : `Demand ×${(1 + (fGrowth / 100) * Math.max(0, fTo - fFrom)).toFixed(3)} by ${fTo}.`}
                </p>
              </div>
            )}
            <div className="forge-actions">
              <button className="run-button" disabled={tempBusy || fTo < fFrom || !onForecastSnapshots} onClick={runForecast}>
                {tempBusy ? 'Projecting…' : `Project to ${fTo}`}
              </button>
            </div>
            {tempError && <p className="forge-status" style={{ color: 'var(--danger, #dc2626)' }}>{tempError}</p>}
          </section>
        ) : (
          <section className="forge-section">
            <header className="forge-section-header">
              <h3>Reduce / cluster network</h3>
              <p>Aggregate buses (and the generators, loads and lines on them) into fewer clustered buses — a smaller network that runs the same physics. Group buses by topology, coordinates, or a column like province; optionally collapse the components on each merged bus to one per carrier. Preview the reduction, then apply to replace the working model.</p>
            </header>

            <div className="sg-setting-row">
              <label className="sg-setting-label">Method</label>
              <div className="sg-btn-row">
                <button
                  className={`tb-btn sg-solver-btn${clusterMethod === 'modularity' ? '' : ' tb-btn--muted'}`}
                  onClick={() => setClusterMethod('modularity')}
                >
                  Modularity
                </button>
                <button
                  className={`tb-btn sg-solver-btn${clusterMethod === 'kmeans' ? '' : ' tb-btn--muted'}`}
                  onClick={() => setClusterMethod('kmeans')}
                >
                  k-means (spatial)
                </button>
                <button
                  className={`tb-btn sg-solver-btn${clusterMethod === 'column' ? '' : ' tb-btn--muted'}`}
                  onClick={() => setClusterMethod('column')}
                >
                  By column
                </button>
              </div>
              <p className="sg-setting-hint">
                {clusterMethod === 'modularity'
                  ? 'Groups electrically-connected regions by network topology — no coordinates needed.'
                  : clusterMethod === 'kmeans'
                    ? 'Groups geographically-near buses — needs bus x/y and scikit-learn on the server.'
                    : 'Merges buses that share a value in the chosen column (e.g. province, country). Blank-valued buses stay on their own.'}
              </p>
            </div>

            {clusterMethod === 'column' ? (
              <div className="sg-setting-row">
                <label className="sg-setting-label" htmlFor="forge-cluster-column">Group buses by</label>
                <select
                  id="forge-cluster-column"
                  className="forge-select"
                  value={effClusterColumn}
                  onChange={(e) => setClusterColumn(e.target.value)}
                  disabled={busCols.length === 0}
                >
                  {busCols.length === 0 && <option value="">No bus columns available</option>}
                  {busCols.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
                <p className="sg-setting-hint">Buses sharing the same {effClusterColumn || 'column'} value merge into one.</p>
              </div>
            ) : (
              <div className="sg-setting-row">
                <label className="sg-setting-label">Target buses</label>
                <NumberDraftInput
                  className="forge-number"
                  min={1}
                  max={Math.max(1, busCount - 1)}
                  value={effClusterN}
                  onCommit={(v) => setClusterN(Math.max(1, Math.min(Math.max(busCount - 1, 1), Math.trunc(v))))}
                />
                <p className="sg-setting-hint">{busCount} bus{busCount === 1 ? '' : 'es'} now → reduce to this many clusters.</p>
              </div>
            )}

            <div className="sg-setting-row">
              <label className="sg-setting-label">Components</label>
              <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                <input
                  type="checkbox"
                  checked={aggComponents}
                  onChange={(e) => setAggComponents(e.target.checked)}
                />
                Aggregate components by carrier
              </label>
              <p className="sg-setting-hint">
                {aggComponents
                  ? 'On each merged bus, collapse the selected components so there is one row per carrier (capacities summed, costs capacity-weighted).'
                  : 'Leave components as individual rows, just reassigned to their merged bus (default).'}
              </p>
              {aggComponents && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 16px', marginTop: 6 }}>
                  {AGGREGATABLE_COMPONENTS.map((c) => (
                    <label key={c.id} style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                      <input
                        type="checkbox"
                        checked={aggSelected.has(c.id)}
                        onChange={() => toggleAggComponent(c.id)}
                      />
                      {c.label}
                    </label>
                  ))}
                </div>
              )}
            </div>

            <div className="sg-setting-row">
              <label className="sg-setting-label">Attribute conflicts</label>
              <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                <input
                  type="checkbox"
                  checked={clusterResolveConflicts}
                  onChange={(e) => setClusterResolveConflicts(e.target.checked)}
                />
                Merge conflicting attributes (keep most common)
              </label>
              <p className="sg-setting-hint">
                {clusterResolveConflicts
                  ? 'When buses in a cluster disagree, text attributes (carrier, unit) keep the most common value; numeric attributes (e.g. voltage setpoint) use the rule below.'
                  : 'Fail the reduction if buses in a cluster disagree on any attribute.'}
              </p>
            </div>

            {clusterResolveConflicts && (
              <div className="sg-setting-row">
                <label className="sg-setting-label" htmlFor="forge-conflict-strategy">Numeric conflicts →</label>
                <select
                  id="forge-conflict-strategy"
                  className="forge-select"
                  value={clusterConflictStrategy}
                  onChange={(e) => setClusterConflictStrategy(e.target.value as typeof clusterConflictStrategy)}
                >
                  <option value="mean">Mean of the cluster</option>
                  <option value="max">Maximum</option>
                  <option value="min">Minimum</option>
                  <option value="zero">Zero</option>
                  <option value="default">Attribute default</option>
                </select>
                <p className="sg-setting-hint">How to merge a numeric attribute whose values differ across the cluster.</p>
              </div>
            )}

            <div className="forge-actions">
              <button
                className="run-button"
                disabled={busCount < 2 || clusterBusy || !onClusterPreview || (clusterMethod === 'column' && !effClusterColumn)}
                onClick={runClusterPreview}
              >
                {clusterBusy ? 'Reducing…' : 'Preview reduction'}
              </button>
              {busCount < 2 && <span className="sg-setting-hint">Need at least 2 buses to cluster.</span>}
              {busCount >= 2 && clusterMethod === 'column' && !effClusterColumn && (
                <span className="sg-setting-hint">Add a column to the buses sheet to group by.</span>
              )}
            </div>

            {clusterError && <p className="forge-status" style={{ color: 'var(--danger, #dc2626)' }}>{clusterError}</p>}

            {clusterResult && (
              <div className="forge-report">
                <p className="forge-report-line">
                  Reduced <b>{clusterResult.before.buses} → {clusterResult.after.buses}</b> buses
                  {' · '}lines {clusterResult.before.lines} → {clusterResult.after.lines}
                  {' · '}generators {clusterResult.before.generators} → {clusterResult.after.generators}
                  {' · '}storage {clusterResult.before.storageUnits} → {clusterResult.after.storageUnits}
                  {' · '}loads {clusterResult.before.loads} → {clusterResult.after.loads}
                  <span style={{ color: 'var(--muted)', marginLeft: 6 }}>({clusterResult.method})</span>
                </p>
                {clusterResult.aggregatedComponents && clusterResult.aggregatedComponents.length > 0 && (
                  <p className="forge-report-line" style={{ color: 'var(--muted)' }}>
                    Aggregated by carrier: <b>{clusterResult.aggregatedComponents.join(', ')}</b>.
                  </p>
                )}
                {clusterResult.resolvedConflicts && clusterResult.resolvedConflicts.length > 0 && (
                  <p className="forge-report-line" style={{ color: 'var(--muted)' }}>
                    Merged conflicting attribute{clusterResult.resolvedConflicts.length === 1 ? '' : 's'} by most-common value: <b>{clusterResult.resolvedConflicts.join(', ')}</b>.
                  </p>
                )}
                <ClusterScatter model={model} busmap={clusterResult.busmap} />
                <div className="forge-actions">
                  <button className="run-button" disabled={!onClusterApply} onClick={applyCluster}>
                    Apply — replace model
                  </button>
                  <span className="sg-setting-hint">Replaces the working model with the reduced network. Re-run to add it to History.</span>
                </div>
              </div>
            )}
          </section>
        )}

        {status && <p className="forge-status">{status}</p>}
      </main>
    </ViewPanel>
  );
}
