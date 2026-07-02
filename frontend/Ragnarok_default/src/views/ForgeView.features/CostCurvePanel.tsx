/**
 * Forge — chart-based quadratic marginal-cost editor (T4).
 *
 * Pick a component (generators / storage_units / stores / links), narrow rows
 * with equality filters (reusing the Adjust machinery), then **draw the
 * marginal-cost-vs-output curve** by dragging control points on the chart. The
 * closest convex quadratic cost `C(p) = c₁·p + c₂·p²` is fit live (marginal
 * cost `MC = c₁ + 2c₂·p`) and, on Apply, `marginal_cost` (c₁) +
 * `marginal_cost_quadratic` (c₂) are written across every matched row.
 *
 * The fit + apply are pure/tested (`lib/forge/costcurve.ts`, `lib/forge/adjust.ts`);
 * this is the thin UI + the drag interaction.
 */
import React, { useMemo, useRef } from 'react';
import type { GridRow, WorkbookModel } from 'lib/types';
import { usePersistedState } from 'shared/hooks/usePersistedState';
import { SearchableSelect } from 'shared/components/SearchableSelect';
import {
  Adjustment,
  AdjustFilter,
  applyAdjustments,
  columnsOf,
  matchCount,
  rowMatches,
  uniqueValues,
} from 'lib/forge/adjust';
import { CurvePoint, fitQuadraticCost, marginalCostAt } from 'lib/forge/costcurve';

interface Props {
  model: WorkbookModel;
  sheetsWithRows: string[];
  currencySymbol?: string;
  onApplySheets: (partial: Record<string, GridRow[]>) => void;
  onStatus: (msg: string) => void;
}

/** PyPSA components that carry `marginal_cost` + `marginal_cost_quadratic`. */
const ELIGIBLE = ['generators', 'storage_units', 'stores', 'links'];

const rowsOf = (model: WorkbookModel, sheet: string): GridRow[] => model[sheet] ?? [];

const DEFAULT_POINTS: CurvePoint[] = [
  { p: 0, mc: 10 },
  { p: 100, mc: 40 },
];

// SVG viewBox geometry (user units; the element scales to its container width).
const VBW = 440;
const VBH = 250;
const PAD = { l: 46, r: 14, t: 14, b: 34 };
const PLOT_W = VBW - PAD.l - PAD.r;
const PLOT_H = VBH - PAD.t - PAD.b;

export function CostCurvePanel({ model, sheetsWithRows, currencySymbol, onApplySheets, onStatus }: Props) {
  const cur = currencySymbol || '';
  const eligible = useMemo(() => sheetsWithRows.filter((s) => ELIGIBLE.includes(s)), [sheetsWithRows]);

  const [sheet, setSheet] = usePersistedState<string>('ui:forge-costcurve-sheet', eligible[0] ?? '');
  const [filters, setFilters] = usePersistedState<AdjustFilter[]>('ui:forge-costcurve-filters', []);
  const [points, setPoints] = usePersistedState<CurvePoint[]>('ui:forge-costcurve-points', DEFAULT_POINTS);
  const [pMax, setPMax] = usePersistedState<number>('ui:forge-costcurve-pmax', 100);

  const activeSheet = eligible.includes(sheet) ? sheet : (eligible[0] ?? '');
  const rows = useMemo(() => rowsOf(model, activeSheet), [model, activeSheet]);
  const columns = useMemo(() => columnsOf(rows), [rows]);
  const matches = useMemo(() => matchCount(model, activeSheet, filters), [model, activeSheet, filters]);

  const fit = useMemo(() => fitQuadraticCost(points), [points]);

  // ── Chart scaling ────────────────────────────────────────────────────────
  const yMax = useMemo(() => {
    const drawn = points.map((q) => q.mc);
    const fitted = marginalCostAt(fit, pMax);
    return Math.max(10, ...drawn, fitted) * 1.15;
  }, [points, fit, pMax]);

  const xPix = (p: number) => PAD.l + (pMax > 0 ? p / pMax : 0) * PLOT_W;
  const yPix = (mc: number) => PAD.t + PLOT_H - (yMax > 0 ? mc / yMax : 0) * PLOT_H;
  const invX = (px: number) => Math.max(0, Math.min(pMax, ((px - PAD.l) / PLOT_W) * pMax));
  const invY = (py: number) => Math.max(0, ((PAD.t + PLOT_H - py) / PLOT_H) * yMax);

  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<number | null>(null);

  // Convert a pointer event to viewBox user coordinates (handles CSS scaling).
  const toUser = (e: React.PointerEvent): { x: number; y: number } => {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };
    const rect = svg.getBoundingClientRect();
    return {
      x: ((e.clientX - rect.left) / rect.width) * VBW,
      y: ((e.clientY - rect.top) / rect.height) * VBH,
    };
  };

  const startDrag = (idx: number) => (e: React.PointerEvent) => {
    e.stopPropagation();
    dragRef.current = idx;
    svgRef.current?.setPointerCapture(e.pointerId);
  };

  const onMove = (e: React.PointerEvent) => {
    if (dragRef.current === null) return;
    const { x, y } = toUser(e);
    const idx = dragRef.current;
    setPoints(points.map((q, i) => (i === idx ? { p: invX(x), mc: invY(y) } : q)));
  };

  const endDrag = (e: React.PointerEvent) => {
    if (dragRef.current !== null) svgRef.current?.releasePointerCapture(e.pointerId);
    dragRef.current = null;
  };

  // Click on empty plot area adds a control point there.
  const addPoint = (e: React.PointerEvent) => {
    const { x, y } = toUser(e);
    if (x < PAD.l || x > VBW - PAD.r || y < PAD.t || y > PAD.t + PLOT_H) return;
    setPoints([...points, { p: invX(x), mc: invY(y) }].sort((a, b) => a.p - b.p));
  };

  const removePoint = (idx: number) => (e: React.MouseEvent) => {
    e.stopPropagation();
    if (points.length <= 1) return;
    setPoints(points.filter((_, i) => i !== idx));
  };

  const sorted = useMemo(() => [...points].sort((a, b) => a.p - b.p), [points]);

  // ── Load / reset ─────────────────────────────────────────────────────────
  const loadFromSelection = () => {
    const matched = rows.filter((r) => rowMatches(r, filters));
    if (matched.length === 0) { onStatus('No rows match — adjust the filters first.'); return; }
    const nums = (key: string) => matched.map((r) => Number(r[key])).filter(Number.isFinite);
    const pnoms = nums('p_nom');
    const nextPMax = pnoms.length ? Math.max(10, Math.max(...pnoms)) : 100;
    const c1s = nums('marginal_cost');
    const c2s = nums('marginal_cost_quadratic');
    const c1 = c1s.length ? c1s.reduce((s, x) => s + x, 0) / c1s.length : 10;
    const c2 = c2s.length ? c2s.reduce((s, x) => s + x, 0) / c2s.length : 0;
    setPMax(nextPMax);
    setPoints([
      { p: 0, mc: Math.max(0, c1) },
      { p: nextPMax, mc: Math.max(0, c1 + 2 * c2 * nextPMax) },
    ]);
    onStatus(`Loaded current cost from ${matched.length} matched row${matched.length === 1 ? '' : 's'} (max output ${Math.round(nextPMax)} MW).`);
  };

  const resetCurve = () => setPoints([{ p: 0, mc: 10 }, { p: pMax, mc: 40 }]);

  // ── Apply: two `set` adjustments through the tested Adjust engine ─────────
  const apply = () => {
    if (!activeSheet) { onStatus('Pick a component first.'); return; }
    if (matches === 0) { onStatus('No rows match — nothing to write. Check the filters.'); return; }
    const c1 = Number(fit.marginalCost.toFixed(6));
    const c2 = Number(fit.marginalCostQuadratic.toFixed(8));
    const adjustments: Adjustment[] = [
      { id: 'cc_mc', sheet: activeSheet, filters, attribute: 'marginal_cost', action: 'set', amount: c1 },
      { id: 'cc_q', sheet: activeSheet, filters, attribute: 'marginal_cost_quadratic', action: 'set', amount: c2 },
    ];
    const result = applyAdjustments(model, adjustments, {});
    onApplySheets(result.sheets);
    onStatus(
      `Set marginal_cost = ${c1} and marginal_cost_quadratic = ${c2} on ${matches} ${activeSheet} row${matches === 1 ? '' : 's'}.`,
    );
  };

  // ── Axis ticks ─────────────────────────────────────────────────────────
  const xTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * pMax);
  const yTicks = [0, 0.5, 1].map((f) => f * yMax);

  if (eligible.length === 0) {
    return (
      <section className="forge-section">
        <header className="forge-section-header"><h3>Marginal cost curve</h3></header>
        <p className="sg-setting-hint">No generators, storage units, stores, or links in this model to price.</p>
      </section>
    );
  }

  return (
    <section className="forge-section">
      <header className="forge-section-header">
        <h3>Marginal cost curve</h3>
        <p>
          Draw the marginal-cost-vs-output curve and apply it to a filtered set of
          components. The closest convex quadratic cost is fit and written as
          <code> marginal_cost</code> (linear) + <code>marginal_cost_quadratic</code>.
        </p>
      </header>

      {/* Component + filters */}
      <div className="forge-adjust-row forge-adjust-spec">
        <SearchableSelect
          className="forge-adjust-select"
          value={activeSheet}
          placeholder="component"
          options={eligible.map((s) => ({ value: s, label: `${s} (${rowsOf(model, s).length})` }))}
          onChange={(v) => { setSheet(v); setFilters([]); }}
        />
        <span className="forge-adjust-match">{matches} row{matches === 1 ? '' : 's'} match</span>
      </div>

      {filters.map((f, idx) => (
        <div className="forge-adjust-row forge-adjust-filter" key={idx}>
          <span className="forge-adjust-and">{idx === 0 ? 'where' : 'and'}</span>
          <SearchableSelect
            className="forge-adjust-select"
            value={f.column}
            placeholder="column"
            options={columns.map((c) => ({ value: c, label: c }))}
            onChange={(v) => setFilters(filters.map((g, i) => (i === idx ? { column: v, value: '' } : g)))}
          />
          <span className="forge-adjust-eq">=</span>
          <SearchableSelect
            className="forge-adjust-select"
            value={f.value}
            placeholder="value"
            disabled={!f.column}
            options={uniqueValues(rows, f.column).map((v) => ({ value: v, label: v }))}
            onChange={(v) => setFilters(filters.map((g, i) => (i === idx ? { ...g, value: v } : g)))}
          />
          <button type="button" className="forge-adjust-remove" onClick={() => setFilters(filters.filter((_, i) => i !== idx))} aria-label="Remove filter">×</button>
        </div>
      ))}

      <div className="forge-adjust-row">
        <button type="button" className="tb-btn tb-btn--muted forge-adjust-addfilter" onClick={() => setFilters([...filters, { column: '', value: '' }])} disabled={!activeSheet}>
          + Add filter
        </button>
        <button type="button" className="tb-btn tb-btn--muted" onClick={loadFromSelection} title="Set the output range and starting curve from the matched rows' current values">
          Load from selection
        </button>
      </div>

      {/* Chart */}
      <div className="forge-costcurve-chartwrap">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${VBW} ${VBH}`}
          className="forge-costcurve-chart"
          role="img"
          aria-label="Marginal cost versus output"
          onPointerMove={onMove}
          onPointerUp={endDrag}
          onPointerDown={addPoint}
        >
          {/* grid + axes */}
          {yTicks.map((t) => (
            <g key={`y${t}`}>
              <line x1={PAD.l} y1={yPix(t)} x2={VBW - PAD.r} y2={yPix(t)} className="cc-grid" />
              <text x={PAD.l - 6} y={yPix(t) + 3} className="cc-axis-label" textAnchor="end">{Math.round(t)}</text>
            </g>
          ))}
          {xTicks.map((t) => (
            <text key={`x${t}`} x={xPix(t)} y={VBH - PAD.b + 16} className="cc-axis-label" textAnchor="middle">{Math.round(t)}</text>
          ))}
          <line x1={PAD.l} y1={PAD.t} x2={PAD.l} y2={PAD.t + PLOT_H} className="cc-axis" />
          <line x1={PAD.l} y1={PAD.t + PLOT_H} x2={VBW - PAD.r} y2={PAD.t + PLOT_H} className="cc-axis" />
          <text x={4} y={PAD.t - 2} className="cc-axis-title">{cur}/MWh</text>
          <text x={VBW - PAD.r} y={VBH - 4} className="cc-axis-title" textAnchor="end">output (MW)</text>

          {/* user's sketch (light) */}
          <polyline
            className="cc-sketch"
            points={sorted.map((q) => `${xPix(q.p)},${yPix(q.mc)}`).join(' ')}
          />
          {/* fitted line (bold): MC(p) = c₁ + 2c₂p */}
          <line
            className="cc-fit"
            x1={xPix(0)} y1={yPix(marginalCostAt(fit, 0))}
            x2={xPix(pMax)} y2={yPix(marginalCostAt(fit, pMax))}
          />
          {/* draggable control points */}
          {points.map((q, i) => (
            <circle
              key={i}
              className="cc-point"
              cx={xPix(q.p)} cy={yPix(q.mc)} r={6}
              onPointerDown={startDrag(i)}
              onDoubleClick={removePoint(i)}
            >
              <title>{`${q.p.toFixed(1)} MW → ${cur}${q.mc.toFixed(1)}/MWh (double-click to remove)`}</title>
            </circle>
          ))}
        </svg>
      </div>

      <div className="forge-adjust-row" style={{ gap: 12, flexWrap: 'wrap' }}>
        <label className="sg-setting-label" style={{ margin: 0 }}>Max output (MW)</label>
        <input
          type="number" className="forge-number" min={1} step={10}
          value={pMax}
          onChange={(e) => setPMax(Math.max(1, Number(e.target.value) || 100))}
          style={{ width: 90 }}
        />
        <button type="button" className="tb-btn tb-btn--muted" onClick={resetCurve}>Reset curve</button>
        <span className="sg-setting-hint" style={{ margin: 0 }}>Click to add a point · drag to move · double-click to remove.</span>
      </div>

      {/* Fit readout */}
      <div className="forge-costcurve-readout">
        <span><b>marginal_cost</b> (c₁) = {cur}{fit.marginalCost.toFixed(2)}/MWh</span>
        <span><b>marginal_cost_quadratic</b> (c₂) = {fit.marginalCostQuadratic.toFixed(4)}</span>
        <span className="sg-setting-hint" style={{ margin: 0 }}>fit R² = {fit.r2.toFixed(3)}</span>
      </div>
      {fit.warning && (
        <p className="sg-setting-hint" style={{ color: 'var(--warning, #b45309)' }}>{fit.warning}</p>
      )}
      {fit.marginalCostQuadratic > 0 && (
        <p className="sg-setting-hint">
          A non-zero quadratic term makes the optimisation a <b>QP</b> — solve with a QP-capable
          solver (HiGHS or Gurobi).
        </p>
      )}

      <div className="forge-adjust-actions">
        <button type="button" className="primary-button" onClick={apply} disabled={!activeSheet || matches === 0}>
          Apply to {matches} row{matches === 1 ? '' : 's'}
        </button>
      </div>
    </section>
  );
}
